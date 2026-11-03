"""Population results (Phase 4). Reads reports/user_metrics.parquet and data/clean.parquet,
writes aggregate-only JSON to reports/ and app/population.json.

Nothing written here contains a user hash or a per-user row.
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

FEATURES = ["predictability_top1", "entropy", "exploration_rate",
            "concentration_top10", "loop_days_per_month"]
PCT_METRICS = FEATURES + ["predictability_top5", "effective_artists", "n_breakouts",
                          "artist_streak_mean", "track_repeat_last_top1",
                          "repeat_last_top1", "most_frequent_top1", "markov1_top1",
                          "time_of_day_top1", "listens_per_session"]
HIGH_LOOP_DAYS = 3  # a "high-loop month" has at least this many loop days
SEED = 20261103


def _q(s):
    s = s.dropna()
    return {"median": float(s.median()), "q1": float(s.quantile(.25)), "q3": float(s.quantile(.75)),
            "mean": float(s.mean()), "n": int(len(s))}


def headline(m):
    return {
        "n_users": int(len(m)),
        "n_listens": int(m.n_listens.sum()),
        "predictability_top1": _q(m.predictability_top1),
        "predictability_top5": _q(m.predictability_top5),
        "share_top1_over_50": float((m.predictability_top1 > .5).mean()),
        "best_baseline_share": m.best_baseline.value_counts(normalize=True).round(4).to_dict(),
        "baseline_top1_median": {b: float(m[f"{b}_top1"].median()) for b in
                                 ["repeat_last", "most_frequent", "markov1", "time_of_day"]},
        "track_level_top1_median": {"repeat_last": float(m.track_repeat_last_top1.median()),
                                    "most_frequent": float(m.track_most_frequent_top1.median())},
        "effective_artists": _q(m.effective_artists),
        "exploration_rate": _q(m.exploration_rate),
        "concentration_top10": _q(m.concentration_top10),
        "loop_days_per_month": _q(m.loop_days_per_month),
        "share_with_breakout": float((m.n_breakouts > 0).mean()),
    }


def _name(c, overall):
    """Descriptive cluster name from standardised centroid values (z-scores)."""
    z = dict(zip(FEATURES, c))
    if z["loop_days_per_month"] > .8:
        return "Loopers"
    if z["exploration_rate"] > .8 or (z["entropy"] > .6 and z["predictability_top1"] < -.4):
        return "Explorers"
    if z["concentration_top10"] > .5 and z["predictability_top1"] > .3:
        return "Devotees"
    if z["predictability_top1"] > .5:
        return "Creatures of habit"
    if z["entropy"] > .3:
        return "Wide rotation"
    return "Steady rotation"


def clusters(m):
    d = m.dropna(subset=FEATURES).copy()
    sc = StandardScaler().fit(d[FEATURES])
    X = sc.transform(d[FEATURES])
    scores = {}
    for k in (3, 4, 5):
        km = KMeans(k, n_init=20, random_state=SEED).fit(X)
        scores[k] = float(silhouette_score(X, km.labels_, sample_size=min(len(X), 5000), random_state=SEED))
    k = max(scores, key=scores.get)
    km = KMeans(k, n_init=20, random_state=SEED).fit(X)
    d["cluster"] = km.labels_
    names, used = {}, set()
    for i, c in enumerate(km.cluster_centers_):
        n = _name(c, None)
        while n in used:
            n += " II"
        used.add(n)
        names[i] = n
    table = []
    for i in range(k):
        g = d[d.cluster == i]
        table.append({"cluster": names[i], "share": float(len(g) / len(d)), "n": int(len(g)),
                      **{f: float(g[f].median()) for f in FEATURES},
                      "effective_artists": float(g.effective_artists.median()),
                      "z": dict(zip(FEATURES, map(float, km.cluster_centers_[i])))})
    # scatter: binned 2-D counts per cluster, not individual points
    bins = d.assign(px=(d.predictability_top1 * 50).round() / 50,
                    ex=(d.exploration_rate * 50).round() / 50)
    scatter = (bins.groupby(["px", "ex", "cluster"]).size().reset_index(name="n")
               .assign(cluster=lambda x: x.cluster.map(names)).to_dict("records"))
    model = {"features": FEATURES, "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist(),
             "centers": km.cluster_centers_.tolist(), "names": [names[i] for i in range(k)]}
    return {"k": k, "silhouette": scores, "table": table, "scatter_binned": scatter}, model, d


def relationships(m):
    d = m.dropna(subset=["predictability_top1", "exploration_rate"])
    out = {"spearman_exploration_predictability":
           float(d.exploration_rate.corr(d.predictability_top1, method="spearman"))}
    b = pd.qcut(d.exploration_rate, 10, duplicates="drop")
    out["predictability_by_exploration_decile"] = [
        {"exploration_mid": float(iv.mid), "predictability_median": float(g.predictability_top1.median()),
         "q1": float(g.predictability_top1.quantile(.25)), "q3": float(g.predictability_top1.quantile(.75))}
        for iv, g in d.groupby(b, observed=True)]
    return out


def loop_breakout(m):
    """P(breakout in the next 1-2 months | high-loop month) vs other months."""
    after_loop, after_other = [0, 0], [0, 0]
    for _, r in m.iterrows():
        rates = {int(k): v for k, v in json.loads(r.monthly_exploration).items()}
        loops = {int(k): v for k, v in json.loads(r.monthly_loop_days).items()}
        br = set(json.loads(r.breakout_months))
        if len(rates) < 4:
            continue
        for mo in sorted(rates):
            nxt = [mo + 1, mo + 2]
            if not any(x in rates for x in nxt):
                continue
            hit = any(x in br for x in nxt)
            tgt = after_loop if loops.get(mo, 0) >= HIGH_LOOP_DAYS else after_other
            tgt[0] += hit
            tgt[1] += 1
    p1 = after_loop[0] / after_loop[1] if after_loop[1] else None
    p0 = after_other[0] / after_other[1] if after_other[1] else None
    return {"high_loop_days_threshold": HIGH_LOOP_DAYS,
            "breakout_rate_after_high_loop": p1, "n_high_loop_months": after_loop[1],
            "breakout_rate_after_other": p0, "n_other_months": after_other[1],
            "lift": (p1 / p0) if p1 is not None and p0 else None}


LOCAL_TROUGH_HOUR = 5  # assumed local hour of a user's quietest (sleep) time


def infer_offset(hour24):
    """UTC offset (hours, -12..+11) that puts the user's quietest 3-hour window at 05:00
    local. ListenBrainz has no timezone; this is an estimate from the daily rhythm."""
    h = np.array(hour24, dtype=float)
    smooth = h + np.roll(h, 1) + np.roll(h, -1)
    trough = int(np.argmin(smooth))
    return (LOCAL_TROUGH_HOUR - trough + 12) % 24 - 12


def time_patterns(m):
    """Predictability and exploration by hour-of-week, (a) in UTC for everyone and
    (b) shifted by each user's inferred offset. Both are reported."""
    out = {}
    offsets = [infer_offset(json.loads(r)) for r in m.listens_by_hour24]
    out["inferred_offset_counts"] = {int(k): int(v) for k, v in
                                     sorted(pd.Series(offsets).value_counts().items())}
    for label, shift in (("utc", False), ("local", True)):
        hits, n, new, post = (np.zeros(168) for _ in range(4))
        for (_, r), off in zip(m.iterrows(), offsets):
            k = off if shift else 0
            eh = json.loads(r.explore_by_hour)
            new += np.roll(np.array(eh["new"]), k)
            post += np.roll(np.array(eh["n"]), k)
            if r.best_baseline:
                bh = json.loads(r.hits_by_hour)
                hits += np.roll(np.array(bh.get(r.best_baseline, [0] * 168)), k)
                n += np.roll(np.array(bh["n"]), k)
        pred = np.where(n > 0, hits / np.maximum(n, 1), np.nan)
        exr = np.where(post > 0, new / np.maximum(post, 1), np.nan)
        wk = lambda a, w, sl: float(np.nansum(a[sl] * w[sl]) / w[sl].sum())
        day = lambda a, w: [float(np.nansum(a[h::24] * w[h::24]) / w[h::24].sum()) for h in range(24)]
        out[label] = {
            "predictability_by_how": [None if np.isnan(x) else float(x) for x in pred],
            "exploration_by_how": [None if np.isnan(x) else float(x) for x in exr],
            "predictability_by_hour": day(pred, n), "exploration_by_hour": day(exr, post),
            "test_listens_by_how": n.astype(int).tolist(),
            "predictability_weekday": wk(pred, n, slice(0, 120)),
            "predictability_weekend": wk(pred, n, slice(120, 168)),
            "exploration_weekday": wk(exr, post, slice(0, 120)),
            "exploration_weekend": wk(exr, post, slice(120, 168)),
        }
        ph = out[label]["predictability_by_hour"]
        out[label]["hour_of_day_range_pts"] = float((max(ph) - min(ph)) * 100)
    out["note"] = ("ListenBrainz has no user timezone. 'utc' treats every user as UTC; 'local' "
                   f"shifts each user so their quietest hours fall at {LOCAL_TROUGH_HOUR}:00.")
    return out


