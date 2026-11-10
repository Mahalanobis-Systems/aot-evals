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


def clustered_pass_rate(trials_by_case: Sequence[Sequence[bool]]) -> dict | None:
    """Pass rate over trials, with an interval that treats each case's k trials as a cluster.

    Trials of one case are not independent, so a binomial interval over N*k trials is too
    narrow. The cluster-robust standard error (Miller 2024, "Adding error bars to evals") is
    used when it is defined; when it collapses to zero (every case passes or fails all its
    trials) the Wilson interval over cases is used instead, since n = cases is the honest
    sample size in that situation.
    """
    clusters = [list(t) for t in trials_by_case if len(t) > 0]
    n_trials = sum(len(c) for c in clusters)
    if n_trials == 0:
        return None
    passes = sum(sum(1 for x in c if x) for c in clusters)
    p = passes / n_trials
    n_clusters = len(clusters)
    if all(len(c) == 1 for c in clusters):
        ci = wilson(passes, n_trials)
        method = "wilson"
    else:
        s = sum((sum(1 for x in c if x) - len(c) * p) ** 2 for c in clusters)
        se = math.sqrt(s) / n_trials
        if se > 0 and n_clusters > 1:
            ci = (max(0.0, p - Z95 * se), min(1.0, p + Z95 * se))
            method = "cluster_robust"
        else:
            case_passes = sum(1 for c in clusters if all(c))
            ci = wilson(round(p * n_clusters), n_clusters) if case_passes in (0, n_clusters) else None
            method = "wilson_over_cases"
    return {"point": p, "ci": list(ci) if ci else None, "n": n_trials, "n_cases": n_clusters,
            "ci_method": method}


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

def variance_components(trials_by_case: Sequence[Sequence[bool]]) -> dict | None:
    """Split the variance of per-trial outcomes into between-case and within-case parts
    (a one-facet G-study: Cronbach et al. 1972; one-way random-effects ANOVA, unequal k).

    Between-case variance is how much cases differ in how hard they are; within-case variance is
    run-to-run noise on one case. Only within-case noise shrinks with more trials, so the split
    says whether the next unit of budget should buy cases or trials (a D-study): the standard
    error of the mean pass rate is sqrt(between / N + within / (N * k)).
    """
    clusters = [[1.0 if x else 0.0 for x in c] for c in trials_by_case if len(c) > 0]
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

def sign_flip_test(deltas: Sequence[float], draws: int = 20_000, seed: int = 0) -> float | None:
    """Two-sided paired permutation (sign-flip) test of a zero mean per-case delta.

    Under no effect each case's delta is as likely to have either sign, so the observed mean is
    compared with the means of every sign pattern: exact up to 16 non-zero deltas, Monte Carlo
    (with the +1 correction) above. Unlike McNemar on majority flips it uses every change in a
    case's pass rate, which is the quantity the minimum detectable effect (M7) is computed for.
    """
    import random as _random
    xs = [d for d in deltas if d != 0]
    if not deltas:
        return None
    if not xs:
        return 1.0
    obs = abs(sum(xs))
    eps = 1e-12
    if len(xs) <= 16:
        hits = 0
        for mask in range(2 ** len(xs)):
            s = sum(x if (mask >> i) & 1 else -x for i, x in enumerate(xs))
            hits += abs(s) >= obs - eps
        return hits / 2 ** len(xs)
    rng = _random.Random(seed)
    hits = sum(abs(sum(x if rng.random() < 0.5 else -x for x in xs)) >= obs - eps for _ in range(draws))
    return (hits + 1) / (draws + 1)


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
