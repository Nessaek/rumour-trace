"""Scores the filter+classifier pipeline against the labelled cases.

Three outcomes, not two, because a first-pass miss and a wrongly-rejected
candidate need opposite fixes:

  correct    the origin was found and labelled as carrying the claim
  rejected   the origin was in the candidate set but labelled mentions_only
             or unrelated  -> the classifier is too strict, and it says why
  missed     the origin never reached the classifier -> stage 3 or the aliases
"""
import json, sys, glob, os, datetime as dt
sys.path.insert(0, '.')
sys.path.insert(0, 'retrieve')
from filter import load_corpus, permalink, source_of
from origin import find_origin
from classify.classify import usage_report, EFFORT, BATCH_API

INHERIT = os.environ.get('INHERIT', '1') == '1'
ONLY = sys.argv[1] if len(sys.argv) > 1 else None


class Tee:
    """Everything on screen also lands in a file.

    A run costs real money and the first two produced nothing but scrollback,
    so the transcript is written as it goes rather than at the end — a run that
    dies on a 400 halfway through still leaves its evidence on disk.
    """

    def __init__(self, path):
        self.file = open(path, 'w', buffering=1)
        self.stdout = sys.stdout

    def write(self, text):
        self.stdout.write(text)
        # A batch run spends most of its life polling, and stdout that is not a
        # terminal — piped, redirected, or an editor's output pane — block-buffers
        # under 8KB. A whole control run is under 1KB, so without this the screen
        # stays empty until the process exits and the run looks like it hung.
        self.stdout.flush()
        self.file.write(text)
        return len(text)

    def isatty(self):
        return self.stdout.isatty()

    def fileno(self):
        return self.stdout.fileno()

    def flush(self):
        self.stdout.flush()
        self.file.flush()


RUNS = os.path.join('eval', 'runs')
os.makedirs(RUNS, exist_ok=True)
ts = dt.datetime.now().strftime('%Y-%m-%d-%H%M%S')
LOG = os.path.join(RUNS, ts + '.log')
sys.stdout = Tee(LOG)
fmt = lambda u: dt.datetime.fromtimestamp(u, dt.UTC).strftime('%Y-%m-%d %H:%M')
link = lambda x: permalink(x) or f"unlinkable [{x['id']}]"


def whence(x):
    """One hop upstream: the outlet that carried the claim into the subreddit,
    and the flair it was filed under. Not the source of the rumour — a post
    with no outbound link means the claim arrived by a route this corpus
    cannot see, which is a finding rather than a blank."""
    where, flair = source_of(x, threads)
    return f"    via {where}" + (f" · {flair}" if flair else "")

print("loading corpus...")
items, threads = load_corpus()
print(f"{len(items)} items, thread inheritance {'on' if INHERIT else 'off'}\n")

cases = []
for p in sorted(glob.glob('eval/cases/*/case.json')):
    c = json.load(open(p))
    ents = json.load(open(os.path.join(os.path.dirname(p), 'entities.json')))
    if ONLY and ONLY not in c['id']:
        continue
    cases.append((c, ents))

tally = {'correct': 0, 'rejected': 0, 'missed': 0, 'control_ok': 0, 'control_fail': 0}
answers = []  # (case id, verdict, item) — reprinted at the end, see below

