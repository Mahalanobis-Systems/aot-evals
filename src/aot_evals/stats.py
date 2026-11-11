"""Intervals and sizing arithmetic. Standard library only.

Every function returns `None` rather than a number when the input cannot support one: the
report's rule is that unknown values are `null`, never `0` (docs/method.md §8).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Z95 = 1.959963984540054
Z80_POWER = 0.8416212335729143


def wilson(count: int, total: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for count/total. Stays inside [0, 1] at 0 and 1, which the normal
    approximation does not."""
    if total <= 0:
        return None
    p = count / total
    denom = 1 + z**2 / total
    center = p + z**2 / (2 * total)
    adj = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2))
    lo = 0.0 if count == 0 else max(0.0, (center - adj) / denom)
    hi = 1.0 if count == total else min(1.0, (center + adj) / denom)
    return (lo, hi)


def clustered_pass_rate(trials_by_case: Sequence[Sequence[bool]],
                        groups: Sequence[str | None] | None = None) -> dict | None:
    """Pass rate over trials, with an interval that treats each case's k trials as a cluster.

    Trials of one case are not independent, so a binomial interval over N*k trials is too
    narrow. The cluster-robust standard error (Miller 2024, "Adding error bars to evals") is
    used when it is defined, with a t(G - 1) critical value rather than z, since cluster-robust
    intervals over-cover nothing and under-cover with few clusters (Cameron, Gelbach & Miller
    2008). When the symmetric interval would cross 0 or 1 it is built on the logit scale
    instead. When the standard error collapses to zero (every case passes or fails all its
    trials) the Wilson interval over clusters is used, since n = clusters is the honest sample
    size then.

    `groups`, one key per case (a template, source trace or seed; None for a case alone),
    clusters cases that tend to pass or fail together (docs/statistics.md §4.3): their trials
    are pooled into one cluster.
    """
    cases = [list(t) for t in trials_by_case]
    keys = list(groups) if groups is not None else [None] * len(cases)
    merged: dict = {}
    for i, (t, g) in enumerate(zip(cases, keys, strict=True)):
        if t:
            merged.setdefault(("g", g) if g is not None else ("c", i), []).extend(t)
    clusters = list(merged.values())
    n_trials = sum(len(c) for c in clusters)
    if n_trials == 0:
        return None
    passes = sum(sum(1 for x in c if x) for c in clusters)
    p = passes / n_trials
    n_clusters = len(clusters)
    n_cases = sum(1 for t in cases if t)
    if all(len(c) == 1 for c in clusters):
        ci = wilson(passes, n_trials)
        method = "wilson"
    else:
        s_ = sum((sum(1 for x in c if x) - len(c) * p) ** 2 for c in clusters)
        se = math.sqrt(s_) / n_trials
        if se > 0 and n_clusters > 1:
            crit = t_quantile(0.975, n_clusters - 1) or Z95
            lo, hi = p - crit * se, p + crit * se
            if (lo < 0 or hi > 1) and 0 < p < 1:
                se_l = se / (p * (1 - p))
                lg = math.log(p / (1 - p))
                lo, hi = 1 / (1 + math.exp(-(lg - crit * se_l))), 1 / (1 + math.exp(-(lg + crit * se_l)))
                method = "cluster_robust_t_logit"
            else:
                method = "cluster_robust_t"
            ci = (max(0.0, lo), min(1.0, hi))
        else:
            all_same = sum(1 for c in clusters if all(c)) in (0, n_clusters)
            ci = wilson(round(p * n_clusters), n_clusters) if all_same else None
            method = "wilson_over_cases" if groups is None else "wilson_over_clusters"
    out = {"point": p, "ci": list(ci) if ci else None, "n": n_trials, "n_cases": n_cases,
           "ci_method": method}
    if groups is not None:
        out["n_clusters"] = n_clusters
    return out


def weighted_estimate(strata: Sequence[tuple[float, float, int]]) -> dict | None:
    """Share-weighted pass rate over strata (weight, passes, n) with a normal interval. `passes`
    may be fractional (the sum of per-case pass rates when n counts cases).

    Used for the quality estimate (M14): weights are each category's observed share of traffic.
    """
    usable = [(w, s, n) for w, s, n in strata if n > 0 and w > 0]
    if not usable:
        return None
    wsum = sum(w for w, _, _ in usable)
    point = 0.0
    var = 0.0
    for w, s, n in usable:
        wn = w / wsum
        p = s / n
        point += wn * p
        # Agresti-Caffo style: never let a stratum at 0 or 1 contribute zero variance.
        pa = (s + 1) / (n + 2)
        var += wn**2 * pa * (1 - pa) / n
    se = math.sqrt(var)
    return {"point": point, "ci": [max(0.0, point - Z95 * se), min(1.0, point + Z95 * se)],
            "weights": {}, "n": sum(n for _, _, n in usable)}


def sample_size_for_halfwidth(halfwidth: float, p: float = 0.5) -> int:
    """Cases needed for a 95% interval of +/- halfwidth on a proportion near p."""
    return math.ceil(Z95**2 * p * (1 - p) / halfwidth**2)


