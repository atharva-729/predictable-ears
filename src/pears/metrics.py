"""Per-user metrics, exactly as specified in METRICS.md.

A listen's artists are a credit: a non-empty tuple of artist keys, first-credited first.
Each credited artist gets weight 1/len(credit); a guess is a hit if it is in the credit.
With one artist per listen everything reduces to the single-artist definitions.
"""
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

MIN_TEST = 100
MIN_MONTH_LISTENS = 20
SESSION_GAP = 1800
BASELINES = ("repeat_last", "most_frequent", "markov1", "time_of_day")


def _ranked(counter, k):
    return [a for a, _ in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def _fill(first, fallback, k):
    out = list(first)
    for a in fallback:
        if len(out) >= k:
            break
        if a not in out:
            out.append(a)
    return out[:k]


def _add(counter, credit, w=1.0):
    share = w / len(credit)
    for a in credit:
        counter[a] += share


def _push(recent, credit, k):
    """Most-recent-first distinct artists; a credit's first artist ends up in front."""
    for a in reversed(credit):
        if a in recent:
            recent.remove(a)
        recent.insert(0, a)
    del recent[k:]


def _time_parts(ts, tz=timezone.utc):
    d = datetime.fromtimestamp(ts, tz)
    return d.year * 12 + d.month - 1, d.weekday() * 24 + d.hour, d.date().toordinal() - 719163  # days since 1970-01-01


def _credits(xs):
    return [tuple(x) if isinstance(x, (list, tuple, np.ndarray)) else (x,) for x in xs]


def predictability(credits, how, k=5, by_hour=None):
    """Hit@1 and hit@k for each baseline. credits: list of artist tuples; how: hour-of-week list.

    by_hour: optional dict; if given, filled with {baseline: [hits per hour-of-week]}
    and "n": [test listens per hour-of-week] (study only, for Phase 4 time patterns).
    """
    n = len(credits)
    n_train = int(n * 0.8)
    if n - n_train < MIN_TEST:
        return None
    hits = {b: [0, 0] for b in BASELINES}
    for i, true, preds in baseline_preds(credits, how, n_train, n, k):
        if by_hour is not None:
            by_hour.setdefault("n", [0] * 168)[how[i]] += 1
        for b, p in preds.items():
            if p and p[0] in true:
                hits[b][0] += 1
                if by_hour is not None:
                    by_hour.setdefault(b, [0] * 168)[how[i]] += 1
            if any(a in true for a in p[:k]):
                hits[b][1] += 1
    m = n - n_train
    return {b: (h1 / m, hk / m) for b, (h1, hk) in hits.items()}


def baseline_preds(credits, how, n_train, end, k=5):
    """Fit the baselines on credits[:n_train]; yield (i, true credit, {baseline: ranked
    list}) for each listen i in [n_train, end)."""
    train = credits[:n_train]
    freq = Counter()
    for c in train:
        _add(freq, c)
    mf = _ranked(freq, k)
    trans = defaultdict(Counter)  # previous artist -> next artist, weight 1/(|prev||next|)
    for a, b in zip(train, train[1:]):
        for x in a:
            _add(trans[x], b, 1 / len(a))
    tod = defaultdict(Counter)
    for c, h in zip(train, how[:n_train]):
        _add(tod[h], c)
    tod_rank = {h: _fill(_ranked(c, k), mf, k) for h, c in tod.items()}
    markov_rank = {}  # cache per previous credit

    recent = []
    for c in train:
        _push(recent, c, k)
    for i in range(n_train, end):
        true, prev = credits[i], credits[i - 1]
        if prev not in markov_rank:
            s = Counter()
            for x in prev:
                if x in trans:
                    for b, v in trans[x].items():
                        s[b] += v
            markov_rank[prev] = _fill(_ranked(s, k), mf, k)
        yield i, true, {
            "repeat_last": list(recent),
            "most_frequent": mf,
            "markov1": markov_rank[prev],
            "time_of_day": tod_rank.get(how[i], mf),
        }
        _push(recent, true, k)


def _runs(credits):
    """Run lengths; a run continues while consecutive listens share an artist."""
    runs, cur = [], 1
    for a, b in zip(credits, credits[1:]):
        if set(a) & set(b):
            cur += 1
        else:
            runs.append(cur)
            cur = 1
    runs.append(cur)
    return runs


def user_metrics(ts, artists, tracks, tz=timezone.utc, by_hour=False):
    """ts, artists, tracks: equal-length sequences sorted by ts. Each artists entry is a
    credit (list/tuple of artist keys) or a single key."""
    ts = [int(t) for t in ts]
    credits, tracks = _credits(artists), list(tracks)
    n = len(credits)
    parts = [_time_parts(t, tz) for t in ts]
    months = [p[0] for p in parts]
    how = [p[1] for p in parts]
    days = [p[2] for p in parts]
    out = {"n_listens": n}

    # predictability
    bh = {} if by_hour else None
    p = predictability(credits, how, by_hour=bh)
    if by_hour:
        out["hits_by_hour"] = bh
    if p is None:
        for b in BASELINES:
            out[f"{b}_top1"] = out[f"{b}_top5"] = None
        out.update(predictability_top1=None, predictability_top5=None, best_baseline=None)
    else:
        for b, (h1, h5) in p.items():
            out[f"{b}_top1"], out[f"{b}_top5"] = h1, h5
        best = max(BASELINES, key=lambda b: (p[b][0], -BASELINES.index(b)))
        out.update(predictability_top1=p[best][0],
                   predictability_top5=max(v[1] for v in p.values()),
                   best_baseline=best)
    tp = predictability([(t,) for t in tracks], how, k=1)
    out["track_repeat_last_top1"] = tp["repeat_last"][0] if tp else None
    out["track_most_frequent_top1"] = tp["most_frequent"][0] if tp else None

    # diversity (fractional counts)
    c = Counter()
    for cr in credits:
        _add(c, cr)
    probs = np.array(list(c.values()), dtype=float) / n
    h = float(-(probs * np.log(probs)).sum())
    out["entropy"] = h
    out["effective_artists"] = math.exp(h)
    out["concentration_top10"] = sum(sorted(c.values(), reverse=True)[:10]) / n
    out["n_artists"] = len(c)

    # exploration: a listen is new in proportion to its first-time credited artists
    first_month = months[0]
    seen, per_month = set(), defaultdict(lambda: [0.0, 0])
    new_h, post_h = [0.0] * 168, [0] * 168  # study only (by_hour): exploration by hour-of-week
    for cr, m, hw in zip(credits, months, how):
        if m - first_month >= 2:
            nw = sum(a not in seen for a in cr) / len(cr)
            per_month[m][1] += 1
            per_month[m][0] += nw
            new_h[hw] += nw
            post_h[hw] += 1
        seen.update(cr)
    if by_hour:
        out["explore_by_hour"] = {"new": new_h, "n": post_h}
        out["listens_by_hour24"] = [sum(1 for hw in how if hw % 24 == hr) for hr in range(24)]
    rates = {m: nw / tot for m, (nw, tot) in per_month.items() if tot >= MIN_MONTH_LISTENS}
    if rates:
        nw = sum(per_month[m][0] for m in sorted(rates))
        tot = sum(per_month[m][1] for m in rates)
        out["exploration_rate"] = nw / tot
    else:
        out["exploration_rate"] = None
    out["monthly_exploration"] = {int(m): r for m, r in sorted(rates.items())}
    breakouts = []
    if len(rates) >= 4:
        v = np.array([rates[m] for m in sorted(rates)])
        thr = v.mean() + 2 * v.std()
        breakouts = [int(m) for m, r in sorted(rates.items()) if r > thr]
    out["breakout_months"] = breakouts
    out["n_breakouts"] = len(breakouts)

    # loops and streaks
    by_day = defaultdict(Counter)
    for t, d in zip(tracks, days):
        by_day[d][t] += 1
    loop_days = []
    for d, cnt in sorted(by_day.items()):
        top, k = max(cnt.items(), key=lambda kv: (kv[1], kv[0]))
        if k >= 5 and k / sum(cnt.values()) >= 0.3:
            loop_days.append((d, top, k))
    span = months[-1] - months[0] + 1
    out["loop_days"] = len(loop_days)
    out["loop_days_per_month"] = len(loop_days) / span
    out["loop_day_list"] = loop_days
    ar, tr = _runs(credits), _runs([(t,) for t in tracks])
    out.update(artist_streak_mean=float(np.mean(ar)), artist_streak_max=int(max(ar)),
               track_streak_mean=float(np.mean(tr)), track_streak_max=int(max(tr)))

    # sessions
    gaps = np.diff(np.array(ts))
    out["n_sessions"] = int((gaps > SESSION_GAP).sum()) + 1
    out["listens_per_session"] = n / out["n_sessions"]
    return out


def run(dest="reports/user_metrics.parquet", log=print):
    """One row per sampled user, read one clean part at a time. Per-user lists (loop
    days etc.) stay in this local file only; nothing here is published."""
    import duckdb
    import pandas as pd

    from pears.clean import parts

    rows, files = [], parts()
    for fi, f in enumerate(files):
        df = duckdb.sql(f"SELECT user, ts, artists, track FROM '{f.as_posix()}' ORDER BY user, ts").df()
        for user, g in df.groupby("user", sort=False):
            r = user_metrics(g.ts.tolist(), g.artists.tolist(), g.track.tolist(), by_hour=True)
            for key in ("hits_by_hour", "explore_by_hour", "listens_by_hour24"):
                r[key] = json.dumps(r[key])
            r["user"] = user
            r["monthly_exploration"] = json.dumps(r["monthly_exploration"])
            r["monthly_loop_days"] = json.dumps(dict(Counter(_day_month(d) for d, _, _ in r.pop("loop_day_list"))))
            r["breakout_months"] = json.dumps(r["breakout_months"])
            rows.append(r)
        log(f"metrics part {fi + 1}/{len(files)}: {len(rows)} users")
    out = pd.DataFrame(rows)
    Path(dest).parent.mkdir(exist_ok=True)
    out.to_parquet(dest)
    return out


def _day_month(day):
    d = datetime.fromtimestamp(day * 86400, timezone.utc)
    return d.year * 12 + d.month - 1
