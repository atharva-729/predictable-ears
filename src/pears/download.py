"""List dump files and sizes, and fetch selected months.

The full listens dump is one ~250 GB .tar.zst, which can't be read selectively.
The spark dump is an *uncompressed* .tar, so we walk its headers with HTTP range
requests and fetch only the members (months) we need.
"""
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://data.metabrainz.org/pub/musicbrainz/listenbrainz/fullexport/"
INDEX_PATH = Path("data/raw/spark_index.json")


def _range(url, start, end, tries=8, deadline=120):
    """GET bytes [start, end]. A connection can trickle slowly enough to never hit the
    socket timeout, so each attempt also has a hard `deadline` in seconds."""
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    want = end - start + 1
    for attempt in range(tries):
        try:
            t0, parts, got = time.time(), [], 0
            with urllib.request.urlopen(req, timeout=30) as r:
                while got < want:
                    buf = r.read(min(1 << 20, want - got))
                    if not buf:
                        break
                    parts.append(buf)
                    got += len(buf)
                    if time.time() - t0 > deadline:
                        raise TimeoutError(f"range {start}-{end} over {deadline}s")
            return b"".join(parts)
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(min(60, 2 ** attempt))


def _octal(b):
    b = b.strip(b"\0 ")
    return int(b, 8) if b else 0


def _pax(data):
    out, i = {}, 0
    while i < len(data):
        sp = data.index(b" ", i)
        n = int(data[i:sp])
        k, _, v = data[sp + 1:i + n - 1].partition(b"=")
        out[k.decode()] = v.decode()
        i += n
    return out


def find_header(url, start, length=256 << 20, part=16 << 20):
    """Offset of the first pax/ustar header at or after `start` (512-aligned).

    Lets the walk start near the end of the archive instead of at byte 0.
    """
    from concurrent.futures import ThreadPoolExecutor

    start -= start % 512
    with ThreadPoolExecutor(8) as ex:
        buf = b"".join(ex.map(lambda i: _range(url, start + i, start + i + part - 1),
                              range(0, length, part)))
    for rel in range(0, len(buf) - 512, 512):
        h = buf[rel:rel + 512]
        if h[257:262] == b"ustar" and h[156:157] == b"x":
            return start + rel
    return None


def index_tar(url, resume=None, start=0, path=None):
    """Return [{name, offset, size}] for every regular file in a remote tar.

    Progress is saved to INDEX_PATH after each member, so a rerun resumes.
    """
    # The server takes ~3 s per request, so read 1.5 KB at a time: that covers a
    # pax header, its (small) data block and the next ustar header in one go.
    path = Path(path or INDEX_PATH)
    members, pos, pax, buf, buf_at = [], start, {}, b"", 0
    if resume and path.exists():
        saved = json.loads(path.read_text())
        if saved["url"] == url and not saved.get("done"):
            members, pos = saved["members"], saved["next_pos"]
    while True:
        if not (buf_at <= pos and pos + 512 <= buf_at + len(buf)):
            buf, buf_at = _range(url, pos, pos + 1535), pos
        h = buf[pos - buf_at:pos - buf_at + 512]
        if len(h) < 512 or h == b"\0" * 512:
            break
        size, kind = _octal(h[124:136]), h[156:157]
        data_start = pos + 512
        if kind in (b"x", b"g"):
            rel = data_start - buf_at
            data = buf[rel:rel + size] if rel + size <= len(buf) else _range(url, data_start, data_start + size - 1)
            pax = _pax(data)
        else:
            name = pax.get("path") or (h[345:500].rstrip(b"\0") + b"/" * bool(h[345]) + h[0:100].rstrip(b"\0")).decode()
            size = int(pax.get("size", size))
            if kind in (b"0", b"\0"):
                members.append({"name": name, "offset": data_start, "size": size})
                print(f"{size / 1e9:8.3f} GB  {name}", flush=True)
            pax = {}
        pos = data_start + (size + 511) // 512 * 512
        if kind not in (b"x", b"g"):
            _save(url, members, pos, False, path)
    _save(url, members, pos, True, path)
    return members


def _save(url, members, pos, done, path=INDEX_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"url": url, "next_pos": pos, "done": done, "members": members}))
    tmp.replace(path)


def fetch(url, member, dest, part=16 << 20, workers=8):
    """Download one tar member to dest using parallel range requests.

    One connection gets ~1.7 MB/s from the MetaBrainz server; 8 get ~9.6 MB/s.
    Skips the file if it is already complete.
    """
    from concurrent.futures import ThreadPoolExecutor

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == member["size"]:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        f.truncate(member["size"])

    def get(i):
        lo = member["offset"] + i
        hi = min(lo + part, member["offset"] + member["size"]) - 1
        for attempt in range(5):
            try:
                data = _range(url, lo, hi)
                if len(data) == hi - lo + 1:
                    break
            except OSError:
                if attempt == 4:
                    raise
        with open(tmp, "r+b") as f:
            f.seek(i)
            f.write(data)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(get, range(0, member["size"], part)))
    tmp.replace(dest)


class RangeFile(io.RawIOBase):
    """Read-only, seekable view of one tar member over HTTP range requests."""

    def __init__(self, url, member):
        self.url, self.off, self.size, self.pos = url, member["offset"], member["size"], 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, pos, whence=0):
        self.pos = [pos, self.pos + pos, self.size + pos][whence]
        return self.pos

    def tell(self):
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        data = _range(self.url, self.off + self.pos, self.off + self.pos + n - 1)
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def ts_range(url, member):
    """(min, max) listened_at of a remote parquet member, as unix seconds."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    col = pq.ParquetFile(io.BufferedReader(RangeFile(url, member), 1 << 20)).read(
        columns=["listened_at"]).column(0)
    mm = pc.min_max(col.cast("timestamp[s]") if col.type != "timestamp[s]" else col)
    return mm["min"].value, mm["max"].value


if __name__ == "__main__":
    url = sys.argv[1]
    index_tar(url, resume=True)
