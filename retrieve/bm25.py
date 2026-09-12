"""BM25 over post titles. No dependencies; the corpus is small enough."""
import json, math, re
from collections import Counter, defaultdict

TOKEN = re.compile(r"[a-z0-9']+")

def tok(s):
    return TOKEN.findall(s.lower())

class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.toks = [tok(d['text']) for d in docs]
        self.len = [len(t) for t in self.toks]
        self.avg = sum(self.len) / max(1, len(self.len))
        self.tf = [Counter(t) for t in self.toks]
        df = Counter()
        for t in self.toks:
            df.update(set(t))
        N = len(docs)
        self.idf = {w: math.log(1 + (N - n + 0.5) / (n + 0.5)) for w, n in df.items()}
        self.postings = defaultdict(list)
        for i, t in enumerate(self.toks):
            for w in set(t):
                self.postings[w].append(i)

    def search(self, query, limit=None):
        q = tok(query)
        scores = defaultdict(float)
        for w in q:
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i in self.postings[w]:
                f = self.tf[i][w]
                denom = f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
                scores[i] += idf * f * (self.k1 + 1) / denom
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        if limit:
            ranked = ranked[:limit]
        return [(self.docs[i], s) for i, s in ranked]

def load(path, kind='post'):
    """Posts and comments are both just dated text with an id."""
    docs = []
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        if kind == 'post':
            text = r['title'] + ' ' + (r.get('selftext') or '')
            label = r['title']
        else:
            text = label = r.get('body') or ''
            if not text or text in ('[deleted]', '[removed]'):
                continue
        docs.append({
            'id': r['id'], 'kind': kind,
            'created_utc': r['created_utc'],
            'score': r.get('score', 0),
            'title': label,
            'text': text,
        })
    return docs