def mde(n: int, p: float = 0.5, k: int = 1, within_case_var: float | None = None) -> float | None:
    """Minimum detectable effect (M7) for a two-arm comparison on the same n cases at 80% power
    and alpha 0.05.

    With no data, this is the unpaired worst case at rate p: an upper bound, since pairing only
    removes variance. With measured within-case variance from a baseline (mean of p_i(1-p_i)
    across cases), the paired form is used: between-case variance cancels in a paired design,
    leaving 2 * within / k per case. Floored at 1/n, the smallest change n cases can show.
    """
    if n <= 0:
        return None
    if within_case_var is None:
        var = 2 * p * (1 - p)
    else:
        var = 2 * within_case_var / max(k, 1)
    value = (Z95 + Z80_POWER) * math.sqrt(var / n)
    return max(value, 1 / n)


def mde_from_deltas(deltas: Sequence[float]) -> float | None:
    """The detectable effect implied by a comparison's own per-case deltas: (z_alpha + z_power) x
    sd(delta) / sqrt(n). Unlike `mde` from baseline noise alone, it includes how unevenly the
    change moved cases (case-by-change interaction), so it is the honest one after the fact."""
    n = len(deltas)
    if n < 2:
        return None
    m = sum(deltas) / n
    sd = math.sqrt(sum((d - m) ** 2 for d in deltas) / (n - 1))
    return max((Z95 + Z80_POWER) * sd / math.sqrt(n), 1 / n)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile, q in [0, 100]."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return float(xs[0])
    pos = (len(xs) - 1) * q / 100
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return float(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


# ---- detection and zero-failure bounds (M30) -------------------------------------------------

def zero_failure_bound(n: int, confidence: float = 0.95) -> float | None:
    """The exact one-sided upper bound on a failure rate when n independent cases show no failure:
    1 - (1 - confidence)^(1/n), about 3/n at 95% (the "rule of three", Hanley & Lippman-Hand 1983).

    Read the other way it is the smallest per-case failure rate that n cases surface at least once
    with that probability, so it also sizes an error-finding set: 10 cases surface a failure that
    hits 26% of runs, not one that hits 5%.
    """
    if n <= 0:
        return None
    return 1 - (1 - confidence) ** (1 / n)


def cases_to_surface(rate: float, probability: float = 0.95) -> int | None:
    """Independent cases needed to see at least one failure that occurs at `rate`, with
    `probability`: ln(1 - probability) / ln(1 - rate). 299 cases for a 1% failure at 95%."""
    if not 0 < rate < 1 or not 0 < probability < 1:
        return None
    return math.ceil(math.log(1 - probability) / math.log(1 - rate))


# ---- evidence for a floor (M35) --------------------------------------------------------------

def labels_for_halfwidth(rate: float, halfwidth: float = 0.10, limit: int = 100_000) -> int | None:
    """The fewest items of one kind for a Wilson 95% interval no wider than +/- halfwidth at
    `rate`. TPR and TNR are each measured on one kind of label, so this is per class."""
    if not 0 <= rate <= 1 or halfwidth <= 0:
        return None
    for n in range(1, limit + 1):
        ci = wilson(round(rate * n), n)
        if ci and (ci[1] - ci[0]) / 2 <= halfwidth:
            return n
    return None


def floor_evidence(k: int, n: int, floor: float, margin: float = 0.10, limit: int = 10_000) -> dict | None:
    """Whether k/n clears `floor` with enough evidence: a non-inferiority reading.

    `meets_point` is the rule the gates apply today (the point estimate at or above the floor).
    `meets_margin` adds that the Wilson 95% lower bound is no more than `margin` below the floor,
    so a rate measured on a handful of items cannot clear it by luck. This is the framing of
    non-inferiority trials and of the alternative-annotator test (Calderon et al. 2025), which
    also accept a stated margin rather than demand the lower bound itself clear the bar.
    `n_needed` is the smallest n at which a result at today's point estimate would meet the
    margin (None when the point is below the floor: more of the same will not help).
    Informational: no gate reads it (docs/statistics.md, proposals).
    """
    ci = wilson(k, n)
    if ci is None:
        return None
    point = k / n
    need = None
    if point >= floor:
        for m in range(n, limit + 1):
            c = wilson(round(point * m), m)
            if c and c[0] >= floor - margin:
                need = m
                break
    return {"point": point, "lower": ci[0], "n": n, "floor": floor, "margin": margin,
            "meets_point": point >= floor, "meets_margin": point >= floor and ci[0] >= floor - margin,
            "n_needed": need}


# ---- agreement that survives a skewed base rate (M34) ---------------------------------------

def agreement_stats(pairs: Sequence[tuple[bool, bool]]) -> dict | None:
    """Two raters' binary verdicts on the same items: Cohen's kappa, Gwet's AC1, and the
    positive and negative specific agreement (Cicchetti & Feinstein 1990).

    Kappa falls toward zero, or below it, when one answer dominates, even at high agreement (the
    "high agreement, low kappa" paradox, Feinstein & Cicchetti 1990). AC1 does not, and the two
    specific agreements say which answer the raters disagree on: at a 95% pass rate, raters can
    agree on every pass and on none of the failures.
    """
    n = len(pairs)
    if n == 0:
        return None
    a = sum(1 for x, y in pairs if x and y)
    d = sum(1 for x, y in pairs if not x and not y)
    bc = n - a - d
    po = (a + d) / n
    pa_, pb_ = sum(1 for x, _ in pairs if x) / n, sum(1 for _, y in pairs if y) / n
    pe_k = pa_ * pb_ + (1 - pa_) * (1 - pb_)
    pi = (pa_ + pb_) / 2
    pe_g = 2 * pi * (1 - pi)
    return {"n": n, "observed": po,
            "kappa": (po - pe_k) / (1 - pe_k) if pe_k < 1 else None,
            "ac1": (po - pe_g) / (1 - pe_g) if pe_g < 1 else None,
            "positive_agreement": 2 * a / (2 * a + bc) if (2 * a + bc) else None,
            "negative_agreement": 2 * d / (2 * d + bc) if (2 * d + bc) else None}


# ---- correcting a rate for a measured judge (M32) -------------------------------------------

def rogan_gladen(q_k: int, q_n: int, tpr_k: int, tpr_n: int, tnr_k: int, tnr_n: int) -> dict | None:
    """The true rate of the positive class, corrected for a judge's measured error
    (Rogan & Gladen 1978), with a delta-method 95% interval.

    q = q_k / q_n is the share of items the judge calls positive; TPR = P(judge positive | truly
    positive) and TNR = P(judge negative | truly negative), measured on human labels. Then
    pi = (q + TNR - 1) / (TPR + TNR - 1). The interval carries the uncertainty of all three
    inputs, so a judge calibrated on few labels gives a wide one. Undefined (None) unless
    TPR + TNR > 1: a judge no better than chance cannot be corrected.
    """
    if min(q_n, tpr_n, tnr_n) <= 0:
        return None
    q, tpr, tnr = q_k / q_n, tpr_k / tpr_n, tnr_k / tnr_n
    j = tpr + tnr - 1
    if j <= 0:
        return None
    pi = (q + tnr - 1) / j
    var = (q * (1 - q) / q_n + (1 - pi) ** 2 * tnr * (1 - tnr) / tnr_n
           + pi ** 2 * tpr * (1 - tpr) / tpr_n) / j ** 2
    se = math.sqrt(max(var, 0.0))
    point = min(1.0, max(0.0, pi))
    return {"point": point, "ci": [max(0.0, pi - Z95 * se), min(1.0, pi + Z95 * se)],
            "observed": q, "youden_j": j, "method": "rogan_gladen_delta"}


# ---- combining a few human labels with many automatic verdicts (M33) ------------------------

def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _var(xs: Sequence[float]) -> float:
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1) if len(xs) > 1 else 0.0


