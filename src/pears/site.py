"""Build app/index.html (personal app) and docs/index.html (results page).

Both are single files with everything inlined; app/index.html makes no requests.
"""
import json
from pathlib import Path


def build_app(pop="app/population.json", out="app/index.html"):
    html = Path("app/template.html").read_text(encoding="utf-8")
    js = Path("app/metrics.js").read_text(encoding="utf-8")
    data = json.dumps(json.loads(Path(pop).read_text()), separators=(",", ":"))
    html = html.replace("/*METRICS_JS*/", js).replace("/*POPULATION_JSON*/", data.replace("</", "<\\/"))
    Path(out).write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build_app())
