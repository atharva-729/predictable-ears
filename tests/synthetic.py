"""Synthetic listeners with known answers. Shared by the Python and JS tests."""
import json
import random

START = 1704067200  # 2024-01-01 00:00 UTC, a Monday
N = 6000
STEP = 3 * 3600 + 7  # ~3 h apart, so listens cover ~2 years and all hours


def _make(artists, step=STEP):
    ts = [START + i * step for i in range(len(artists))]
    return {"ts": ts, "artists": artists, "tracks": [a + "|t" for a in artists]}


def parrot():
    return _make(["a"] * N)


def uniform(n_art=10, seed=1):
    r = random.Random(seed)
    return _make([f"a{r.randrange(n_art)}" for _ in range(N)])


def cycle():
    return _make([["a", "b", "c"][i % 3] for i in range(N)])


def explorer():
    return _make([f"new{i}" for i in range(N)])


def night_owl(seed=2):
    # artists depend on the hour; shuffled within each hour so repeat_last fails
    r = random.Random(seed)
    ts = [START + i * STEP for i in range(N)]
    arts = []
    for t in ts:
        h = (t // 3600) % 24
        arts.append(f"h{h // 3}_{r.randrange(2)}")
    return {"ts": ts, "artists": arts, "tracks": [a + "|t" for a in arts]}


ALL = {"parrot": parrot, "uniform": uniform, "cycle": cycle,
       "explorer": explorer, "night_owl": night_owl}

if __name__ == "__main__":
    print(json.dumps({k: f() for k, f in ALL.items()}))
