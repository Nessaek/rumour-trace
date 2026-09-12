// Usage: node ingest/run.js posts 2024-01-01 2025-01-01
//        node ingest/run.js comments 2024-06-01 2024-07-01

import { createWriteStream } from 'node:fs';
import { page } from './fetch.js';

const [kind, after, before] = process.argv.slice(2);
const SUB = process.env.SUBREDDIT || 'Fauxmoi';

if (!['posts', 'comments'].includes(kind) || !after || !before) {
  console.error('usage: node ingest/run.js <posts|comments> <after> <before>');
  process.exit(1);
}

const out = `data/${SUB}-${kind}-${after}-${before}.ndjson`;
const stream = createWriteStream(out);
let n = 0, last = Date.now();

for await (const item of page(kind, { subreddit: SUB, after, before })) {
  if (!stream.write(JSON.stringify(item) + '\n')) {
    await new Promise(r => stream.once('drain', r));
  }
  if (++n % 1000 === 0) {
    const date = new Date(item.created_utc * 1000).toISOString().slice(0, 10);
    const rate = Math.round(1000 / ((Date.now() - last) / 1000));
    process.stderr.write(`  ${n} ${kind} — at ${date} (${rate}/s)\n`);
    last = Date.now();
  }
}

stream.end();
console.log(`${n} ${kind} → ${out}`);
