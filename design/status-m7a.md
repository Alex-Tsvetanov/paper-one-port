# M7a: the frozen analysis pipeline, 2026-10-03

Branch `m7-analysis`, from main adbc041. Pure Python on W; no lab run, no other machine. Nothing
here is a result: every number below comes from synthetic data or from Appendix A's model.
`hypotheses.md` is not edited; its readings are listed below for the revision log.

## Commits (m7-analysis)

- 4f3a569 `stats.py` and its tests.
- 7b3bee9 `pilot.py`, `cells.py`, `rows.py`, `versions.py`, `requirements.txt`, `synth.py`, and
  the pilot's tests.
- 9700c0c `analyse.py`, `macros.py`, the end-to-end test and the registry tests.
- 4302d6d the outputs name the analysis commit and list their inputs in order; the pilot entry's
  N_SIM and each C3 cell's rate are checked.
- This file, in the commit after them.

## What `analysis/` holds

| Module | What it does |
|---|---|
| `stats.py` | 4.2's computations: the exact sign test (one-sided and TOST, on `Fraction`), the clustered BCa (z0 with ties as half, jackknife acceleration, clipped shares, one-sided p-values, intervals), Holm, Holm's levels (4.3), the dual rule; the chi-square quantile and Silverman's factor of 4.6. |
| `cells.py` | The frozen cell lists of section 6 (36 cost cells numbered c = 1 to 36, B3's 18 Holm and 16 descriptive cells, the 20 M cells), section 10's cells with sessions of their own, the order of every `SEED_BOOT_S` draw (285 in all), and the check of the 14 seeds of 4.7. |
| `rows.py` | The row contract (below), the refusals (dry run, synthetic, development), the gate through `bench/check_rows.py`'s own functions, sessions (X Y Y X, validity, roles), window values. |
| `pilot.py` | 4.6 and 9.2: Power_c(R), the resolved list, R_C, m_C, the joint powers, lambda per C3 cell, G_L and G_W, GAP_SPLIT, the pilot's invalid windows and excluded part runs. |
| `analyse.py` | Every family's tests and decisions (C, B3, M), the descriptive cells, section 10's intervals, section 12's wording, the claims, B1 flags, K_BASE; writes `summary.json` and `decisions.csv`. |
| `macros.py` | `results/macros.tex` from `summary.json`, names letters only. |
| `versions.py` | The pins (numpy 2.5.0, Python 3.14; `requirements.txt`), the analysis commit in every output, the guard that keeps synthetic outputs out of `results/`. |
| `synth.py` | Synthetic rows in the runners' formats. Tests only; every row says `"synthetic": true`. |

Adapted from the previous paper (`papers/typed-routing/analysis/`, same author): the BCa over
clusters and Holm (`stats.py`, `holm.py`), the macro store and rounding (`macros.py`,
`macros_util.py`). Each module says what changed. `appendix_a_r_rule.py` is unchanged; the chi-square
functions are copied from it unchanged.

## Tests

`python -m pytest analysis` on W (Python 3.14.5, numpy 2.5.0): 66 passed, 2 skipped.

| File | Tests | What they check against |
|---|---|---|
| `test_stats.py` | 36 (1 skipped without SciPy) | 4.5's sign-test grid at R_C = 11 to 31 and its rounded "one more" values; the allowed count at every R from 11 to 32 (steps only at 11, 15, 18, 22, 25, 28, 31); proposal 5.6's fractions and R = 32; R = 16's values; an independent tail sum for n = 0 to 32; ties and missing values against; one out on each side at R = 15 still passes. Holm on the textbook example (Holm 1979, p = 0.01, 0.04, 0.03, 0.005 at 0.05) and on 4.5's "k <= 11" and "k <= 2" for m = 18 and 20. The BCa equal to `appendix_a_r_rule.bca_p` and `passes` draw for draw at R = 11 to 31; equal to an inline textbook BCa (Efron and Tibshirani 1993, ch. 14); 4.3's "passes at alpha exactly when the interval lies inside the margin" over 300 random cells at alpha, alpha/36 and alpha/7; clusters resampled whole; the degenerate map; q = 10.306959006625288 and s_U / s = 1.2063695181246945 (status.md's recorded output). |
| `test_pilot.py` | 15 (1 slow, opt-in) | The rule on hand-made pass counts (a cell whose power is not monotone in R: R_C = 18 where the cells' own R_c are 15 and 11); 0.80 exact; the joint power as a product; the streams of 4.6 step 3; the simulation equal to the confirmatory function; worker count without effect; G, GAP_SPLIT and lambda on hand-made rows; the refusals; Appendix A's 24 pilots (their sd as status.md records them); a whole synthetic pilot; the command line byte for byte at 1 and 2 workers, and never under `results/`. |
| `test_cells.py` | 7 | The orders of 6.1, 6.2, 6.3 and of `SEED_BOOT_S`; the seeds file; a letters-only macro word for every cell; no en or em dash in `analysis/` or this file. |
| `test_analyse.py` | 10 | The whole pipeline through the three command-line tools on synthetic rows (below). |

With SciPy: in a scratch virtual environment made offline from uv's cache (SciPy 1.17.1, numpy
2.4.6, nothing downloaded), `test_stats.py` passes 36 of 36, so `scipy.stats.bootstrap(method="BCa")`
gives the same bootstrap distribution and bounds within one order statistic (SciPy interpolates
linearly).

