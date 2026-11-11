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
    # true pass rate 70%, judge TPR 0.9, TNR 0.8: the judge passes 0.7*0.9 + 0.3*0.2 = 69%
    r = stats.rogan_gladen(690, 1000, 900, 1000, 800, 1000)
    assert abs(r["point"] - 0.70) < 1e-9 and r["ci"][0] < 0.70 < r["ci"][1]
    thin = stats.rogan_gladen(690, 1000, 27, 30, 24, 30)  # same rates on 30 labels a side
    assert (thin["ci"][1] - thin["ci"][0]) > (r["ci"][1] - r["ci"][0])
    assert stats.rogan_gladen(50, 100, 50, 100, 50, 100) is None  # a coin flip can't be corrected


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
