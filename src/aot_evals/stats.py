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