def ppi_mean(f_unlabeled: Sequence[float], f_labeled: Sequence[float], y_labeled: Sequence[float]) -> dict | None:
    """Prediction-powered estimate of a mean (PPI++, Angelopoulos, Duchi & Zrnic 2023).

    y are human labels (1 pass, 0 fail) on n items; f are the automatic verdicts on those same
    items and on N items nobody labeled. The estimate is mean(y) + lambda * (mean(f_unlabeled) -
    mean(f_labeled)): the labels' mean, corrected by how far the verdicts on the labeled items
    sit from the verdicts on everything else. lambda is tuned to the data and clipped to [0, 1];
    at 0 it is the labels-only estimate, so it is never meaningfully worse. Valid when the
    labeled items are a random sample of the same population as the unlabeled ones.
    """
    n, big_n = len(y_labeled), len(f_unlabeled)
    if n < 2 or big_n < 1 or len(f_labeled) != n:
        return None
    fy = list(zip(f_labeled, y_labeled, strict=True))
    my, mfl, mfu = _mean(y_labeled), _mean(f_labeled), _mean(f_unlabeled)
    cov = sum((f - mfl) * (y - my) for f, y in fy) / (n - 1)
    var_f = _var(list(f_labeled) + list(f_unlabeled))
    lam = 0.0 if var_f == 0 else min(1.0, max(0.0, cov / ((1 + n / big_n) * var_f)))
    point = my + lam * (mfu - mfl)
    resid = [y - lam * f for f, y in fy]
    var = _var(resid) / n + lam ** 2 * _var(f_unlabeled) / big_n
    se = math.sqrt(max(var, 0.0))
    labels_only = wilson(round(sum(y_labeled)), n)
    return {"point": min(1.0, max(0.0, point)),
            "ci": [max(0.0, point - Z95 * se), min(1.0, point + Z95 * se)],
            "lambda": lam, "n_labeled": n, "n_unlabeled": big_n,
            "labels_only": {"point": my, "ci": list(labels_only) if labels_only else None},
            "method": "ppi++ (power-tuned), normal interval"}


# ---- where the noise comes from: cases or trials (M31) --------------------------------------

