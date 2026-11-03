"""Python and JS metric implementations must agree on the synthetic listeners."""
import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))
import synthetic as s
from pears.metrics import user_metrics


def _messy(seed=3):
    # irregular gaps, loops, ties: exercises every code path
    r = random.Random(seed)
    t, ts, arts, trs = 1700000000, [], [], []
    for i in range(5000):
        t += r.choice([60, 200, 4000, 90000])
        a = r.choice(["a", "b", "c", "d"]) if r.random() < 0.7 else f"n{i}"
        tr = a + "|" + r.choice(["x", "x", "y"])
        if r.random() < 0.15:  # collab credits
            a = [a, r.choice(["b", "e", f"f{i % 7}"])]
            if a[1] == a[0]:
                a = a[:1]
        ts.append(t); arts.append(a); trs.append(tr)
    return {"ts": ts, "artists": arts, "tracks": trs}


def _close(a, b, path=""):
    if isinstance(a, dict):
        assert set(map(str, a)) == set(map(str, b)), path
        bb = {str(k): v for k, v in b.items()}
        for k, v in a.items():
            _close(v, bb[str(k)], f"{path}.{k}")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12), (path, a, b)
    else:
        assert a == b, (path, a, b)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_parity(tmp_path):
    users = {k: f() for k, f in s.ALL.items()} | {"messy": _messy()}
    src = tmp_path / "u.json"
    src.write_text(json.dumps(users))
    js = json.loads(subprocess.run(["node", str(HERE / "parity.mjs"), str(src)],
                                   capture_output=True, text=True, check=True).stdout)
    for k, u in users.items():
        py = json.loads(json.dumps(user_metrics(u["ts"], u["artists"], u["tracks"])))
        _close(py, js[k], k)


NAMES = ["BTS, Halsey", "Kanye West, Ye", "Torsten Abrolat & Regen Macher", "The  Beatles",
         "Daft Punk feat. Pharrell Williams", "Unknown Artist", "Various Artists, Björk",
         "BTS, Halsey • From Smart Shuffle", "  ADAMS AVENUE ", "Ado & Hatsune Miku",
         "Jay-Z ft. Kanye West", "Simon & Garfunkel", "Bach with Glenn Gould", ""]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_artist_split_parity():
    import duckdb
    from pears.clean import PLACEHOLDER_NAMES, _parts
    con = duckdb.connect()
    sql = [con.execute(f"SELECT {_parts('?')}", [n]).fetchone()[0] for n in NAMES]
    con.close()
    py = [list(dict.fromkeys(a for a in parts if a not in PLACEHOLDER_NAMES)) for parts in sql]
    js = json.loads(subprocess.run(
        ["node", "-e", "const P=require(process.argv[1]);console.log(JSON.stringify(JSON.parse(process.argv[2]).map(P.splitArtists)))",
         str(HERE.parent / "app" / "metrics.js"), json.dumps(NAMES)],
        capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    assert py == js, list(zip(NAMES, py, js))
    assert js[0] == ["bts", "halsey"] and js[5] == [] and js[7] == ["bts", "halsey"]
