# Quick design for P3's new campaigns

This design supersedes the long design for the new campaigns only. It edits no frozen file: `hypotheses.md`, `design/seeds.json`,
everything under `results/` and every existing plan and runner behaviour are untouched. The October Arch rows stay the prior
study. Where this file says "the frozen rule", it points to a section of `hypotheses.md` and does not copy it.

Authority: the three-model votes `decisions/d006-p3-quick-design.md` and `decisions/d007-p3-quick-design-r2.md` (Papers repository),
option E, which stands under CLAUDE.md rule 13 because Claude, Grok and Gemini all ranked it first. Rule 5 sets the length: a
campaign takes at most 10 minutes. The long reruns (queue files `gap84-*`) were dropped before they started and are archive only.

## What each campaign tests

- **Cost, C2 keep-alive and C1 churn.** One cell per campaign: one protocol (HTTP/1.1, h2c, TLS or MQTT) on one backend. Arm A is
  one-port mode, arm B is dedicated mode, the same binary, in-process dispatch. Both arms run rule E's default detection mode for
  the backend: `runlib.PROPOSED_RULE_E`, which is `replay` on epoll, io_uring and IOCP, and equals both committed `rule_e.json`
  files (`lab/analysis-inputs/rule_e.json` and `laptop-w/rule_e.json`). The claim is the frozen cost claim (hypotheses.md 5.1):
  equivalence within [0.98, 1.02].
- **M1.** One cell per campaign: HTTP/1.1 or h2c churn on epoll, one-port mode in both arms, arm A the default detection mode
  (`replay`), arm B the other (`peek`). The claim is the frozen M1 claim (hypotheses.md 5.3).
- **A/A noise run.** HTTP/1.1 keep-alive, dedicated mode against dedicated mode, the same binary on ports 20000 and 20100: the arms of
  `aa.py` and `waa.py`. Its windows are `cellwin.run` and `wcellwin.run`, the windows of the cost cells in dedicated mode, and not
  `window.run_window` of `aa.py` or the window of `waa.py`, so its noise is the noise of the cost cells' own window. It is measured once per OS and reported, never tuned (CLAUDE.md rule 4). It sizes the noise and sets no bound.
- **Hard cases (B1 and B2).** `hardcase_run.py` and `whardcase_run.py` run through their own `part_server`. This is a correctness
  claim, not a timing claim.

## Campaigns and plans

