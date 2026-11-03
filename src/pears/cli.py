"""pears <step>: sizes | download | ingest | clean | metrics | smarter | population | site"""
import json
import sys
import threading
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))
from pears import download as dl  # noqa: E402

TAIL_INDEX = Path("data/raw/spark_tail_index.json")
# First member before the window (2025-10-02), found with find_header + ts_range probes.
TAIL_START = 215594033152


def cfg():
    return yaml.safe_load(open("config.yaml"))


def sizes():
    idx = json.loads(TAIL_INDEX.read_text())
    tot = sum(m["size"] for m in idx["members"])
    print(f"{len(idx['members'])} files, {tot / 1e9:.1f} GB (done={idx.get('done')})")


def download():
    """Walk the tar from TAIL_START and download each parquet member as it is found."""
    url = cfg()["spark_tar"]
    done = threading.Event()

    def walker():
        try:
            dl.index_tar(url, resume=True, start=TAIL_START, path=TAIL_INDEX)
        finally:
            done.set()

    from concurrent.futures import ThreadPoolExecutor

    def one(m):
        dest = dl.Path("data/raw/spark") / m["name"].split("/")[-1]
        t = time.time()
        dl.fetch(url, m, dest)
        print(f"{dest.name} {m['size'] / 1e6:.0f} MB in {time.time() - t:.0f}s", flush=True)

    threading.Thread(target=walker, daemon=True).start()
    pool = ThreadPoolExecutor(3)  # 3 files x 8 connections each
    got = set()
    while True:
        try:
            idx = json.loads(TAIL_INDEX.read_text())
        except (OSError, ValueError):
            idx = {"members": []}
        todo = [m for m in idx["members"] if m["name"].endswith(".parquet") and m["name"] not in got]
        futs = [pool.submit(one, m) for m in todo]
        got.update(m["name"] for m in todo)
        for f in futs:
            f.result()
        if not todo:
            if done.is_set():
                break
            time.sleep(5)


def main():
    step = sys.argv[1]
    if step in ("sizes", "download"):
        globals()[step]()
    elif step == "ingest":
        from pears import ingest
        ingest.run()
    elif step == "clean":
        from pears import clean
        print(json.dumps(clean.run(), indent=1, default=str))
    elif step == "metrics":
        from pears import metrics
        metrics.run()
    elif step == "smarter":
        from pears import smarter
        print(json.dumps(smarter.run(), indent=1))
    elif step == "population":
        from pears import population
        population.run()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
