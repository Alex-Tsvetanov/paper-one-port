# P3 state digest: "One listener for every protocol"

A digest for orientation, refreshed at each milestone. It is not a record: it holds no result and
compares no arms. `design/status.md` and the revision log at the end of `hypotheses.md` stay
authoritative; open them only at the section named here, by grep or line range. As of 2026-10-06,
one-port 9830457 plus the B1 change's docs (status.md, "The B1 change, 2026-10-06"), plus facts
from the coordinator not yet in the repo, marked "(coord.)".

## 1. Where P3 stands

Code frozen at ff2679c; A/A pilots done on L and W; pilot entry, rule E and M2_RATE logged; the
confirmatory runs are under way. L: cost family, hard cases' server part and mechanism family done;
section 10 stopped after 384 windows (sl1) on the B1 counting defect; B3's sessions (bs1) running.
The B1 change is committed (fix 9cae2de, entry 9830457, a later change under section 8): sl1 is
archived as evidence only and section 10 runs again from its start (sl3 on L, ws1 on W), all
prepared, none launched. W: cost family (wc1, stopped at Alex's request, then wc2), M1's IOCP cells
(wm1) and hard cases on IOCP (wh1) ended 2026-10-06 02:53:16 (wc2, wm1 and wh1 exit 0); the
follow-up is done: every W cell reached its R, the three invalid windows are in status.md, the
hard cases all passed, each out directory archived and journaled; W has no job left except
section 10's ws1 (prepared in `m7g\wsfix`). Freeze order (hypotheses.md section 8): steps 1
to 6 done (hypotheses freeze 64a23f7, engineering, CODE_FREEZE, A/A pilots, simulation, pilot
entry). Step 7: rule E, M2's rates, B3 feasibility windows and K_BASE's windows done; confirmatory,
secondary and hard-case runs in progress. Then the analysis of each family once both hosts' data
are in, `results/macros.tex`, the paper.

## 2. Fixed points

- hypotheses.md frozen at 64a23f7 (2026-10-02). Only the revision log grows, append-only.
- CODE_FREEZE = ff2679cc89d23e08a817308c9aeba7901e056fef (entry "The code freeze", c5b1dd9).
  Unchanged by the B1 change; every runner keeps `--code-freeze` with it.
- CHANGE_COMMIT = 9cae2deff2b01896bfab25c5af4c610381dc3c1d (entry "The B1 count of the mixed cell
  (a later change under section 8)", 9830457). `bench/run/freeze_guard.py` from 9cae2de on checks a
  frozen run's `bench`, `tests` and `CMakeLists.txt` against the last commit a revision-log line
  names with CHANGE_COMMIT (else against CODE_FREEZE), and accepts such a commit only if it differs
  from CODE_FREEZE in Python files directly under `bench/run` alone. So a frozen run needs a clone
  at 9830457 or later. A clone before 9cae2de has the frozen guard and the defective count, and
  that guard cannot refuse it: never start a frozen run from one. Rows record the commit at
  `provenance.freeze.freeze.change_commit`.
- ANALYSIS_COMMIT = 9de26d614c85b606fb5169ed16528b7189a87ac4 (2055e63; replaced 7364fbb of d16d8b4);
  unchanged by the B1 change (no file under `analysis/` changed).
  numpy 2.5.0 and Python 3.14.7 in L's venv `~/opt/analysis-numpy-2.5.0/venv`.
- Pilot entry (7455e28): R_C = 28 (rerun cap 7 per cell); m_C = 32 (32 of 36 cost cells resolved).
  Not resolved: cells 34 (C3.W.IOCP.h2c) and 36 (C3.W.IOCP.mqtt), Power_c(31) 0.000; they run at
  R_C and are reported as not resolved, no equivalence claimed. Outside the family: cells 10
  (C1.W.IOCP.h2c) and 12 (C1.W.IOCP.mqtt), run in the pilot only, for WL2's lambda. G_L = 4 ms,
  G_W = 17 ms, GAP_SPLIT = 5 ms. Joint power, reported not targeted: http1 on IOCP 0.7902, tls on
  IOCP 0.8484, every L triple 0.993 or more. Lambda per C3 cell: the entry's item 10.
  `pilot.json` sha256 bc48a736e97a33392b5545f2ba79e317daa19e37e3990c40a232e160f448771d.
- Rule E (77cedae): replay on epoll, io_uring and IOCP; user-space relay buffers on epoll and
  io_uring; the zero-byte WSARecv form on IOCP; so no HAProxy `splice-auto`.
  `rule_e.json` sha256 fb50302aa4e42fc453e7230ed6472e0010f7ac98f1fab96b3daf7ead5ca2dec5.
- M2_RATE (7a63a08): M2.L.epoll.http1 6,887.012 and M2.L.io_uring.http1 7,408.660 exchanges/s.
  M2's two TLS cells have no rate: not run, p = 1 in Holm, m_M stays 20.
  `m2_rates.json` sha256 5c7ddc3ef16a04a8f3be3fbe91ee26d662f4ab8d8be937fcfb530b14f1cff3f6.
- Seeds: 14 names (entry procedure 45d8b03, values 2e6b539), never changed. `design/seeds.json`
  sha256 3a2dd43623aa96190b5b3fac737d96af5a8fabed9853a82233c3a3c9f4c35b3e. A new development seed
  must appear in no line of Papers `lab/journal.jsonl` and in no `design/*.md` or `hypotheses.md`.
- Section 9.1 values: K_SRC 16, N_ACCEPTEX 64, RELAY_BUF 4096 bytes per direction, N_BG_TLS =
  N_BG_MQTT = N_BG_SILENT = 64, ell 206; pins unchanged at the freeze (c5b1dd9, item 3).
- R per family: cost 28; mechanism R_M 16; B3 and section 10 R = 16; K_BASE 16 valid windows. Each
  job starts with JOB_WARMUP_S = 80 s of discarded windows (2055e63).
- Sanitizer records at CODE_FREEZE, all green, in Papers `lab/sanitizer-records/*-ff2679cc8-*`: L
  seven (oneport asan, tsan, msan; harness_cmux asan, tsan; harness_hyper_util asan, tsan); W one
  (oneport W asan). They still cover the build at 9cae2de: on W every target's inputs hash equals
  the measured build's (`m7g\b1fix\b1fix.inputs.json`), and the change touched Python only.
- Build gates (rule D5; not W's quiet gate): `gate-L.json` sha256
  c6517177d497dc7f6951d2860926e950618a17cd6b1fc9568e0f8375ccfc1ab9; `gate-W.json` sha256
  329d372ee7d4dc15ef6b7bac76fb9d8de35d5d048f9eea5108ae08caefc9e1fc. Frozen runs use the records
  jobs' `build-release` (section 7); `bench/check_rows.py` binds every row to its gate.
- W's job-start quiet gate (`bench/run/wsys.py`): mean idle at least 90%, each used CPU at least
  90% idle, no process above 10% of one CPU (1fca359). `--allow-noisy` marks a functional check,
  never a measurement.
- W's frozen runs run in Python's UTF-8 mode: `PYTHONUTF8=1` in the launching process only, never a
  user or machine setting (f185a8a). The guard's cp1252 bug itself is unfixed.

## 3. Revision-log entries since the freeze plan, and decisions

Before these: readings of M1, M2a, M2b, M3, M4a, M4b-2, M5 and M6a; host change, clock floor, THP,
sslh-ev's stalled exchanges, section 10's syscall check (2026-10-02 and 03; `git log -- hypotheses.md`).

| Date | Entry (heading, shortened) | Commit | In one line |
|---|---|---|---|
| 10-03 | The code freeze's preparation (M7) | 3382bb8 | route without ALPN in all five proxies; the three background counts 64 |
| 10-03 | Readings (M7c) | 071b0f9 | five readings: relay copy per backend, pilot order, timer lateness, split replicate, arm value |
| 10-04 | M7c's open items | 13004bc | mixed cell's background and placement; B3 other-mode in relay; ALPN h2 runs; TLS resumption not run; M2 cell without rate not run |
| 10-04 | ANALYSIS_COMMIT | d16d8b4 | 7364fbb (superseded by 2055e63) |
| 10-04 | The pre-freeze items on L (M7d) | 9d7aa15 | M2's backend in a SO_REUSEPORT group; rule E's test; K_BASE's windows; pins, slab, 9.1 values; OpenSSL under TSan |
| 10-04 | The seeds of section 4.7 (M7d) | 45d8b03, 2e6b539 | procedure before the draw, then the 14 values and seeds.json |
| 10-04 | W before the code freeze | ecb8ee7 | Alex's two decisions (below); W's frequency rule fallback; W's WL4 in cycles; W procedure approved |
| 10-04 | ANALYSIS_COMMIT moved (M7e) | 2055e63 | 9de26d6 |
| 10-04 | The job's warm-up and W's runners (M7e) | 2055e63 | 80 s warm-up; W churn h2c/MQTT pilot only; 2-core IOCP cell not run; W mixed-cell placement |
| 10-05 | W's quiet gate lowered (Alex's decision) | 1fca359 | 90/90/10 |
| 10-05 | The code freeze | c5b1dd9 | CODE_FREEZE, suites, 9.1 values, pins, slab, records, gates |
| 10-05 | W's frozen runs in UTF-8 mode (a record) | f185a8a | PYTHONUTF8=1 for every W frozen run |
| 10-05 | The pilot entry | 7455e28 | R_C, m_C, resolved list, G_L, G_W, GAP_SPLIT, lambda |
| 10-05 | Rule E's choices | 77cedae | every proposed default kept |
| 10-05 | B3 feasibility windows and competitors' table (two readings) | 1c4193a | `b3.py` runs the 21 windows; the table runs for all nine systems, last on L |
| 10-05 | M2's rates (M2_RATE) | 7a63a08 | HTTP/1.1 rates; TLS cells not run |
| 10-06 | The B1 count of the mixed cell (a later change under section 8) | 9830457 | fix 9cae2de (CHANGE_COMMIT); section 8 read part by part; records and gates of CODE_FREEZE still cover the build; sl1 archived as evidence and section 10 again, as Alex's decision (not compelled by the archive clause) |

Alex's decisions:
- 2026-10-03: L kernel 7.2.6 by kexec, for NOTRACK (7001e91); THP at madvise for every lab job
  (9bd2bec); W's procedure approved (ecb8ee7, item 8).
- 2026-10-04: W's churn h2c and churn MQTT are generator-bound, outside the cost family; M2's TLS
  cells not run, M2 tested on HTTP/1.1 only (ecb8ee7, items 1 and 2).
- 2026-10-05 00:50: lower W's quiet gate to 90/90/10, checks run as functional checks (1fca359).
- 2026-10-05: wc1 stopped at his request at 20:06:04 (coord.).
- 2026-10-05, B1 counting defect (status.md, "L after the cost family", section 4 item 1): option
  (a), a re-derivation from sl1's rows (coord.). Never applied; replaced on 2026-10-06.
- 2026-10-06, B1 counting defect: follow section 8's rule for a later change. Fix the runners (the
  analysis did not need to change), the entry before any new data, sl1 archived and kept only as
  evidence, section 10 again from its start on L and W with the fixed runner (entry 9830457, item 5).
- 2026-10-05: no larger io_uring buffer pool in P3 (a compiled change after CODE_FREEZE); a
  labelled exploratory follow-up after the confirmatory runs; buffer sizing goes to P4 (coord.).
- 2026-10-05: W's section 10 run (ws1) waits for the B1 fix (coord.). The fix is in; ws1 is
  prepared in `m7g\wsfix`.

Coordinator's decision, 2026-10-05 17:55: run bf1, bk1, bs1, then hc1 on L; hold sl2 for the B1 fix.
sl2 (the resumption of sl1) is not run: section 10 starts again as sl3.

## 4. Run status

L outputs under `~/lab/p3/`, W outputs under `C:\Users\alext\lab\p3\`. Counts from status.md; W's
from its section "W's confirmatory jobs, 2026-10-05/06" (validity read, no arm compared).

| Family | Host | Job(s) | Out | State |
|---|---|---|---|---|
| A/A pilot | L, W | pl1, wp1 | `pilot-L`, `pilot-W` | done, every window valid; archived; journaled |
| Rule E (development) | L, W | re1, wre1 | `m7g/rule_e.json` | done; journaled |
| Cost (C) | L | cl1 (job pc1) | `cost-L` | done: 24 cells x 28, 2,688 windows, all valid; archived; journaled |
| Cost (C) | W | wc1, wc2 | `cost-W` | done: 10 cells x 28 valid sessions (R_C reached, no more). wc1 14:12:55 to 20:06:04, exit 130, stopped at Alex's request (coord.), 857 rows, 14 refusals before it; wc2 23:11:22 to 01:10:03, exit 0, 272 rows, 2 refusals. 1,129 rows = 1,120 planned, less 3 windows of the session the stop cut short (C3.W.IOCP.mqtt.s22), plus 3 reruns (C3 HTTP/1.1, h2c, MQTT; 12 rows). 3 invalid windows (status.md). Archived (`C:\Users\alext\lab\p3-raw-2026-10-05-wc1-wc2-ff2679cc8.tar.gz`, sha256 c1c8804d76fbe71b56bbbacb551a5481a17af34c71e84186a113322f7d6a16e9); journaled (2 lines) |
| Hard cases B1, B2 | L | hl1 (job pc1) | `hard-L` | done: 20,992 runs, all passed; archived; journaled |
| Hard cases B1, B2 | W | wh1 | `hard-W` | done: 02:28:41 to 02:53:16, exit 0; 5,248 runs on 2 IOCP entries, all passed; archived (`C:\Users\alext\lab\p3-raw-2026-10-06-wh1-ff2679cc8.tar.gz`, sha256 46df3e6edbaff644e53da4398ec2aba413a50e06baa99414a30d292dd14d1aa3); journaled |
| M2 rates (development) | L | mr1 | `m2rate-L` | done; archived; journaled |
| Mechanism (M) | L | ml1 | `m-L` | done: 14 cells 16 valid each; sslh-ev's two M3 cells none (logged defect); M2 TLS not run; archived; journaled |
| Mechanism (M) | W | wm1 | `m-W` | done: M1's two IOCP cells, 01:10:03 to 02:28:41, exit 0, 128 rows, 16 valid sessions each, no invalid window; archived (`C:\Users\alext\lab\p3-raw-2026-10-06-wm1-ff2679cc8.tar.gz`, sha256 acb1590cb0adc18ce6dc2191ec65ca7d88dfe25912b9f63a8ca7431fa84b0b9a); journaled |
| Section 10 | L | sl1; sl3 | `s-L` | sl1 stopped 17:53:12 (exit 143), 384 windows, 331 valid; archived (partial); journaled. Under the B1 change: evidence only, never used; `s-L` to be moved to `~/lab/p3/evidence/s-L-sl1-b1count` after bs1. sl3 (section 10 from its start) prepared, not launched |
| Section 10 | W | ws1 | `s-W` | prepared in `m7g\wsfix` (clone `m7g\ws-src1` at 9830457 or later, cutoff at launch); not launched |
| B3 feasibility (development) | L | bf1 | `b3feas-L` | done: 21 windows, 20 valid; archived; journal line after bs1 |
| K_BASE | L | bk1 | `b3-L` | done: 17 windows, 16 valid; journal line after bs1 |
| B3 sessions | L | bs1 | `b3-L` | started 18:26:25 (lab job pid 791871, clone `m7g/post-src7` at d29968b); 2,432 windows without reruns; running as far as known (coord.), not checked |
| Competitors' table | L | hc1 | `hardcomp-L` | not launched; runs last on L, after sl3, from a clone at 9830457 or later |

bs1's end, an estimate: status.md gives about 33 h at bf1's pace, so near 2026-10-07 03:30.

Not run by design, with the reason logged: M2's TLS cells (7a63a08); W's churn h2c and MQTT
(2055e63); section 10's 2-core IOCP cell (2055e63) and TLS resumption (13004bc). Expected without
a valid session: sslh-ev's M3 cells and their section 10 cells (logged defect); section 10's SSH C2
cells (opgen has no keep-alive SSH form, status.md section 4 item 3); W's mixed cell (generator
rule, status.md "M7 freeze night" item 7).

## 5. Open items, in order

1. Done: W follow-up for wc1/wc2, wm1, wh1 (status.md, "W's confirmatory jobs, 2026-10-05/06").
   wc1 had 14 refusals (its `chain.done`), not the 2 the earlier W section records; that section
   is not edited, the new one corrects it.
2. Done: the B1 change (fix 9cae2de, entry 9830457, docs after it; status.md, "The B1 change,
   2026-10-06"). The entry was written after the code, since it names the code's commit (as the
   code freeze's entry did); it came before any new data. ANALYSIS_COMMIT unchanged. Reviewed
   adversarially in two rounds before the commits; every finding fixed.
3. bs1's end (agent, no connection to L before it). Then: journal bf1, bk1, bs1; archive `b3-L`;
   push the queued commits to the `lab` remote (nothing goes there while bs1 runs, so L's clones
   cannot see newer commits, 9cae2de and 9830457 included, until then).
4. L after item 3 (agent), in the order and with the exact commands of status.md, "The B1 change,
   2026-10-06", section 2: (a) sl1's archive checked by its sha256, `~/lab/p3/s-L` moved to
   `~/lab/p3/evidence/s-L-sl1-b1count`, and a journal line (sl1 archived, evidence only); (b) a
   fresh clone `m7g/post-src8` at 9830457 or later, and `test_frozen` and `test_runner` run on L
   from it, both exit 0, written into status.md; (c) sl3: `l_run.sh post-src8 s sl3`, section 10
   from its start into the emptied `s-L`. sl2 is not run.
5. hc1 on L (agent): after sl3, from its own fresh clone `m7g/post-src9` at 9830457 or later,
   `l_run.sh post-src9 comp hc1` (status.md, the same section 2, step 4). Last on L.
6. ws1 on W (agent, quiet W window): clone `m7g\ws-src1` at 9830457 or later, set the cutoff in
   `m7g\wsfix\run_chain.cmd`, launch through `wlaunch.ps1` (status.md, the same section 2). The old
   chain `m7g\ws` is retired (its launcher and steps renamed `*.superseded-b1fix`).
7. Before any analysis of sl3, ws1 and hc1: every row names `change_commit` 9cae2de at
   `provenance.freeze.freeze.change_commit` (status.md, the same section, section 3); sl1's rows
   are given to no analysis. Then the analysis per family at ANALYSIS_COMMIT: cost (L and W),
   mechanism (L and W), B (L and W), B3 and K_BASE (L), section 10 (sl3 and ws1 only). Then
   `results/macros.tex` and the paper, which reports sl1's mixed-cell rows as the defect's
   evidence and names what sl1 showed (entry 9830457, items 2 and 5).
8. The exploratory io_uring buffer-pool follow-up, labelled exploratory, after the confirmatory
   runs (agent, per Alex's decision).
9. For Alex, undecided: the guard's encoding fix (a later change); Windows `Server::start()`
   returning before the AcceptEx requests are posted; the wider generator placement for W's mixed
   cell; the mixed cell on io_uring starving its churn (status.md section 4 item 2), as the paper
   reports it.

## 6. Rules every agent keeps

- No connection of any kind to L (ssh, scp, `git push lab`) while bs1 runs: section 7's TIME-WAIT
  rule. Check bs1 only through a watch the coordinator opened before it started.
- L jobs: from bash at nice 0 under `SRC/bench/run/lab_job.sh` (lab lock, clock floor, THP madvise,
  NOTRACK), each from a fresh clone of the lab remote; watch pid and done files in `~/lab/p3/m7g/`;
  never `pgrep -f` or `pkill -f`. ssh only to 192.168.1.62 (wired), never 192.168.1.9.
- Every frozen run from now on starts from a clone at 9830457 or later, on L and on W (the B1
  change); never from an older clone such as `post-src2` to `post-src7` or W's `post-src2`.
- W: no work of any kind while W measures; never change a Windows setting; Alex's power plan
  ("ChrisTitus - Ultimate Power Plan") restored after every job (wjob does it; check
  `plan_restored` in the done file).
- Frozen text append-only; the rows are never edited; a stopped session reruns on resumption.
- Never invent or project a number; no em or en dashes; no private library named; nothing public.
- Sub-agents in the foreground only.

## 7. Paths

| What | Where |
|---|---|
| Repo | `D:\Dev\GitHub\Papers\papers\one-port`; remotes `origin` GitHub paper-one-port (private), `lab` alex@192.168.1.62:lab/p3/one-port.git |
| Mono-repo | `D:\Dev\GitHub\Papers` (origin only); journal `lab/journal.jsonl`, records `lab/sanitizer-records/` |
| W branch worktree | `D:\Dev\GitHub\Papers\papers\one-port-m6b` (branch m6b-windows, merged; untracked in Papers) |
| L job dir | `~/lab/p3/m7g/`: `NAME.pid`, `NAME.done`, `NAME.log`; `l_run.sh`, `l_check.py`, `post_chain.sh`, `b3feas.sh` |
| L clones | `m7g/post-src2` 77cedae, `post-src3` 86c0283, `post-src4` 7a63a08, `post-src5..7` d29968b, `ana-src` 9de26d6; to make after bs1: `post-src8` (sl3), `post-src9` (hc1), each at 9830457 or later |
| L evidence | `~/lab/p3/evidence/s-L-sl1-b1count` (sl1's output, moved there after bs1; never analysed) |
| L frozen build | `~/lab/p3/m7g/records-ff2679c/build-release`, `gate-L.json`; pilot output `m7g/pilot-entry/pilot.json` |
| L archives, logs | `~/lab/p3-raw-2026-10-05-<job>-ff2679cc8.tar.gz` (+ `.sha256`); `~/lab/records-logs/<record>/` |
| L launch | `bash -c '(setsid nohup bash SRC/bench/run/lab_job.sh ~/lab/p3/m7g NAME bash ~/lab/p3/m7g/l_run.sh SRC STEP JOB > /dev/null 2>&1 &)'` |
| W job dirs | `C:\Users\alext\lab\p3\m7g\` `wcost`, `wm`, `whard`, `wnight2` (chain wc2, wm1, wh1; `chain.log`, `chain.done`), `wpilot`, `wrule`; `wsfix` (ws1, prepared); `ws` retired (B1 change) |
| W clones, files | `m7g\post-src2` 77cedae, `m7g\pilot-src2` f185a8a; to make: `m7g\ws-src1` at 9830457 or later; `m7g\pilot.json`, `m7g\rule_e.json`, `m7g\stopat.py`; the B1 change's checks `m7g\b1fix\` (`SHA256SUMS` sha256 32418367ea727376f6566a8502f3450183f796e10649429548f0954dc832789e) |
| W frozen build | `C:\Users\alext\lab\p3\m7g\records-ff2679c-W\build-release`, `gate-W.json` |
| W launchers | `run_chain.cmd` per dir, its `chain.py`, `steps.json`, `launches.txt`; WMI launch by `C:\Users\alext\lab\p3\m6b\wlaunch.ps1`; stop with `chain.stop` |
| W Python | `C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe` |