Appendix A at full size (`ONEPORT_SLOW=1`, SEED_SIM = 43, 11 worker processes, 112 s for 24
cells): the frozen rule chooses the same R as the appendix's script in 21 of 24 pilots. The three
others lie where the deciding candidate's power is within 1.7 standard errors (0.0126) of 0.80:

| Pilot (sigma, index) | Appendix | Here | Power here at the two candidates |
|---|---|---|---|
| 0.010, 7 | 15 | 18 | 0.796 at 15, 0.940 at 18 |
| 0.0125, 4 | 28 | 31 | 0.778 at 28, 0.845 at 31 |
| 0.0125, 6 | 25 | 28 | 0.789 at 25, 0.877 at 28 |

The streams differ from the script's (the script draws per job, the frozen rule per (SEED_SIM, c,
j) and (SEED_SIM, c, j, R)), so this is Monte Carlo noise, not a difference of rule. The four cells
the appendix leaves unresolved are unresolved here too. The whole pilot (36 cells) should take
about three minutes at 11 workers on W.

## The end-to-end test's known answers

`test_analyse.py` writes synthetic rows to pytest's temporary directory, runs `pilot.py` (N_SIM =
20, a test-only value the command line takes only with `--allow-synthetic`), `analyse.py` and
`macros.py`, twice. All pass.

| Case | Construction | Result |
|---|---|---|
| Pilot | 9 cost cells at log sd 0.002, one W cell at 0.06 | resolved = the 9, R_C = 11, m_C = 9, joint powers for HTTP/1.1 and h2c on epoll, G = 2 ms on L and W, GAP_SPLIT = 5 ms |
| Equivalent within the margin | HTTP/1.1 on epoll, C1, C2 and C3, ratios 1.0 +- 0.4% | pass; Holm-level interval inside [0.98, 1.02]; the claim for HTTP/1.1, epoll, L with its joint power |
| Not equivalent, a measured cost | h2c C1 at 0.95; h2c C3 (TTFB) at 1.05 | "equivalence not shown; a measured cost" |
| Not equivalent, in one-port mode's favour | h2c C2 at 1.05 | "equivalence not shown; the 95% interval lies wholly outside the margin, in one-port mode's favour" |
| Noisy | TLS C1, ratios 1.0 +- 5% | not shown, no cost |
| Invalid window, run again | MQTT C1, one session invalid and run again; a session with a driver-fault row | pass with 11 of 12 sessions valid; the invalid window listed with its arm |
| Invalid windows, reruns spent | HTTP/1.1 on io_uring C1, 8 valid | untested, p = 1 in Holm |
| Not resolved | HTTP/1.1 on IOCP C1 | "not resolved at R <= 32", outside Holm, interval from the family's draws |
| Superior (B3) | nginx silent, Q = 1.5 | shown, X = 16, D = 3,500 bytes with its interval |
| Inferior (B3) | sslh-ev silent, Q = 0.93 | "not shown; loss" |
| B3 near 1 | HAProxy silent, Q = 1.0 +- 5% | "not shown" (no loss) |
| W_srv = 0 | nginx partial ClientHello, one session at W_srv = 0 | Q = 0 for that session, still shown with X = 15 |
| Descriptive | Netty silent, Q = 2.0 | "descriptive", interval reported |
| M | M1 1.05 shown; M1 IOCP 0.98 not; M2 0.70 shown; M2 TLS 1.03 not; M3 nginx 1.2 shown; M3 HAProxy 0.9 loss; M3 sslh-ev every session invalid, untested | as constructed; M3's listen overflows per arm |
| Secondary | SSH C1, B3 in the other mode, M1's TTFB, WL4 on the cost cells, by job | intervals where R sessions exist; 2 jobs give a clustered interval, 1 job none |
| Draws | the cost family's intervals recomputed from SEED_BOOT_C in 6.1's order | equal |
| Refusals | a B3 row without binaries; a row with development true; a dry run; synthetic rows without the flag; an output under `results/` | each refused; nothing written under `results/` |
| Reproducibility | the same inputs and seeds twice | `summary.json`, `decisions.csv` and `macros.tex` byte-identical |

