# Eval cases

One folder per rumour, each with a `case.json`:

```json
{
  "id": "example-rumour",
  "claim": "The polished, widely-circulated version of the rumour.",
  "claim_variants": ["An earlier, vaguer phrasing, if one is known."],
  "origin": {
    "id": "1abcdef",
    "kind": "post",
    "created_utc": 1712345678,
    "how_known": "receipts | external | crosspost",
    "evidence": "Why we believe this is the first mention in this corpus."
  },
  "window": { "after": "2024-01-01", "before": "2025-01-01" },
  "resolved": { "outcome": "confirmed | denied | unresolved", "date": "2024-05-02",
                "source": "https://..." },
  "notes": ""
}
```

## What counts as an origin

The **earliest trace of the claim in this corpus**, however hedged, and
including a question about it. "Are these split rumours just rumours?" is an
origin: someone asking is evidence the claim was already circulating, and on a
link-aggregating subreddit that question often precedes the first report.

A post that merely names the people involved, with no claim attached, is not.

Where the first *report* differs from the origin it is recorded as
`first_report` and scored separately. A run that finds the report but not the
question is late, not wrong — and the gap between them is worth watching,
because the question is the harder retrieval target by every measure: vaguer,
unvoted, and worded nothing like the claim you would search with. If the earliest mention is a
comment and we have only posts ingested, the case is marked
`origin.kind: "comment"` and skipped by post-only runs rather than being
scored against the wrong answer.

`how_known` is the provenance of the *label*, and it is the thing that
decides how much a case is worth:

- `external` — the claim is datable outside Reddit (an official announcement,
  a trade-press story), so the origin must precede that date. Strongest.
- `receipts` — a later thread links back to the origin. Strong, but only as
  honest as the linker.
- `crosspost` — explicit parent metadata. Strong but rare.

## Scoring

Two numbers, neither of them recall@k:

1. **Found at all** — is the true origin anywhere in the retrieved set?
   If it isn't, nothing downstream matters.
2. **Hours late** — the gap between the true origin's timestamp and the
   earliest item we ranked as a mention. Landing two hours late is a useful
   system; two weeks late is not. Ordinary relevance metrics cannot tell
   those apart, which is why this is the number that gets reported.

A run also reports **false-early rate**: how often we name something earlier
than the true origin that isn't actually the claim. That failure is worse
than being late, because it is the one a user cannot detect.
