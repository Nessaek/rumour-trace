"""Draws when a claim surfaced, as an SVG.

    python3 eval/spread.py <case-id>

Reads the labels a scored run left in eval/runs/ and buckets the items that
carry the claim by week. With no labels on disk it falls back to the entity
filter and says so on the chart, because the two answer different questions:
the filter finds everyone talking about these people, the labels find the ones
carrying this rumour, and conflating them is how you end up reporting a
red-carpet remark as an origin.

What this cannot show, and the chart says so:

  Removed comments. 31% of this corpus is moderator-removed with the row kept
  and the text gone, and on a gossip subreddit the removed ones skew towards
  exactly the claims worth tracing. Every bar here is a floor, not a count.

  Spread anywhere but here. This is one subreddit. In the tabloid case the
  rumour arrived from the press fully formed; what a chart of it shows is
  uptake on Reddit, not a rumour being born.

No dependencies: the repo runs on pydantic and anthropic, and a chart is not
worth a third.
"""
import json, sys, os, glob, datetime as dt
sys.path.insert(0, '.')
sys.path.insert(0, 'retrieve')

W, H = 920, 430
PAD_L, PAD_R, PAD_T, PAD_B = 56, 26, 84, 62
PLOT_W, PLOT_H = W - PAD_L - PAD_R, H - PAD_T - PAD_B
CARRIES = ('asserts', 'references')


def load_labels(case_id):
    """Most recent scored run for this case, if one exists."""
    runs = sorted(glob.glob(os.path.join('eval', 'runs', f'*-{case_id}.json')))
    if not runs:
        return None, None
    d = json.load(open(runs[-1]))
    items = [x for x in d['labelled'] if x.get('label') in CARRIES]
    series = [('asserts', [x for x in items if x['label'] == 'asserts']),
              ('references', [x for x in items if x['label'] == 'references'])]
    return series, os.path.basename(runs[-1])


def load_candidates(case_id, ents):
    """Fallback: the entity filter, which is free but answers a looser question."""
    from filter import load_corpus, candidates
    items, threads = load_corpus()
    cands = candidates(items, threads, ents, None)
    return [('posts', [c for c in cands if c['kind'] == 'post']),
            ('comments', [c for c in cands if c['kind'] == 'comment'])], None


