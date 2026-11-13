import pytest

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


# ---- docs/statistics.md: the numbers behind each decision ----------------------------------

def test_zero_failure_bound_is_the_rule_of_three():
    assert abs(stats.zero_failure_bound(10) - 0.2589) < 1e-4  # 10 clean cases rule out only >26%
    assert abs(stats.zero_failure_bound(100) - 0.0295) < 1e-4  # about 3/n
    assert stats.cases_to_surface(0.01) == 299 and stats.cases_to_surface(0.05) == 59
    assert stats.zero_failure_bound(0) is None and stats.cases_to_surface(0) is None


def test_floor_evidence_separates_clearing_a_floor_from_having_shown_it():
    e = stats.floor_evidence(13, 15, 0.85)  # 87% on 15 runs: clears the point floor
    assert e["meets_point"] and not e["meets_margin"] and 0.6 < e["lower"] < 0.65
    assert e["n_needed"] > 15
    assert stats.floor_evidence(2, 2, 0.75)["meets_margin"] is False  # TNR on two labels
    big = stats.floor_evidence(90, 100, 0.85)
    assert big["meets_point"] and big["meets_margin"] and big["n_needed"] == 100
    assert stats.floor_evidence(5, 10, 0.85)["n_needed"] is None  # below the floor: more won't help
    assert stats.labels_for_halfwidth(0.8, 0.10) == 60


def test_ac1_and_specific_agreement_survive_a_skewed_pass_rate():
    # Feinstein & Cicchetti's paradox: 90% agreement, kappa below zero
    pairs = [(True, True)] * 90 + [(True, False)] * 5 + [(False, True)] * 5
    a = stats.agreement_stats(pairs)
    assert a["observed"] == 0.9 and a["kappa"] < 0 and a["ac1"] > 0.85
    assert a["negative_agreement"] == 0.0  # they agreed on no failure at all
    assert stats.agreement_stats([]) is None


def test_rogan_gladen_undoes_a_known_judge_error():
    # true failure rate 30%, catch 0.8, clean 0.9: the judge fails 0.3*0.8 + 0.7*0.1 = 31%
    r = stats.rogan_gladen(310, 1000, 800, 1000, 900, 1000)
    assert abs(r["point"] - 0.30) < 1e-9 and r["ci"][0] < 0.30 < r["ci"][1]
    assert abs(r["j"] - 0.7) < 1e-12 and r["youden_j"] == r["j"]  # 1.x key kept until stage 8
    thin = stats.rogan_gladen(310, 1000, 24, 30, 27, 30)  # same rates on 30 labels a kind
    assert (thin["ci"][1] - thin["ci"][0]) > (r["ci"][1] - r["ci"][0])
    assert stats.rogan_gladen(50, 100, 50, 100, 50, 100) is None  # a coin flip can't be corrected


def test_rogan_gladen_matches_the_labels_per_kind_table():
    # statistics §3.4: true failure rate 5%, catch 0.80, clean 0.95, 10,000 graded runs
    rows = {(30, 30): (24, 28, 0.0, 14.7), (100, 100): (80, 95, 0.0, 10.5),
            (200, 200): (160, 190, 1.1, 8.9), (100, 300): (80, 285, 1.7, 8.3),
            (50, 350): (40, 332, 1.7, 7.9)}
    for (n_fail, n_pass), (ck, cl, lo, hi) in rows.items():
        ci = stats.rogan_gladen(875, 10_000, ck, n_fail, cl, n_pass)["ci"]
        assert [round(100 * x, 1) for x in ci] == [lo, hi], (n_fail, n_pass)


def test_corrected_trigger_rate_is_unchanged_by_the_catch_clean_signature():
    from aot_evals.report import corrected_trigger_rate
    # pass is the positive in the 1.x confusion matrix: tp both pass, tn both fail
    judge = {"confusion": {"tp": 45, "fn": 5, "tn": 16, "fp": 4}, "status": "calibrated"}
    r = corrected_trigger_rate(0.25, 40, judge)
    # the 1.x arithmetic, pass as the positive, then complemented
    q, tpr, tnr = 30 / 40, 45 / 50, 16 / 20
    j = tpr + tnr - 1
    assert abs(r["point"] - (1 - (q + tnr - 1) / j)) < 1e-12
    assert r["ci"][0] < r["point"] < r["ci"][1] and r["calibrated"]


