"""Dedupe, artist identity, sessions, warm-up months (Phase 2).

data/listens.parquet → data/clean/part-XX.parquet (users split into N_PARTS groups, each
part sorted by user, ts), plus reports/clean_report.json.

Every credited artist is kept: a listen has a list of artist keys (METRICS.md, "Artist
identity"). Global work runs on one row per distinct raw credit (artist_name,
artist_mbids), which is small; per-listen work runs one user group at a time so each
step fits in memory on an 8 GB laptop.

Normalisation follows METRICS.md and matches PEARS.splitArtists in app/metrics.js.
"""
import json
import time
from pathlib import Path

from pears.ingest import _cfg, _low_priority, connect

SPLIT = r" feat\. | feat | ft\. | ft | featuring | & |, | with "
# Placeholders, not artists. Listens credited only to these are recovered or dropped.
PLACEHOLDER_NAMES = ["unknown artist", "unknown", "[unknown]", "<unknown>", "various artists",
                     "various", "va", "[no artist]", "no artist", "[anonymous]", "anonymous"]
PLACEHOLDER_MBIDS = ["89ad4ac3-39f7-470e-963a-56509c546377",  # Various Artists
                     "125ec42a-7229-4250-afc5-e057484327fe"]  # [unknown]
N_PARTS = 16
OUT = Path("data/clean")
SRC = "'data/listens.parquet'"
CID = "hash(artist_name, artist_mbids)"  # one 64-bit key per distinct raw credit


def _norm(col):
    # strip import junk such as "BTS, Halsey • From Smart Shuffle", then lower/trim
    s = f"regexp_replace(coalesce({col}, ''), '\\s*\\x{{2022}}.*$', '')"
    return f"regexp_replace(trim(lower(nfc_normalize({s}))), '\\s+', ' ', 'g')"


def _parts(col):
    return (f"list_filter(list_transform(regexp_split_to_array({_norm(col)}, '{SPLIT}'), "
            f"lambda x: trim(x)), lambda x: x <> '')")


def parts():
    return sorted(OUT.glob("part-*.parquet"))


def glob():
    return f"'{OUT.as_posix()}/part-*.parquet'"


def _sql_list(xs):
    return "[" + ", ".join("'" + x.replace("'", "''") + "'" for x in xs) + "]"


def build_credit_tables(con):
    """credit_artists: one row per distinct raw credit (cid) with `artists`, the ordered
    list of artist keys."""
    ph_names, ph_mbids = _sql_list(PLACEHOLDER_NAMES), _sql_list(PLACEHOLDER_MBIDS)
    con.execute(f"""
        CREATE TABLE credits AS
        SELECT {CID} AS cid, artist_name, artist_mbids, count(*) AS n, {_parts('artist_name')} AS parts
        FROM {SRC} GROUP BY artist_name, artist_mbids
    """)
    # name part -> MBID, learned from tagged credits (zip parts with MBIDs when the
    # counts line up; otherwise only first part <-> first MBID)
    con.execute(f"""
        CREATE TABLE part_mbid AS
        SELECT part, arg_max(mbid, n) AS mbid FROM (
          SELECT unnest(parts) AS part, unnest(artist_mbids) AS mbid, n FROM credits
          WHERE len(artist_mbids) > 0 AND len(parts) = len(artist_mbids)
          UNION ALL
          SELECT parts[1], artist_mbids[1], n FROM credits
          WHERE len(artist_mbids) > 0 AND len(parts) <> len(artist_mbids) AND len(parts) > 0)
        WHERE NOT list_contains({ph_names}, part) AND NOT list_contains({ph_mbids}, mbid)
        GROUP BY part
    """)
    # artist keys per credit: tagged -> its MBIDs; untagged -> each name part, mapped to
    # an MBID when one is known. Placeholders and duplicates removed, order kept.
    con.execute(f"""
        CREATE TABLE credit_artists AS
        WITH tagged AS (
          SELECT cid, generate_subscripts(artist_mbids, 1) AS pos, unnest(artist_mbids) AS key
          FROM credits WHERE len(artist_mbids) > 0),
        untagged AS (
          SELECT u.cid, u.pos, coalesce(pm.mbid, u.part) AS key FROM (
            SELECT cid, generate_subscripts(parts, 1) AS pos, unnest(parts) AS part
            FROM credits WHERE coalesce(len(artist_mbids), 0) = 0) u
          LEFT JOIN part_mbid pm USING (part)),
        keyed AS (
          SELECT cid, key, min(pos) AS pos FROM (SELECT * FROM tagged UNION ALL SELECT * FROM untagged)
          WHERE NOT list_contains({ph_mbids}, key) AND NOT list_contains({ph_names}, key)
          GROUP BY cid, key),
        lists AS (SELECT cid, list(key ORDER BY pos) AS artists FROM keyed GROUP BY cid)
        SELECT c.cid, c.artist_name, c.artist_mbids, c.n, c.parts, coalesce(l.artists, []) AS artists
        FROM credits c LEFT JOIN lists l USING (cid)
    """)