def weeks(series, lo, hi):
    """Monday-anchored buckets spanning the whole window, gaps included."""
    start = lo - dt.timedelta(days=lo.weekday())
    n = ((hi - start).days // 7) + 1
    out = [[0] * n for _ in series]
    for si, (_, items) in enumerate(series):
        for it in items:
            d = dt.datetime.fromtimestamp(it['created_utc'], dt.UTC).date()
            out[si][(d - start).days // 7] += 1
    return start, out


def bar(x, y, w, h, round_top):
    if h <= 0:
        return ''
    r = min(4, w / 2, h)
    if not round_top:
        return f'<path d="M{x:.1f} {y:.1f}h{w:.1f}v{h:.1f}h-{w:.1f}z"/>'
    return (f'<path d="M{x:.1f} {y + r:.1f}a{r} {r} 0 0 1 {r} -{r}'
            f'h{w - 2 * r:.1f}a{r} {r} 0 0 1 {r} {r}v{h - r:.1f}h-{w:.1f}z"/>')


def render(case, series, source, out_path):
    all_items = [i for _, items in series for i in items]
    if not all_items:
        sys.exit(f"nothing to draw for {case['id']}")
    lo = dt.date(*map(int, case['window']['after'].split('-')))
    hi = dt.date(*map(int, case['window']['before'].split('-'))) - dt.timedelta(days=1)
    start, buckets = weeks(series, lo, hi)
    n = len(buckets[0])
    peak = max((sum(b[i] for b in buckets) for i in range(n)), default=1) or 1
    step = PLOT_W / n
    bw = max(3.0, step - 2)

    def x_of(d):
        return PAD_L + ((d - start).days / 7) * step

    def y_of(v):
        return PAD_T + PLOT_H - (v / peak) * PLOT_H

    p = []
    # y grid — recessive, four lines, labelled
    ticks = [round(peak * f / 4) for f in range(5)]
    for t in sorted(set(ticks)):
        y = y_of(t)
        p.append(f'<line class="grid" x1="{PAD_L}" y1="{y:.1f}" x2="{PAD_L + PLOT_W}" y2="{y:.1f}"/>')
        p.append(f'<text class="tick" x="{PAD_L - 9}" y="{y + 4:.1f}" text-anchor="end">{t}</text>')

    # month ticks
    m = dt.date(lo.year, lo.month, 1)
    while m <= hi:
        if m >= start:
            p.append(f'<text class="tick" x="{x_of(m):.1f}" y="{PAD_T + PLOT_H + 20:.1f}" '
                     f'text-anchor="middle">{m.strftime("%b")}</text>')
        m = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)

    # stacked columns, 2px surface gap between segments
    for i in range(n):
        y = PAD_T + PLOT_H
        wk = start + dt.timedelta(days=7 * i)
        for si in range(len(series) - 1, -1, -1):
            v = buckets[si][i]
            if not v:
                continue
            # A week holding one comment is the whole point of this tool, and
            # against a peak of 291 it rounds to nothing. Floor it at 2px so a
            # non-zero week is never drawn as an empty one.
            h = max(2.0, (v / peak) * PLOT_H)
            top = si == max(j for j in range(len(series)) if buckets[j][i])
            p.append(f'<g class="s{si + 1}"><title>{wk:%-d %b %Y} — '
                     f'{v} {series[si][0]}</title>'
                     f'{bar(PAD_L + i * step, y - h, bw, h, top)}</g>')
            y -= h + 2

    # the narrative: origin, and whatever the case says resolved it
    marks = [(dt.datetime.fromtimestamp(case['origin']['created_utc'], dt.UTC).date(),
              'origin')]
    if case.get('resolved', {}).get('date'):
        marks.append((dt.date(*map(int, case['resolved']['date'].split('-'))),
                      case['resolved']['outcome']))
    for i, (d, lab) in enumerate(marks):
        if not (start <= d <= hi):
            continue
        x = x_of(d)
        # Stagger: origin and resolution can sit five weeks apart on a year-wide
        # axis, which is closer than their labels are wide.
        top = PAD_T - 30 + i * 16
        p.append(f'<line class="mark" x1="{x:.1f}" y1="{top + 4:.1f}" x2="{x:.1f}" y2="{PAD_T + PLOT_H}"/>')
        p.append(f'<text class="marklab" x="{x + 5:.1f}" y="{top:.1f}" '
                 f'text-anchor="start">{lab} {d:%-d %b}</text>')

    # legend — always present at two series, and both are direct-labelled
    lx = PAD_L
    for si, (name, items) in enumerate(series):
        p.append(f'<rect class="s{si + 1}" x="{lx}" y="{H - 26}" width="10" height="10" rx="2"/>')
        p.append(f'<text class="legend" x="{lx + 15}" y="{H - 17}">{name} ({len(items)})</text>')
        lx += 26 + 7.4 * len(f'{name} ({len(items)})')

    # The subtitle must not claim more than the data does: without labels these
    # are items that name the people, which is a different and much looser set.
    what = ('items per week carrying the claim · labels from ' + source if source else
            'items per week NAMING THESE PEOPLE — no scored run on disk, so the '
            'claim filter has not been applied and this is not a rumour curve')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Helvetica, Arial, sans-serif">
<style>
  .surface {{ fill: #fcfcfb; }}
  .title {{ fill: #0b0b0b; font-size: 15px; font-weight: 600; }}
  .sub, .legend {{ fill: #52514e; font-size: 11.5px; }}
  .tick {{ fill: #52514e; font-size: 10.5px; }}
  .marklab {{ fill: #0b0b0b; font-size: 10.5px; font-weight: 600; }}
  .grid {{ stroke: #0b0b0b; stroke-opacity: .10; stroke-width: 1; }}
  .mark {{ stroke: #0b0b0b; stroke-opacity: .45; stroke-width: 1; stroke-dasharray: 3 3; }}
  .s1 {{ fill: #2a78d6; }}
  .s2 {{ fill: #eb6834; }}
  .foot {{ fill: #52514e; font-size: 10px; }}
  @media (prefers-color-scheme: dark) {{
    .surface {{ fill: #1a1a19; }}
    .title, .marklab {{ fill: #ffffff; }}
    .sub, .legend, .tick, .foot {{ fill: #c3c2b7; }}
    .grid {{ stroke: #ffffff; stroke-opacity: .13; }}
    .mark {{ stroke: #ffffff; stroke-opacity: .5; }}
    .s1 {{ fill: #3987e5; }}
    .s2 {{ fill: #d95926; }}
  }}
</style>
<rect class="surface" width="{W}" height="{H}"/>
<text class="title" x="{PAD_L}" y="26">{case['id']}</text>
<text class="sub" x="{PAD_L}" y="45">{what}</text>
{chr(10).join(p)}
<text class="foot" x="{PAD_L}" y="{H - 3}">31% of comments in this corpus are moderator-removed with no text preserved — every bar is a floor, and this is one subreddit, not the world</text>
</svg>'''
    open(out_path, 'w').write(svg)
    return out_path, peak, len(all_items)


if __name__ == '__main__':
    want = sys.argv[1] if len(sys.argv) > 1 else None
    paths = sorted(glob.glob('eval/cases/*/case.json'))
    hit = [p for p in paths if not want or want in p]
    if not hit:
        sys.exit(f"no case matching {want!r}; have: "
                 + ', '.join(os.path.basename(os.path.dirname(p)) for p in paths))
    for path in hit:
        case = json.load(open(path))
        if case.get('kind') == 'control':
            continue
        series, source = load_labels(case['id'])
        if series is None:
            ents = json.load(open(os.path.join(os.path.dirname(path), 'entities.json')))
            series, source = load_candidates(case['id'], ents)
        out = os.path.join('eval', 'runs', f"spread-{case['id']}.svg")
        out, peak, total = render(case, series, source, out)
        print(f"{out}  ({total} items, peak week {peak})")