def test_ppi_is_unbiased_and_tighter_than_labels_alone_when_the_suite_is_good():
    import random
    rng = random.Random(0)
    truth = [rng.random() < 0.8 for _ in range(2100)]
    suite = [t if rng.random() < 0.95 else not t for t in truth]
    est = stats.ppi_mean([float(x) for x in suite[100:]], [float(x) for x in suite[:100]],
                         [float(x) for x in truth[:100]])
    true_rate = sum(truth) / len(truth)
    assert est["ci"][0] <= true_rate <= est["ci"][1]
    lo, hi = est["labels_only"]["ci"]
    assert (est["ci"][1] - est["ci"][0]) < (hi - lo) and est["lambda"] > 0.5
    # a suite unrelated to the truth earns no weight
    noise = [rng.random() < 0.5 for _ in range(2100)]
    est2 = stats.ppi_mean([float(x) for x in noise[100:]], [float(x) for x in noise[:100]],
                          [float(x) for x in truth[:100]])
    assert est2["lambda"] < 0.3
    assert stats.ppi_mean([], [1.0], [1.0]) is None


def test_variance_components_say_whether_to_buy_cases_or_trials():
    # every case deterministic: all variance is between cases, extra trials buy nothing
    fixed = [[True] * 3] * 6 + [[False] * 3] * 4
    v = stats.variance_components(fixed)
    assert v["within_case"] == 0 and v["icc"] == 1.0 and v["se_double_trials"] == v["se_now"]
    assert v["effective_n"] == 10  # 30 trials, but only 10 independent cases
    # every case a coin flip: all variance is within cases
    flips = [[True, False, True, False]] * 10
    w = stats.variance_components(flips)
    assert w["between_case"] == 0 and w["se_double_trials"] < w["se_now"]
    assert stats.variance_components([[True]]) is None


def test_mde_from_deltas_includes_uneven_effects():
    even = [0.1] * 50
    uneven = [0.6] * 10 + [-0.025] * 40  # same mean, the change moved a few cases a lot
    assert stats.mde_from_deltas(even) == 1 / 50  # no spread: floored at the smallest step
    assert stats.mde_from_deltas(uneven) > 0.1
    assert stats.mde_from_deltas([0.1]) is None


def test_sign_flip_test_and_false_discovery_adjustment():
    assert stats.sign_flip_test([0.0, 0.0]) == 1.0
    assert stats.sign_flip_test([1.0] * 6) == 2 / 64  # exact: all-same-sign is 2 of 64 patterns
    assert stats.sign_flip_test([]) is None
    assert stats.sign_flip_test([0.2] * 30) < 0.001  # Monte Carlo path
    adj = stats.benjamini_hochberg([0.01, 0.04, None, 0.03, 0.5])
    assert adj[2] is None and adj[0] == 0.04 and adj[4] == 0.5
    assert all(a >= p for a, p in zip(adj, [0.01, 0.04, 0, 0.03, 0.5], strict=True) if a is not None)


# ---- review: uneven costs, category weights, flip rate and clusters ------------------------

def test_t_quantiles_match_the_tables():
    assert abs(stats.t_quantile(0.975, 9) - 2.262) < 1e-3
    assert abs(stats.t_quantile(0.975, 1) - 12.706) < 1e-3
    assert abs(stats.t_quantile(0.975, 10_000) - 1.960) < 1e-3
    assert abs(stats.t_cdf(0.0, 5) - 0.5) < 1e-12


def test_flip_rate_sets_a_comparisons_precision():
    clean, churn = stats.flip_summary(10, 0, 200), stats.flip_summary(30, 20, 200)
    assert clean["net"] == churn["net"] == 0.05
    assert abs(1.96 * clean["se"] - 0.030) < 1e-3 and abs(1.96 * churn["se"] - 0.069) < 1e-3
    assert stats.cases_for_flip_rate(0.25, 0.05) == 785  # about 7.85 d / effect^2
    assert stats.mcnemar_midp(5, 5) == 1.0 and stats.mcnemar_midp(6, 0) < stats.mcnemar_midp(6, 0) * 2
    assert stats.mcnemar_midp(8, 1) < 0.05  # exact McNemar: 0.039; mid-p is smaller


