"""Spark-dump Parquet → per-user stats, sample, and sampled listens (Phase 1).

Runs one calendar month at a time so the machine stays usable (8 GB laptop): each step
reads only that month's files, on few threads, at below-normal CPU priority.

Pass 1, per month: per user-day counts (listens, duplicate timestamps, gaps < 30 s),
  saved to data/raw/daystats/<month>.parquet (small).
Combine: per-user stats → eligibility + bot filters → seeded sample.
Pass 2, per month: the sampled users' listens → data/listens.parquet.
User ids are hashed with the salt from .env; raw ids are never written outside data/raw.
"""
import ctypes
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import duckdb
import yaml

RAW = Path("data/raw/spark")
DAYSTATS = Path("data/raw/daystats")
PARTS = Path("data/raw/sampled")


def _cfg():
    return yaml.safe_load(open("config.yaml"))


def _salt():
    for line in open(".env"):
        if line.startswith("PEARS_SALT="):
            return line.strip().split("=", 1)[1]
    raise SystemExit("PEARS_SALT missing from .env")


def _low_priority():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    else:
        os.nice(10)


def connect(cfg):
    con = duckdb.connect()
    con.execute(f"SET threads={cfg['duckdb_threads']}")
    con.execute(f"SET memory_limit='{cfg['duckdb_memory']}'")
    con.execute("SET temp_directory='data/raw/duckdb_tmp'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET TimeZone='UTC'")
    return con


def months(cfg):
    m = dt.date.fromisoformat(str(cfg["window_start"]))
    end = dt.date.fromisoformat(str(cfg["window_end"]))
    while m < end:
        nxt = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield m, nxt
        m = nxt


def month_files(lo, hi):
    """Files whose listened_at range overlaps [lo, hi). Uses data/raw/file_ranges.json."""
    ranges = json.loads(Path("data/raw/file_ranges.json").read_text())
    a = dt.datetime(lo.year, lo.month, 1, tzinfo=dt.timezone.utc).timestamp()
    b = dt.datetime(hi.year, hi.month, 1, tzinfo=dt.timezone.utc).timestamp()
    return [str(RAW / f).replace("\\", "/") for f, (mn, mx, _) in ranges.items() if mn < b and mx >= a]


def _src(lo, hi):
    return (f"read_parquet({month_files(lo, hi)!r}) WHERE listened_at >= TIMESTAMP '{lo}' "
            f"AND listened_at < TIMESTAMP '{hi}'")


def pass1(con, cfg, log):
    DAYSTATS.mkdir(parents=True, exist_ok=True)
    for lo, hi in months(cfg):
        out = DAYSTATS / f"{lo:%Y-%m}.parquet"
        if out.exists():
            continue
        t = time.time()
        con.execute(f"""
            COPY (
              WITH l AS (SELECT user_id, epoch(listened_at)::BIGINT AS ts FROM {_src(lo, hi)}),
              g AS (SELECT user_id, ts // 86400 AS day,
                           ts - lag(ts) OVER (PARTITION BY user_id, ts // 86400 ORDER BY ts) AS gap
                    FROM l)
              SELECT user_id, day, '{lo:%Y-%m}' AS month, count(*)::INT AS n,
                     count(*) FILTER (WHERE gap = 0)::INT AS n_dup_ts,
                     count(*) FILTER (WHERE gap < 30)::INT AS n_fast_gaps
              FROM g GROUP BY ALL
            ) TO '{out.as_posix()}.tmp' (FORMAT parquet)
        """)
        os.replace(f"{out}.tmp", out)
        log(f"pass 1 {lo:%Y-%m}: {time.time() - t:.0f}s")


