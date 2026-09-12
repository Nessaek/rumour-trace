"""Stage 4: decide whether an item carries the claim.

Four labels, nothing else. The schema is enforced by the API, so a fifth label
is impossible rather than discouraged — the same reason the BrickSolver tool
enum is built from the set's real inventory.

The labels exist because of specific things in the corpus:

  asserts       states the claim as fact or report
                "There was that blind item about him seeing a divorce attorney"
  references    treats the claim as circulating, without asserting it. This is
                still an origin — a question is evidence the rumour existed.
                "are these split rumors, just rumors?"
  mentions_only names the people, carries no claim. The failure that broke the
                BM25 baseline.
                "I genuinely love that red carpet shot of them."
  unrelated     different people, or the text does not concern them at all
"""
import json, os, pathlib, time
from typing import List, Literal
from pydantic import BaseModel
import anthropic

MODEL = os.environ.get('CLAUDE_MODEL', 'claude-opus-5')
BATCH = int(os.environ.get('CLASSIFY_BATCH', '40'))

# Thinking is on by default on claude-opus-5 at effort 'high', and thinking
# tokens bill as output at 5x the input rate. On the first full run that was
# most of the bill: ~282k tokens of corpus went in, and roughly three times
# their cost came back out as reasoning about four-way labels. Labelling
# against a fixed rubric is the flat part of the effort curve, so 'low' is the
# default here. Raise it with CLASSIFY_EFFORT and score the result — the three
# cases plus the control are exactly the check that tells you what it bought.
EFFORT = os.environ.get('CLASSIFY_EFFORT', 'low')

# The whole run is offline scoring over a frozen corpus, so nothing is waiting
# on a response and the batch API's 50% applies to every token. It is off by
# default because results arrive within 24 hours rather than 24 seconds, which
# is the wrong trade while you are iterating on the rubric and the right one
# for a full scoring run.
BATCH_API = os.environ.get('CLASSIFY_BATCH_API', '0') == '1'
POLL_SECONDS = int(os.environ.get('CLASSIFY_POLL', '30'))

# Per-MTok, claude-opus-5. Cache writes cost 1.25x input and reads 0.1x, which
# is the whole reason the rubric sits in a cached prefix. The batch API halves
# everything, so a run reports what it actually cost rather than list price.
PRICES = {'input': 5.0, 'output': 25.0, 'cache_write': 6.25, 'cache_read': 0.5}

_usage = {'input': 0, 'output': 0, 'cache_write': 0, 'cache_read': 0, 'requests': 0}


def _record(u):
    _usage['input'] += u.input_tokens
    _usage['output'] += u.output_tokens
    _usage['cache_write'] += getattr(u, 'cache_creation_input_tokens', 0) or 0
    _usage['cache_read'] += getattr(u, 'cache_read_input_tokens', 0) or 0
    _usage['requests'] += 1


def usage_report():
    """Tokens and dollars for everything classified so far this process.

    The number exists because this pipeline's first full run cost $6 and
    nobody found out until the bill arrived. A run that prints its own cost
    cannot surprise you twice.
    """
    u = dict(_usage)
    u['cost'] = sum(u[k] * PRICES[k] for k in PRICES) / 1e6
    if BATCH_API:
        u['cost'] /= 2
    return u


Label = Literal['asserts', 'references', 'mentions_only', 'unrelated']


class Verdict(BaseModel):
    index: int
    label: Label
    quote: str


class Verdicts(BaseModel):
    verdicts: List[Verdict]


RUBRIC = """You label short items from a celebrity gossip forum according to whether they carry a specific claim.

You will be given one CLAIM and a numbered list of ITEMS. Label every item.

  asserts        The item states the claim as fact, reports it, or relays someone else reporting it.
  references     The item treats the claim as something already circulating, without asserting it
                 itself. Questions count: asking "are the split rumours true?" is evidence the claim
                 was in circulation. Denials count too — denying a rumour references it.
  mentions_only  The item concerns these people but carries no version of this claim.
  unrelated      The item does not concern these people, or the match is coincidental.

Rules that matter more than they look:

- The claim is about a SPECIFIC EVENT. An item about the same people and the same KIND of event at a
  different time is `mentions_only`, not `references`. A 2024 divorce rumour and a reference to their
  breakup twenty years earlier are different claims.
- Sarcasm, jokes and hypotheticals ("imagine if they split") are `mentions_only`.
- An ADJACENT claim is not this claim. Strain, concern, unhappiness, a rough patch or a source
  "worried about them" is `mentions_only` unless the item goes as far as the claim itself. A
  headline reporting that a third party "is concerned about their marriage" does not say they are
  splitting, and is not evidence that anyone yet said so. Label what the item claims, not what it
  foreshadows.
- A claim needs an IDENTIFIED subject. If the claim-bearing words attach to a bare "him", "her" or
  "they", and the item's own text does not say who, it is `mentions_only` — however strongly the
  thread implies it. "the divorce has hit him hard", posted in a thread naming five celebrities, is
  about none of them as far as you can tell, and guessing is how a comment about someone else's
  divorce becomes the earliest trace of this one.
- Some items are comments shown with the title of the thread they were posted in. The thread title is
  context only. Label the item's own text. If the item's own text carries no claim and only the thread
  title does, the label is `mentions_only`.
- `quote` must be a verbatim substring of the item's own text, at most 15 words, showing what earned
  the label. For `mentions_only` and `unrelated`, return an empty string.

Return a verdict for every item, using the index given."""