`bench/run/quick_plans.py` writes the 22 plans into `bench/run/plans/quick/`. Each plan names its host, kind, cells, arms, R, the job
warm-up and its expected worst-case seconds; the runner records the plan's sha256 in `quick.json` and in every row. `quick_plans.py
--check` fails if a file differs from what the script makes.

| Plan file | Host | Kind | Cell | Arms (A against B) | R | Worst case |
|---|---|---|---|---|---|---|
| quick-L-epoll-c2-http1, -h2c, -tls, -mqtt | L | cost | C2.L.epoll.PROTO | one-port against dedicated | 16 | 590.3 s |
| quick-L-epoll-c1-http1, -h2c, -tls, -mqtt | L | cost | C1.L.epoll.PROTO | one-port against dedicated | 16 | 590.3 s |
| quick-L-uring-c2-http1, -h2c, -tls, -mqtt | L | cost | C2.L.io_uring.PROTO | one-port against dedicated | 16 | 590.3 s |
| quick-W-iocp-c2-http1, -h2c, -tls, -mqtt | W | cost | C2.W.IOCP.PROTO | one-port against dedicated | 16 | 576.0 s |
| quick-L-epoll-m1-http1, -h2c | L | m1 | M1.L.epoll.PROTO | replay against peek | 16 | 590.3 s |
| quick-L-aa | L | aa | AA.L.epoll.http1.keepalive | dedicated against dedicated | 16 | 590.3 s |
| quick-W-aa | W | aa | AA.W.IOCP.http1.keepalive | dedicated against dedicated | 16 | 576.0 s |
| quick-L-hard | L | hard | 25 cases, 4 entries | epoll and io_uring, replay and peek, in-process | 2 | 555.6 s |
| quick-W-hard | W | hard | 25 cases, 2 entries | IOCP, replay and peek, in-process | 5 | 573.6 s |

The io_uring plans set `uring_job`; the L jobs carry `uring` true and `cgdeleg` false (labrun's defaults, which the gap84 L jobs used).

## Sessions per cell, with the arithmetic

A window is a 1 s warm-up and a 5 s measured window plus start, probe and stop: 6.3 s on L with connection tracking off
(`design/status.md`, 47 consecutive windows, 294 s) and 6.123 s on W (the figure plan v2 used). A session is four windows, X Y Y X
(hypotheses.md 4.1): 25.2 s on L and 24.492 s on W. The brief's single figure of 24.5 s holds for W; L uses its own 6.3 s, so the L
numbers are the larger and the safer ones. The constants are `quick_plans.WINDOW_S`, and `test_quick.py` checks them against
`window.WARMUP_MS`, `window.DURATION_MS` and `sessions.JOB_WARMUP_S`.

The session engine runs a discarded job warm-up of `sessions.JOB_WARMUP_S` = 80 s before the first session, on both OSes. The window
that runs when the time is up completes, so the warm-up costs at most 80 s plus one window. The frozen rule allows `ceil(R/4)`
reruns of invalid sessions per cell (hypotheses.md 4.1; `sessions.rerun_cap`). A campaign of c cells fits when

    worst case:  80 + window + c * (R + ceil(R/4)) * session <= 600 s
    no rerun:    80 + window + c * R * session               <= 600 s

and R is the largest count for which the worst case fits.

- L, one cell: 80 + 6.3 + 20 * 25.2 = 590.3 s at R = 16 (16 + 4 sessions); R = 17 needs 22 sessions, 80 + 6.3 + 554.4 = 640.7 s. No
  rerun: 80 + 6.3 + 16 * 25.2 = 489.5 s.
- W, one cell: 80 + 6.123 + 20 * 24.492 = 575.96 s at R = 16; R = 17 gives 624.9 s. No rerun: 478.0 s.
- Every session plan has one cell, so R = 16 for all 20 of them; none had to be lowered. The cost, M1 and A/A plans each hold one cell,
  so the "R lowered if it does not fit" rule did not fire.

`test_quick.py` asserts, for every plan file and with the window figures written out again in the test, that the no-rerun total and the
worst case are at most 600 s and that R + 1 does not fit. The 25.2 s and 24.492 s sessions are nominal. The overhead of starting and
stopping processes beyond the 0.3 s and 0.123 s per window is not in them, and neither is a window that waits for a timeout (the job's
`timeout_s` of 1,800 s is the real stop); the rerun allowance is the only margin, and a campaign that
needs it all still ends at 590 s.

### Hard cases: the sizing

The hard-case runner runs no sessions, so its time is not a session count. The long design ran 25 cases, 164 variants per entry, 16
replicates. Measured: L's `hl1` took 4,850 s for 8 entries (13:14:33 to 14:35:23; `design/status.md`); W's `wh1` took 1,475 s for 2
entries (02:28:41 to 02:53:16). The gap84 queue files expected 2,500 s for L's 4 io_uring entries (625 s per entry) and 1,400 s for W's
2 entries. The larger per-entry figure is used: L 625 s, W 737.5 s.

A variant costs its R replicate runs plus at most 2 reference runs (the dedicated reply and the dedicated HTTP/1.1 reply), and the
servers are started once per entry. So the time at R replicates is bounded by

    entries * (long time per entry) * (R + 2) / (16 + 2)

because (R + f) / (16 + f) grows with f and f is at most 2.

- L, 4 entries (epoll and io_uring, replay and peek, in-process): 4 * 625 * (R + 2) / 18. R = 2 gives 555.6 s; R = 3 gives 694.4 s.
- W, 2 entries (IOCP, replay and peek, in-process): 2 * 737.5 * (R + 2) / 18. R = 5 gives 573.6 s; R = 6 gives 655.6 s.

L's eight entries do not fit even one replicate with the reference runs (8 * 625 * 3 / 18 = 833 s), so L runs four of them. The four
are the in-process entries of the default and the other detection mode on both backends. The relay entries are dropped with M2 and
M3, whose claim they belong to. The per-entry figure of `hl1` includes relay entries, which are slower than in-process ones, so the
bound is high for the chosen entries. The bound is not a ceiling: a failing variant can wait up to 20 s per run (`SERVER_WAIT_MS`), and
the job's `timeout_s` of 1,800 s is the real stop. The reference-run allowance and the entry time are not measured for the quick subset; the first
quick run is the check, and the plan's expected seconds are the only claim made about it. G and GAP_SPLIT are the pilot entry's values
(`lab/analysis-inputs/pilot.json`: G 4 ms on L, GAP_SPLIT 5 ms; `laptop-w/pilot.json`: G 16 ms on W), copied into the plan and checked
against those files by the test. All 25 cases run, so the h2c and MQTT cases are kept.

## Statistics

The statistics are the frozen ones, applied to fewer sessions (CLAUDE.md rule 4). Each contestant is reported as its median and
spread. The cell statistic is the median over the R session ratios one-port / dedicated (for M1, replay / peek), with the clustered
interval of `analysis/stats.py` (the session as the cluster, the BCa interval). The Holm test is not run. A cell whose interval is not
inside [0.98, 1.02] is reported with its interval and is not worded as equivalent. Arms are interleaved: X Y Y X within a session,
X drawn per session, and sessions in a shuffled order from the seed (`sessions.make_plan`). The seed is given on the command line
(`quick_requests.py` uses the first four bytes of the sha256 of the plan's stem), recorded in every row as `seed` and in `quick.json`.
The A/A campaign is reported as the noise of each OS, once, and sets no bound. The hard-case campaign is a pass count per variant and
entry, and B2's lateness distributions as hypotheses.md 5.2 reports them; it is not a timing claim.

## Running a plan

`quick_run.py --plan PLAN --build BUILD --out DIR --quick SHA256_OF_PLAN (--seed N | --seeds design/seeds.json)`. It refuses unless
(`bench/run/quick_guard.py`):

- the plan lives directly under `bench/run/plans/quick/`;
- its sha256 equals `--quick` (on the laptop `lab_p3.py quick` computes the argument from the deployed file, so this compares the file with
  itself; the protection that counts is the folder check and the equality with the generator's output);
- the plan equals what `quick_plans.py` makes for its stem, so an edited plan with a fresh hash is refused;
- the plan's host is this machine's, and its worst case is at most 600 s;
- the build is a Release build (`CMAKE_BUILD_TYPE` Release, no sanitizer; CMake gives -O3 with clang and /O2 with MSVC).

The runner then runs the plan with the frozen runners' own code: `cost_run.cost_cells`, `m_run.m_cells`, `cellwin.run` and
`wcellwin.run`, the session engine, `hardcase_run.part_server`. The freeze guard is not asked: there is no pilot entry for these
campaigns, and a build made for the job has no records. Its place is the plan-hash gate, the only way a one-port window is timed
against dedicated mode without the pilot entry:

- `quick_guard.QuickClearance` is made by `check_plan` alone. `cellwin.guard` accepts it by class (one added function,
  `is_quick_clearance`; `wcellwin` calls the same guard). A frozen `Clearance`, `None` and a look-alike object are all refused as
  before; `test_quick.py` proves each. The session engine still writes a stub row in development and raises in a frozen run without a
  clearance (tested). `cost_run.py`, `m_run.py` and `hardcase_run.py` have no `--quick` option and still refuse a run without the
  freeze inputs, and `hardcase_run.py` still refuses a narrowed run (tested).
- On this branch the frozen runners also refuse for another reason: `bench/run` holds new files, so `freeze_guard` finds HEAD's frozen
  paths different from CODE_FREEZE. Nothing frozen is meant to run from this branch.

Every row says `development: false` (the analysis's frozen check reads that) and also `quick: true`, `quick_plan`,
`quick_plan_sha256` and `campaign: "quick"`, and `provenance.freeze` is the quick clearance (`quick: true`, `pilot: null`). The row's
`mode` stays the arm's mode, one-port or dedicated, because the engine and the analysis read it. So the label of a quick row is the
`quick` key and not `mode`.

### Jobs

One labrun job is one plan. `bench/run/quick_requests.py --commit C --os L|W` prints the job entries (16 for L, 6 for W). The build phase
is `bench/run/lab_p3.py prepare` (the Release build of the commit in the quick home, `build-<C12>`, made once per OS and commit and
reused by the other jobs). The run phase is `lab_p3.py quick`, which runs `l_quick.sh` on L and `wjob.py run` around `quick_run.py` on W.
The homes are `~/lab/p3/quick-L` and `C:\Users\alext\lab\p3\quick-W`; the source-block files are in them (`src-blocks.json`,
`src-blocks-w.json`), so no frozen state is touched. The jobs set the environment the gap84 jobs set: on L the clock-floor and THP
records; on W Ninja on PATH, `C:\Python314`, the numpy venv `C:\Users\alext\lab\p3\venv-numpy` and `PYTHONNOUSERSITE`.

## What the analysis reads

Quick rows live in their own folders, `out/<plan stem>/` of each job (`windows.jsonl` for the session plans, `hardcases.jsonl` and
`hardcases-table-<job>.json` for the hard cases), with `quick.json` (plan, sha256, seed, commit, build, exit) and
`provenance-<job>.json`. The analysis must read these folders only for the new results, and must keep every row whose `quick` is true
apart from any frozen or October row. Quick rows carry the frozen analysis's cell ids (`C2.L.epoll.http1`, `M1.L.epoll.h2c`) and
`development: false`, so `analysis/rows.py` would accept them as frozen rows if they were put in one folder with frozen rows: the
separation is the folder and the `quick` key. They are not bound to a gate by `bench/check_rows.py` (the build has no sanitizer records;
rule 2 of the Papers repository keeps sanitizers off the numbers); each row records its build's inputs hash and binaries' sha256. The
A/A rows have the cell id `AA.<host>.<backend>.http1.keepalive` and family `AA`, which the frozen analysis does not know; they are read
by the session ratio only.

## What is dropped, for the paper to state

- C3 latency (it needs the A/A pilot's open-loop rate), B3 footprint (the proxies and competitor installs), M2 and M3 (proxies, relay).
- The two-core and mixed-protocol secondary cells, and the SSH and SMTP cells. The census of listening descriptors stays untimed and
  descriptive.
- Windows churn: a churn window on Windows waits for TIME-WAIT to drain, 24.8 to 30.1 s on the desktop (`lab/laptop/bringup-w-p3p4.md`
  section 4), so a churn session takes 125 to 145 s and about three fit in 600 s (d006 facts).
- io_uring churn, io_uring M1, IOCP M1 and the Windows M1: option E drops them.
- In the hard cases: the relay entries on L (they belong to the dropped M2 and M3), and replicates: L 2 and W 5 instead of 16. No case
  is dropped, so the h2c and MQTT hard cases stay.
- The competitors' hard-case table (descriptive) is not re-run.
- The October Arch rows remain the prior study, reported as such.

## The two named deviations from the frozen design

The paper must state both beside every result.

1. **R is 16 for the cost cells, not R_C (28 on L, 18 on W), and the Holm test is not run.** (M1's R is the frozen R_M = 16.) The cost cell
   keeps the frozen margin [0.98, 1.02] and the frozen rerun allowance of `ceil(R/4)`; only R is smaller. With R = 16 an interval is
   wide; the paper states R beside each result and claims no more than the interval supports (the October keep-alive A/A spread was
   0.5 to 1.1 percent, so a 16-session interval inside a 2 percent margin is plausible, not certain). Hypothesis tests of the frozen
   design (Holm over a family) do not run (CLAUDE.md rule 4).
2. **Windows churn is not run** (the TIME-WAIT facts above). The Windows cost result is C2 keep-alive only.

A third difference is stated here as well: the hard-case replicates (L 2, W 5) and the L entries (four of eight) are a reduction forced by
the 600 s limit, not by choice of claim; the hard-case result is "every case passed in each run" and not a 16-replicate pass rate.

## Unverified here

- That the laptop's L and W have what the Release build needs: L, the pinned OpenSSL and nghttp2 under `~/opt` (the gap84 L jobs built
  from the same CMake line, so they exist unless removed); W, the OpenSSL and nghttp2 release installs under `%USERPROFILE%\opt` that
  `wdeps.py` made (gap84's job `p3-deps-w2` runs only when they are missing), and `vcvarsall.bat` (`LAB_VCVARS` or vswhere).
- That `C:\lab\src\Papers\lab\bin` exists on W (used for `--tools`; the runner works without it, only the inputs hash of the build is
  then missing from the provenance) and that `~/lab/Papers/lab/bin/pin.sh` exists on L (the same as the gap84 L jobs).
- The time of the hard-case subsets (see the sizing above), and the time of the Release build, which is outside the 600 s: the build
  timeout is 1,800 s on L and 3,600 s on W.
- That the first quick run's window overhead stays at 0.3 s (L) and 0.123 s (W) per window.
