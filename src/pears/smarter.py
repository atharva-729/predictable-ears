"""Phase 5 (optional): is a smarter model much better than the best dumb rule?

Model: a per-user weighted vote of the four baselines. Each baseline gives its top-5
artists rank scores 5, 4, ..., 1; an artist's score is the weighted sum, and the top
scorer is the prediction. Weights are chosen per user by grid search on an inner split
(baselines fit on the first 80% of training, scored on the last 20% of training), then
evaluated on the same test split as the headline metric.

Also reported: the "oracle switcher" ceiling, the share of test listens where at least
one baseline's top-1 is right. No combination of these rules can beat it.
"""
import itertools
import json
from collections import defaultdict
from datetime import timezone
from pathlib import Path

import duckdb
import numpy as np

from pears.metrics import BASELINES, MIN_TEST, _time_parts, baseline_preds

GRID = np.array([w for w in itertools.product((0, 1, 2, 3), repeat=4) if any(w)], dtype=float)
MAXC = 4 * 5  # at most 20 distinct candidates per listen


def _tensor(rows):
    """rows: [(true, preds)] -> R (m, MAXC, 4) rank scores, T (m, MAXC) is-true mask.

    Candidates are sorted by artist key descending, so argmax breaks score ties toward
    the larger key (same rule as max() over (score, key) pairs)."""
    m = len(rows)
    R, T = np.zeros((m, MAXC, 4)), np.zeros((m, MAXC), bool)
    for i, (t, p) in enumerate(rows):
        cands = sorted({a for b in BASELINES for a in p[b][:5]}, reverse=True)
        pos = {a: j for j, a in enumerate(cands)}
        for bi, b in enumerate(BASELINES):
            for r, a in enumerate(p[b][:5]):
                R[i, pos[a], bi] = 5 - r
        for a in t:  # t is the listen's credit: any credited artist is a hit
            if a in pos:
                T[i, pos[a]] = True
    return R, T


def _hits(R, T, W):
    """Hits for each weight vector in W (g, 4) -> (g,)."""
    S = R @ W.T  # (m, MAXC, g)
    pick = S.argmax(axis=1)  # (m, g)
    return np.take_along_axis(T, pick, axis=1).sum(axis=0)


def user(artists, how):
    n = len(artists)
    n_train = int(n * .8)
    if n - n_train < MIN_TEST:
        return None
    inner = int(n_train * .8)
    val = [(t, p) for _, t, p in baseline_preds(artists, how, inner, n_train)]
    h = _hits(*_tensor(val), GRID)
    # most hits; ties -> smallest total weight, then grid order
    w = GRID[np.lexsort((np.arange(len(GRID)), GRID.sum(1), -h))[0]]
    test = [(t, p) for _, t, p in baseline_preds(artists, how, n_train, n)]
    best_single = max(sum(bool(p[b]) and p[b][0] in t for t, p in test) for b in BASELINES)
    oracle = sum(any(p[b] and p[b][0] in t for b in BASELINES) for t, p in test)
    m = len(test)
    mix = int(_hits(*_tensor(test), w[None])[0])
    return {"best_single": best_single / m, "mixture": mix / m,
            "oracle": oracle / m, "weights": dict(zip(BASELINES, map(int, w)))}


def run(log=print):
    from pears.clean import parts
    from pears.metrics import _credits

    res, files = [], parts()
    for fi, f in enumerate(files):
        df = duckdb.sql(f"SELECT user, ts, artists FROM '{f.as_posix()}' ORDER BY user, ts").df()
        for _, g in df.groupby("user", sort=False):
            how = [_time_parts(int(t), timezone.utc)[1] for t in g.ts]
            r = user(_credits(g.artists.tolist()), how)
            if r:
                res.append(r)
        log(f"smarter part {fi + 1}/{len(files)}: {len(res)} users")
    bs, mx, orc = (np.array([r[k] for r in res]) for k in ("best_single", "mixture", "oracle"))
    gain = mx - bs
    top_w = defaultdict(int)
    for r in res:
        top_w[max(r["weights"], key=r["weights"].get)] += 1
    out = {"n_users": len(res),
           "best_single_median": float(np.median(bs)), "mixture_median": float(np.median(mx)),
           "oracle_median": float(np.median(orc)),
           "gain_median_pts": float(np.median(gain) * 100), "gain_mean_pts": float(gain.mean() * 100),
           "share_users_gain_over_5pts": float((gain > .05).mean()),
           "share_users_mixture_worse": float((gain < 0).mean()),
           "heaviest_weight_share": {k: v / len(res) for k, v in top_w.items()}}
    Path("reports/smarter.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
