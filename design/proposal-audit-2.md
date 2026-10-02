# Second audit of the P3 design proposal

Audited: `design/proposal.md` at commit 785ec73 of `paper-one-port`, against the first audit
(`design/proposal-audit.md`), rules D1 to D9 (`CLAUDE.md`) and P2's frozen
`papers/typed-routing/hypotheses-round2.md`. Written 2026-10-02 by an adversarial reviewer,
before the freeze. Nothing here is a result.

Method:
- Section 5 was read in full and checked against P2's section 5.
- Every number in the sign-test table, the D9 table, the ST13 constants and section 9 was
  recomputed. The script ran in the auditor's scratch directory and is not committed. It used
  Python 3.14.5 and numpy 2.5.0, exact binomial sums in `fractions`, the chi-square quantile by
  bisection on the regularized incomplete gamma function, and `statistics.NormalDist` for Φ. Its
  logic is given beside each result.
- Kernel claims were read in the Linux v7.2 sources, the version the proposal and the first audit
  use (https://raw.githubusercontent.com/torvalds/linux/v7.2/).
- The author's decisions of 2026-10-02 were taken as given. They were only checked for whether
  the text applies them.

Counts: 0 BLOCKER, 3 MAJOR, 12 MINOR. Verdict: freeze after these small fixes (section 7).

## 1. Statistics (section 5)

### 1.1 The equivalence test

- **Two one-sided tests, with the cell's p the larger of the two: valid.** A cell's null is a
  union: the ratio is at most 0.98, or at least 1.02. Rejecting it needs both one-sided nulls
  rejected. So the larger of two level-α p-values is a level-α intersection-union test. Testing
  each side at 0.025, not 0.0125, is correct for this construction.
- **The sign test: exact.** At each one-sided null's boundary, the count of sessions strictly on
  the hypothesis side is binomial (R, 1/2) or smaller, and ties count against (ST7, ST12). Each
  side's p is valid whatever the shape of the session distribution.
- **The BCa: approximate, as in P2.** ST12 says a BCa pass at 0.025 is the same as the 95%
  interval lying inside [0.98, 1.02]. That is right. The lower test passes at 0.025 exactly when
  the lower bound of the 1 - 2(0.025) interval is above 0.98, and the upper test likewise.
- **The dual rule is coherent.** A cell passes only if both computations reject, so the rule's
  rejection region lies inside the sign test's. The per-cell error is therefore at most the sign
  test's, which is exact. The BCa can only remove passes. Family-wise error control rests on the
  sign test alone; the BCa adds the interval and some conservatism. This is the safe way round:
  the approximate computation cannot create a pass.
- **Holm on TOST p-values: valid.** Holm needs one valid p-value per null, and the larger of the
  two one-sided p-values is one. ST8 runs Holm once per computation and requires both. That keeps
  the family-wise error at or below Holm on the sign test alone, so at or below 0.025.
- **Caveats.** ST6's floor holds for even R only (N4). The interval shown should be at the level
  Holm used (N6). Reruns of invalid windows can hide a defect in one arm (N7).

### 1.2 The R_C sizing rule (ST13)

The rule is defined in its essentials: per cell; centred at the pilot median; a smoothed
bootstrap scaled to the one-sided 80% upper bound of σ; B = 10,000 inside the simulation; the
same analysis code as the real test; α/36; target 0.80. All four of the first audit's
objections to the old rule are gone: the two readings, B = 2,000, the order statistic, and the
margin taken from data.

Constants recomputed:
- q, the 0.20 quantile of the chi-square distribution with 15 degrees of freedom: 10.3070. Then
  s_U / s = sqrt(15/q) = 1.20637. Both as stated.
- Largest bandwidth factor at P = 16: 0.9 × 16^(-1/5) = 0.5169.
- Monte Carlo standard error at 0.80 over 1,000 runs: 0.01265. As stated.
- Variance of the scaled draws. A draw with replacement from the 16 values e_i/s has variance
  (P - 1)/P = 0.9375, not 1, because s uses divisor P - 1. After the kernel term and the scaling,
  the draws have variance between 0.9375 s_U² (b = 0) and 0.9507 s_U² (b = 0.5169). Their
  standard deviation is therefore about 3% below s_U. ST13's "about the variance s_U²" is true to
  that extent (N5).

**Free of one-port data:** yes. Both arms run in dedicated mode, and the WL2 rates come from the
same pilot.

**Reproducible from a seed:** not yet. `SEED_SIM` is named, but the text does not say how it is
consumed or which analysis commit runs the simulation (N5).

**Dropping "not resolved" cells: m changes correctly.**
- Holm runs over the resolved cells only, and m_C is fixed before any confirmatory session.
- The selection uses the A/A pilot, which holds no one-port data.
- A smaller m only raises Holm's thresholds, so no resolved cell loses power.
- D9 holds at any m_C ≤ 36, since 2^-11 < 0.025/36.

This is allowed without peeking only if two things hold. The resolved list must be committed
before any one-port timing. And the pilot must not be rerun after that point. The text says
neither yet (N1).

**Appendix A, checked independently.** True power needs both computations to pass, so it
cannot exceed the probability that the sign test alone passes. Under the appendix's model that
probability can be computed exactly: a multinomial over sessions below log 0.98, above log 1.02
and between. All 21 reported values lie within 1.5 Monte Carlo standard errors of it:

| σ | R = 11 | 15 | 18 | 22 | 25 | 28 | 31 |
|---|---|---|---|---|---|---|---|
| 0.0100, reported / sign test alone | 0.614 / 0.599 | 0.909 / 0.912 | 0.991 / 0.985 | 0.996 / 0.997 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| 0.0125 | 0.296 / 0.279 | 0.645 / 0.638 | 0.849 / 0.858 | 0.936 / 0.941 | 0.978 / 0.979 | 0.996 / 0.993 | 0.999 / 0.998 |
| 0.0150 | 0.109 / 0.109 | 0.353 / 0.339 | 0.583 / 0.593 | 0.732 / 0.742 | 0.857 / 0.859 | 0.927 / 0.925 | 0.966 / 0.961 |

Under the normal model, then, the sign test almost alone sets the pass rate. This supports
ST7's statement that it is the binding computation.

### 1.3 The sign-test steps

Check: for each R, the largest k such that P(X ≥ R - k) ≤ α/36 = 6.944e-4, with
X ~ Bin(R, 1/2). Exact fractions, reduced:

| R | Allowed beyond each bound | p at that count | p at one more |
|---|---|---|---|
| 10 | none | (0 out: 1/1024 = 9.766e-4) | |
| 11 | 0 | 1/2048 = 4.883e-4 | 3/512 = 5.859e-3 |
| 12 | 0 | 1/4096 = 2.441e-4 | 13/4096 = 3.174e-3 |
| 13 | 0 | 1/8192 = 1.221e-4 | 7/4096 = 1.709e-3 |
| 14 | 0 | 1/16384 = 6.104e-5 | 15/16384 = 9.155e-4 |
| 15 | 1 | 1/2048 = 4.883e-4 | 121/32768 = 3.693e-3 |
| 16 | 1 | 17/65536 = 2.594e-4 | 137/65536 = 2.090e-3 |
| 17 | 1 | 9/65536 = 1.373e-4 | 77/65536 = 1.175e-3 |
| 18 | 2 | 43/65536 = 6.561e-4 | 247/65536 = 3.769e-3 |
| 19 | 2 | 191/524288 = 3.643e-4 | 145/65536 = 2.213e-3 |
| 20 | 2 | 211/1048576 = 2.012e-4 | 1351/1048576 = 1.288e-3 |
| 21 | 2 | 29/262144 = 1.106e-4 | 781/1048576 = 7.448e-4 |
| 22 | 3 | 897/2097152 = 4.277e-4 | 9109/4194304 = 2.172e-3 |
| 23 | 3 | 1/4096 = 2.441e-4 | 10903/8388608 = 1.300e-3 |
| 24 | 3 | 2325/16777216 = 1.386e-4 | 12951/16777216 = 7.719e-4 |
| 25 | 4 | 3819/8388608 = 4.553e-4 | 34203/16777216 = 2.039e-3 |
| 26 | 4 | 8951/33554432 = 2.668e-4 | 41841/33554432 = 1.247e-3 |
| 27 | 4 | 10427/67108864 = 1.554e-4 | 6349/8388608 = 7.569e-4 |
| 28 | 5 | 61219/134217728 = 4.561e-4 | 249589/134217728 = 1.860e-3 |
| 29 | 5 | 36649/134217728 = 2.731e-4 | 38851/33554432 = 1.158e-3 |
| 30 | 5 | 174437/1073741824 = 1.625e-4 | 192053/268435456 = 7.155e-4 |
| 31 | 6 | 942649/2147483648 = 4.390e-4 | 6977/4194304 = 1.663e-3 |
| 32 | 6 | 1149017/4294967296 = 2.675e-4 | 4514873/4294967296 = 1.051e-3 |

- **The steps fall at 11, 15, 18, 22, 25, 28 and 31: confirmed.** Every p in 5.6's table
  reproduces. Some of its fractions are unreduced but equal: 172/262144 = 43/65536,
  1794/4194304 = 897/2097152, 15276/33554432 = 3819/8388608, 122438/268435456 = 61219/134217728,
  16/32768 = 1/2048. R = 32 allows 6, as 5.6 says.
- **Near misses.** At R = 21, 24, 27 and 30, one more session out gives 7.448e-4, 7.719e-4,
  7.569e-4 and 7.155e-4, just above 6.944e-4. So the grid belongs to m = 36: at α/30 the steps
  would fall at 21, 24, 27 and 30. Keeping R_C after cells are dropped is conservative and needs
  no change.

### 1.4 R_B = R_M = 16 (D9)

- **B3, m = 18:** α/18 = 1.389e-3. The D9 minimum is 10 (2^-10 = 9.766e-4 is below it;
  2^-9 = 1.953e-3 is not). R = 16 passes.
- **Mechanism, m = 20:** α/20 = 1.25e-3. The D9 minimum is 10. R = 16 passes.
- **5.6's counts at R = 16 reproduce:**
  - 1 out: 17/65536 = 2.594e-4, which clears α/m in both families;
  - 2 out: 137/65536 = 2.090e-3, which clears α/k for k ≤ 11;
  - 3 out: 697/65536 = 1.064e-2, which clears α/k for k ≤ 2.
- **Holm's first thresholds** in 5.6's table (6.94e-4, 1.39e-3, 1.25e-3) are correct.

### 1.5 B3

B3 is statistically valid: a paired difference, superiority at 0, both computations, and Holm
over 18 cells at R = 16. Its wording is honest:
- it speaks of whole-system footprints;
- it reports beside each pass both footprints, D, `K_BASE` and the ratio;
- it keeps the JVM and Go cells outside Holm, with the reason (RK9). That choice is right, since
  their footprint depends on the collector.

But yes, it lets trivially small differences count as passes. What a reviewer would say:
- "The null 'the median D is at most 0' compares a minimal server built for this metric (I32)
  with full proxies. It is not in doubt before the run. At R = 16 any difference with a
  consistent sign passes, a few bytes as well as a few kilobytes. Holm lends these passes a
  weight they do not carry; the information is all in the size."
- "The server is engineered for memory per pending connection, while the competitors keep their
  default per-connection buffer settings. Section 6 changes only limits and the timer for B3.
  That is not each competitor's documented best configuration for this metric (D2)."
- "T leaves out the kernel objects each system adds per connection, and those differ by design
  between an io_uring receive and an epoll registration" (N3).
- "The B3 feasibility windows show each system's footprint before any margin is chosen" (N2).

The wording survives the first objection only if no sentence of the paper calls a B3 pass
anything but "fewer bytes, by D, with this interval". N2 and N3 give the fixes.

## 2. The first audit's BLOCKER and MAJOR findings

| Finding | Severity | Status |
|---|---|---|
| F1 | BLOCKER | Fixed. ST13 is replaced: per cell; B = 10,000 in the simulation; a smoothed bootstrap scaled to an upper bound; the margin fixed by Alex (ST12, ST13). Residuals are text and definitions: N4, N5. |
| F2 | BLOCKER | Fixed on its five items. Limits are raised with sources (WL7 "Limits", CP1, CP2, CP5). Opening is paced, with an overflow rule. `K_BASE` comes from `ophold`. `f` is reported, not added. Collections are forced and the live heap reported. G1 is explicit. The settling rule and ℓ are defined. The fix itself raises N2, N3 and N8. |
| F3 | MAJOR | Fixed (ST7, ST13, 5.6). The table reproduces (section 1.3). |
| F4 | MAJOR | Partly fixed. Alex set the margin before any code existed, and the pilot runs once with logged seeds (ST12, I31 E1, ST13). Missing: the resolved list and m_C among what is committed before one-port timing; a cutoff for pilot reruns; a freeze order that agrees with the status paragraph (N1). |
| F5 | MAJOR | Fixed for M1, M2 and the cost wording (5.8, S2, A2). The same wording fix is missing for M3 and B3 (N10). |
| F6 | MAJOR | Fixed: fresh source blocks and `IP_BIND_ADDRESS_NO_PORT` (I30); TIME-WAIT and overflow counters (LB5, ST10); the pilot's port offset (ST13 step 1). |
| F7 | MAJOR | Partly fixed. S2, 5.3, 5.8 and Q17 scope the claim to single-protocol load, and the mixed cell is secondary (5.7). The title does not carry this scope, although the revision log says it does (N11). |
| F8 | MAJOR | Fixed: synchronous peeks; `SO_RCVLOWAT` set to the total and reset; IOCP switches to replay; `POLLRDHUP` through `IORING_OP_POLL_ADD`; each pinned by a test (I11, I29, RK4, RK5, Z2). |
| F9 | MAJOR | Partly fixed. In: logging off, Envoy's statistics matched, `multi_accept`, `splice-auto`, the TLS exchange, the relay buffer, overflows reported, and the open-loop departure stated. Section 6 contradicts the two-route table (N9). |
| F10 | MAJOR | Fixed (B3; the JVM and Go cells are descriptive). |
| F11 | MAJOR | Fixed (WL6, ST10, LB2). |
| F12 | MAJOR | Fixed in what it asked for (S6 a, b and h; HC7's G; I13's clock re-check). Residuals: no defined pilot sets G (N13), and the tie rule reaches less far than S6(b) says (N14). |
| F13 | MAJOR | Fixed, contingent on Alex approving the W procedure (Q6). |
| F14 | MAJOR | Fixed. Every row reproduces (section 3). Small gaps remain (N5, N13). |
| F15 | MAJOR | Fixed (Z1 to Z6). |

## 3. Time arithmetic

Everything was recomputed from the stated cell counts, window counts and window lengths: 6.63 s,
and 30.63 s for B3. Every row of 9.1, 9.2 and 9.3 reproduces to the second, and so do the
totals at the other candidates. There is no mismatch.

| R_C | L total | W total |
|---|---|---|
| 11 | 154,538.49 s = 42 h 55 min 38 s | 17,432.64 s = 4 h 50 min 33 s |
| 15 | 157,720.89 s = 43 h 48 min 41 s | 19,023.84 s = 5 h 17 min 4 s |
| 18 | 160,266.81 s = 44 h 31 min 7 s | 20,296.80 s = 5 h 38 min 17 s |
| 22 | 163,449.21 s = 45 h 24 min 9 s | 21,888.00 s = 6 h 4 min 48 s |
| 25 | 165,995.13 s = 46 h 6 min 35 s | 23,160.96 s = 6 h 26 min 1 s |
| 28 | 167,904.57 s = 46 h 38 min 25 s | 24,115.68 s = 6 h 41 min 56 s |
| 31 | 170,450.49 s = 47 h 20 min 50 s | 25,388.64 s = 7 h 3 min 9 s |

Parts at R_C = 11:
- On L: primary 81,780.00 s; pilot 10,826.91 s; secondary 25,039.50 s; reruns 26,685.12 s; hard
  cases 8,934 s; development 1,272.96 s.
- On W: 4,349.28 s; 5,091.84 s; 4,667.52 s; 2,333.76 s; 672 s; 318.24 s.

All match 9.3. The rows' compositions also match the body:
- the secondary cells split as 40 on L (6 + 2 + 4 + 2 + 2 + 10 + 4 + 10) and 11 on W
  (3 + 1 + 2 + 1 + 2 + 2), the 5.7 list by host;
- mechanism has 18 cells on L and 2 on W;
- ⌈R_C/4⌉ is 3 at 11 and 8 at 31;
- the hard cases come to 6 × 128 × 3 + 128 × 3 = 2,688 s on L and 6 × 32 × 3 + 32 × 3 = 672 s on
  W;
- the competitors' bound is 432 + 1,080 + 4,734 = 6,246 s.

Gaps, not arithmetic errors:
- the pilot that sets G and `GAP_SPLIT` is not in the table, and HC7's late run waits more than
  the 3 s its "at most" row counts (N13);
- reruns of invalid pilot sessions are not counted (N5).

## 4. Internal consistency

Consistent:
- **Hypothesis names.** C1 to C3, B1 to B3 and M1 to M3 are used the same way in sections 3, 5,
  9, 10 and 11 and in the revision log.
- **Cell counts.**
  - Cost: 4 protocols × 3 backends = 12 per hypothesis (8 on L, 4 on W), so m_C ≤ 36.
  - B3: (5 + 4) × 2 = 18 Holm cells, plus 4 × 2 × 2 = 16 descriptive cells, giving 34 in 9.2.
  - Mechanism: 6 + 4 + 10 = 20 cells, 18 on L and 2 on W.
- **m and Holm thresholds.** 5.6's table, RK12 and the revision log agree (m_B = 18, m_M = 20).
- **Questions.** Q1 to Q21 are in 11.1 (Q6 and Q21 in part); Q6 and Q22 are open in 11.2. Every
  "Applied in" pointer leads to text that applies the decision.
- **The author's decisions are applied.**
  - Q1, the cost family leads, then M3, B3 and cost per backend give way in that order: A2, 5.8.
  - Q2, [0.98, 1.02] for C1 to C3 on L and W, and the A/A pilot only sizes R_C, with candidates
    up to 31: ST12, ST13.
  - Q5, L downloads into `~/opt` and `pacman -S`, never `-Syu`: LB1, RK8.
  - Q6, W only when freed, with Strawberry Perl and NASM: LB3, I23.
  - Q7, no licence, and P1's loop copied with attribution: I2.

Inconsistent: N1 (the status paragraph against ST13), N9 (section 6 against M3), N11 (the title
against the revision log), N12 (WL2 against 5.7) and N13 ("the pilot" in I30 and HC7).

## 5. Rules

- **No private library of the author is named.** Every occurrence of "library", "private" and
  "thesis" in `proposal.md` was read. They concern OpenSSL, third-party libraries in general,
  Rust's standard library, and the privacy of the paper repositories. The only first-party code
  named is this paper's own programs (`oneport`, `opgen`, `opcase`, `ophold`) and the P1 and P2
  paper repositories, cited as design sources.
- **No em or en dashes.** A count of U+2013 and U+2014 gives 0 in `proposal.md` and in
  `proposal-audit.md`. This file was checked the same way before the commit.
- **Numbers.** Every number checked traces to a source, a placeholder with a rule, a pilot output
  or a labelled design choice, or is arithmetic that reproduces. The exceptions are listed in N15.

## 6. Findings

### N1. MAJOR. The freeze order leaves room to choose the confirmatory cost family after one-port timing

Location: the status paragraph (lines 6 to 7); I31 E1 (lines 448 to 454); ST13 step 1 (lines 804
to 810) and step 6 (lines 843 to 848); RK12.

Evidence:
- The status paragraph says section 5 becomes `hypotheses.md`, "frozen before any gated run".
  ST13 runs the A/A pilot "on the frozen code", a measured and therefore gated build. It also
  fixes m_C "at the freeze", which places the hypotheses freeze after the pilot. The two orders
  cannot both hold.
- E1 lets one-port against dedicated timing start once "the margin and R_C are committed". It
  does not name the resolved list or m_C.
- ST13 step 1 allows a pilot rerun with a revision-log entry, and sets no cutoff. A rerun after
  one-port timing has started redraws which cells are resolved, and so which cells enter Holm,
  with one-port data in view.
- Nothing says what happens if one-port development timing leads to a code change after the
  pilot. The pilot's code would then not be the measured code.

Fix:
- One revision-log entry, made from the simulation's output alone, commits R_C, the resolved
  list, m_C and the WL2 rates together. No one-port against dedicated timing comes before it.
- A pilot rerun is allowed only before that entry, and only when a named ST10 rule failed. After
  the entry, never.
- State the order: code freeze and records, A/A pilot, simulation, that entry, hypotheses freeze.
  Reword the status paragraph so that it does not exclude the pilot.
- State that a code change after the pilot means new records and a new pilot.

### N2. MAJOR. B3's bound of 0 bytes makes a pass uninformative, and Q22 can still be answered after the footprints are seen

Location: B3 (lines 892 to 914); Q22 (lines 1344 to 1346); 9.2, the B3 feasibility row (line
1203), and line 1243; the introduction of section 6 (lines 1036 to 1041); I32.

Evidence:
- Superiority at 0 bytes: any difference with a consistent sign passes at R = 16. Even one
  session on the wrong side still gives p = 2.594e-4, below α/18. The reviewer's view is in 1.5.
- The B3 feasibility windows run every system in the B3 layout (21 windows) before the freeze, to
  measure the window's start and teardown. They also sample U and Kq, so they show each system's
  footprint. Q22 has no deadline. A margin chosen after those windows is chosen with the data in
  view. That is the pattern F4 closed for the cost family.
- Section 6 changes only limits and the timer for B3, so every competitor keeps its default
  per-connection buffers. One example is nginx's `preread_buffer_size`, 16k in the proposal's
  sources. The server, meanwhile, is engineered for this metric (I32). Rule D2 asks for each
  competitor's documented best configuration.

Fix:
- Alex answers Q22 before the feasibility windows run. He sets either a margin in bytes per
  pending connection or a minimum for (T_comp + `K_BASE`) / (T_srv + `K_BASE`). Or he locks the
  default (no margin) now, and B3 states that a pass shows direction only, with every sentence
  about B3 in the paper quoting D and its interval.
- For each competitor, name the documented settings that size what a pending connection holds.
  Either configure them for many pending connections where the project documents how, with the
  source, or state that the defaults are kept and why.

### N3. MAJOR. B3's footprint T leaves out kernel objects that differ between the server's io_uring arm and every competitor

Location: WL7 (T = U + Kq, line 609; Ks and `K_BASE`, lines 606 to 623); B3 (lines 892 to 909);
I11 and I15 (replay on io_uring keeps one pending receive per connection).

Evidence:
- T = U + Kq. Ks, the growth of slab memory, is reported but is not part of T. WL7 itself reads
  Ks - `K_BASE` as "the kernel objects it adds beyond a bare held socket, such as its poll
  registrations".
- Those objects differ by design:
  - In replay mode on io_uring, every pending connection has an armed `IORING_OP_RECV` (I11,
    I15). Until it completes, each io_uring request is a `struct io_kiocb` from the slab cache
    "io_kiocb" (io_uring/io_uring.c line 3257 at v7.2).
  - Every competitor, and the server on epoll, registers the socket with epoll instead. That is
    an `epitem` from the cache "eventpoll_epi" (fs/eventpoll.c line 3015 at v7.2).
- So in the 9 io_uring cells of B3's 18 Holm cells, part of the per-connection cost that differs
  between the arms is outside the tested statistic. The sign of the omission is unknown without
  measuring it. And the wording "whole-system footprint" (B3, after the first audit's F10) does
  not hold for T as defined.

Fix, either:
- T = U + Kq + (Ks - `K_BASE`), with N8's fix so that Ks is clean; or
- keep T, rename it for what it measures (user memory plus receive queue), drop "whole-system"
  from B3, and report Ks - `K_BASE` beside every cell, with a sentence on the io_uring cells.

### N4. MINOR. ST6's floor and its |z0| limit hold for even R only

Location: ST6 (lines 737 to 741); 5.6 (line 986).

Evidence:
- P2's acceleration of 0 comes from an even number of pairs: the leave-one-out medians take two
  values, eight times each (`hypotheses-round2.md`, section 5). Four of the seven candidates (11,
  15, 25, 31) are odd.
- For odd R = 2k + 1, the leave-one-out medians take three values (k, k and 1 times), so the
  jackknife acceleration is not 0. Its largest magnitude is reached when one of the two gaps
  beside the median is 0: 1/(6 sqrt(k(k + 1)(2k + 1))). That is 0.0092 at R = 11, 0.0058 at 15,
  0.0027 at 25 and 0.0019 at 31. 4,000 normal samples per R reached these values and none
  exceeded them.
- With that acceleration on the unfavourable side:
  - the floor at z0 = 0 rises from 5.0e-5 to 8.6e-5 at R = 11;
  - the |z0| limit for passing α/36 falls from 0.347 to 0.289 at R = 11, 0.311 at 15, 0.330 at
    25 and 0.335 at 31.
- The simulation runs the real code, so the power figures are unaffected. Only the sentences are
  wrong.

Fix: say that the floor Φ(Φ⁻¹(1/(2B)) + 2|z0|) and the 0.347 limit hold for even R, and give
the odd-R values; or drop the number and refer to the simulation.

### N5. MINOR. ST13 cannot yet be reproduced from `SEED_SIM`, and "resolved" has two definitions

Location: ST13 steps 1, 2, 4 and 5 (lines 803 to 850); ST9 (lines 753 to 758); Appendix A (lines
1472 to 1479).

Evidence:
- **Two definitions of "resolved".** Step 4 calls a cell "not resolved" when Power_c(31) < 0.80.
  Step 4's first sentence and step 5 treat a cell as resolved when some candidate reaches 0.80.
  With a Monte Carlo error of 0.0126 at 0.80, a cell can reach 0.80 at 25 and miss it at 31. Step
  5's last sentence would then apply, but step 4 has already declared the cell not resolved.
- **Seed use unstated.** `SEED_SIM` is named, but not how it is consumed:
  - one generator, or one per cell;
  - the order of the cells;
  - whether a cell's 1,000 runs reuse their draws across candidates (common random numbers keep
    the power estimates monotone between candidates, up to the sign test's steps);
  - how the BCa resamples inside a run are drawn.

  The analysis commit that runs the simulation is not named either.
- **Variance of the scaled draws.** It is 0.9375 to 0.9507 of s_U², not s_U² (section 1.2).
- **Invalid pilot sessions.** The pilot needs P = 16 valid sessions per cell. No rerun rule for
  invalid pilot sessions is given, and section 9 counts none.
- **Order seeds.** ST9 names none for the secondary and descriptive cells.
- **Appendix A.** Its script is not committed.

Fix:
- Define "resolved" once. For example: a cell is resolved if Power_c(31) ≥ 0.80, and R_c is the
  smallest candidate with Power_c ≥ 0.80.
- Give the stream layout, for example one generator from `SEED_SIM` per cell, cells in the
  family's order, the same draws for every candidate. Name the analysis commit.
- Rescale the draws by sqrt(P/(P - 1)), or write "0.94 to 0.95 of s_U²".
- Apply ST4's rerun rule to the pilot, and count its reruns in section 9.
- Name the order seeds of the secondary and descriptive cells.
- Commit the Appendix A script under `analysis/`.

### N6. MINOR. The headline's power and the interval the paper shows are not stated

Location: 5.8 (lines 1019 to 1022); ST12 (lines 793 to 795); ST13 step 4.

Evidence:
- "No measurable cost" is claimed for a protocol, backend and host only where C1, C2 and C3 all
  pass. R_C gives each cell power 0.80; it does not give the claim 0.80. As a hypothetical, not a
  projection: three independent cells at 0.80 each would give the claim 0.80³ = 0.512.
- ST12 equates a BCa pass at 0.025 with a 95% interval inside the margin, but cells are decided
  at Holm's thresholds. A 95% interval inside [0.98, 1.02] on a cell that fails Holm will read as
  a contradiction.

Fix:
- Beside R_C, report the simulation's joint power for each protocol, backend and host. The cells
  are simulated independently, so it is the product of the cell powers.
- For each cost cell, show the interval at the level Holm used for it, beside the 95% interval.

### N7. MINOR. Rerunning invalid windows can hide a defect in one arm

Location: ST4 (lines 724 to 727); ST10 (lines 760 to 773).

Evidence: a window is invalid when its error share exceeds 0.1%, a connect fails, or a
connection is classified other than as its script's protocol. In a cost cell, any of these can
come from one arm only, for example a one-port misclassification. ST4 then discards the session
and runs it again, up to ⌈R/4⌉ times. A defect of the one-port arm thus becomes noise that the
rerun removes, and the cell can still pass.

Fix:
- Report invalid windows per arm and cell, beside each decision.
- Treat a misclassified connection in any measured window as a server defect, reported the way
  B1 and B2 failures are (5.8), not only as a reason to rerun.

### N8. MINOR. B3's slab figures carry earlier windows' TIME-WAIT sockets, and the settling rule breaks near zero

Location: WL7 (the closing phase, line 595; Ks, lines 606 to 608; `K_BASE`, lines 612 to 623;
the settling rule, lines 591 to 594).

Evidence:
- **TIME-WAIT carry-over.** `opcase` closes first, so the client ends enter TIME-WAIT.
  - TIME-WAIT sockets are slab objects (net/ipv4/inet_timewait_sock.c line 178 at v7.2), and
    they last 60 s (`TCP_TIMEWAIT_LEN`, cited in I30).
  - With B3 windows back to back at 30.63 s, the floor of section 9, one window's closing phase
    (t = 25 to 30 s) is freed 85 to 90 s after that window started. That is 23.7 to 28.7 s into
    the window after next, around its sample 2 (t = 25 s). Longer windows move it earlier, but
    still inside that window.
  - Loopback reuse of TIME-WAIT sockets (LB5) frees some of them during a later opening phase as
    well.
  - So Slab moves between a window's baseline and its samples for reasons outside the system
    under test. This biases Ks, `K_BASE` (also measured in back-to-back windows), each
    Ks - `K_BASE`, and the reported ratio. The settling rule checks U only.
- **Settling rule.** The rule is relative: the window is invalid if U changes by more than 2% of
  sample 2's U. The server is built to hold little per pending connection (I32). When U is near
  0, the tolerance falls below the resolution of `VmRSS`, which moves in whole pages. When U is 0
  or negative, the rule is undefined.

Fix:
- Either close B3 connections by reset (`SO_LINGER` with a zero timeout), so that no TIME-WAIT is
  left, or record the TIME-WAIT count at the baseline and at each sample and make the window
  invalid if it changed.
- If N3 puts Ks into T, add Ks to the settling check.
- Give the settling rule an absolute tolerance in bytes per pending connection, a named design
  choice, beside the 2%.

### N9. MINOR. M3's two-route table contradicts section 6

Location: M3, "Routes" (lines 936 to 939); the introduction of section 6 (lines 1038 to 1040);
CP2, CP4, CP5.

Evidence:
- M3 says every system holds the same two routes.
- Section 6 gives each system two configurations, "the one for the cases and M3, and the one for
  B3".
- The case configurations also route SSH and MQTT:
  - HAProxy's `req.payload(0,4)` and `mqtt_is_valid` (CP2);
  - caddy-l4's ssh and regexp matchers (CP4);
  - sslh's ssh probe and MQTT regex probe (CP5).
- Under section 6, M3 would run with those extra routes. That is the unequal route table the
  first audit's F9.5 asked to remove.

Fix: give each system three configurations: cases, M3 and B3. M3's holds exactly the two routes.
Say which route set B3's configuration starts from.

### N10. MINOR. A failed M3 or B3 cell is still called a "loss"

Location: 5.8 (lines 1025 and 1029); RK3 (lines 1258 to 1259).

Evidence: F5 fixed this for M1 and M2: a failed superiority cell shows only that a difference was
not shown. But 5.8 and RK3 still say "each loss is reported" and "report a loss" for M3 and B3.
A cell can fail with the server ahead in most sessions.

Fix: call a failed cell "not shown". Use "loss" only where the interval lies wholly on the
competitor's side.

### N11. MINOR. The title does not carry the single-protocol scope that the revision log claims for it

Location: the working title (line 10); revision log, F7 (line 1520).

Evidence: the F7 entry says the claim is scoped to single-protocol load "(S2, title)". The working
title scopes the claim to client-first TCP protocols and to cost, not to single-protocol load.
S2, 5.3 and 5.8 do carry the scope.

Fix: add the load scope to the working title, or correct the log entry.

### N12. MINOR. The SSH C3 secondary cells have no load rate

Location: WL2 (lines 538 to 541); 5.7 (lines 994 to 995).

Evidence: for a cost cell, λ is `RATE_FRAC` × the pilot median of the C1 pilot cell "with the
same protocol and backend". The A/A pilot runs C1 to C3 for HTTP/1.1, h2c, TLS and MQTT only.
Yet 5.7 runs C3 for SSH on three backends, and those cells have no λ.

Fix: give them a rule, for example the slower arm of their own C1 secondary sessions, as WL2 does
for the secondary M cells. Or drop SSH C3.

### N13. MINOR. The pilot that sets G and `GAP_SPLIT` is not defined or timed

Location: I30, `GAP_SPLIT` (lines 439 to 441); HC7 (line 676); 9.2 (lines 1215 and 1221 to
1222); line 1244.

Evidence:
- G is set "in the pilot above the 99th percentile of B2's timer lateness". `GAP_SPLIT` is set
  "in the pilot" on L and W.
- The pilot of ST13 runs cost cells only. Those fire no detection timer and split no signature.
- No other pilot is described or counted in section 9.
- HC7's late run waits T_fb + G, more than the 3 s that its "at most" row counts.

Fix:
- Describe a hard-case pilot: its cases, backends, modes and replicates, and the statistic it
  reads. Mark it as development data and add its time to section 9.
- Count HC7's late run as 3 s + G.

### N14. MINOR. The tie rule's peek cannot see bytes that a completed receive has already taken

Location: S6(b) (lines 78 to 83); I11's table, the io_uring and IOCP replay columns; I12; I13.

Evidence:
- S6(b) says the one-byte peek before a fallback dispatch settles "a receive that completed on
  IOCP but was not yet dequeued". That holds for the zero-byte `WSARecv`, which leaves the bytes
  queued in the socket.
- It fails where the completed receive carried a buffer:
  - replay on io_uring, the proposed default on every backend (I12), keeps an `IORING_OP_RECV`
    armed on each pending connection (I11);
  - IOCP's posted-buffer form, which rule E may choose, does the same.
- Such a receive has already moved the bytes into the user buffer. Its completion can wait in the
  ring or the port while the loop handles an expiry in the same pass. The peek then finds
  nothing, and the connection goes to the fallback with bytes that arrived before T_fb.
- HC7's guard band G keeps B1 from ever seeing this.

Fix:
- In every loop pass, handle all completions and readiness events before any expiry, and say so
  in I13.
- Before a fallback dispatch on a connection whose receive was posted with a buffer, check that
  receive's state (a non-waiting dequeue of the ring or port) instead of peeking.
- Reword S6(b) to claim only what these rules give.

### N15. MINOR. Numbers added by the revision without a label or a source

Location: WL7 (lines 580 to 594); `K_BASE` (line 615); ST13 step 2 (lines 815 to 816 and 829);
9.2 (line 1217).

Evidence:
- **WL7's phases.** The opening of at most 10 s, settling to 20 s, and samples at 20 s and 25 s
  carry no label. The 25 ms pace follows from 10 s and batches of 25. Only the 30 s total and the
  halving of ℓ are labelled design choices.
- **`K_BASE`.** Its 16 windows carry no label.
- **Silverman's rule of thumb.** It is named without a source line in "Sources added beyond the
  survey".
- **`N_SIM` = 1,000.** It is given with its standard error, but not called a design choice.
- **HAProxy's default wait.** 9.2 counts it as 0 s, and no source is given for that.

Fix: label each as a design choice with its reason, or give its source.

## 7. Verdict

Freeze after these small fixes.

These must land before the freeze:
- **N1:** one revision-log entry, plus the stated order of freeze, pilot, entry and timing.
- **N2:** Alex answers or locks Q22 before the B3 feasibility windows; the rule for wording B3;
  the competitors' buffer settings.
- **N3:** either Ks - `K_BASE` goes into T, or T is renamed and "whole-system" is dropped.

Each is a few sentences, and none needs a new experiment. But each changes what a reviewer reads
as pre-registered, and none can be changed after the freeze. If neither alternative of N3 is
taken, section 5.4 is not ready to freeze.

The MINOR findings, N4 to N15, are text and small design fixes for the same revision. N8 adds
one `opcase` option, and N13 adds one short pilot.

The core of section 5 is sound: the two one-sided tests, the dual rule, Holm on TOST p-values,
the R_C rule, the sign-test grid, and D9 for all three families. It needs no third audit once
these fixes are made.