def build_recovery(con):
    """For listens whose credit is only placeholders: the artists of the same recording
    (by recording MBID, else by track name + release) when that points to one credit."""
    con.execute(f"""
        CREATE TABLE unk AS
        SELECT DISTINCT l.recording_mbid, {_norm('l.recording_name')} AS rn, {_norm('l.release_name')} AS rel
        FROM {SRC} l SEMI JOIN (SELECT cid FROM credit_artists WHERE len(artists) = 0) u
          ON u.cid = hash(l.artist_name, l.artist_mbids)
    """)
    con.execute(f"""
        CREATE TABLE known AS
        SELECT l.recording_mbid, {_norm('l.recording_name')} AS rn, {_norm('l.release_name')} AS rel, c.artists
        FROM {SRC} l JOIN credit_artists c ON c.cid = hash(l.artist_name, l.artist_mbids)
        WHERE len(c.artists) > 0 AND (
          l.recording_mbid IN (SELECT recording_mbid FROM unk WHERE recording_mbid IS NOT NULL)
          OR ({_norm('l.recording_name')}, {_norm('l.release_name')}) IN (SELECT rn, rel FROM unk WHERE rel <> ''))
    """)
    con.execute("""
        CREATE TABLE rec_by_mbid AS
        SELECT recording_mbid, any_value(artists) AS artists FROM known
        WHERE recording_mbid IS NOT NULL GROUP BY 1 HAVING count(DISTINCT artists) = 1;
        CREATE TABLE rec_by_name AS
        SELECT rn, rel, any_value(artists) AS artists FROM known
        WHERE rel <> '' GROUP BY 1, 2 HAVING count(DISTINCT artists) = 1;
    """)


