"""Resolves every id in every case file against the corpus.

This exists because a case file once shipped with invented comment ids. In a
provenance tool the citation IS the product, so an id that does not resolve,
or resolves to something whose text does not match the quoted evidence, is a
hard failure. Run before any scoring run counts.
"""
import json, glob, re, sys, datetime as dt

POSTS = 'data/Fauxmoi-posts-2024-01-01-2025-01-01.ndjson'
COMMENTS = 'data/Fauxmoi-comments-2024-01-01-2025-01-01.ndjson'

index = {}
for path, kind in ((POSTS, 'post'), (COMMENTS, 'comment')):
    try:
        for line in open(path):
            if not line.strip():
                continue
            r = json.loads(line)
            index[r['id']] = (kind, r)
    except FileNotFoundError:
        print(f"  (no {kind} corpus at {path})")

print(f"{len(index)} items indexed\n")

# Any {"id": ...} object anywhere in a case, plus loose *_id fields.
def refs(obj, path=''):
    if isinstance(obj, dict):
        if 'id' in obj and isinstance(obj['id'], str):
            yield path or 'root', obj
        for k, v in obj.items():
            if k.endswith('_id') and isinstance(v, str) and not v.startswith('t3_'):
                yield f'{path}.{k}', {'id': v}
            yield from refs(v, f'{path}.{k}' if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from refs(v, f'{path}[{i}]')

fails = 0
for cf in sorted(glob.glob('eval/cases/*/case.json')):
    case = json.load(open(cf))
    print(case['id'])
    for where, ref in refs(case):
        if where == 'root':
            continue
        rid = ref['id']
        if rid not in index:
            print(f"  FAIL {where}: id {rid} not in corpus")
            fails += 1
            continue
        kind, item = index[rid]
        note = f"  ok   {where}: {rid} ({kind})"
        if 'kind' in ref and ref['kind'] != kind:
            print(f"  FAIL {where}: labelled {ref['kind']}, corpus says {kind}")
            fails += 1
            continue
        if 'created_utc' in ref and ref['created_utc'] != item['created_utc']:
            print(f"  FAIL {where}: created_utc {ref['created_utc']} != corpus {item['created_utc']}")
            fails += 1
            continue
        # If the case quotes text, that text must really be in the item.
        body = item.get('title', '') + ' ' + (item.get('selftext') or '') + (item.get('body') or '')
        norm = lambda s: re.sub(r"[^a-z0-9 ]", '', s.lower())
        quoted = re.findall(r"'([^']{25,})'", json.dumps(ref, ensure_ascii=False))
        bad = [q for q in quoted if norm(q)[:60] not in norm(body)]
        if bad:
            print(f"  FAIL {where}: quoted text not found in {rid} — {bad[0][:60]!r}")
            fails += 1
            continue
        print(note)
    print()

print("VALID" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