for case, ents in cases:
    print(f"=== {case['id']}")
    res = find_origin(case['claim'], ents, items, threads, inherit=INHERIT, verbose=True)
    got = res['origin']

    # Every labelled candidate, not just the answer. The classifier has already
    # been paid for by this point and the labels are the only record of what it
    # decided; throwing them away means re-buying them to ask any second
    # question, and "how did this spread" is entirely a second question.
    with open(os.path.join(RUNS, f"{ts}-{case['id']}.json"), 'w') as fh:
        json.dump({'case': case['id'], 'effort': EFFORT,
                   'origin': got['id'] if got else None,
                   'labelled': [{k: v for k, v in x.items() if k != 'text'}
                                | {'text': x['text'][:300]}
                                for x in res['labelled']]}, fh, indent=1)

    if case.get('kind') == 'control':
        if got is None:
            print(f"  ABSTAINED — {res['reason']}\n")
            tally['control_ok'] += 1
            answers.append((case['id'], 'ABSTAINED', None))
        else:
            print(f"  FAILED TO ABSTAIN — named {got['id']} ({got['label']})")
            print(f"    {got['text'][:110]}")
            print(f"    {link(got)}")
            print(whence(got) + "\n")
            tally['control_fail'] += 1
            answers.append((case['id'], 'FAILED TO ABSTAIN', got))
        continue

    truth = case['origin']
    labelled = {x['id']: x for x in res['labelled']}
    in_set = truth['id'] in labelled

    if got and got['id'] == truth['id']:
        print(f"  CORRECT — {fmt(got['created_utc'])} [{got['id']}] {got['label']}")
        print(f"    {got['quote']!r}")
        print(f"    {link(got)}")
        print(whence(got) + "\n")
        tally['correct'] += 1
        answers.append((case['id'], 'CORRECT', got))
    elif in_set and labelled[truth['id']]['label'] not in ('asserts', 'references'):
        print(f"  REJECTED — origin was a candidate but labelled "
              f"{labelled[truth['id']]['label']}")
        print(f"    origin: {labelled[truth['id']]['text'][:100]}")
        print(f"    origin: {link(labelled[truth['id']])}")
        print(whence(labelled[truth['id']]))
        if got:
            h = (got['created_utc'] - truth['created_utc']) / 3600
            print(f"    answered instead: {fmt(got['created_utc'])} ({h:+.1f}h) {got['text'][:80]}")
            print(f"    answered instead: {link(got)}")
        print()
        tally['rejected'] += 1
        answers.append((case['id'], 'REJECTED', got))
    elif not in_set:
        print(f"  MISSED — origin never reached the classifier (stage 3 / aliases)")
        if got:
            h = (got['created_utc'] - truth['created_utc']) / 3600
            print(f"    answered instead: {fmt(got['created_utc'])} ({h:+.1f}h)")
            print(f"    answered instead: {link(got)}")
        print()
        tally['missed'] += 1
        answers.append((case['id'], 'MISSED', got))
    else:
        h = (got['created_utc'] - truth['created_utc']) / 3600
        print(f"  EARLY — answered {fmt(got['created_utc'])} ({h:+.1f}h before origin)")
        print(f"    {got['text'][:100]}")
        print(f"    labelled {got['label']}: {got['quote']!r}")
        print(f"    {link(got)}")
        print(whence(got) + "\n")
        tally['rejected'] += 1
        answers.append((case['id'], 'EARLY', got))

print(json.dumps(tally, indent=2))

u = usage_report()
print(f"\neffort {EFFORT}{' via batch API' if BATCH_API else ''}, "
      f"{u['requests']} requests")
print(f"{u['input']:,} in / {u['output']:,} out, "
      f"cache {u['cache_write']:,} written {u['cache_read']:,} read")
print(f"cost ${u['cost']:.2f}")
print(f"\ntranscript: {LOG}")
print(f"labels:     {RUNS}/{ts}-<case>.json")

# The answer last, on its own, because it is the thing you came for and the
# thing you will paste to someone else. Everything above it is diagnostics.
print("\n" + "=" * 62)
for cid, verdict, item in answers:
    print(f"{verdict}  {cid}")
    if item is None:
        print("  no item carries the claim — nothing to link\n")
        continue
    print(f"  {fmt(item['created_utc'])}  {item['kind']}  labelled {item['label']}")
    if item.get('quote'):
        print(f"  {item['quote']!r}")
    print(f"  {link(item)}")
    print(f"  {whence(item).strip()}\n")