Synthetic data is never written under `results/`: rows carry `"synthetic": true`; `pilot.py` and
`analyse.py` refuse them unless `--allow-synthetic`, and then refuse any output path under
`results/`; `macros.py` refuses to write a synthetic summary there; a synthetic `macros.tex`
begins with a line saying it is synthetic; the tests write only into temporary directories and
check that nothing appeared under `results/`.

## The row contract (what the frozen runners must write)

`analysis/rows.py` holds it in full. In short, every window row of a frozen run carries:
- `job`, `session` (unique within the job), `position` 0 to 3, `arm` (two labels, X Y Y X),
  `valid`, `invalid_reasons`;
- `development: false` (also in a driver fault's row, which `window.run_window` writes with
  `true` today), no `dry_run`, no `synthetic`;
- `provenance.binaries` with the sha256 of every first-party binary the window ran (`b3.py`
  writes none yet: the M7 checklist's item 1);
- `misclassified`, the count of connections classified other than as their script's protocol,
  where the runner can read it (B1, section 7);
- `family` and the fields of its cell and role, with the server's tokens (`one-port`,
  `dedicated`, `replay`, `peek`, `inproc`, `relay`, `epoll`, `io_uring`, `IOCP`):
  - C: `workload`, `proto`, `backend`, `mode`; one-port rows `detect` (rule E's default) and
    `dispatch: inproc`; `metric` as `window.py` writes it;
  - B3: `b3.py`'s rows, with `session`, `position` and `arm` added by the session runner; the
    server arm's `backend` and `detect`; ophold rows give K_BASE;
  - M1: `proto`, `backend`, `mode: one-port`, `dispatch: inproc`, `detect`, `metric` conn_per_s;
  - M2: `proto`, `backend`, `dispatch`, `metric` `{"name": "wl6_cpu_us_per_conn"}` (front and
    backend together in relay, the server alone in-process);
  - M3: `handoff.py`'s rows as they are (`family: "M3"`);
  - S (section 10): `bullet` (`ssh`, `mixed`, `tls-variants`, `two-cores`, `relay-io_uring`,
    `iocp-forms`, `m-ttfb`, `b3-other-mode`) and its fields (`variant`, `listener`,
    `iocp_accept`, `iocp_receive`, `hyp`).
- The pilot's rows are `aa.py`'s (arm A the first start, B the offset start, `mode: dedicated`,
  `seed` = SEED_PILOT_L or SEED_PILOT_W), development true or false.
- The pilot's parts, which no runner writes yet: `{"part": "timer", "backend", "mode":
  "dedicated", "run", "valid", "invalid_reasons", "lateness_ns"}` and `{"part": "split",
  "backend", "mode": "dedicated", "gap_ms", "replicate", "valid", "invalid_reasons",
  "recv_data"}`, with `provenance.binaries`.
- Two input files beside the rows: the seeds (a JSON object of the 14 names of 4.7) and rule E's
  choices (`{"default": {backend: mode}, "relay_copy", "iocp_receive"}`).

## Readings for the revision log

Each is a reading of the frozen text that the code takes; none changes a rule.

1. The pilot's session ratio is B / A, arm A the binary's first start and B the start on the port
   offset, as `aa.py` computes it. 4.6 names no direction; the log bounds are not symmetric, so the
   direction can move Power_c slightly through skew.
2. WL2's "the session's mean connections per second" is the mean of the session's four windows
   (`aa.py`), over the valid sessions of the C1 pilot cell; lambda = 0.5 x their median.
3. The pilot is development data (4.6 step 1; proposal ST13), so `pilot.py` takes rows marked
   development; it still refuses one-port rows (4.6 step 1), dry runs and rows the gate refuses
   (rule D5: R_C, lambda and G are cited).
4. 4.7's order within a section 10 bullet is applied as written: hypothesis, host, backend,
   protocol in 6.1's order (HTTP/1.1, h2c, TLS, MQTT), then the system in 2.3's order, then a
   case, variant or form in the bullet's order. So, unlike 6.3, the relay on io_uring and M3's
   TTFB cells take HTTP/1.1 before TLS; the M1 cells of the bullet "for M1 and M3, TTFB at a fixed
   load; for every M cell, CPU per connection" go backend first; the 2-core cells and the
   `SO_REUSEPORT` cells alternate by backend; the TLS variants go by backend, then resumption,
   then ALPN h2.
5. B3's descriptive cells take 6.2's listing order (Netty, Jetty, caddy-l4, cmux) with the Holm
   cells' rule (case, then system, then backend), since 4.7 draws "in the family's list in
   section 6"; 2.3's order would put caddy-l4 first.
6. The first bullet of section 10 has, per cost cell (all 36, at R_C): CPU per connection or
   request, resident memory at the end, its peak (WL4 names both), then, for C3 cells, p99 TTFB;
   each metric draws its own resamples ("within a cell, the metrics follow the order the bullet
   names them").
7. A family cell draws once (4.7) and that draw serves all of its statistics: the cost cell's 95%
   and Holm-level intervals and both one-sided p-values; B3's Q and D.
8. B3's D is reported as the median of the session values D = W_comp - W_srv (ST5's statistic),
   with its 95% BCa interval from the cell's draw.
9. Section 12's "measured cost" is called only on the side against one-port mode: for C1 and C2
   (higher is better) an interval wholly below 0.98, for C3 (lower is better) wholly above 1.02.
   An interval wholly outside on the other side is reported as lying outside the margin in
   one-port mode's favour, and equivalence is still not shown.
10. 9.2's G: "the smallest whole number of milliseconds above the largest lateness" is
    floor(max / 1 ms) + 1, so a maximum of exactly 2 ms gives 3 ms.
11. 9.2's GAP_SPLIT: "shows the split read" is at least two receives that returned payload
    (`recv_data` >= 2). "If none does, 100 ms" applies when both hosts' split rows are in the
    input; without one host's rows the value is not computable and the pilot entry incomplete,
    since the entry needs both hosts (8 step 6).
12. The Holm-level interval is computed where the text names it: the cost family (4.3) and B3
    (5.2, on B3's BCa ranks); not for M.
13. The analysis clustered by lab job (4.1, section 10) resamples jobs and reports the family
    statistic's 95% interval and its BCa p for the family's test; a cell from fewer than 2 jobs
    has no interval but still draws, so the later intervals keep their streams.
14. Section 10's "the receive form rule E did not choose": the default arm is the one whose
    `iocp_receive` equals rule E's (the zero-byte form, the coordinator's decision of
    2026-10-03); section 10 names no metric for the two IOCP cells, so the analysis takes the
    windows' own metric and requires both arms to carry the same.
15. "In its default detection mode" (5.1, 5.2) is checked where a row carries `detect`: a cost
    or B3 server row in the other mode refuses the input.
16. B1 (5.2, section 7): a window whose `misclassified` count is above 0 is a B1 failure,
    whether or not the window is valid.
17. WL6's "CPU time of the front and the backend together" is, in M2's in-process arm, the
    server's own CPU time: that arm has no backend.
18. "A cell is resolved if it has P valid pilot sessions": the P sessions must each have a
    positive ratio.

## Design choices (for the revision log)

Each is a choice the frozen text leaves open, made here.

1. The BCa interval's quantile is the inverse of the resamples' empirical distribution (NumPy
   "inverted_cdf"). With it 4.3's statement (the BCa form passes at alpha exactly when the
   1 - 2 alpha interval lies inside the margin) holds, side by side, except at the p's floor,
   where no resample lies beyond the bound and the clipped share gives a p above a small alpha
   (|z0| beyond 4.2's limits). The test checks it on 300 random cells.
2. z0's share is clipped to [1/(2B), 1 - 1/(2B)] like the share beyond a bound, as Appendix A's
   code does, so z0 is finite when every resample lies on one side.
3. Where the BCa map does not reach a bound (1 + a(w - z0) <= 0) the p is reported as degenerate
   and taken as 1, and the interval bound as missing. A median at R = 11 to 32 cannot produce it;
   a clustering by few jobs can.
4. Outside B3, a valid session whose ratio cannot be formed (an arm value missing or not
   positive) leaves the cell untested (p = 1 in both computations). B3 uses Q = 0 (5.2).
5. Sessions are ordered by (job, session id) as strings; the resample indices and the pilot's
   e_i refer to that order.
6. The generator is NumPy's `default_rng` (PCG64) seeded by the seed or by the tuple (SEED_SIM,
   c, j) and (SEED_SIM, c, j, R), c and j counted from 1; a resample is `integers(0, K, size=(B,
   K))`; the simulation's draws are `integers(0, 16, 31)` then `normal(0, b, 31)`.
7. The IQR of Silverman's factor uses NumPy's default percentiles (linear), and b is computed as
   h / s, as Appendix A's code does.
8. A pilot cell whose sessions all have the same ratio (s = 0) simulates every session at a
   ratio of 1.
9. The power target is compared exactly, as a count: 800 or more of 1,000.
10. In the simulation a run's BCa is computed only when its sign test passes. The result is the
    same, since a run passes only if both do and each BCa draws from its own stream.
11. A refused row refuses the whole input (no filtering); a cell with more than R valid sessions,
    a session of another shape than X Y Y X, or one arm with two roles refuses it too; a session
    with fewer than four windows is invalid.
12. The pins: numpy 2.5.0 on Python 3.14 (Appendix A's versions), enforced by the command lines.
13. The seeds are read from a JSON file of the 14 names; the code holds no seed value.
14. The row formats of the timer and split parts, and the rows of the runners not yet written
    (the contract above).
15. Macro names: each part of a cell id maps to a word (C1 COne, io_uring Iouring, caddy-l4
    CaddyLFour, tls-stub TlsSni); per cell Median, Low, High, HolmLow, HolmHigh, PBoot, PSign,
    SignX (SignXLow, SignXHigh for the cost cells), Holds, Verdict, Valid, InvalidWindows; B3's D
    and parts; secondary intervals under Sec. A missing value writes no macro.

## Not produced by `analysis/`

- B1's hard-case table and B2's checks: from the hard-case runs, whose runner is still to be
  written (status.md, "What M7 starts from"). `analyse.py` reports only B1's misclassification
  flags from measured windows.
- "The server's bounds" beside B3 (5.2): engineering constants of the server.
- The competitors' hard-case outcomes and B2's distributions: descriptive tables of those runs.
- Operations, copies and system calls per connection (section 10): counts of untimed windows.
- The pilot archive's sha256 (9.2): `pilot.py` hashes its input files; the archive's sha256 is
  the runner's.

## For the coordinator: making this ANALYSIS_COMMIT

1. Review and merge `m7-analysis` into main. The merge commit is the candidate ANALYSIS_COMMIT
   (section 9.1: "the commit of analysis/ that runs 4.6 and the confirmatory analysis, with its
   tests"). From then on nothing under `analysis/` changes; a change is a later change.
2. On the merged tree, on Python 3.14.5 with numpy 2.5.0: `python -m pytest analysis` (66 pass,
   2 skip), and once `ONEPORT_SLOW=1 python -m pytest analysis/test_pilot.py -k appendix` (about
   two minutes at 11 workers). Optionally the SciPy cross-check in an environment with SciPy.
3. Log ANALYSIS_COMMIT in the revision log with the readings and design choices above (section 8
   step 2 asks for it before the code freeze, and section 9.1 names it).
4. The seeds entry (checklist item 5): fix the 14 seeds, and commit beside the entry a JSON file
   with them, outside `analysis/` (for example `design/seeds.json`), which `pilot.py` and
   `analyse.py` read with `--seeds`.
5. The runners must write the contract above before their rows can be analysed: the pilot runner
   (aa.py's rows on the frozen binary, with the host's order seed), the timer and split parts,
   the cost family's one-port against dedicated runner (`family: "C"`), the B3 session runner
   (sessions, and `binaries`, item 1 of the checklist), M1 and M2, section 10's cells, rule E's
   file; `development: false` in every frozen row, fault rows included.
6. At step 5 of section 8: `pilot.py --seeds ... --gate gate-L.json --gate gate-W.json --rows
   <pilot windows> --parts <parts> --out <pilot.json> --workers 11`, then the pilot entry from
   its output. After the runs: `analyse.py ... --out results/`, then `macros.py
   results/summary.json`.
