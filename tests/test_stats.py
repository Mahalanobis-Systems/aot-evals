from aot_evals import stats
from aot_evals.scrub import scan


def test_wilson_stays_in_bounds_at_extremes():
    lo, hi = stats.wilson(0, 10)
    assert lo == 0.0 and 0.2 < hi < 0.35
    lo, hi = stats.wilson(10, 10)
    assert hi == 1.0 and 0.65 < lo < 0.8
    assert stats.wilson(0, 0) is None


def test_clustered_interval_is_wider_than_naive_binomial():
    # 10 cases x 3 trials, perfectly correlated within case: effective n is 10, not 30
    trials = [[True] * 3] * 6 + [[False] * 3] * 4
    r = stats.clustered_pass_rate(trials)
    naive = stats.wilson(18, 30)
    assert r["point"] == 0.6
    assert (r["ci"][1] - r["ci"][0]) > (naive[1] - naive[0])
    assert r["n"] == 30 and r["n_cases"] == 10


def test_sizing_and_mde():
    assert stats.sample_size_for_halfwidth(0.05) == 385
    assert stats.sample_size_for_halfwidth(0.10) == 97
    # 100 cases at p=0.5, unpaired: about 19.8 points
    assert 0.19 < stats.mde(100) < 0.21
    assert stats.mde(5) >= 1 / 5
    assert stats.mde(0) is None


def test_percentile():
    assert stats.percentile([1, 2, 3, 4], 50) == 2.5
    assert stats.percentile([], 50) is None


def test_scrub_flags_secrets_and_spares_example_domains():
    found = scan('{"key": "sk-ant-abcdefghijklmnopqrstuvwxyz123", "to": "ana@example.com"}')
    assert [f.pattern for f in found] == ["openai_style_key"]
    found = scan("call 415-555-0134 or mail ana@realcorp.io")
    assert {f.pattern for f in found} == {"phone", "email"}
