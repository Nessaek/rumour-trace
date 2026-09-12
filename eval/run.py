"""Scores retrieval against the labelled cases.

Not recall@k. Two numbers: was the origin retrieved at all, and how many hours
late was the earliest thing we would have shown the user. Plus a false-early
count, because naming something earlier that isn't the claim is the failure a
user cannot detect.
"""
import json, sys, glob, datetime as dt
sys.path.insert(0, 'retrieve')
from bm25 import BM25, load

POSTS = 'data/Fauxmoi-posts-2024-01-01-2025-01-01.ndjson'
COMMENTS = 'data/Fauxmoi-comments-2024-01-01-2025-01-01.ndjson'
K = int(sys.argv[1]) if len(sys.argv) > 1 else 200

docs = load(POSTS, 'post') + load(COMMENTS, 'comment')
idx = BM25(docs)
byid = {d['id']: d for d in docs}
fmt = lambda u: dt.datetime.fromtimestamp(u, dt.UTC).strftime('%Y-%m-%d %H:%M')

cases = [json.load(open(p)) for p in sorted(glob.glob('eval/cases/*/case.json'))]
np = sum(1 for d in docs if d['kind'] == 'post')
print(f"{np} posts + {len(docs)-np} readable comments, k={K}, {len(cases)} cases")
print("note: 30.9% of comments are [removed] with no body preserved\n")

found = late = 0
lates, fails = [], []

for c in cases:
    queries = [c['claim']] + c.get('claim_variants', [])
    hits = {}
    for q in queries:
        for d, s in idx.search(q, limit=K):
            if d['id'] not in hits or s > hits[d['id']][1]:
                hits[d['id']] = (d, s)
    ranked = sorted(hits.values(), key=lambda ds: -ds[1])[:K]

    if c.get('kind') == 'control':
        top = ranked[0][1] if ranked else 0
        print(f"CONTROL {c['id']}")
        print(f"  best score {top:.1f} — needs a threshold below which we abstain")
        if ranked:
            print(f"  top hit: {ranked[0][0]['title'][:80]}")
        print()
        continue

    origin = c['origin']
    got = origin['id'] in {d['id'] for d, _ in ranked}
    earliest = min((d for d, _ in ranked), key=lambda d: d['created_utc'], default=None)
    delta_h = (earliest['created_utc'] - origin['created_utc']) / 3600 if earliest else None

    print(f"{'FOUND ' if got else 'MISS  '} {c['id']}")
    otxt = byid[origin['id']]['title'][:66] if origin['id'] in byid else '(NOT IN CORPUS)'
    print(f"  origin   {fmt(origin['created_utc'])}  [{origin['id']}] {origin.get('kind','')[:1]}  {otxt}")
    if earliest:
        rank = [d['id'] for d, _ in ranked].index(earliest['id']) + 1
        print(f"  earliest {fmt(earliest['created_utc'])}  [{earliest['id']}] {earliest['kind'][:1]}  {earliest['title'][:66]}")
        print(f"  {delta_h:+.1f}h vs origin, at rank {rank} of {len(ranked)}")
        if delta_h < 0:
            print(f"  FALSE EARLY — this predates the origin and is probably not the claim")
    if got:
        found += 1
        r = [d['id'] for d, _ in ranked].index(origin['id']) + 1
        print(f"  origin retrieved at rank {r}")
        lates.append(delta_h)
    else:
        fails.append(c['id'])
    print()

n = len([c for c in cases if c.get('kind') != 'control'])
print(f"origin retrieved: {found}/{n}")
if lates:
    print(f"earliest-shown vs origin: {', '.join(f'{h:+.1f}h' for h in lates)}")
if fails:
    print(f"missed: {', '.join(fails)}")