def test_signs_flip_per_cluster_and_few_clusters_cannot_reach_five_percent():
    clusters = [f"t{i // 6}" for i in range(24)] + [f"u{i}" for i in range(6)]
    deltas = [1.0] * 24 + [-1.0] * 6
    assert stats.sign_flip_test(deltas) < 0.01
    assert stats.sign_flip_test(deltas, clusters=clusters) > 0.05
    assert stats.min_attainable_p(5) == 0.0625
    five = [f"t{i % 5}" for i in range(50)]
    assert stats.sign_flip_interval([0.2] * 50, clusters=five) is None
    s = stats.cluster_summary(five)
    assert s["regime"] == "fixed_suite_only" and s["n_clusters"] == 5
    assert stats.cluster_summary(["a"] * 4 + [None] * 6)["dominant"] == ["a"]
    assert stats.cluster_summary([None] * 3)["regime"] == "cases_assumed_independent"


def test_sign_flip_interval_covers_the_mean_and_widens_with_clusters():
    import random
    rng = random.Random(1)
    deltas = [rng.choice([0.0, 0.0, 1 / 3, -1 / 3, 2 / 3]) for _ in range(40)]
    lo, hi = stats.sign_flip_interval(deltas)
    assert lo < sum(deltas) / 40 < hi
    keys = [f"t{i // 4}" for i in range(40)]
    clo, chi = stats.sign_flip_interval(deltas, clusters=keys)
    assert clo < sum(deltas) / 40 < chi
    jk = stats.cluster_jackknife(deltas, keys)
    assert jk["df"] == 9 and jk["ci"][0] < jk["mean"] < jk["ci"][1]


def test_effective_n_bounds_and_clustered_pass_rate():
    assert stats.effective_n(100, 10, 1.0) == 10  # all-or-nothing per seed: the seeds are the sample
    assert abs(stats.zero_failure_bound(10) - 0.259) < 1e-3
    assert stats.effective_n(100, 10, 0.0) == 100 and stats.effective_n(100, 10, None) is None
    trials = [[True, True, False]] * 6 + [[True] * 3] * 6
    flat = stats.clustered_pass_rate(trials)
    grouped = stats.clustered_pass_rate(trials, [f"g{i % 3}" for i in range(12)])
    assert grouped["n_clusters"] == 3 and flat["ci_method"].startswith("cluster_robust_t")
    assert (grouped["ci"][1] - grouped["ci"][0]) > (flat["ci"][1] - flat["ci"][0])
    near_ceiling = stats.clustered_pass_rate([[True, True, True]] * 29 + [[True, True, False]])
    assert near_ceiling["ci_method"] == "cluster_robust_t_logit" and near_ceiling["ci"][1] <= 1.0


def test_dependence_checks_find_shocks_and_template_clusters():
    shock = [[True, True, False]] * 20 + [[True, True, True]] * 10  # the third repeat failed 20 cases
    assert stats.cochran_q(shock)["p"] < 0.01
    calm = [[True, False, True], [False, True, True], [True, True, False]] * 10
    assert stats.cochran_q(calm)["p"] > 0.05
    together = [[1.0] * 5, [0.0] * 5, [1.0] * 5, [0.0] * 5]
    assert stats.overdispersion_test(together)["p"] < 0.05