def variance_components(trials_by_case: Sequence[Sequence[float]]) -> dict | None:
    """Split the variance of per-trial outcomes into between-case and within-case parts
    (a one-facet G-study: Cronbach et al. 1972; one-way random-effects ANOVA, unequal k).

    Between-case variance is how much cases differ in how hard they are; within-case variance is
    run-to-run noise on one case. Only within-case noise shrinks with more trials, so the split
    says whether the next unit of budget should buy cases or trials (a D-study): the standard
    error of the mean pass rate is sqrt(between / N + within / (N * k)).

    The same split works one level up: pass each cluster's per-case pass rates (cases grouped
    by template or source trace) and `icc` is the cluster-level correlation that sets the
    design effect 1 + (m - 1) * icc for the cases themselves.
    """
    clusters = [[float(x) for x in c] for c in trials_by_case if len(c) > 0]
    n_cases = len(clusters)
    total = sum(len(c) for c in clusters)
    if n_cases < 2 or total <= n_cases:
        return None
    grand = sum(sum(c) for c in clusters) / total
    ssw = sum(sum((x - _mean(c)) ** 2 for x in c) for c in clusters)
    ssb = sum(len(c) * (_mean(c) - grand) ** 2 for c in clusters)
    msw = ssw / (total - n_cases)
    msb = ssb / (n_cases - 1)
    k0 = (total - sum(len(c) ** 2 for c in clusters) / total) / (n_cases - 1)
    between = max(0.0, (msb - msw) / k0) if k0 > 0 else 0.0
    within = msw
    tot = between + within
    k = total / n_cases

    def se(n_, k_):
        return math.sqrt(between / n_ + within / (n_ * k_))

    icc = between / tot if tot > 0 else None
    deff = 1 + (k - 1) * icc if icc is not None else None
    return {"n_cases": n_cases, "mean_k": k, "between_case": between, "within_case": within,
            "icc": icc, "design_effect": deff,
            "effective_n": total / deff if deff else None,
            "within_share_of_error": (within / k) / (between + within / k) if (between + within / k) > 0 else None,
            "se_now": se(n_cases, k), "se_double_cases": se(2 * n_cases, k), "se_double_trials": se(n_cases, 2 * k),
            "method": "one-way random effects (ANOVA), unequal k"}


# ---- tests for comparisons -------------------------------------------------------------------

WEBB = (-math.sqrt(1.5), -1.0, -math.sqrt(0.5), math.sqrt(0.5), 1.0, math.sqrt(1.5))


def _cluster_sums(deltas: Sequence[float], clusters: Sequence[str | None] | None, mu: float = 0.0) -> list[float]:
    """Sum of (delta - mu) per cluster; a case without a key is its own cluster."""
    if clusters is None:
        return [d - mu for d in deltas]
    sums: dict = {}
    for i, (d, g) in enumerate(zip(deltas, clusters, strict=True)):
        key = ("g", g) if g is not None else ("c", i)
        sums[key] = sums.get(key, 0.0) + (d - mu)
    return list(sums.values())


def min_attainable_p(n_clusters: int) -> float | None:
    """The smallest two-sided p-value a sign-flip test can return on G clusters: 2 / 2^G. At
    G <= 5 it is at least 0.0625, so no number of cases per cluster can reach 5%."""
    return None if n_clusters <= 0 else min(1.0, 2 / 2 ** n_clusters)


def _sign_patterns(g: int, draws: int, seed: int, weights: str) -> tuple[list[list[float]], bool]:
    """Every +/-1 pattern when that is at most 2^16 of them (exact), else Monte Carlo draws."""
    if weights == "rademacher" and g <= 16:
        return [[1.0 if (m >> i) & 1 else -1.0 for i in range(g)] for m in range(2 ** g)], True
    import random as _random
    rng = _random.Random(seed)
    if weights == "webb":
        return [[rng.choice(WEBB) for _ in range(g)] for _ in range(draws)], False
    return [[1.0 if rng.random() < 0.5 else -1.0 for _ in range(g)] for _ in range(draws)], False


def _flip_p(sums: Sequence[float], patterns: list[list[float]], exact: bool) -> float:
    obs = abs(sum(sums))
    eps = 1e-12 * (1 + obs)
    hits = sum(abs(sum(w * x for w, x in zip(pat, sums, strict=True))) >= obs - eps for pat in patterns)
    return hits / len(patterns) if exact else (hits + 1) / (len(patterns) + 1)


def sign_flip_test(deltas: Sequence[float], draws: int = 20_000, seed: int = 0,
                   clusters: Sequence[str | None] | None = None, weights: str | None = None) -> float | None:
    """Two-sided paired permutation (sign-flip) test of a zero mean per-case delta.

    Under no effect each case's delta is as likely to have either sign, so the observed mean is
    compared with the means of every sign pattern: exact up to 16 units, Monte Carlo (with the
    +1 correction) above. Unlike McNemar on majority flips it uses every change in a case's pass
    rate, which is the quantity the minimum detectable effect (M7) is computed for.

    With `clusters` (one key per case), signs flip per cluster, not per case: cases that share a
    template or source trace move together, and flipping them one by one overstates the
    evidence (docs/statistics.md §4.3). `weights` is "rademacher" (+/-1) or "webb" (Webb's
    six-point weights, for 6 to 9 clusters, where +/-1 has too few distinct patterns; Webb
    2023); by default Webb is used for 6 <= G < 10 and Rademacher otherwise. At G <= 5 the test
    cannot reach 5% (see `min_attainable_p`).
    """
    if not deltas:
        return None
    sums = [x for x in _cluster_sums(deltas, clusters) if x != 0]
    if not sums:
        return 1.0
    g = len(_cluster_sums(deltas, clusters))
    w = weights or ("webb" if clusters is not None and 6 <= g < 10 else "rademacher")
    patterns, exact = _sign_patterns(len(sums), draws, seed, w)
    return _flip_p(sums, patterns, exact)


