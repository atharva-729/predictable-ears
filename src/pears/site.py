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


# Light/dark toggle shared by both GitHub pages. The pages follow the system theme;
# the toggle sets data-theme on <html> and remembers the choice in this browser.
THEME_HEAD = ("<script>try{var t=localStorage.getItem('pe-theme');"
              "if(t)document.documentElement.dataset.theme=t}catch(e){}</script>\n")
THEME_TOGGLE = """<script>
(function () {
  var r = document.documentElement, b = document.getElementById("theme-toggle");
  if (!b) return;
  function eff() { return r.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); }
  function label() { var d = eff() === "dark"; b.textContent = d ? "Light mode" : "Dark mode"; b.setAttribute("aria-label", "Switch to " + (d ? "light" : "dark") + " mode"); }
  b.addEventListener("click", function () {
    var next = eff() === "dark" ? "light" : "dark";
    r.dataset.theme = next;
    try { localStorage.setItem("pe-theme", next); } catch (e) {}
    label();
    dispatchEvent(new Event("resize"));  // redraw charts with the new colours
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", label);
  label();
})();
</script>
"""
EXPLAINER_BODY = Path(__file__).with_name("explainer") / "body.html"
EXPLAINER_TOGGLE_CSS = """<style>
.theme-toggle{position:fixed;top:calc(env(safe-area-inset-top,0px) + 12px);right:max(12px,env(safe-area-inset-right,0px));z-index:20;
  font:600 12px var(--display);padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:var(--sheet);color:var(--ink);cursor:pointer}
.theme-toggle:hover{border-color:var(--cobalt)}
</style>
"""


def build_explainer(out="docs/explainer.html"):
    """The explainer artifact's body, wrapped as a standalone page with a theme toggle."""
    src = EXPLAINER_BODY.read_text(encoding="utf-8")
    head, body = src.split("</style>", 1)
    html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<meta name="description" content="The whole Predictable Ears project explained: idea, theory, data, '
            'plan vs reality, results, conclusions and business sense.">\n'
            + THEME_HEAD + head + "</style>\n" + EXPLAINER_TOGGLE_CSS + "</head>\n<body>\n"
            + '<button type="button" class="theme-toggle" id="theme-toggle">Dark mode</button>\n'
            + body + THEME_TOGGLE + "</body>\n</html>\n")
    Path(out).write_text(html, encoding="utf-8")
    return out


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
            .replace("/*DATA*/", _inline(data)).replace("/*NARRATIVE*/", narrative)
            .replace("</head>", THEME_HEAD + "</head>", 1).replace("</body>", THEME_TOGGLE + "</body>", 1))
    Path(out).parent.mkdir(exist_ok=True)
    Path(out).write_text(html, encoding="utf-8")
    Path(out).with_name(".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build_app())
    print(build_docs())
    print(build_explainer())
