"""The two computations of hypotheses.md, section 4.2, and Holm's step-down, for every family.

    hypotheses.md 4.2  the cell statistic (the median of the R session values), the clustered BCa
                       interval and its one-sided p-value, the exact sign test, Holm per family;
    hypotheses.md 4.3  the cost family's two one-sided tests at [0.98, 1.02];
    hypotheses.md 4.4  superiority, B3 against 1.10, M1 and M3 against 1.00 (lower end), M2 against
                       1.00 (upper end);
    hypotheses.md 4.6  the chi-square quantile and Silverman's bandwidth of the R_C rule.

Adapted from the previous paper's analysis/stats.py and analysis/holm.py
(papers/typed-routing, same author): the BCa over clusters, z0 with ties counted as half, the
jackknife acceleration, Holm's adjusted p-values. What changed: the p-value of a bound counts the
share of resamples strictly beyond it (4.3, "the share of resamples below 0.98"; 5.2, "the share
of resamples below 1.10"), as the power simulation of design/proposal.md, Appendix A
(analysis/appendix_a_r_rule.py) does, and both tails are given; the statistic is the median of one
value per cluster member; the chi-square functions are copied from appendix_a_r_rule.py unchanged.

The clustered BCa. A cell's session is its cluster (4.2): one value per session, so a resample
draws sessions with replacement. The analysis clustered by lab job (4.1, section 10) passes each
session's job as its cluster label; a resample then draws jobs with replacement and keeps every
session of a drawn job.

Every random draw goes through `draw_clusters`, which takes the generator it is given and draws
`rng.integers(0, K, size=(B, K))`: B resamples of the K clusters. The callers own the order of the
draws (section 4.7; analysis/cells.py).

Pure NumPy and the standard library; `statistics.NormalDist` gives the normal functions, as in
Appendix A.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from math import comb, exp, isfinite, lgamma, log
from statistics import NormalDist
from typing import Callable, Sequence

import numpy as np

# ---------------------------------------------------------------- frozen constants

# hypotheses.md, "Words": alpha = 0.025, family-wise and one-sided, in every family.
ALPHA = 0.025
# hypotheses.md 4.2: 10,000 resamples of the sessions with replacement.
B_RESAMPLES = 10_000
# hypotheses.md 4.3: the cost family's margin, fixed by Alex on 2026-10-02.
COST_LOW, COST_HIGH = 0.98, 1.02
# hypotheses.md 5.2: B3's margin, Q at least 1.10 (Alex, 2026-10-02).
B3_BOUND = 1.10
# hypotheses.md 4.4: M1 and M3 "at most 1.00", M2 "at least 1.00" under the null.
M_BOUND = 1.00
# hypotheses.md 4.3: the BCa interval that each cost cell shows beside its Holm-level one.
LEVEL_95 = 0.95

_N = NormalDist()


def ndtr(x: float) -> float:
    """The standard normal distribution function."""
    return _N.cdf(float(x))


def ndtri(p: float) -> float:
    """Its inverse, for 0 < p < 1."""
    return _N.inv_cdf(float(p))


# ---------------------------------------------------------------- the exact sign test (4.2)


def sign_p(x: int, n: int) -> Fraction:
    """P(X >= x) for X binomial with n trials and 1/2, exactly (4.2: "p = P(X >= x), computed
    exactly")."""
    if n < 0:
        raise ValueError("n < 0")
    lo = max(int(x), 0)
    return Fraction(sum(comb(n, k) for k in range(lo, n + 1)), 2 ** n)


def _has_value(v: float | None) -> bool:
    return v is not None and isfinite(float(v))


def count_above(values: Sequence[float | None], bound: float) -> int:
    """The sessions strictly above the bound. A tie, or a session without a value, counts against
    (4.2)."""
    return sum(1 for v in values if _has_value(v) and float(v) > bound)


def count_below(values: Sequence[float | None], bound: float) -> int:
    """The sessions strictly below the bound; a tie or a missing value counts against (4.2)."""
    return sum(1 for v in values if _has_value(v) and float(v) < bound)


@dataclass(frozen=True)
class SignResult:
    """One exact sign test: x of n sessions on the hypothesis side, and p = P(X >= x)."""
    x: int
    n: int
    p: Fraction

    @property
    def p_float(self) -> float:
        return float(self.p)


def sign_greater(values: Sequence[float | None], bound: float) -> SignResult:
    """H1: the median is above the bound (B3 against 1.10; M1 and M3 against 1.00; 4.4)."""
    x = count_above(values, bound)
    return SignResult(x, len(values), sign_p(x, len(values)))


def sign_less(values: Sequence[float | None], bound: float) -> SignResult:
    """H1: the median is below the bound (M2 against 1.00; 4.4)."""
    x = count_below(values, bound)
    return SignResult(x, len(values), sign_p(x, len(values)))


@dataclass(frozen=True)
class SignTost:
    """The cost family's sign test (4.3): X_low counts the sessions above 0.98, X_high those below
    1.02; the cell's p is the larger of the two one-sided p-values."""
    low: SignResult
    high: SignResult

    @property
    def p(self) -> Fraction:
        return max(self.low.p, self.high.p)


def sign_tost(values: Sequence[float | None], lo: float = COST_LOW, hi: float = COST_HIGH) -> SignTost:
    return SignTost(sign_greater(values, lo), sign_less(values, hi))


# ---------------------------------------------------------------- the clustered BCa (4.2)


def clusters_of(labels: Sequence) -> list[np.ndarray]:
    """The member indices of each cluster, clusters in order of first appearance."""
    groups: dict = {}
    for i, lab in enumerate(labels):
        groups.setdefault(lab, []).append(i)
    return [np.array(m, dtype=np.intp) for m in groups.values()]


def draw_clusters(rng: np.random.Generator, k: int, b: int = B_RESAMPLES) -> np.ndarray:
    """B resamples of K clusters with replacement: rng.integers(0, K, size=(B, K)). The one place
    where a resample consumes the generator, so the order of the draws is the callers' (4.7)."""
    if k < 1:
        raise ValueError("no cluster to resample")
    return rng.integers(0, k, size=(b, k))


def clip_share(share: float, b: int) -> float:
    """4.2: the share of resamples beyond a bound is clipped to [1/(2B), 1 - 1/(2B)]."""
    return min(max(share, 1.0 / (2 * b)), 1.0 - 1.0 / (2 * b))


@dataclass
class Boot:
    """The bootstrap of one statistic: the estimate, the B resampled values, z0 and the
    acceleration, the number of clusters, and the jackknife values."""
    theta: float
    theta_b: np.ndarray
    z0: float
    a: float
    clusters: int
    jackknife: list[float] = field(default_factory=list)

    @property
    def b(self) -> int:
        return int(len(self.theta_b))


def _median_rows(values: np.ndarray, rows: np.ndarray) -> np.ndarray:
    return np.median(values[rows], axis=1)


def bca_fit(values: Sequence[float], draws: np.ndarray, clusters: Sequence | None = None) -> Boot:
    """The median of `values` (4.2: "Cell statistic: the median of the R session values"), its
    bootstrap over the drawn clusters, z0 and the jackknife acceleration.

    `draws` is a (B, K) matrix of cluster indices from draw_clusters. With clusters None every
    value is its own cluster (the session, 4.2), and a resample is values[draws[i]]: the
    computation of appendix_a_r_rule.bca_p, draw for draw. With cluster labels (the lab job,
    section 10), a resample joins the members of its drawn clusters.
    z0 = Phi^-1 of the share of resamples below the estimate, ties counted as half (4.2), clipped
    as the share of 4.2 is (a design choice, as appendix_a_r_rule.py does, so that z0 is finite
    when every resample lies on one side). The acceleration comes from the jackknife over
    clusters: d = mean(jk) - jk, a = sum(d^3) / (6 sum(d^2)^1.5), 0 when every jk is equal."""
    v = np.asarray(values, dtype=float)
    if v.ndim != 1 or len(v) == 0 or not np.all(np.isfinite(v)):
        raise ValueError("bca_fit needs a non-empty vector of finite values")
    theta = float(np.median(v))
    if clusters is None:
        members = None
        k = len(v)
    else:
        if len(clusters) != len(v):
            raise ValueError("one cluster label per value")
        members = clusters_of(clusters)
        k = len(members)
    draws = np.asarray(draws)
    if draws.ndim != 2 or draws.shape[1] != k:
        raise ValueError(f"draws must be (B, {k})")
    b = draws.shape[0]
    if members is None:
        theta_b = _median_rows(v, draws)
    else:
        theta_b = np.array([float(np.median(v[np.concatenate([members[c] for c in row])])) for row in draws])
    share = (np.sum(theta_b < theta) + 0.5 * np.sum(theta_b == theta)) / b
    z0 = ndtri(clip_share(float(share), b))
    if members is None:
        jk = np.array([float(np.median(np.delete(v, i))) for i in range(k)]) if k > 1 else np.array([theta])
    else:
        jk_list = []
        for c in range(k):
            keep = np.setdiff1d(np.arange(len(v)), members[c])
            jk_list.append(float(np.median(v[keep])) if len(keep) else theta)
        jk = np.array(jk_list)
    d = jk.mean() - jk
    den = float(np.sum(d ** 2))
    a = float(np.sum(d ** 3) / (6 * den ** 1.5)) if den > 0 else 0.0
    return Boot(theta, theta_b, z0, a, k, [float(x) for x in jk])


@dataclass(frozen=True)
class BcaP:
    """A one-sided BCa p-value; `degenerate` when the BCa map does not reach the bound (its
    denominator 1 + a(w - z0) is at or below 0), which a median at R = 11 to 32 cannot produce
    (|a| <= 1/(6 sqrt(k(k + 1)(2k + 1))), 4.2) but a clustering by a few lab jobs can. A
    degenerate p is reported as such and taken as 1, so it never passes (a design choice)."""
    p: float
    share: float
    degenerate: bool = False


def p_lower(boot: Boot, bound: float) -> BcaP:
    """H1: the median lies above the bound. p is the level alpha at which the lower end of the
    two-sided 1 - 2 alpha interval equals the bound (4.2, 4.4), from the share of resamples
    strictly below the bound (4.3, 5.2), clipped (4.2). As appendix_a_r_rule.bca_p's p_lo."""
    s = clip_share(float(np.sum(boot.theta_b < bound)) / boot.b, boot.b)
    w = ndtri(s)
    den = 1.0 + boot.a * (w - boot.z0)
    if den <= 0:
        return BcaP(1.0, s, True)
    u = (w - boot.z0) / den
    return BcaP(ndtr(u - boot.z0), s)


def p_upper(boot: Boot, bound: float) -> BcaP:
    """H1: the median lies below the bound; from the share strictly above it (4.3: "the upper test
    the share above 1.02"; 4.4, M2). As appendix_a_r_rule.bca_p's p_hi."""
    s = clip_share(float(np.sum(boot.theta_b > bound)) / boot.b, boot.b)
    w2 = ndtri(1.0 - s)
    den = 1.0 + boot.a * (w2 - boot.z0)
    if den <= 0:
        return BcaP(1.0, s, True)
    u2 = (w2 - boot.z0) / den
    return BcaP(ndtr(boot.z0 - u2), s)


@dataclass(frozen=True)
class Interval:
    """A two-sided BCa interval at `level`; None bounds where the BCa map is degenerate."""
    level: float
    low: float | None
    high: float | None


def _percentile(boot: Boot, z: float) -> float | None:
    t = boot.z0 + z
    den = 1.0 - boot.a * t
    if den <= 0:
        return None
    return ndtr(boot.z0 + t / den)


def bca_interval(boot: Boot, level: float) -> Interval:
    """The two-sided BCa interval at `level` (1 - 2 alpha): the order statistics of the resamples
    at the BCa-adjusted percentiles. The quantile is the inverse of the resamples' empirical
    distribution (NumPy's "inverted_cdf"), a design choice: with it the interval and the p-values
    above, which count resamples, agree. A one-sided BCa p is at most alpha exactly when the bound
    lies outside the 1 - 2 alpha interval on that side (4.3: the BCa form "passes at 0.025 exactly
    when the two-sided 95% interval lies inside [0.98, 1.02]"), except where a share is clipped
    or equals the adjusted percentile, which continuous data reach with probability 0."""
    if not 0 < level < 1:
        raise ValueError("level must lie in (0, 1)")
    alpha = (1.0 - level) / 2.0
    out = []
    for z in (ndtri(alpha), ndtri(1.0 - alpha)):
        q = _percentile(boot, z)
        out.append(None if q is None else float(np.quantile(boot.theta_b, q, method="inverted_cdf")))
    return Interval(level, out[0], out[1])


def bca_tost(boot: Boot, lo: float = COST_LOW, hi: float = COST_HIGH) -> tuple[BcaP, BcaP, float]:
    """The cost family's BCa form (4.3): the lower test uses the share below 0.98, the upper test
    the share above 1.02; the cell's p is the larger of the two."""
    pl = p_lower(boot, lo)
    ph = p_upper(boot, hi)
    return pl, ph, max(pl.p, ph.p)


# ---------------------------------------------------------------- the cost cell's decision (4.3, 4.6)


@dataclass(frozen=True)
class TostResult:
    """Both computations of 4.3 on one set of session values. `boot` is None when the sign test
    alone was asked for (the simulation of 4.6 needs the BCa only where the sign test passes)."""
    sign: SignTost
    boot: Boot | None
    p_boot_low: BcaP | None
    p_boot_high: BcaP | None

    @property
    def p_sign(self) -> float:
        return float(self.sign.p)

    @property
    def p_boot(self) -> float | None:
        if self.p_boot_low is None or self.p_boot_high is None:
            return None
        return max(self.p_boot_low.p, self.p_boot_high.p)


def cost_tost(values: Sequence[float], draws: np.ndarray | None) -> TostResult:
    """The confirmatory cost-cell computation of 4.3 on R session ratios: the sign test, and the
    clustered BCa from `draws` (B, R) when given. The simulation of 4.6 calls this same function
    ("each run is analysed by the confirmatory code itself")."""
    st = sign_tost(values)
    if draws is None:
        return TostResult(st, None, None, None)
    boot = bca_fit(values, draws)
    pl, ph, _ = bca_tost(boot)
    return TostResult(st, boot, pl, ph)


def cost_run_passes(values: Sequence[float], draws_for: Callable[[], np.ndarray], threshold: float) -> bool:
    """4.6 step 2: "A run passes if both p-values are at most alpha/36". The BCa is computed only
    when the sign test passes; its resamples come from `draws_for()`, a stream of their own
    (4.6 step 3), so skipping it changes no other draw."""
    st = cost_tost(values, None)
    if st.p_sign > threshold:
        return False
    full = cost_tost(values, draws_for())
    return full.p_boot is not None and full.p_boot <= threshold


# ---------------------------------------------------------------- Holm (4.2)


def holm_adjust(pvals: Sequence[float]) -> list[float]:
    """Holm's adjusted p-values (Holm 1979), in the order given: sorted ascending, the i-th
    smallest times (m - i + 1), made monotone, capped at 1."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: (pvals[i], i))
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * float(pvals[i])))
        adj[i] = running
    return adj


def holm_pass(pvals: Sequence[float], alpha: float = ALPHA) -> list[bool]:
    """Holm's step-down at family-wise alpha: a hypothesis is rejected when its adjusted p is at
    most alpha (4.2: "Holm's step-down per family at family-wise alpha = 0.025, one-sided")."""
    return [a <= alpha for a in holm_adjust(pvals)]


def holm_levels(boot_pvals: Sequence[float], alpha: float = ALPHA) -> list[tuple[int, float]]:
    """4.3: alpha_j = 0.025 / (m - j + 1), j the cell's rank among the family's BCa p-values, ties
    in the family's order (the order given). Returns (j, alpha_j) per cell, in the order given;
    the cell shows the two-sided interval at level 1 - 2 alpha_j."""
    m = len(boot_pvals)
    order = sorted(range(m), key=lambda i: (boot_pvals[i], i))
    out: list[tuple[int, float]] = [(0, 0.0)] * m
    for rank, i in enumerate(order):
        j = rank + 1
        out[i] = (j, alpha / (m - j + 1))
    return out


@dataclass(frozen=True)
class Dual:
    """The decision of one cell under the dual rule (4.2): Holm per computation; the cell passes
    only if it passes under both; if they disagree, both are reported and it does not pass."""
    p_boot_holm: float
    p_sign_holm: float
    pass_boot: bool
    pass_sign: bool

    @property
    def passes(self) -> bool:
        return self.pass_boot and self.pass_sign

    @property
    def disagree(self) -> bool:
        return self.pass_boot != self.pass_sign


def dual_rule(p_boot: Sequence[float | None], p_sign: Sequence[float | None], alpha: float = ALPHA) -> list[Dual]:
    """Holm's step-down, once for each computation, over the whole family; a cell that cannot be
    tested (p None) enters with p = 1 (4.2)."""
    pb = [1.0 if p is None else float(p) for p in p_boot]
    ps = [1.0 if p is None else float(p) for p in p_sign]
    ab, as_ = holm_adjust(pb), holm_adjust(ps)
    return [Dual(x, y, x <= alpha, y <= alpha) for x, y in zip(ab, as_)]


# ---------------------------------------------------------------- the R_C rule's helpers (4.6)


def chi2_cdf(x: float, k: int) -> float:
    """The chi-square distribution function by the series of the lower incomplete gamma function.
    Copied unchanged from analysis/appendix_a_r_rule.py (same author)."""
    a, xx = k / 2.0, x / 2.0
    term = 1.0 / a
    s = term
    n = 0
    while term > 1e-15 * s:
        n += 1
        term *= xx / (a + n)
        s += term
    return exp(-xx + a * log(xx) - lgamma(a)) * s


def chi2_ppf(q: float, k: int) -> float:
    """Its quantile by bisection. Copied unchanged from analysis/appendix_a_r_rule.py."""
    lo, hi = 0.0, 10.0 * k + 100
    for _ in range(200):
        mid = (lo + hi) / 2
        if chi2_cdf(mid, k) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def silverman_factor(e: np.ndarray, s: float) -> float:
    """4.6 step 2: b = 0.9 x min(1, IQR(e)/(1.34 s)) x P^(-1/5), Silverman's rule of thumb divided
    by s. Computed as appendix_a_r_rule.rule_power does, h / s with h = 0.9 min(s, IQR/1.34)
    P^-0.2, the IQR from NumPy's default percentiles (linear interpolation, a design choice the
    frozen text leaves open)."""
    p = len(e)
    q75, q25 = np.percentile(e, [75, 25])
    h = 0.9 * min(s, (q75 - q25) / 1.34) * p ** (-0.2)
    return float(h / s)