def select_users(con, cfg):
    s, b = cfg["sample"], cfg["bots"]
    con.execute(f"""
        CREATE OR REPLACE TABLE users AS
        WITH d AS (
          -- fast day: median gap < 30 s <=> more than half of that day's gaps are < 30 s
          SELECT *, n >= {b['min_day_listens_for_gap_check']} AND n_fast_gaps > (n - 1) / 2 AS fast
          FROM '{DAYSTATS.as_posix()}/*.parquet'),
        u AS (
          -- volume stats exclude fast days: a user with <= max_fast_days of them is kept,
          -- and those days' listens are dropped in pass 2
          SELECT user_id, count(*) FILTER (WHERE fast) AS fast_days,
                 coalesce(sum(n) FILTER (WHERE NOT fast), 0) AS listens,
                 count(DISTINCT month) FILTER (WHERE NOT fast) AS active_months,
                 max(n) FILTER (WHERE NOT fast) AS max_day_listens,
                 sum(n_dup_ts) FILTER (WHERE NOT fast) / sum(n) FILTER (WHERE NOT fast) AS identical_ts_share,
                 coalesce(sum(n) FILTER (WHERE fast), 0) AS fast_day_listens
          FROM d GROUP BY user_id)
        SELECT *, CASE
            WHEN fast_days > {b['max_fast_days']} THEN 'bot_fast_day'
            WHEN listens < {s['min_listens']} THEN 'too_few_listens'
            WHEN active_months < {s['min_active_months']} THEN 'too_few_active_months'
            WHEN max_day_listens > {b['max_listens_per_day']} THEN 'bot_day_volume'
            WHEN identical_ts_share > {b['max_identical_ts_share']} THEN 'bot_identical_ts'
            ELSE 'eligible' END AS status
        FROM u
    """)
    salt, seed = _salt(), s["seed"]
    con.execute(f"""
        ALTER TABLE users ADD COLUMN user VARCHAR;
        UPDATE users SET user = sha256('{salt}' || user_id::VARCHAR)[:16];
        ALTER TABLE users ADD COLUMN sampled BOOLEAN DEFAULT false;
        UPDATE users SET sampled = true WHERE user_id IN (
          SELECT user_id FROM users WHERE status = 'eligible'
          ORDER BY sha256('{seed}' || user) LIMIT {s['n']});
    """)
    con.execute("COPY (SELECT * EXCLUDE (user_id) FROM users) TO 'data/users.parquet' (FORMAT parquet)")


def pass2(con, cfg, log):
    PARTS.mkdir(parents=True, exist_ok=True)
    con.execute("CREATE OR REPLACE TABLE sample AS SELECT user_id, user FROM users WHERE sampled")
    b = cfg["bots"]
    con.execute(f"""
        CREATE OR REPLACE TABLE fast_days AS
        SELECT d.user_id, d.day FROM '{DAYSTATS.as_posix()}/*.parquet' d SEMI JOIN sample USING (user_id)
        WHERE d.n >= {b['min_day_listens_for_gap_check']} AND d.n_fast_gaps > (d.n - 1) / 2
    """)
    for lo, hi in months(cfg):
        out = PARTS / f"{lo:%Y-%m}.parquet"
        t = time.time()
        con.execute(f"""
            COPY (
              SELECT s.user, epoch(r.listened_at)::BIGINT AS ts, r.artist_name,
                     r.artist_credit_mbids AS artist_mbids, r.recording_name,
                     r.recording_mbid, r.release_name
              FROM (SELECT *, epoch(listened_at)::BIGINT // 86400 AS day FROM {_src(lo, hi)}) r
              JOIN sample s USING (user_id)
              ANTI JOIN fast_days f ON f.user_id = r.user_id AND f.day = r.day
            ) TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
        """)
        log(f"pass 2 {lo:%Y-%m}: {time.time() - t:.0f}s")
    con.execute(f"""
        COPY (SELECT * FROM '{PARTS.as_posix()}/*.parquet' ORDER BY user, ts)
        TO 'data/listens.parquet' (FORMAT parquet, COMPRESSION zstd)
    """)


def run(only_month=None):
    cfg = _cfg()
    _low_priority()
    os.makedirs("data/raw/duckdb_tmp", exist_ok=True)
    con = connect(cfg)
    log = lambda m: print(m, flush=True)
    if only_month:  # timing test: one month of pass 1
        cfg = dict(cfg, window_start=only_month, window_end=(dt.date.fromisoformat(only_month)
                   .replace(day=28) + dt.timedelta(days=4)).replace(day=1).isoformat())
        pass1(con, cfg, log)
        return
    pass1(con, cfg, log)
    t = time.time()
    select_users(con, cfg)
    log(f"select users: {time.time() - t:.0f}s")
    pass2(con, cfg, log)
    return con


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
