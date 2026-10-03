#!/usr/bin/env python3
"""Tests of analysis/stats.py against known values.

    python -m pytest analysis/test_stats.py      (or: python analysis/test_stats.py)

The oracles are values stated in the frozen text or computed independently here, never values
the code under test printed:
1. The exact sign test: the grid of hypotheses.md 4.5 (R_C = 11 to 31, the count allowed beyond
   each bound at alpha/36 and the p at that count and at one more), the allowed count at every R
   from 11 to 32 (4.6 step 4: it steps only at 11, 15, 18, 22, 25, 28 and 31), R = 32
   (design/proposal.md 5.6), and B3 and M at R = 16 (4.5), against an independent tail sum.
2. Holm's step-down on the textbook example (Holm 1979, as Wikipedia's "Holm-Bonferroni method"
   gives it) and on 4.5's statements for B3 (m = 18) and M (m = 20).
3. The BCa: draw for draw equal to appendix_a_r_rule.bca_p (Appendix A's code, which section 4.6
   says the simulation runs "as it is"); equal to an inline textbook BCa (Efron and Tibshirani
   1993, ch. 14) on the same resamples; and, where SciPy is installed, equal to
   scipy.stats.bootstrap(method="BCa") on unclustered data: the same bootstrap distribution, the
   same adjusted percentiles, and bounds within one order statistic (SciPy interpolates).
4. 4.3's statement that the BCa form passes at alpha exactly when the 1 - 2 alpha interval lies
   inside [0.98, 1.02], over many random cells.
5. The chi-square quantile and the factor s_U / s of 4.6 (q = 10.307, s_U = 1.2064 s).
"""

from __future__ import annotations

import importlib.util
import sys
from fractions import Fraction
from math import comb
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import stats as S  # noqa: E402

ALPHA36 = S.ALPHA / 36


