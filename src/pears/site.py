"""Build app/index.html (personal app) and docs/index.html (results page).

Both are single files with everything inlined. app/index.html makes no requests.
docs/index.html is built only from aggregate JSON; no user hash or per-user row.
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DOCS_TEMPLATE = Path(__file__).with_name("site_template.html")


def _inline(data):
    return json.dumps(data, separators=(",", ":"), default=float).replace("</", "<\\/")


def build_app(pop="app/population.json", out="app/index.html"):
    html = Path("app/template.html").read_text(encoding="utf-8")
    js = Path("app/metrics.js").read_text(encoding="utf-8")
    data = json.loads(Path(pop).read_text(encoding="utf-8"))
    html = html.replace("/*METRICS_JS*/", js).replace("/*POPULATION_JSON*/", _inline(data))
    Path(out).write_text(html, encoding="utf-8")
    return out


def _funnel():
    """Aggregate sampling counts (no user ids)."""
    rows = duckdb.sql("SELECT status, count(*) AS n, sum(sampled::INT) AS s FROM 'data/users.parquet' GROUP BY 1").fetchall()
    by = {r[0]: int(r[1]) for r in rows}
    return {"window_users": sum(by.values()), "by_status": by,
            "eligible": by.get("eligible", 0), "sampled": int(sum(r[2] for r in rows))}


def _volume_hist(m):
    v = np.log10(m.n_listens.clip(lower=1))
    c, e = np.histogram(v, bins=30)
    return {"log10_edges": e.tolist(), "counts": c.tolist(),
            "median": float(m.n_listens.median()), "q1": float(m.n_listens.quantile(.25)),
            "q3": float(m.n_listens.quantile(.75)), "max": int(m.n_listens.max())}


def build_docs(out="docs/index.html"):
    m = pd.read_parquet("reports/user_metrics.parquet")
    data = {
        "pop": json.loads(Path("reports/population.json").read_text(encoding="utf-8")),
        "smarter": json.loads(Path("reports/smarter.json").read_text(encoding="utf-8")),
        "clean": {k: v for k, v in json.loads(Path("reports/clean_report.json").read_text(encoding="utf-8")).items()
                  if k not in ("name_spelling_merges",)},
        "funnel": _funnel(),
        "volume": _volume_hist(m),
    }
    narrative = DOCS_TEMPLATE.with_name("site_narrative.js").read_text(encoding="utf-8")
    html = (DOCS_TEMPLATE.read_text(encoding="utf-8")
            .replace("/*DATA*/", _inline(data)).replace("/*NARRATIVE*/", narrative))
    Path(out).parent.mkdir(exist_ok=True)
    Path(out).write_text(html, encoding="utf-8")
    Path(out).with_name(".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build_app())
    print(build_docs())