def _client():
    """An unset ANTHROPIC_API_KEY does not mean there are no credentials: the
    SDK also resolves ANTHROPIC_AUTH_TOKEN, an `ant auth login` profile, and
    workload identity federation. So load .env if there is one, then hand off
    to the SDK and let it look — don't pre-empt it with a raise."""
    env = pathlib.Path('.env')
    if not os.environ.get('ANTHROPIC_API_KEY') and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('ANTHROPIC_API_KEY=') and line.split('=', 1)[1].strip():
                os.environ['ANTHROPIC_API_KEY'] = line.split('=', 1)[1].strip().strip('"\'')
    client = anthropic.Anthropic()
    # The SDK constructs happily with no credentials and only fails deep in the
    # request, with a stack trace that says nothing about what to do. Check the
    # resolved credential here instead — any of the three counts, so an
    # `ant auth login` profile or federation still works without a key.
    if not (client.api_key or client.auth_token or client.credentials):
        raise SystemExit(
            "No credentials resolved.\n"
            f"  looked for .env at: {env.resolve()} ({'present' if env.exists() else 'MISSING'})\n"
            "  fix, either:\n"
            "    cp .env.example .env   then paste your key after the =\n"
            "    ant auth login         (no secret stored in the project)")
    return client


def _render(items):
    out = []
    for i, it in enumerate(items):
        text = it['text'].replace('\n', ' ').strip()[:600]
        line = f"[{i}] ({it['kind']}) {text}"
        if it.get('parent_title') and not it.get('own_text_matches', True):
            line += f"\n     thread: {it['parent_title'][:120]}"
        out.append(line)
    return '\n'.join(out)


def _system(claim):
    """Rubric and claim are byte-identical across every batch of a case — 93 of
    them on the largest — so they belong above the cache breakpoint and the
    items belong in the turn. Caching is a prefix match: the claim only caches
    if it sits above the marker, which is why it moved out of the user message.

    Whether the prefix clears claude-opus-5's 512-token minimum is a
    count_tokens call, not an eyeball. Under the minimum the marker is ignored
    silently, so this is free either way, but the run reports cache reads and
    a column of zeros is the thing to look at."""
    return [{'type': 'text',
             'text': f"{RUBRIC}\n\nCLAIM: {claim}",
             'cache_control': {'type': 'ephemeral'}}]


def _params(claim, chunk):
    return {'model': MODEL,
            'max_tokens': 8000,
            'system': _system(claim),
            'messages': [{'role': 'user', 'content': f"ITEMS:\n{_render(chunk)}"}]}


def _collect(results, start, verdicts, chunk):
    for v in verdicts:
        if 0 <= v.index < len(chunk):
            results[start + v.index] = {'label': v.label, 'quote': v.quote}


def _sync(client, claim, chunks, results, verbose):
    for i, chunk in enumerate(chunks):
        resp = client.messages.parse(**_params(claim, chunk),
                                     output_config={'effort': EFFORT},
                                     output_format=Verdicts)
        _record(resp.usage)
        _collect(results, i * BATCH, resp.parsed_output.verdicts, chunk)
        if verbose:
            u = resp.usage
            print(f"  batch {i + 1}: {len(chunk)} items, "
                  f"{u.input_tokens} in / {u.output_tokens} out, "
                  f"cache read {getattr(u, 'cache_read_input_tokens', 0)}")


def _batch_api(client, claim, chunks, results, verbose):
    """Same requests, submitted as one batch at half price.

    The schema transform is the SDK's own — messages.parse() applies it to the
    pydantic model before sending, and a batch request carries raw params with
    no parse() to do it. Reproducing it by hand would drift from whatever the
    SDK sends; importing it keeps the two paths identical at the cost of one
    private import, which is the trade worth making here.
    """
    from pydantic import TypeAdapter
    from anthropic.lib._parse._transform import transform_schema

    fmt = {'type': 'json_schema',
           'schema': transform_schema(TypeAdapter(Verdicts).json_schema())}
    batch = client.messages.batches.create(requests=[
        {'custom_id': f'c{i}',
         'params': {**_params(claim, chunk),
                    'output_config': {'effort': EFFORT, 'format': fmt}}}
        for i, chunk in enumerate(chunks)])

    if verbose:
        print(f"  batch {batch.id}: {len(chunks)} requests submitted, polling")
    while True:
        state = client.messages.batches.retrieve(batch.id)
        if state.processing_status == 'ended':
            break
        if verbose:
            print(f"  {state.processing_status}: {state.request_counts}")
        time.sleep(POLL_SECONDS)

    # Results arrive in any order — key by custom_id, never by position.
    failed = []
    for entry in client.messages.batches.results(batch.id):
        i = int(entry.custom_id[1:])
        chunk = chunks[i]
        if entry.result.type != 'succeeded':
            failed.append((entry.custom_id, entry.result.type))
            continue
        _record(entry.result.message.usage)
        text = ''.join(b.text for b in entry.result.message.content
                       if b.type == 'text')
        _collect(results, i * BATCH, Verdicts.model_validate_json(text).verdicts,
                 chunk)
    if failed:
        # Not raised: an unlabelled item is already handled as label None below,
        # and losing one batch of 40 should not throw away the other 92.
        print(f"  {len(failed)} batch requests did not succeed: {failed[:5]}")


def classify(claim, items, client=None, verbose=False):
    """Returns a list parallel to `items` of {'label', 'quote'}."""
    client = client or _client()
    results = [None] * len(items)
    chunks = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    (_batch_api if BATCH_API else _sync)(client, claim, chunks, results, verbose)
    # An item the model skipped is not silently 'unrelated'.
    for i, r in enumerate(results):
        if r is None:
            results[i] = {'label': None, 'quote': ''}
    return results
