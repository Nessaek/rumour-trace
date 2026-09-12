"""Stage 3: narrow the corpus to items that could plausibly carry the claim.

This is a filter, not a search. Entity co-occurrence takes 1.56M items to
between 58 and ~3,200, which is small enough for the classifier to read every
one. Getting the alias list right matters more than anything downstream: a
missed alias is a silent miss, not an error.
"""
import json, re

POSTS = 'data/Fauxmoi-posts-2024-01-01-2025-01-01.ndjson'
COMMENTS = 'data/Fauxmoi-comments-2024-01-01-2025-01-01.ndjson'


def _pattern(aliases):
    """One case-insensitive alternation per entity. Aliases are matched loosely
    on purpose — the corpus routinely misspells the names it is matching."""
    return re.compile('|'.join(re.escape(a) for a in sorted(aliases, key=len, reverse=True)), re.I)


def source_of(item, threads):
    """Where the corpus says this entered the subreddit, as (label, flair).

    This is one hop upstream, not the source of the rumour. r/Fauxmoi is a link
    aggregator, so a post's url is the outlet that carried the claim here —
    where *that* outlet got it is not in this corpus and never will be.

    A post with no outbound link is the interesting case, not a missing value.
    In the tabloid case the origin is a self-post asking whether the rumour is
    true: the claim
    reached the asker by some route this corpus cannot see, and reporting that
    is more honest than reporting nothing.
    """
    src = item if item['kind'] == 'post' else (threads.get(item['thread']) or {})
    url, flair = src.get('url'), src.get('flair')
    if not url:
        return 'no link', flair
    host = url.split('//', 1)[-1].split('/', 1)[0].removeprefix('www.')
    if host.endswith('reddit.com'):
        return 'self-post, no external link', flair
    if host in ('i.redd.it', 'v.redd.it', 'preview.redd.it'):
        return f'media uploaded to reddit ({host})', flair
    return host, flair


def permalink(item):
    """Reddit's own URL for an item, so an answer can be opened and checked
    rather than trusted.

    The subreddit is deliberately left out: /comments/<id> resolves without it,
    and hardcoding one would go stale the moment SUBREDDIT changes. A comment
    is only addressable through its thread, so a missing link_id returns None
    rather than a URL that 404s — a citation that does not resolve is the exact
    failure this tool exists to avoid.
    """
    if item['kind'] == 'post':
        return f"https://www.reddit.com/comments/{item['id']}"
    thread = item.get('thread')
    if not thread:
        return None
    return f"https://www.reddit.com/comments/{thread.removeprefix('t3_')}/_/{item['id']}"


def load_corpus(posts=POSTS, comments=COMMENTS):
    items, threads = [], {}
    for line in open(posts):
        if not line.strip():
            continue
        r = json.loads(line)
        text = r['title'] + ' ' + (r.get('selftext') or '')
        threads['t3_' + r['id']] = {'title': r['title'], 'url': r.get('url'),
                                    'flair': r.get('link_flair_text')}
        items.append({'id': r['id'], 'kind': 'post', 'created_utc': r['created_utc'],
                      'score': r.get('score', 0), 'text': text, 'thread': None,
                      'url': r.get('url'), 'flair': r.get('link_flair_text')})
    for line in open(comments):
        if not line.strip():
            continue
        r = json.loads(line)
        body = r.get('body') or ''
        if body in ('', '[removed]', '[deleted]'):
            continue
        items.append({'id': r['id'], 'kind': 'comment', 'created_utc': r['created_utc'],
                      'score': r.get('score', 0), 'text': body, 'thread': r.get('link_id')})
    items.sort(key=lambda x: x['created_utc'])
    return items, threads


def candidates(items, threads, entities, window=None):
    """entities is a list of alias-lists, one per person. An item qualifies if
    every entity matches — in its own text, or in its parent post's title.

    Thread inheritance is what catches 'they're definitely splitting' posted
    inside a thread that already names the couple. Without it that comment is
    invisible, and it is a very common way for people to talk.
    """
    pats = [_pattern(a) for a in entities]
    out = []
    for it in items:
        if window:
            if it['created_utc'] < window[0] or it['created_utc'] >= window[1]:
                continue
        parent = (threads.get(it['thread']) or {}).get('title', '') if it['thread'] else ''
        hay = it['text'] + ' ' + parent
        if all(p.search(hay) for p in pats):
            item = dict(it)
            item['parent_title'] = parent or None
            item['own_text_matches'] = all(p.search(it['text']) for p in pats)
            out.append(item)
    return out