def test_weights_blind_spots_and_allocation():
    w = stats.objective_weights({"a": 0.98, "b": 0.02}, {"a": 1, "b": 1})
    assert abs(w["b"] - 0.02) < 1e-12
    assert stats.objective_weights({"a": 0.5, "b": 0.5}, {"a": 1}) is None  # unstated is unknown
    bs = stats.blind_spot(w["b"], 0.10, 0.11)
    assert abs(bs["moves_objective_by"] - 0.002) < 1e-12 and bs["blind"]
    heavy = stats.objective_weights({"a": 0.98, "b": 0.02}, {"a": 1, "b": 60})
    # even weighted 60x, a 10-point drop moves the score 5.5 points: still blind to an 11-point MDE
    assert stats.blind_spot(heavy["b"], 0.10, 0.11)["blind"]
    assert not stats.blind_spot(heavy["b"], 0.25, 0.11)["blind"]
    assert [stats.cases_per_arm(1 - r, 1 - r / 2) for r in (0.5, 0.3)] == [55, 118]
    assert [stats.cases_to_surface(d) for d in (0.10, 0.05, 0.02, 0.01)] == [29, 59, 149, 299]
    t = stats.allocation_target("solved", tolerated_drop=0.05, costly_mode_rates=[0.02])
    assert t["target"] == 149 and t["needs"]["regression_guard"] == 59
    imp = stats.allocation_target("improve", smallest_change=0.10, flip_rate=0.2)
    assert imp["target"] == stats.cases_for_flip_rate(0.2, 0.10)
    assert stats.allocation_target("improve")["unknown_needs"] == ["improvement"]
    n = stats.neyman_allocation({"easy": (0.5, 0.99), "hard": (0.5, 0.7)}, 100, floor=5)
    assert sum(n.values()) == 100 and n["hard"] > n["easy"] >= 5


def test_stratified_draw_records_inclusion_probabilities():
    pop = {"a": [f"a{i}" for i in range(10)], "b": [f"b{i}" for i in range(4)]}
    d = stats.stratified_draw(pop, {"a": 5, "b": 4}, seed=7)
    assert d == stats.stratified_draw(pop, {"a": 5, "b": 4}, seed=7)  # seeded: reproducible
    assert len(d["drawn"]["a"]) == 5 and d["inclusion_probability"]["b0"] == 1.0
    assert all(d["inclusion_probability"][x] == 0.5 for x in d["drawn"]["a"])


def test_cost_flags_catch_a_write_in_a_read_only_category():
    assert stats.failure_severity(writes=True, reversible=False, noticed=None) == "high"
    assert stats.failure_severity(writes=False, reversible=None, noticed=True) == "low"
    assert stats.failure_severity(writes=True, reversible=None, noticed=True) is None
    f = stats.cost_flags([("report", "low"), ("report", "high"), ("book", "medium")],
                         {"report": "low", "book": "medium"})
    assert f["categories"]["report"]["flag"] and f["categories"]["report"]["exceeds_declared"]
    assert not f["categories"]["book"]["flag"] and f["even"] is False
    assert stats.cost_flags([("book", "medium")], {"book": "medium"})["even"] is True


# ---- 2.0 statistics library (docs/statistics.md §2.1, §2.3, §3.3, §4.1, §4.5, §4.6) ----------

def test_hajek_mean_weights_each_case_by_one_over_pi():
    # an oversampled case (pi = 0.25) counts four times; the others twice
    h = stats.hajek_mean([1.0, 0.0, 1.0], [0.5, 0.5, 0.25])
    assert abs(h["point"] - 0.75) < 1e-12 and h["sum_weights"] == 8.0
    assert abs(h["n_effective"] - 64 / 24) < 1e-12  # unequal weights are worth fewer cases
    equal = stats.hajek_mean([1.0, 0.0, 1.0, 1.0], [0.1] * 4)  # equal pi: the plain mean
    assert equal["point"] == 0.75 and abs(equal["n_effective"] - 4) < 1e-12
    assert abs(equal["se"] - 0.25) < 1e-12  # s / sqrt(n) = 0.5 / 2
    assert stats.hajek_mean([1.0], [0.5])["se"] is None
    assert stats.hajek_mean([], []) is None
    assert stats.hajek_mean([1.0, 0.0], [0.5, None]) is None  # no recorded pi: not in a rate
    assert stats.hajek_mean([1.0], [0.0]) is None