def appendix():
    spec = importlib.util.spec_from_file_location("appendix_a_r_rule", HERE / "appendix_a_r_rule.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tail_by_complement(x: int, n: int) -> Fraction:
    """P(X >= x) as 1 - P(X <= x - 1): an independent sum."""
    return 1 - Fraction(sum(comb(n, k) for k in range(0, max(x, 0))), 2 ** n)


# ---------------------------------------------------------------- 1. the sign test


# hypotheses.md 4.5: R_C, allowed beyond each bound, p at that count, p at one more (rounded).
GRID = [
    (11, 0, Fraction(1, 2048), "5.86e-03"),
    (15, 1, Fraction(1, 2048), "3.69e-03"),
    (18, 2, Fraction(43, 65536), "3.77e-03"),
    (22, 3, Fraction(897, 2097152), "2.17e-03"),
    (25, 4, Fraction(3819, 8388608), "2.04e-03"),
    (28, 5, Fraction(61219, 134217728), "1.86e-03"),
    (31, 6, Fraction(942649, 2147483648), "1.66e-03"),
]


@pytest.mark.parametrize("r,allowed,p_at,p_more", GRID)
def test_sign_grid_of_4_5(r, allowed, p_at, p_more):
    assert S.sign_p(r - allowed, r) == p_at
    assert S.sign_p(r - allowed, r) <= Fraction(1, 40) / 36
    assert f"{float(S.sign_p(r - allowed - 1, r)):.2e}" == p_more
    assert S.sign_p(r - allowed - 1, r) > Fraction(1, 40) / 36
    # the same through the test: `allowed` sessions beyond the lower bound
    vals = [1.0] * (r - allowed) + [0.97] * allowed
    st = S.sign_tost(vals)
    assert st.low.x == r - allowed and st.high.x == r
    assert st.p == p_at


def test_proposal_5_6_fractions_and_r32():
    # design/proposal.md 5.6 writes the same p-values with other denominators
    assert S.sign_p(14, 15) == Fraction(16, 32768)
    assert S.sign_p(16, 18) == Fraction(172, 262144)
    assert S.sign_p(19, 22) == Fraction(1794, 4194304)
    assert S.sign_p(21, 25) == Fraction(15276, 33554432)
    assert S.sign_p(23, 28) == Fraction(122438, 268435456)
    # R = 32: still 6 allowed, p = 1,149,017 / 2^32; 7 out gives 1.05e-3
    assert S.sign_p(26, 32) == Fraction(1149017, 2 ** 32)
    assert f"{float(S.sign_p(26, 32)):.2e}" == "2.68e-04"
    assert f"{float(S.sign_p(25, 32)):.2e}" == "1.05e-03"


def test_allowed_count_steps_only_at_the_candidates():
    """4.6 step 4: between 11 and 32 the allowed count rises only at 11, 15, 18, 22, 25, 28, 31."""
    want = {}
    for r in range(11, 33):
        want[r] = 0 if r < 15 else 1 if r < 18 else 2 if r < 22 else 3 if r < 25 else 4 if r < 28 else 5 if r < 31 else 6
    for r in range(11, 33):
        allowed = max(k for k in range(r + 1) if S.sign_p(r - k, r) <= Fraction(1, 40) / 36)
        assert allowed == want[r], r
    steps = [r for r in range(12, 33) if want[r] != want[r - 1]]
    assert [11] + steps == [11, 15, 18, 22, 25, 28, 31]


def test_tails_against_an_independent_sum():
    for n in range(0, 33):
        for x in range(-1, n + 2):
            assert S.sign_p(x, n) == tail_by_complement(x, n), (x, n)


def test_r16_values_of_4_5():
    assert S.sign_p(16, 16) == Fraction(1, 65536)
    assert f"{float(S.sign_p(16, 16)):.2e}" == "1.53e-05"
    assert S.sign_p(15, 16) == Fraction(17, 65536)
    assert S.sign_p(14, 16) == Fraction(137, 65536)
    assert S.sign_p(13, 16) == Fraction(697, 65536)
    # B3: X counts the sessions with Q strictly above 1.10 (5.2)
    q = [1.2] * 15 + [1.10]
    r = S.sign_greater(q, S.B3_BOUND)
    assert r.x == 15 and r.p == Fraction(17, 65536)
    # M2: the sessions below 1.00 (4.4)
    r = S.sign_less([0.9] * 14 + [1.0, 1.1], S.M_BOUND)
    assert r.x == 14 and r.p == Fraction(137, 65536)


def test_ties_and_missing_values_count_against():
    st = S.sign_tost([0.98] + [1.0] * 14)
    assert st.low.x == 14 and st.high.x == 15
    st = S.sign_tost([1.02] + [1.0] * 14)
    assert st.low.x == 15 and st.high.x == 14
    assert S.sign_greater([None, float("nan"), 2.0], 1.0).x == 1
    assert S.sign_less([None, float("nan"), 0.5], 1.0).x == 1


def test_tost_one_out_on_each_side_still_passes_at_r15():
    """design/proposal.md 5.6: one session beyond the lower bound and another beyond the upper
    leave each one-sided test with one session out; the larger p decides."""
    vals = [0.97, 1.03] + [1.0] * 13
    st = S.sign_tost(vals)
    assert st.low.x == 14 and st.high.x == 14
    assert st.p == Fraction(1, 2048) and st.p <= Fraction(1, 40) / 36


# ---------------------------------------------------------------- 2. Holm


def test_holm_textbook_example():
    """Holm (1979), as Wikipedia's "Holm-Bonferroni method" states it: p = 0.01, 0.04, 0.03,
    0.005 at alpha = 0.05; H4 (0.005 < 0.05/4) and H1 (0.01 < 0.05/3) are rejected, then 0.03 >
    0.05/2 stops: H2 and H3 are not."""
    p = [0.01, 0.04, 0.03, 0.005]
    assert S.holm_pass(p, 0.05) == [True, False, False, True]
    adj = S.holm_adjust(p)
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02], abs=1e-15)


def test_holm_statements_of_4_5():
    p0 = float(Fraction(1, 65536))
    p1 = float(Fraction(17, 65536))
    p2 = float(Fraction(137, 65536))
    p3 = float(Fraction(697, 65536))
    for m in (18, 20):
        assert all(S.holm_pass([p1] * m))
        for k in range(1, m + 1):
            assert all(S.holm_pass([p0] * (m - k) + [p2] * k)) is (k <= 11), (m, k)
            assert all(S.holm_pass([p0] * (m - k) + [p3] * k)) is (k <= 2), (m, k)
    assert f"{S.ALPHA / 18:.2e}" == "1.39e-03" and f"{S.ALPHA / 20:.2e}" == "1.25e-03"
    assert f"{S.ALPHA / 36:.2e}" == "6.94e-04"


def test_holm_levels_rank_ties_in_family_order():
    lv = S.holm_levels([0.01, 0.001, 0.01, 0.5])
    assert [j for j, _ in lv] == [2, 1, 3, 4]
    assert [a for _, a in lv] == pytest.approx([0.025 / 3, 0.025 / 4, 0.025 / 2, 0.025 / 1])


def test_dual_rule_untestable_and_disagreement():
    d = S.dual_rule([1e-6, 1e-6, None], [1e-6, 0.5, 1e-6])
    assert d[0].passes and not d[0].disagree
    assert not d[1].passes and d[1].disagree and d[1].pass_boot and not d[1].pass_sign
    assert not d[2].passes and d[2].p_boot_holm == 1.0