def sign_flip_interval(deltas: Sequence[float], clusters: Sequence[str | None] | None = None,
                       alpha: float = 0.05, draws: int = 4_000, seed: int = 0) -> list[float] | None:
    """A confidence interval for the mean per-case delta, by inverting the sign-flip test: every
    mu at which flipping the signs of (delta - mu) per case, or per cluster, is not rejected.

    It assumes only that each unit's delta is symmetric about mu, not that the mean is normal,
    so it holds its coverage on small suites near a ceiling where the percentile bootstrap does
    not. The same sign patterns are reused at every mu, so the bounds are deterministic. None
    when there are too few units for any interval at this alpha (2 / 2^G >= alpha).
    """
    n = len(deltas)
    if n < 2:
        return None
    g = len(_cluster_sums(deltas, clusters))
    if (min_attainable_p(g) or 1) >= alpha:
        return None
    w = "webb" if clusters is not None and 6 <= g < 10 else "rademacher"
    patterns, exact = _sign_patterns(g, draws, seed, w)
    mean = sum(deltas) / n

    def accepted(mu: float) -> bool:
        return _flip_p(_cluster_sums(deltas, clusters, mu), patterns, exact) > alpha

    def bound(direction: int) -> float:
        inside, outside = mean, mean + direction * (max(abs(d) for d in deltas) + 1.0)
        while accepted(outside):  # widen until rejected (the range of deltas always is)
            outside += direction * 1.0
        for _ in range(40):
            mid = (inside + outside) / 2
            if accepted(mid):
                inside = mid
            else:
                outside = mid
        return inside

    return [bound(-1), bound(+1)]


def mcnemar_midp(gains: int, losses: int) -> float:
    """McNemar's test with the mid-p correction: the exact two-sided p-value minus the
    probability of the observed split itself. The exact conditional test is conservative (its
    real size is often near 2% at a nominal 5%); the mid-p version keeps close to nominal and is
    the one recommended for paired binary data (Fagerland, Lydersen & Laake 2013)."""
    n = gains + losses
    if n == 0:
        return 1.0
    k = min(gains, losses)
    below = sum(math.comb(n, i) for i in range(k)) / 2 ** n
    at = math.comb(n, k) / 2 ** n
    return min(1.0, 2 * (below + 0.5 * at)) if gains != losses else 1.0


def flip_summary(gains: int, losses: int, n_cases: int) -> dict | None:
    """What a paired comparison's flips hold: b losses (pass -> fail), c gains (fail -> pass)
    among N cases. The net change is (c - b)/N, the flip rate d = (b + c)/N, and the standard
    error of the net is sqrt((d - net^2)/N). The same +5 points from 10 clean fixes and from 30
    gains with 20 losses are different changes: the second is more than twice as uncertain."""
    if n_cases <= 0:
        return None
    net = (gains - losses) / n_cases
    d = (gains + losses) / n_cases
    se = math.sqrt(max(d - net ** 2, 0.0) / n_cases)
    return {"gains": gains, "losses": losses, "n_cases": n_cases, "net": net, "flip_rate": d,
            "se": se, "ci": [net - Z95 * se, net + Z95 * se]}


def cases_for_flip_rate(flip_rate: float, effect: float, power_z: float = Z80_POWER) -> int | None:
    """Cases a paired comparison needs to detect a net change `effect` (two-sided 5%, 80% power
    by default) when a share `flip_rate` of cases flip between versions: (z_a + z_b)^2 d / effect^2,
    about 7.85 d / effect^2. The flip rate, not the pass rate, sets it, so size the next
    comparison from the flip rate of the last one, or of an A/A rerun for the noise floor."""
    if effect <= 0 or not 0 < flip_rate <= 1:
        return None
    return math.ceil((Z95 + power_z) ** 2 * flip_rate / effect ** 2)


# ---- correlated cases: clusters (docs/statistics.md §4.3) -----------------------------------

