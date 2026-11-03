"""Personal data is never tracked; published outputs hold no user identifiers."""
import re
import subprocess
from pathlib import Path

import duckdb

ROOT = Path(__file__).parents[1]
PUBLISHED = [ROOT / "docs", ROOT / "app" / "population.json", ROOT / "reports" / "population.json"]


def test_no_personal_files_tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    bad = [f for f in out.splitlines()
           if f.startswith("personal/") or re.search(r"Streaming_History.*\.json$", f)]
    assert not bad, bad


def _hashes():
    p = ROOT / "data" / "users.parquet"
    if not p.exists():
        return set()
    return {r[0] for r in duckdb.sql(f"SELECT user FROM '{p.as_posix()}'").fetchall()}


def test_published_outputs_have_no_user_hashes():
    hashes = _hashes()
    for p in PUBLISHED:
        files = [p] if p.is_file() else list(p.rglob("*")) if p.exists() else []
        for f in files:
            if f.is_file() and f.suffix in (".html", ".json", ".js", ".md"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                found = set(re.findall(r"\b[0-9a-f]{16}\b", text)) & hashes
                assert not found, (f, list(found)[:3])