def drift(m):
    rows = []
    for _, r in m.iterrows():
        for k, v in json.loads(r.monthly_exploration).items():
            rows.append((int(k), v))
    d = pd.DataFrame(rows, columns=["month", "rate"])
    g = d.groupby("month").rate.agg(["mean", "median", "count"]).reset_index()
    g["label"] = g.month.map(lambda x: f"{x // 12}-{x % 12 + 1:02d}")
    slope = float(np.polyfit(g.month - g.month.min(), g["mean"], 1)[0]) if len(g) > 2 else None
    return {"by_month": g.drop(columns="month").to_dict("records"),
            "slope_per_month": slope,
            "note": "Weak evidence: one year, seasonality, and users' warm-up months differ."}


def composites(table):
    cards = []
    for c in table:
        cards.append({
            "name": c["cluster"], "label": "composite, not a real person", "share": c["share"],
            "predictability_top1": c["predictability_top1"],
            "effective_artists": c["effective_artists"],
            "exploration_rate": c["exploration_rate"],
            "concentration_top10": c["concentration_top10"],
            "loop_days_per_month": c["loop_days_per_month"],
            "line": (f"Next artist guessed {c['predictability_top1']:.0%} of the time; "
                     f"{c['effective_artists']:.0f} effective artists; "
                     f"{c['exploration_rate']:.0%} of listens are first-time artists; "
                     f"{c['loop_days_per_month']:.1f} loop days a month."),
        })
    return cards