def test_optimum_allocation_follows_spread_and_cost_around_minimums():
    def uc(w, p=None, c=None):
        return {"weight": w, "pass_rate": p, "cost": c}
    # before a baseline: proportional to weight
    prop = stats.optimum_allocation({"a": uc(0.8), "b": uc(0.2)}, 100)
    assert prop["allocation"] == {"a": 80, "b": 20} and prop["spread"] == "assumed_equal"
    # a use case at 99% needs fewer cases than one at 70% for the same precision
    ney = stats.optimum_allocation({"easy": uc(0.5, 0.99, 1), "hard": uc(0.5, 0.70, 1)}, 100)
    assert ney["allocation"]["hard"] > 3 * ney["allocation"]["easy"] and ney["spread"] == "measured"
    # four times the cost per case: half the cases (1 / sqrt(4))
    cost = stats.optimum_allocation({"cheap": uc(0.5, 0.8, 1), "dear": uc(0.5, 0.8, 4)}, 90)
    assert cost["allocation"] == {"cheap": 60, "dear": 30}
    # a minimum above the formula's share is fixed, and the rest spread over the others
    m = stats.optimum_allocation({"a": uc(0.7), "b": uc(0.2), "c": uc(0.1)}, 100, {"c": 30})
    assert m["allocation"] == {"a": 54, "b": 16, "c": 30} and m["at_minimum"] == ["c"]
    assert sum(m["allocation"].values()) == 100
    # fixing one at its minimum can push another under its own: repeat until all hold
    chain = stats.optimum_allocation({"a": uc(0.9), "b": uc(0.05), "c": uc(0.05)}, 100, {"b": 40, "c": 9})
    assert chain["allocation"]["b"] == 40 and chain["allocation"]["c"] >= 9
    assert sum(chain["allocation"].values()) == 100
    short = stats.optimum_allocation({"a": uc(0.5), "b": uc(0.5)}, 50, {"a": 40, "b": 40})
    assert short["allocation"] == {"a": 40, "b": 40} and short["shortfall"] == 30
    assert stats.optimum_allocation({"a": uc(None), "b": uc(1.0)}, 10) is None  # unstated weight


def test_judge_inflation_matches_the_table():
    # statistics §3.3, rounded as printed there
    table = {(0.95, 0.95): (1.2, 1.4, 1.7, 3.0), (0.90, 0.90): (1.6, 1.9, 2.6, 5.8),
             (0.80, 0.90): (2.0, 2.3, 3.2, 7.5), (0.80, 0.80): (2.8, 3.8, 5.9, 16.3),
             (0.75, 0.75): (4.0, 5.7, 9.3, 26.8)}
    for (c, s), want in table.items():
        got = tuple(round(stats.judge_inflation(p, c, s), 1) for p in (0.5, 0.2, 0.1, 0.03))
        assert got == want, (c, s)
    assert stats.judge_inflation(0.03, 1.0, 1.0) == 1.0  # a code check costs nothing extra
    assert stats.judge_inflation(0.1, 0.5, 0.5) is None  # J = 0: a coin
    assert stats.judge_inflation(0.0, 0.9, 0.9) is None
    assert stats.cases_needed(100, 0.03, 0.9, 0.9) == 584  # 5.83x, rounded up
    assert stats.cases_needed(59, 0.05) == 59
    assert stats.cases_needed(59, 0.05, 0.6, 0.4) is None


def test_threshold_n_with_a_code_check_and_with_judges():
    # statistics §3.3: refunds break the policy less than 5%, 80% power at a true 1%. The formula
    # gives 122.2, 862.4 and 175.0 ("about 120, 860 and 175"), rounded up to whole cases.
    assert stats.threshold_n(0.05, 0.01) == 123
    assert stats.threshold_n(0.05, 0.01, catch=0.80, clean=0.90) == 863
    assert stats.threshold_n(0.05, 0.01, catch=0.95, clean=0.99) == 176
    assert stats.threshold_n(0.05, 0.05) is None and stats.threshold_n(0.05, 0.01, catch=0.5, clean=0.5) is None
    # the other side: show a failure rate is above 20% when it is 30%
    assert stats.threshold_n(0.20, 0.30) == stats.threshold_n(0.20, 0.30, alpha=0.05)
    assert stats.threshold_n(0.20, 0.30) > 100


