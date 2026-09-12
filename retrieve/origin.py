"""Stages 3-5: filter, classify, take the earliest that carries the claim.

There is no ranking anywhere in here. The candidate set is small enough to read
in full, so the answer is the earliest item that passes, not the best match.
"""
import sys
sys.path.insert(0, 'retrieve')
from filter import candidates
from classify.classify import classify

ORIGIN_LABELS = {'asserts', 'references'}


def find_origin(claim, entities, items, threads, window=None, inherit=True,
                verbose=False, client=None):
    cands = candidates(items, threads, entities, window)
    if not inherit:
        cands = [c for c in cands if c['own_text_matches']]
    if verbose:
        print(f"  {len(cands)} candidates after entity filter"
              f"{'' if inherit else ' (no thread inheritance)'}")
    if not cands:
        return {'origin': None, 'reason': 'no candidates', 'candidates': 0, 'labelled': []}

    labels = classify(claim, cands, client=client, verbose=verbose)
    labelled = [dict(c, **l) for c, l in zip(cands, labels)]
    carriers = [x for x in labelled if x['label'] in ORIGIN_LABELS]

    if not carriers:
        return {'origin': None, 'reason': 'no item carries the claim',
                'candidates': len(cands), 'labelled': labelled}

    carriers.sort(key=lambda x: x['created_utc'])
    return {'origin': carriers[0], 'reason': None,
            'candidates': len(cands), 'carriers': len(carriers), 'labelled': labelled}
