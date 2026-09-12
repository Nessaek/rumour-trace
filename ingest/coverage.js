// Usage: node ingest/coverage.js data/Fauxmoi-posts-2024-01-01-2025-01-01.ndjson
//
// "First mention" is only meaningful over a complete corpus, so a hole is a
// correctness bug, not a cosmetic one. This reports per-day counts and flags
// any day far below the local median, plus days missing entirely.

import { readFileSync } from 'node:fs';

const file = process.argv[2];
const [, sub, kind, ...rest] = file.match(/([^/]+)-(posts|comments)-(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})/) || [];
const [from, to] = rest;

const days = new Map();
let removed = 0, total = 0;
for (const line of readFileSync(file, 'utf8').split('\n')) {
  if (!line) continue;
  const r = JSON.parse(line);
  const d = new Date(r.created_utc * 1000).toISOString().slice(0, 10);
  days.set(d, (days.get(d) || 0) + 1);
  total++;
  // Complete days are not the same as complete content: Arctic Shift keeps the
  // row for a moderator-removed comment but usually not its text. On a gossip
  // sub the removed ones skew towards exactly the claims we care about, so this
  // number is a ceiling on what any origin search can possibly see.
  const body = r.body ?? r.selftext;
  if (body === '[removed]' || body === '[deleted]') removed++;
}

const expected = [];
for (let t = new Date(from); t < new Date(to); t.setUTCDate(t.getUTCDate() + 1)) {
  expected.push(t.toISOString().slice(0, 10));
}

const counts = expected.map(d => days.get(d) || 0);
const sorted = [...counts].filter(Boolean).sort((a, b) => a - b);
const median = sorted[Math.floor(sorted.length / 2)] || 0;
const floor = Math.max(1, Math.round(median * 0.25));

const missing = expected.filter(d => !days.has(d));
const thin = expected.filter(d => days.has(d) && days.get(d) < floor);

console.log(`${sub} ${kind}: ${counts.reduce((a, b) => a + b, 0)} items over ${expected.length} days`);
console.log(`median ${median}/day, flagging anything under ${floor}`);
if (removed) {
  const pct = (removed / total * 100).toFixed(1);
  console.log(`${removed} of ${total} (${pct}%) have no readable body — moderator-removed`);
}
if (missing.length) console.log(`\nMISSING ${missing.length} days:\n  ${missing.join(' ')}`);
if (thin.length) console.log(`\nTHIN ${thin.length} days:\n  ${thin.map(d => `${d}(${days.get(d)})`).join(' ')}`);
if (!missing.length && !thin.length) console.log('\nNo gaps.');

process.exit(missing.length || thin.length ? 1 : 0);