# ---------------------------------------------------------------- 3. the BCa


def lognormal_cell(seed: int, r: int, sigma: float, shift: float = 0.0) -> np.ndarray:
    return np.exp(np.random.default_rng(seed).normal(shift, sigma, size=r))


@pytest.mark.parametrize("r", [11, 15, 16, 18, 22, 25, 28, 31])
def test_bca_equals_appendix_a_draw_for_draw(r):
    app = appendix()
    for seed in range(6):
        vals = lognormal_cell(100 * r + seed, r, 0.004 + 0.002 * seed)
        want = app.bca_p(vals, np.random.default_rng(seed))
        boot = S.bca_fit(vals, S.draw_clusters(np.random.default_rng(seed), r))
        _, _, got = S.bca_tost(boot)
        assert got == want, (r, seed)
        # and the run's verdict of 4.6 step 2
        app_pass = app.passes(vals, np.random.default_rng(seed))
        got_pass = S.cost_run_passes(vals, lambda: S.draw_clusters(np.random.default_rng(seed), r), ALPHA36)
        assert got_pass == app_pass


def textbook_bca(vals: np.ndarray, idx: np.ndarray, level: float):
    """Efron and Tibshirani (1993), An Introduction to the Bootstrap, eq. 14.10 to 14.15, inline:
    z0 from the share below the estimate (ties half), a from the jackknife, the adjusted
    percentiles, and the empirical quantiles of the same resamples."""
    from statistics import NormalDist
    nd = NormalDist()
    theta = np.median(vals)
    tb = np.median(vals[idx], axis=1)
    b = len(tb)
    share = (np.sum(tb < theta) + 0.5 * np.sum(tb == theta)) / b
    z0 = nd.inv_cdf(share)
    jk = np.array([np.median(np.delete(vals, i)) for i in range(len(vals))])
    u = jk.mean() - jk
    a = np.sum(u ** 3) / (6 * np.sum(u ** 2) ** 1.5)
    alpha = (1 - level) / 2
    out = []
    for z in (nd.inv_cdf(alpha), nd.inv_cdf(1 - alpha)):
        q = nd.cdf(z0 + (z0 + z) / (1 - a * (z0 + z)))
        srt = np.sort(tb)
        out.append(srt[int(np.ceil(q * b)) - 1])
    return z0, a, out


def test_bca_equals_textbook_on_the_same_resamples():
    for seed in range(10):
        r = 16 if seed % 2 else 15
        vals = lognormal_cell(seed, r, 0.01, 0.003)
        idx = S.draw_clusters(np.random.default_rng(seed + 50), r)
        boot = S.bca_fit(vals, idx)
        z0, a, (lo, hi) = textbook_bca(vals, idx, 0.95)
        assert boot.z0 == pytest.approx(z0, abs=1e-12) and boot.a == pytest.approx(a, abs=1e-15)
        iv = S.bca_interval(boot, 0.95)
        assert iv.low == lo and iv.high == hi
        assert iv.low <= boot.theta <= iv.high


def test_bca_against_scipy_where_installed():
    scipy_stats = pytest.importorskip("scipy.stats")
    for seed in range(6):
        r = (11, 16, 31)[seed % 3]
        vals = lognormal_cell(700 + seed, r, 0.012)
        res = scipy_stats.bootstrap((vals,), np.median, n_resamples=S.B_RESAMPLES, vectorized=True,
                                    method="BCa", confidence_level=0.95, rng=np.random.default_rng(seed))
        boot = S.bca_fit(vals, S.draw_clusters(np.random.default_rng(seed), r))
        assert np.array_equal(np.asarray(res.bootstrap_distribution), boot.theta_b)
        iv = S.bca_interval(boot, 0.95)
        srt = np.sort(boot.theta_b)
        for mine, theirs in ((iv.low, res.confidence_interval.low), (iv.high, res.confidence_interval.high)):
            k = np.searchsorted(srt, theirs)
            nearby = srt[max(k - 1, 0):k + 2]
            assert np.any(nearby == mine), (seed, mine, theirs)