def cluster_summary(clusters: Sequence[str | None], dominant_share: float = 0.30) -> dict:
    """G, the cluster sizes, and what inference G allows. A case without a key counts as its own
    cluster. Regimes: at G <= 5 no sign-flip test can reach 5%, so only "better on these cases"
    can be said; at 6 <= G < 10 Webb weights; above, Rademacher signs. A cluster holding more
    than `dominant_share` of the cases is flagged: one template then decides the result."""
    sizes: dict = {}
    for i, g in enumerate(clusters):
        key = g if g is not None else f"\0case{i}"
        sizes[key] = sizes.get(key, 0) + 1
    n = len(clusters)
    g_ = len(sizes)
    keyed = sum(1 for g in clusters if g is not None)
    regime = ("cases_assumed_independent" if keyed == 0 else
              "fixed_suite_only" if g_ <= 5 else "webb" if g_ < 10 else "rademacher")
    named = {k: v for k, v in sizes.items() if not str(k).startswith("\0case")}
    return {"n_cases": n, "n_clusters": g_, "keyed_cases": keyed,
            "largest": max(sizes.values()) if sizes else 0,
            "mean_size": n / g_ if g_ else None,
            "dominant": sorted(k for k, v in named.items() if n and v / n > dominant_share),
            "min_attainable_p": min_attainable_p(g_), "regime": regime}


def design_effect(mean_cluster_size: float, icc: float) -> float:
    """Kish's design effect for clusters of mean size m with intra-cluster correlation rho:
    1 + (m - 1) * rho. Variances computed as if cases were independent are too small by this
    factor."""
    return 1 + (mean_cluster_size - 1) * icc


def effective_n(n: int, mean_cluster_size: float, icc: float | None) -> float | None:
    """How many independent cases n correlated ones are worth: n / design effect. Feed it to
    `zero_failure_bound` and `wilson` in place of n. With failures all-or-nothing per cluster
    (icc = 1) it is the number of clusters: 100 cases from 10 seeds bound a clean result's
    failure rate at about 26%, not 3%."""
    if icc is None or n <= 0 or mean_cluster_size <= 0:
        return None
    return n / design_effect(mean_cluster_size, max(0.0, min(1.0, icc)))


def cluster_jackknife(deltas: Sequence[float], clusters: Sequence[str | None]) -> dict | None:
    """The mean per-case delta with a leave-one-cluster-out (CV3) standard error and a t(G - 1)
    interval: the cross-check MacKinnon, Nielsen & Webb (2023) recommend beside a wild cluster
    test when clusters are few or unequal."""
    n = len(deltas)
    groups: dict = {}
    for i, (d, g) in enumerate(zip(deltas, clusters, strict=True)):
        groups.setdefault(("g", g) if g is not None else ("c", i), []).append(d)
    g_ = len(groups)
    if n < 2 or g_ < 2:
        return None
    total = sum(deltas)
    loo = [(total - sum(v)) / (n - len(v)) for v in groups.values() if n - len(v) > 0]
    m = sum(loo) / len(loo)
    se = math.sqrt((g_ - 1) / g_ * sum((x - m) ** 2 for x in loo))
    crit = t_quantile(0.975, g_ - 1) or Z95
    mean = total / n
    return {"mean": mean, "se": se, "df": g_ - 1, "ci": [mean - crit * se, mean + crit * se],
            "method": "cluster jackknife (CV3), t(G-1)"}


def overdispersion_test(values_by_cluster: Sequence[Sequence[float]], draws: int = 5_000,
                        seed: int = 0) -> dict | None:
    """Do cases in one cluster pass or fail together more than chance allows? The statistic is
    the between-cluster sum of squares of case pass rates (a Pearson-style dispersion); its
    null distribution comes from shuffling cases across clusters, keeping cluster sizes. A
    small p means the clusters are real, and inference should flip signs per cluster."""
    import random as _random
    clusters = [list(map(float, c)) for c in values_by_cluster if c]
    if len(clusters) < 2:
        return None
    flat = [x for c in clusters for x in c]
    sizes = [len(c) for c in clusters]
    grand = sum(flat) / len(flat)

    def stat(cs):
        return sum(len(c) * (sum(c) / len(c) - grand) ** 2 for c in cs)

    obs = stat(clusters)
    rng = _random.Random(seed)
    hits = 0
    for _ in range(draws):
        rng.shuffle(flat)
        cs, i = [], 0
        for sz in sizes:
            cs.append(flat[i:i + sz])
            i += sz
        hits += stat(cs) >= obs - 1e-12
    vc = variance_components(clusters)
    return {"statistic": obs, "p": (hits + 1) / (draws + 1), "n_clusters": len(clusters),
            "icc": vc["icc"] if vc else None, "method": "permutation of cases across clusters"}


def cochran_q(trials_by_case: Sequence[Sequence[bool]], draws: int = 5_000, seed: int = 0) -> dict | None:
    """Did one repeat of the run fail more cases than the others (an outage, a rate limit, a
    provider change mid-run)? Cochran's Q with cases as blocks and repeats as treatments; the p
    comes from shuffling each case's outcomes across its repeats. Needs the same k per case,
    trials in repeat order. A small p means a shock hit some repeats: interleave baseline and
    candidate trials so it hits both sides, or re-run the affected repeat."""
    import random as _random
    rows = [[1 if x else 0 for x in t] for t in trials_by_case if t]
    if len(rows) < 2:
        return None
    k = len(rows[0])
    if k < 2 or any(len(r) != k for r in rows):
        return None

    def q(rs):
        cols = [sum(r[j] for r in rs) for j in range(k)]
        rowsum = [sum(r) for r in rs]
        t = sum(cols)
        den = k * t - sum(x * x for x in rowsum)
        return (k - 1) * (k * sum(c * c for c in cols) - t * t) / den if den else 0.0

    obs = q(rows)
    rng = _random.Random(seed)
    hits = 0
    for _ in range(draws):
        hits += q([rng.sample(r, k) for r in rows]) >= obs - 1e-12
    return {"q": obs, "df": k - 1, "p": (hits + 1) / (draws + 1), "repeats": k,
            "method": "Cochran's Q, permutation within cases"}