def test_threshold_test_is_the_zero_failure_rule_and_handles_a_judge():
    assert stats.threshold_test(0, 59, 0.05)["passed"]  # 0.95^59 < 0.05
    t58 = stats.threshold_test(0, 58, 0.05)
    assert not t58["passed"] and abs(t58["p"] - 0.95 ** 58) < 1e-12
    assert abs(stats.threshold_test(0, 59, 0.05)["bound"] - stats.zero_failure_bound(59)) < 1e-9
    # 2 failures in 200 with a code check: well under 5%
    t = stats.threshold_test(2, 200, 0.05)
    assert t["passed"] and t["bound"] < 0.05 and t["estimate"] == 0.01
    # the same agent through a judge at catch 0.80, clean 0.90: about 10.7% of runs flagged.
    # 200 cases cannot show it; the 863 threshold_n plans for can.
    judged = stats.threshold_test(21, 200, 0.05, catch=0.80, clean=0.90)
    assert not judged["passed"] and abs(judged["grader_bar"] - 0.135) < 1e-12
    big = stats.threshold_test(92, 863, 0.05, catch=0.80, clean=0.90)
    assert big["passed"] and big["bound"] < 0.05 and abs(big["estimate"] - (92 / 863 - 0.1) / 0.7) < 1e-12
    # passed and the bound agree
    for k in range(0, 15):
        r = stats.threshold_test(k, 150, 0.05)
        assert r["passed"] == (r["bound"] < 0.05)
    up = stats.threshold_test(40, 100, 0.25, side="above")
    assert up["passed"] and up["bound"] > 0.25
    assert stats.threshold_test(1, 10, 0.05, catch=0.5, clean=0.5) is None
    assert stats.threshold_test(11, 10, 0.05) is None and stats.threshold_test(0, 10, 0.05, side="x") is None


def test_non_inferiority_is_not_no_significant_difference():
    # statistics §4.5: 4 fixes and 4 breaks on 50 cases, an interval of about +/-11 points
    deltas = [1.0] * 4 + [-1.0] * 4 + [0.0] * 42
    assert stats.sign_flip_test(deltas) == 1.0  # "no difference"...
    five = stats.non_inferiority_test(deltas, 0.05)
    assert not five["passed"] and five["lower"] < -0.05  # ...but not shown within 5 points
    wide = stats.non_inferiority_test(deltas, 0.15)
    assert wide["passed"] and wide["lower"] > -0.15
    # a clean candidate on 60 cases clears a 2-point margin
    assert stats.non_inferiority_test([0.0] * 55 + [1 / 3] * 5, 0.02)["passed"]
    # a real 5-point drop does not clear a 2-point margin
    drop = stats.non_inferiority_test([0.0] * 190 + [-1.0] * 10, 0.02)
    assert not drop["passed"] and drop["mean"] == -0.05
    # four clusters: a one-sided test cannot go below 1/16
    clustered = stats.non_inferiority_test([0.0] * 40, 0.02, clusters=[f"t{i % 4}" for i in range(40)])
    assert clustered["n_clusters"] == 4 and clustered["min_attainable_p"] == 1 / 16
    assert not clustered["passed"] and clustered["lower"] is None
    many = stats.non_inferiority_test([0.0] * 40, 0.02, clusters=[f"t{i % 20}" for i in range(40)])
    assert many["passed"] and many["weights"] == "rademacher"
    assert stats.non_inferiority_test([0.0] * 40, 0.02, clusters=[f"t{i % 7}" for i in range(40)])["weights"] == "webb"
    assert stats.non_inferiority_test([], 0.02) is None and stats.non_inferiority_test([0.0], 0) is None


def test_holm_controls_any_false_alarm_and_is_stricter_than_bh():
    adj = stats.holm([0.01, 0.04, None, 0.03, 0.5])
    assert adj == [0.04, 0.09, None, 0.09, 0.5]
    bh = stats.benjamini_hochberg([0.01, 0.04, None, 0.03, 0.5])
    assert all(h >= b for h, b in zip(adj, bh, strict=True) if h is not None)
    assert stats.holm([0.3, 0.9]) == [0.6, 0.9]  # monotone, capped at 1
    assert stats.holm([]) == [] and stats.holm([None]) == [None]