def percentiles(m):
    qs = np.linspace(0, 1, 101)
    return {k: [float(x) for x in m[k].dropna().quantile(qs)] for k in PCT_METRICS if k in m}


def histograms(m):
    out = {}
    for k, lo, hi in [("predictability_top1", 0, 1), ("predictability_top5", 0, 1),
                      ("exploration_rate", 0, .6), ("entropy", 0, 8),
                      ("effective_artists", 0, 600), ("concentration_top10", 0, 1),
                      ("loop_days_per_month", 0, 15)]:
        v = m[k].dropna().clip(lo, hi)
        c, e = np.histogram(v, bins=40, range=(lo, hi))
        out[k] = {"edges": e.tolist(), "counts": c.tolist(), "median": float(v.median())}
    return out


def run():
    m = pd.read_parquet("reports/user_metrics.parquet")
    res = {"headline": headline(m), "histograms": histograms(m)}
    res["clusters"], model, _ = clusters(m)
    res["relationships"] = relationships(m)
    res["loop_breakout"] = loop_breakout(m)
    res["time_patterns"] = time_patterns(m)
    res["drift"] = drift(m)
    res["composites"] = composites(res["clusters"]["table"])
    Path("reports").mkdir(exist_ok=True)
    Path("reports/population.json").write_text(json.dumps(res, indent=1))
    pop = {"source": "ListenBrainz, 2,000 sampled listeners, Nov 2025 - Oct 2026 (CC0)",
           "n_users": res["headline"]["n_users"], "percentiles": percentiles(m),
           "cluster_model": model, "composites": res["composites"],
           "headline": {k: res["headline"][k] for k in
                        ["predictability_top1", "predictability_top5", "effective_artists",
                         "exploration_rate", "share_top1_over_50"]}}
    Path("app/population.json").write_text(json.dumps(pop))
    return res


if __name__ == "__main__":
    r = run()
    print(json.dumps(r["headline"], indent=1))