def benjamini_hochberg(pvalues: Sequence[float | None]) -> list[float | None]:
    """Benjamini-Hochberg adjusted p-values (false discovery rate), None left in place. Use when
    several categories are each tested: at 10 categories and alpha 0.05, two suites in five with
    no real change would show at least one "significant" category by chance."""
    idx = [(p, i) for i, p in enumerate(pvalues) if p is not None]
    m = len(idx)
    out: list[float | None] = [None] * len(pvalues)
    running = 1.0
    for rank, (p, i) in reversed(list(enumerate(sorted(idx), start=1))):
        running = min(running, p * m / rank)
        out[i] = min(1.0, running)
    return out


# ---- Student t (the standard library has none) ----------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return h


def betainc_regularized(a: float, b: float, x: float) -> float:
    """I_x(a, b), the regularized incomplete beta function."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def t_cdf(t: float, df: float) -> float | None:
    """The Student t distribution function."""
    if df <= 0:
        return None
    tail = 0.5 * betainc_regularized(df / 2, 0.5, df / (df + t * t))
    return 1 - tail if t >= 0 else tail


def t_quantile(p: float, df: float) -> float | None:
    """The Student t quantile, by bisection on `t_cdf`. t(0.975, 9) = 2.262."""
    if df <= 0 or not 0 < p < 1:
        return None
    lo, hi = -1e3, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---- what the score is for: category weights (docs/statistics.md §1.1, §2.2) ---------------

def objective_weights(shares: dict[str, float | None], weights: dict[str, float | None]) -> dict[str, float] | None:
    """Normalized weights of the headline objective, sum(share x weight x pass rate) /
    sum(share x weight). `weights` is how much a failure in each category matters, as a ratio;
    equal weights give the traffic-weighted score as the special case. None when a category
    lacks a share or a weight: an unstated weight is unknown, not 1."""
    if not shares or any(not isinstance(shares.get(c), (int, float)) for c in shares):
        return None
    if any(not isinstance(weights.get(c), (int, float)) or weights[c] < 0 for c in shares):
        return None
    raw = {c: shares[c] * weights[c] for c in shares}
    total = sum(raw.values())
    return {c: v / total for c, v in raw.items()} if total > 0 else None


def blind_spot(objective_weight: float, smallest_drop: float, overall_mde: float | None) -> dict | None:
    """Can the headline score see a regression in this category? A drop of `smallest_drop` in a
    category moves the objective by objective_weight x smallest_drop. If that is below the
    comparison's detectable effect, the score is blind to it, and the category needs a guardrail
    of its own: a non-inferiority test on that category alone. A 2% category that drops 10
    points moves a traffic-weighted score by 0.2 points; a 100-case comparison detects about 11."""
    if overall_mde is None or objective_weight < 0 or smallest_drop <= 0:
        return None
    moves = objective_weight * smallest_drop
    return {"moves_objective_by": moves, "overall_mde": overall_mde, "blind": moves < overall_mde}


def cases_per_arm(p1: float, p2: float, power_z: float = Z80_POWER) -> int | None:
    """Cases per version to detect a change from pass rate p1 to p2, unpaired, two-sided 5%:
    (z_a + z_b)^2 (p1 q1 + p2 q2) / (p1 - p2)^2. Pairing lowers it. Halving a failure rate takes
    55 cases at 50% failure, 118 at 30%, 431 at 10% and 4,665 at 1%: improvement is sized by the
    change worth seeing, not by how hard the category is."""
    if p1 == p2 or not (0 <= p1 <= 1 and 0 <= p2 <= 1):
        return None
    return math.ceil((Z95 + power_z) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p1 - p2) ** 2)


def allocation_target(state: str, *, smallest_change: float | None = None, flip_rate: float | None = None,
                      tolerated_drop: float | None = None, costly_mode_rates: Sequence[float] = (),
                      guardrail_drop: float | None = None, floor: int = 3,
                      probability: float = 0.95) -> dict | None:
    """One category's case target, from its state and its costly failure modes.

    - state "improve" (room to improve): cases to see a net change of `smallest_change` given the
      category's `flip_rate` (cases_for_flip_rate);
    - state "solved" (the remaining failures explained): a regression guard that surfaces a
      `tolerated_drop` with `probability` (cases_to_surface: 29 for 10 points, 59 for 5,
      149 for 2, 299 for 1, past which a check on every production run beats offline cases);
    - on top, in either state: each rare, costly failure mode at its rate needs enough cases to
      surface it (one entry in `costly_mode_rates` per mode);
    - if the blind-spot check fired, the cases a non-inferiority guardrail on the category alone
      needs to see `guardrail_drop` (taken as a detection need, the conservative reading).

    The target is the largest of the needs (the same cases serve every job), never below
    `floor`. Weights enter through the inputs: a heavier category gets a smaller smallest_change,
    tolerated_drop and guardrail_drop, and more of its failure modes count as costly.
    """
    needs: dict[str, int | None] = {}
    if state == "improve":
        needs["improvement"] = (cases_for_flip_rate(flip_rate, smallest_change)
                                if flip_rate and smallest_change else None)
    elif state == "solved":
        needs["regression_guard"] = cases_to_surface(tolerated_drop, probability) if tolerated_drop else None
    else:
        return None
    for i, r in enumerate(costly_mode_rates):
        needs[f"costly_mode_{i + 1}"] = cases_to_surface(r, probability)
    if guardrail_drop:
        needs["guardrail"] = cases_to_surface(guardrail_drop, probability)
    known = [v for v in needs.values() if v is not None]
    return {"state": state, "needs": needs, "target": max([floor, *known]),
            "unknown_needs": sorted(k for k, v in needs.items() if v is None)}


def neyman_allocation(strata: dict[str, tuple[float, float]], total: int, floor: int = 0) -> dict[str, int] | None:
    """Split `total` cases across strata in proportion to objective weight x standard deviation
    (Neyman 1934), with weight = share x category weight: the narrowest interval on the weighted
    objective for a fixed budget. `strata` maps a category to (objective weight, expected pass
    rate). A stratum near 0% or 100% still gets `floor`. Rounded by largest remainder."""
    if total <= 0 or not strata:
        return None
    score = {c: w * math.sqrt(max(p * (1 - p), 0.0025)) for c, (w, p) in strata.items()}
    s = sum(score.values())
    if s <= 0:
        return None
    left = max(total - floor * len(strata), 0)
    raw = {c: left * v / s for c, v in score.items()}
    out = {c: floor + math.floor(v) for c, v in raw.items()}
    rest = total - sum(out.values())
    for c in sorted(raw, key=lambda c: raw[c] - math.floor(raw[c]), reverse=True)[:max(rest, 0)]:
        out[c] += 1
    return out


def stratified_draw(population: dict[str, Sequence[str]], n_by_stratum: dict[str, int], seed: int) -> dict:
    """A seeded simple random draw within each stratum, recorded with each item's inclusion
    probability n_h / N_h, so the quality-estimate set is a stratified random sample rather than
    a quota the author fills, and Horvitz-Thompson weights (1 / probability) are known. Skips
    after the draw must be recorded with a reason; replace a skip with the next item of a
    second seeded draw, never by hand."""
    import random as _random
    rng = _random.Random(seed)
    drawn, probs = {}, {}
    for stratum in sorted(population):
        items = sorted(population[stratum])
        n = min(n_by_stratum.get(stratum, 0), len(items))
        pick = rng.sample(items, n) if n else []
        drawn[stratum] = sorted(pick)
        for it in pick:
            probs[it] = n / len(items)
    return {"seed": seed, "drawn": drawn, "inclusion_probability": probs, "method": "stratified simple random"}


# ---- are failures equally costly? (docs/statistics.md §1.2) ---------------------------------

SEVERITY = ("low", "medium", "high")


def failure_severity(*, writes: bool, reversible: bool | None, noticed: bool | None) -> str | None:
    """A failure's cost class from what it did: a write, delete or send that can't be undone is
    high; a side effect that can be undone, or a wrong answer nobody would notice before acting
    on it, is medium; a wrong answer a person would notice is low. Unknown parts are unknown."""
    if writes:
        if reversible is None:
            return None
        return "medium" if reversible else "high"
    if noticed is None:
        return None
    return "low" if noticed else "medium"


def cost_flags(failures: Sequence[tuple[str, str | None]], declared: dict[str, str | None]) -> dict:
    """The uneven-cost check on real failures. `failures` is (category, severity) for each
    baseline failure or triaged disagreement; `declared` is each category's declared cost
    (low, medium, high) from the owner. A category is flagged when its failures span more than
    one severity with a high one among them (uneven), or when any failure is worse than its
    declared cost (e.g. a read-only request that wrote to a record, in a category the owner
    rated low). `even` is true only when no category is flagged and every severity is known."""
    by_cat: dict[str, list[str | None]] = {}
    for cat, sev in failures:
        by_cat.setdefault(cat, []).append(sev)
    rank = {s: i for i, s in enumerate(SEVERITY)}
    out, unknown = {}, 0
    for cat, sevs in sorted(by_cat.items()):
        known = [s for s in sevs if s in rank]
        unknown += len(sevs) - len(known)
        worst = max(known, key=rank.get) if known else None
        decl = declared.get(cat)
        uneven = len(set(known)) > 1 and "high" in known
        exceeds = bool(worst and decl in rank and rank[worst] > rank[decl])
        out[cat] = {"failures": len(sevs), "severities": {s: known.count(s) for s in SEVERITY if s in known},
                    "worst": worst, "declared": decl, "uneven": uneven, "exceeds_declared": exceeds,
                    "flag": uneven or exceeds}
    return {"categories": out, "unknown_severity": unknown,
            "even": bool(out) and unknown == 0 and not any(v["flag"] for v in out.values())}
