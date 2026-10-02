"""Synthetic check of the R rule of the cost family: design/proposal.md, Appendix A (ST13), the
rule of hypotheses.md, section 4.6. A computation under a stated model, not a lab result.

    python analysis/appendix_a_r_rule.py

Model: the log session ratios of a pilot cell are iid normal with mean 0 (A/A truth) and standard
deviation sigma; P = 16 sessions. The rule: centre at the median; the smoothed bootstrap with
Silverman's bandwidth, scaled to the one-sided upper confidence bound s_U of the pilot's standard
deviation (80%, and 90% for comparison); both computations at the margin [0.98, 1.02] (the BCa
with B = 10,000 resamples and the exact sign test, ties against), alpha/36; N_SIM = 1,000 runs per
candidate R in {11, 15, 18, 22, 25, 28, 31}; target power 0.80. "True power" (oracle) is the pass
rate of 1,000 fresh normal samples of size R at the true sigma, analysed the same way. Eight
pilots per sigma, sigma in {0.010, 0.0125, 0.015}; master seed 43.

The script was written during the design as two scratch files, rrule.py (the analysis of one run)
and rrule2.py (this check), and is committed here as one file with the numerical code unchanged,
so the random streams are drawn in the same order. Run with Python 3.14.5 and numpy 2.5.0 on
2026-10-02, it prints the output that design/status.md records, which reproduces Appendix A. This
is not the confirmatory analysis code of section 4.6 (ANALYSIS_COMMIT): that code seeds its
streams per cell, run and candidate from SEED_SIM, as section 4.6 step 3 states.
"""
import sys
from math import comb, exp, lgamma, log, sqrt
from statistics import NormalDist
import numpy as np
from concurrent.futures import ProcessPoolExecutor

ND = NormalDist()
LO, HI = 0.98, 1.02
ALPHA_STAR = 0.025 / 36
B = 10_000
N_SIM = 1_000
P = 16
CANDIDATES = [11, 15, 18, 22, 25, 28, 31]


def sign_p(R, x):
    return sum(comb(R, j) for j in range(x, R + 1)) / 2 ** R


def bca_p(ratios, rng):
    R = len(ratios)
    theta = np.median(ratios)
    idx = rng.integers(0, R, size=(B, R))
    boot = np.median(ratios[idx], axis=1)
    lo_clip, hi_clip = 1 / (2 * B), 1 - 1 / (2 * B)
    share = (np.sum(boot < theta) + 0.5 * np.sum(boot == theta)) / B
    z0 = ND.inv_cdf(min(max(share, lo_clip), hi_clip))
    jk = np.array([np.median(np.delete(ratios, i)) for i in range(R)])
    d = jk.mean() - jk
    den = np.sum(d ** 2)
    a = float(np.sum(d ** 3) / (6 * den ** 1.5)) if den > 0 else 0.0
    s_lo = min(max(np.sum(boot < LO) / B, lo_clip), hi_clip)
    w = ND.inv_cdf(s_lo)
    u = (w - z0) / (1 + a * (w - z0))
    p_lo = ND.cdf(u - z0)
    s_hi = min(max(np.sum(boot > HI) / B, lo_clip), hi_clip)
    w2 = ND.inv_cdf(1 - s_hi)
    u2 = (w2 - z0) / (1 + a * (w2 - z0))
    p_hi = ND.cdf(z0 - u2)
    return max(p_lo, p_hi)


def passes(ratios, rng):
    R = len(ratios)
    ps = max(sign_p(R, int(np.sum(ratios > LO))), sign_p(R, int(np.sum(ratios < HI))))
    if ps > ALPHA_STAR:
        return False
    return bca_p(ratios, rng) <= ALPHA_STAR


def chi2_cdf(x, k):
    a, xx = k / 2.0, x / 2.0
    term = 1.0 / a
    s = term
    n = 0
    while term > 1e-15 * s:
        n += 1
        term *= xx / (a + n)
        s += term
    return exp(-xx + a * log(xx) - lgamma(a)) * s


def chi2_ppf(q, k):
    lo, hi = 0.0, 10.0 * k + 100
    for _ in range(200):
        mid = (lo + hi) / 2
        if chi2_cdf(mid, k) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def rule_power(args):
    pilot, conf, R, seed = args
    rng = np.random.default_rng(seed)
    e = pilot - np.median(pilot)
    s = np.std(e, ddof=1)
    q75, q25 = np.percentile(e, [75, 25])
    h = 0.9 * min(s, (q75 - q25) / 1.34) * P ** (-0.2)
    b = h / s
    s_u = s * sqrt((P - 1) / chi2_ppf(1 - conf, P - 1))
    z = e / s
    ok = 0
    for _ in range(N_SIM):
        y = s_u * (rng.choice(z, size=R, replace=True) + rng.normal(0.0, b, size=R)) / sqrt(1 + b * b)
        ok += passes(np.exp(y), rng)
    return ok / N_SIM


def oracle_power(args):
    sigma, R, seed = args
    rng = np.random.default_rng(seed)
    return sum(passes(np.exp(rng.normal(0.0, sigma, size=R)), rng) for _ in range(N_SIM)) / N_SIM


if __name__ == "__main__":
    print("chi2 ppf 0.20, 0.10 at 15 df:", chi2_ppf(0.20, 15), chi2_ppf(0.10, 15))
    print("factors 80%, 90%:", sqrt(15 / chi2_ppf(0.20, 15)), sqrt(15 / chi2_ppf(0.10, 15)))
    sigmas = [0.010, 0.0125, 0.015]
    confs = [0.80, 0.90]
    npilot = 8
    master = np.random.default_rng(43)
    pilots = {s: [master.normal(0.0, s, size=P) for _ in range(npilot)] for s in sigmas}
    with ProcessPoolExecutor(max_workers=11) as ex:
        orc = {}
        jobs = [(s, R, int(master.integers(1 << 31))) for s in sigmas for R in CANDIDATES]
        for (s, R, _), p in zip(jobs, ex.map(oracle_power, jobs)):
            orc[(s, R)] = p
        rjobs = [(pilots[s][i], c, R, int(master.integers(1 << 31)))
                 for s in sigmas for i in range(npilot) for c in confs for R in CANDIDATES]
        rp = list(ex.map(rule_power, rjobs))
    k = 0
    for s in sigmas:
        print(f"sigma={s} oracle:", " ".join(f"R{R}={orc[(s, R)]:.3f}" for R in CANDIDATES))
        for i in range(npilot):
            sd = np.std(pilots[s][i] - np.median(pilots[s][i]), ddof=1)
            line = f"  pilot {i} sd={sd:.4f}"
            for c in confs:
                pw = rp[k:k + len(CANDIDATES)]
                k += len(CANDIDATES)
                chosen = next((R for R, p in zip(CANDIDATES, pw) if p >= 0.80), None)
                op = orc[(s, chosen)] if chosen else float('nan')
                line += f" | conf {c:.2f}: R={chosen} true power={op:.3f}"
            print(line)
    sys.stdout.flush()
