// Pages the Arctic Shift API into a newline-delimited JSON file.
//
// Arctic Shift caps a single response, so we walk forward in time: ask for the
// next batch after the newest thing we've seen, repeat until a batch comes back
// empty. Posts sharing a created_utc with the cursor are dropped by id, because
// advancing the cursor by one second would skip them instead.

const BASE = 'https://arctic-shift.photon-reddit.com/api';

const POST_FIELDS = [
  'id', 'created_utc', 'title', 'selftext', 'author', 'score', 'num_comments',
  'link_flair_text', 'url',
].join(',');

const COMMENT_FIELDS = [
  'id', 'created_utc', 'body', 'author', 'score', 'link_id', 'parent_id',
].join(',');

async function get(url, attempt = 0) {
  const res = await fetch(url);
  // 422 is not a client error here: the server returns it under load for
  // requests that succeed on retry.
  if (res.status === 429 || res.status === 422 || res.status >= 500) {
    if (attempt >= 5) throw new Error(`${res.status} after ${attempt} retries: ${url}`);
    const wait = 2 ** attempt * 1000;
    process.stderr.write(`  ${res.status}, waiting ${wait}ms\n`);
    await new Promise(r => setTimeout(r, wait));
    return get(url, attempt + 1);
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${url}`);
  return (await res.json()).data;
}

export async function* page(kind, { subreddit, after, before }) {
  const fields = kind === 'posts' ? POST_FIELDS : COMMENT_FIELDS;
  let cursor = Math.floor(new Date(after).getTime() / 1000);
  const end = Math.floor(new Date(before).getTime() / 1000);
  // Only ids from the cursor second can come back again; nothing older can.
  let boundary = new Set();
  let empties = 0;

  while (cursor < end) {
    const url = `${BASE}/${kind}/search?subreddit=${subreddit}`
      + `&after=${cursor}&before=${end}&sort=asc&limit=auto&fields=${fields}`;
    const batch = await get(url);
    if (batch.length === 0) {
      // An empty batch normally means we're done. Retry a few times anyway:
      // a truncated corpus makes every "first mention" unfalsifiable, and a
      // silent short read is the one failure this project cannot tolerate.
      if (++empties < 4) {
        await new Promise(r => setTimeout(r, 2 ** empties * 1000));
        continue;
      }
      return;
    }
    empties = 0;

    const fresh = batch.filter(x => !boundary.has(x.id));
    if (fresh.length === 0) {
      // Every result is one we already have, so a single second holds more
      // items than one response can carry. Step past it or we spin here.
      cursor += 1;
      boundary = new Set();
      continue;
    }
    for (const x of fresh) yield x;

    cursor = batch[batch.length - 1].created_utc;
    boundary = new Set(batch.filter(x => x.created_utc === cursor).map(x => x.id));
  }
}
