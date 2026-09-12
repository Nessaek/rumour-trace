"""Propose eval cases by pairing a resolution post with earlier rumour posts.

A usable case needs a datable resolution and a rumour that preceded it. This
finds candidate pairs by name overlap; a human still has to confirm that the
earlier posts carry the *same* claim. It proposes, it does not label.
"""
import json, re, sys, datetime as dt
from collections import defaultdict

ROWS = [json.loads(l) for l in open(sys.argv[1] if len(sys.argv) > 1
        else 'data/Fauxmoi-posts-2024-01-01-2025-01-01.ndjson')]

RESOLVE = re.compile(r'\b(confirms?|confirmed|denies|denied|announces?|announced|'
                     r'files? for|filed for|admits?|split|divorce|engaged|expecting)\b', re.I)
RUMOUR  = re.compile(r'\b(rumou?rs?|reportedly|allegedly|sources say|speculation|'
                     r'spotted|claims?|is it true|are they)\b', re.I)
STOP = set('''the a an and or of to in on at for with from is are was were be been being
this that these those they them their his her he she it its as by not no new says say said
after before amid over about into out up down off who what when where why how all any more
most some such only own same so than too very can will just now then i you we us our your
first last year years old man woman girl boy people best worst top show film movie star'''.split())

def names(title):
    """Capitalised tokens, which on a gossip sub are overwhelmingly people."""
    toks = re.findall(r"\b[A-Z][a-zA-Z'À-ɏ-]{2,}\b", title)
    return {t.lower() for t in toks if t.lower() not in STOP}

by_name = defaultdict(list)
for r in ROWS:
    for n in names(r['title']):
        by_name[n].append(r)

seen_pairs = set()
out = []
for r in ROWS:
    if not RESOLVE.search(r['title']) or r['score'] < 800:
        continue
    ns = names(r['title'])
    # Rare-ish names only: a token in half the corpus tells us nothing.
    ns = {n for n in ns if 3 <= len(by_name[n]) <= 400}
    if not ns:
        continue
    # Require two shared name tokens, i.e. a full name. One token pairs
    # "Margot Robbie is expecting" with "Tom Holland denies breakup" on "Tom".
    uniq = {}
    for n in ns:
        for p in by_name[n]:
            if p['created_utc'] >= r['created_utc'] or not RUMOUR.search(p['title']):
                continue
            if len(names(p['title']) & ns) >= 2:
                uniq[p['id']] = p
    if len(uniq) < 2:
        continue
    lead = sorted(uniq.values(), key=lambda p: p['created_utc'])
    gap_days = (r['created_utc'] - lead[0]['created_utc']) / 86400
    if gap_days < 0.5:
        continue
    key = tuple(sorted(ns))
    if key in seen_pairs:
        continue
    seen_pairs.add(key)
    out.append((r, lead, gap_days))

out.sort(key=lambda x: -x[0]['score'])
d = lambda u: dt.datetime.fromtimestamp(u, dt.UTC).strftime('%Y-%m-%d')
print(f"{len(out)} candidate arcs\n")
for r, lead, gap in out[:12]:
    print(f"RESOLUTION {d(r['created_utc'])} ({r['score']}) {r['title'][:88]}")
    print(f"  {len(lead)} earlier rumour posts, first {gap:.0f} days before:")
    for p in lead[:3]:
        print(f"    {d(p['created_utc'])} {str(p['score']):>5} {p['title'][:80]}")
    print()