def run(log=print):
    _low_priority()
    con = connect(_cfg())
    rep = {}
    q = lambda sql: con.execute(sql).fetchone()[0]
    t = time.time()
    build_credit_tables(con)
    build_recovery(con)
    log(f"credit + recovery tables: {time.time() - t:.0f}s")

    OUT.mkdir(parents=True, exist_ok=True)
    for old in parts():
        old.unlink()
    for i in range(N_PARTS):
        t = time.time()
        out = OUT / f"part-{i:02d}.parquet"
        con.execute(f"""
            COPY (
              WITH l AS (
                SELECT l.user, l.ts, {_norm('l.recording_name')} AS track_name,
                       CASE WHEN len(c.artists) > 0 THEN c.artists
                            ELSE coalesce(rm.artists, rn.artists, []) END AS artists,
                       len(c.artists) = 0 AS was_unknown
                FROM {SRC} l
                JOIN credit_artists c ON c.cid = hash(l.artist_name, l.artist_mbids)
                LEFT JOIN rec_by_mbid rm ON len(c.artists) = 0 AND rm.recording_mbid = l.recording_mbid
                LEFT JOIN rec_by_name rn ON len(c.artists) = 0 AND rm.recording_mbid IS NULL
                     AND rn.rn = {_norm('l.recording_name')} AND rn.rel = {_norm('l.release_name')}
                WHERE hash(l.user) % {N_PARTS} = {i}),
              k AS (SELECT * FROM l WHERE len(artists) > 0),
              -- dedupe: the same user + track within 30 s counts once
              d AS (
                SELECT user, ts, artists, artists[1] || '|' || track_name AS track, was_unknown FROM (
                  SELECT *, ts - lag(ts) OVER (PARTITION BY user, artists[1], track_name ORDER BY ts) AS dt FROM k)
                WHERE dt IS NULL OR dt >= 30),
              g AS (SELECT *, ts - lag(ts) OVER (PARTITION BY user ORDER BY ts) AS gap FROM d)
              SELECT user, ts, artists, track, was_unknown,
                     sum(CASE WHEN gap IS NULL OR gap > 1800 THEN 1 ELSE 0 END)
                       OVER (PARTITION BY user ORDER BY ts ROWS UNBOUNDED PRECEDING)::INT AS session,
                     ((isodow(to_timestamp(ts)) - 1) * 24 + hour(to_timestamp(ts)))::INT AS how,
                     datediff('month', min(date_trunc('month', to_timestamp(ts))) OVER (PARTITION BY user),
                              date_trunc('month', to_timestamp(ts))) < 2 AS warmup
              FROM g ORDER BY user, ts
            ) TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
        """)
        log(f"part {i + 1}/{N_PARTS}: {time.time() - t:.0f}s")

    c = f"FROM {glob()}"
    rep["rows_in"] = q(f"SELECT count(*) FROM {SRC}")
    rep["unknown_rows"] = int(q("SELECT coalesce(sum(n), 0) FROM credit_artists WHERE len(artists) = 0"))
    rep["unknown_recovered_rows"] = q(f"SELECT count(*) {c} WHERE was_unknown")
    rep["rows_out"] = q(f"SELECT count(*) {c}")
    rep["dedupe_removed"] = rep["rows_in"] - rep["unknown_rows"] + rep["unknown_recovered_rows"] - rep["rows_out"]
    rep["multi_artist_share"] = q(f"SELECT avg((len(artists) > 1)::INT) {c}")
    rep["users"] = q(f"SELECT count(DISTINCT user) {c}")
    rep["name_spelling_merges"] = [
        {"key": k, "variants": v, "listens": int(n)} for k, v, n in con.execute("""
            SELECT parts[1], list(artist_name ORDER BY n DESC)[:5], sum(n) AS n FROM credit_artists
            WHERE coalesce(len(artist_mbids), 0) = 0 AND len(parts) = 1
            GROUP BY 1 HAVING count(DISTINCT artist_name) > 1 ORDER BY n DESC LIMIT 15""").fetchall()]
    rep["collab_examples"] = [
        {"credit": a, "artists": k, "listens": int(n)} for a, k, n in con.execute("""
            SELECT artist_name, artists, n FROM credit_artists WHERE len(artists) > 1
            ORDER BY n DESC LIMIT 10""").fetchall()]
    rep["session_minutes_quantiles"] = q(f"""
        SELECT quantile_cont(m, [0.1, 0.25, 0.5, 0.75, 0.9]) FROM (
          SELECT (max(ts) - min(ts)) / 60.0 AS m {c} GROUP BY user, session)""")
    rep["listens_per_session_quantiles"] = q(f"""
        SELECT quantile_cont(n, [0.1, 0.25, 0.5, 0.75, 0.9]) FROM (
          SELECT count(*) AS n {c} GROUP BY user, session)""")
    rep["warmup_share"] = q(f"SELECT avg(warmup::INT) {c}")
    rep["timezone"] = "not in the dump: all times treated as UTC"
    Path("reports").mkdir(exist_ok=True)
    Path("reports/clean_report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, default=str))
