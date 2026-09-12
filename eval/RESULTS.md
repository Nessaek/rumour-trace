# Baseline

BM25 over titles and comment bodies, top-k by score, answer = earliest retrieved.

```
corpus   26,690 posts + 1,057,522 readable comments (31% of comments removed)
k        200
cases    2 positive, 1 control
```

| case | origin found | rank | answer | error |
|---|---|---|---|---|
| blind-item case | yes | 36 | a list of three actresses, one of them the subject | 53 days early |
| tabloid case | yes | 114 | a fond remark about a red-carpet photo of the couple | 135 days early |

**Recall 2/2. Answers 0/2.**

## Diagnosis

Retrieval is not the problem and tuning it will not help. Both cases fail
identically: BM25 ranks on the names, because a celebrity's full name is
high-IDF and discriminative, while "divorce", "split" and
"rumours" are common and contribute almost nothing. The retrieved set is
therefore *everything about these people*, and the oldest thing in it is
always a red-carpet remark.

Sorting that set by time is guaranteed to return a false early. It is not a
threshold problem — the control's best hit scores 34.1 for a claim that is not
in the corpus at all, higher than plenty of genuine matches.

**The claim filter is the product.** Deciding whether an item asserts the
claim has to be a separate stage after retrieval, not a cutoff applied to it.

## Also learned

Adding comments moved the tabloid case's origin from rank 60 to rank 114 — a million
more documents means more competition for the same query. It also made the
blind-item case solvable at all, since its origin is a comment. Both are
true; the trade is worth it, but recall@k gets harder as the corpus grows and
that has to be budgeted for rather than discovered later.