# ---- 2.0 estimand and design (docs/statistics.md §2.1-§2.4, §4.1, §4.5; estimators §7) ----------

def test_stratified_draw_is_prefix_stable_and_replaces_skips_from_its_order():
    pop = {"a": [f"a{i}" for i in range(20)], "b": [f"b{i}" for i in range(5)]}
    small = stats.stratified_draw(pop, {"a": 4, "b": 2}, seed=3)
    big = stats.stratified_draw(pop, {"a": 9, "b": 2}, seed=3)
    assert set(small["drawn"]["a"]) < set(big["drawn"]["a"])  # drawing more extends the draw
    assert small["drawn"]["b"] == big["drawn"]["b"]  # and leaves the other strata alone
    order = stats.draw_order(pop["a"], 3, "a")
    assert sorted(order[:4]) == small["drawn"]["a"] and small["index"][order[0]] == 0
    skipped = stats.stratified_draw(pop, {"a": 4, "b": 2}, seed=3, skip=[order[1]])
    assert skipped["drawn"]["a"] == sorted([order[0], *order[2:5]])  # the next of the same order
    assert skipped["replaced"]["a"] == [order[1]] and skipped["frame_size"]["a"] == 19
    assert skipped["inclusion_probability"][order[0]] == 4 / 19
    assert stats.draw_order(pop["a"], 3, "a") != stats.draw_order(pop["a"], 4, "a")


def test_hajek_counts_clusters_not_cases():
    ys = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    alone = stats.hajek_mean(ys, [0.5] * 6)
    paired = stats.hajek_mean(ys, [0.5] * 6, ["t1", "t1", "t1", "t2", "t2", "t2"])
    assert alone["point"] == paired["point"] == 0.5
    assert paired["n_clusters"] == 2 and paired["n_effective"] == 2 and paired["se"] > alone["se"]
    assert stats.hajek_mean([1.0, 0.0], [0.5, 0.5], ["x", "x"])["se"] is None  # one cluster: no SE


def test_stratified_hajek_weights_use_cases_and_never_gives_zero_variance():
    strata = {"common": {"weight": 0.7, "values": [1.0] * 30 + [0.0] * 10, "inclusion_probs": [0.1] * 40},
              "rare": {"weight": 0.3, "values": [1.0] * 10, "inclusion_probs": [0.5] * 10}}
    r = stats.stratified_hajek(strata)
    assert r["point"] == pytest.approx(0.7 * 0.75 + 0.3 * 1.0)
    rare = r["per_use_case"]["rare"]
    assert rare["se"] == 0 and rare["variance_used"] == pytest.approx((11 / 12) * (1 / 12) / 10)
    assert r["ci"][1] <= 1 and r["ci"][0] < r["point"]
    # weights are normalized; a weight-0 use case may have no cases; any other may not
    assert stats.stratified_hajek({**strata, "none": {"weight": 0, "values": [], "inclusion_probs": []}})["point"] \
        == pytest.approx(r["point"])
    missing = stats.stratified_hajek({**strata, "gift": {"weight": 0.1, "values": [], "inclusion_probs": []}})
    assert missing["point"] is None and missing["missing"] == ["gift"]
    assert stats.stratified_hajek({"a": {"weight": None, "values": [1.0], "inclusion_probs": [1.0]}}) is None


def test_paired_n_matches_the_non_inferiority_figures():
    # statistics §4.5: a cheaper model within 5 points at a 16% flip rate
    assert stats.paired_n(0.16, 0.05, alpha=0.025) == stats.cases_for_flip_rate(0.16, 0.05) == 503
    assert stats.paired_n(0.16, 0.05, alpha=0.05) == 396  # "about 400"
    assert stats.paired_n(0.16, 0) is None and stats.paired_n(0, 0.05) is None


def test_allocation_design_effect():
    w = {"a": 0.9, "b": 0.1}
    assert stats.allocation_design_effect(w, {"a": 90, "b": 10}) == pytest.approx(1.0)
    assert stats.allocation_design_effect(w, {"a": 50, "b": 50}) == pytest.approx(100 * (0.81 / 50 + 0.01 / 50))
    assert stats.allocation_design_effect(w, {"a": 100, "b": 0}) is None
