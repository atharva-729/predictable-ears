import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import synthetic as s
from pears.metrics import user_metrics


def m(u):
    return user_metrics(u["ts"], u["artists"], u["tracks"])


def test_parrot():
    r = m(s.parrot())
    assert r["repeat_last_top1"] == 1.0
    assert r["entropy"] == 0
    assert r["exploration_rate"] == 0


def test_uniform():
    r = m(s.uniform(10))
    assert abs(r["predictability_top1"] - 0.1) < 0.03
    assert abs(r["entropy"] - math.log(10)) < 0.01


def test_cycle():
    r = m(s.cycle())
    assert r["markov1_top1"] == 1.0
    assert r["repeat_last_top1"] == 0


def test_explorer():
    r = m(s.explorer())
    assert r["exploration_rate"] == 1.0
    assert r["predictability_top1"] == 0


def test_night_owl():
    r = m(s.night_owl())
    assert r["time_of_day_top1"] > r["most_frequent_top1"] + 0.2


def test_loop_day():
    # 10 plays of one track in a day among 20 listens -> loop day
    ts = [1704067200 + i * 60 for i in range(20)]
    tracks = ["x|t" if i % 2 else f"y{i}|t" for i in range(20)]
    r = user_metrics(ts, [t.split("|")[0] for t in tracks], tracks)
    assert r["loop_days"] == 1


def test_collab_credits():
    # every listen is the same two-artist collab: either artist counts as a hit
    u = s._make(["x"] * s.N)
    u["artists"] = [["a", "b"]] * s.N
    r = m(u)
    assert r["repeat_last_top1"] == 1.0 and r["most_frequent_top1"] == 1.0
    assert abs(r["entropy"] - math.log(2)) < 1e-12
    assert abs(r["effective_artists"] - 2) < 1e-9
    assert r["exploration_rate"] == 0
    assert r["artist_streak_max"] == s.N


def test_collab_exploration_is_fractional():
    # a known artist featuring a brand-new one each time counts as half a new listen:
    # months fully in the first half explore 0, months fully in the second half 0.5
    n = 3000
    u = s._make(["x"] * n)
    u["artists"] = [["a"]] * (n // 2) + [["a", f"new{i}"] for i in range(n - n // 2)]
    rates = list(m(u)["monthly_exploration"].values())
    assert min(rates) == 0 and abs(max(rates) - 0.5) < 1e-12
    assert all(0 <= v <= 0.5 + 1e-12 for v in rates)