def test_clusters_resampled_whole_and_singletons_equal_sessions():
    vals = lognormal_cell(3, 16, 0.01)
    idx = S.draw_clusters(np.random.default_rng(11), 16)
    plain = S.bca_fit(vals, idx)
    single = S.bca_fit(vals, idx, clusters=list(range(16)))
    assert np.array_equal(plain.theta_b, single.theta_b)
    assert plain.z0 == single.z0 and plain.a == pytest.approx(single.a, abs=1e-15)
    jobs = [k // 4 for k in range(16)]
    idx4 = S.draw_clusters(np.random.default_rng(12), 4)
    boot = S.bca_fit(vals, idx4, clusters=jobs)
    assert boot.clusters == 4 and len(boot.jackknife) == 4
    for row, tb in zip(idx4[:50], boot.theta_b[:50]):
        members = np.concatenate([np.arange(4 * c, 4 * c + 4) for c in row])
        assert tb == float(np.median(vals[members]))


def test_degenerate_bca_is_reported_and_never_passes():
    boot = S.Boot(theta=1.0, theta_b=np.linspace(0.9, 1.1, 1000), z0=0.0, a=2.0, clusters=3)
    p = S.p_lower(boot, 0.9)
    assert p.degenerate and p.p == 1.0
    iv = S.bca_interval(boot, 0.95)
    assert iv.high is None


def test_interval_ordered_and_p_monotone():
    vals = lognormal_cell(21, 16, 0.02, 0.01)
    boot = S.bca_fit(vals, S.draw_clusters(np.random.default_rng(1), 16))
    iv = S.bca_interval(boot, 0.95)
    assert iv.low <= boot.theta <= iv.high
    ps = [S.p_lower(boot, x).p for x in (0.95, 0.98, 1.0, 1.02)]
    assert ps == sorted(ps)
    ps = [S.p_upper(boot, x).p for x in (1.05, 1.03, 1.02, 1.0)]
    assert ps == sorted(ps)


def test_no_spread():
    vals = np.full(16, 1.0)
    boot = S.bca_fit(vals, S.draw_clusters(np.random.default_rng(1), 16))
    iv = S.bca_interval(boot, 0.95)
    assert iv.low == 1.0 == iv.high
    _, _, p = S.bca_tost(boot)
    assert p == pytest.approx(S.ndtr(S.ndtri(1 / (2 * S.B_RESAMPLES)) + 2 * abs(boot.z0)))


# ---------------------------------------------------------------- 4. the BCa form against the interval


@pytest.mark.parametrize("level_alpha", [S.ALPHA, S.ALPHA / 36, S.ALPHA / 7])
def test_bca_pass_iff_interval_inside_margin(level_alpha):
    """4.3: "the BCa form passes at 0.025 exactly when the two-sided 95% interval lies inside
    [0.98, 1.02]"; the same holds at Holm's levels, side by side. The one exception is the floor
    of the p: where no resample lies beyond a bound, the clipped share gives a p that can exceed a
    small alpha (|z0| above the limits of 4.2) while the interval lies inside; those sides are
    counted and skipped."""
    checked = floor = passed = 0
    rng = np.random.default_rng(2026)
    for case in range(300):
        r = int(rng.choice([11, 15, 16, 18, 22, 25, 28, 31]))
        vals = np.exp(rng.normal(rng.uniform(-0.01, 0.01), rng.uniform(0.003, 0.02), size=r))
        boot = S.bca_fit(vals, S.draw_clusters(np.random.default_rng(case), r))
        pl, ph, p = S.bca_tost(boot)
        iv = S.bca_interval(boot, 1 - 2 * level_alpha)
        sides = ((pl, np.sum(boot.theta_b < S.COST_LOW), iv.low >= S.COST_LOW),
                 (ph, np.sum(boot.theta_b > S.COST_HIGH), iv.high <= S.COST_HIGH))
        ok = []
        for bp, beyond, inside in sides:
            if beyond == 0 and bp.p > level_alpha:
                floor += 1
                ok = None
                break
            assert (bp.p <= level_alpha) == inside, (case, bp, iv)
            ok.append(inside)
        if ok is None:
            continue
        assert (p <= level_alpha) == all(ok)
        checked += 1
        passed += all(ok)
    assert checked >= 200 and passed >= 20 and checked - passed >= 20, (checked, passed, floor)


# ---------------------------------------------------------------- 5. the R_C rule's helpers


def test_chi_square_quantile_and_su_factor_of_4_6():
    q = S.chi2_ppf(0.20, 15)
    assert q == 10.306959006625288  # appendix_a_r_rule.py's output, design/status.md
    assert f"{q:.3f}" == "10.307"
    f = (15 / q) ** 0.5
    assert f == 1.2063695181246945
    assert f"{f:.4f}" == "1.2064"
    assert S.chi2_ppf(0.10, 15) == 8.546756241704546


def test_silverman_factor_as_appendix_a():
    app = appendix()
    for seed in range(5):
        pilot = np.random.default_rng(seed).normal(0, 0.01, size=16)
        e = pilot - np.median(pilot)
        s = np.std(e, ddof=1)
        q75, q25 = np.percentile(e, [75, 25])
        want = 0.9 * min(s, (q75 - q25) / 1.34) * app.P ** (-0.2) / s
        assert S.silverman_factor(e, s) == want


def main() -> int:
    return pytest.main([__file__, "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
