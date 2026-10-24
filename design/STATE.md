# P3 state digest: "One listener for every protocol"

A digest for orientation, refreshed at each milestone. It is not a record: it holds no result and
compares no arms. `design/status.md` and the revision log at the end of `hypotheses.md` stay
authoritative; open them only at the section named here, by grep or line range. As of 2026-10-08
(morning): the commits of this refresh add section 10's four descriptive outputs (status.md,
"Section 10's four descriptive outputs and lab job st1, 2026-10-08"; revision-log entry of
2026-10-08, bd9a720, item 7 appended with them); before them, the competitors' macros and the
follow-up of hc1 (status.md, "The competitors' table hc1, 2026-10-07", and the sections before it),
plus facts from the coordinator not yet in the repo, marked "(coord.)". All confirmatory and
descriptive data are in; no job is open on L or W.

## 0. W moves to the laptop's Windows (2026-10-23; supersedes the W parts below where they differ)

Alex's decision of 2026-10-23 (Papers plan v2, Q3 option A): W's cells run again on the laptop's
Windows (Ryzen 7 5800H, 8 cores, MSVC 19.51.36248); L's rows stand; the desktop's rows enter no
analysis. Work on the local branch `laptop-w-bringup` (worktree `D:\Dev\worktrees\p3-laptop`),
cut from main 1f27ea8: main holds the whole revision log (so an entry appends at its true end; a
branch from 29ae2b6 would fork it), its `bench`, `tests` and `CMakeLists.txt` equal CHANGE_COMMIT
9cae2de's, and it descends from 9830457, so its guard is the fixed one. Pushed with Alex's yes
(2026-10-23) to the public branch `laptop-w-bringup`: up to 6c7be67, then up to 632b242 (item 10
and the R per host now have their public timestamp before any probe data).

Alex's answers of 2026-10-23: push the branch (done to 6c7be67); R per host in `analysis/`
(8815d89, below); the frequency counter is not tested on the laptop; the TCP settings are set on
the laptop to the design's values if they differ, else the laptop's are documented (item 10).

- 8e7d4a6: the reading entry "A probe of window times on the laptop's Windows, before the entry
  that moves W's runs there (a reading)". Pure addition after the 10-08 entry; the guard still
  names 9cae2de. Its item 9, appended in the docs commit after b20f415, names b20f415 as the
  probe's commit and corrects items 5, 6 and 8 after the review (no line of the entry holds the
  word the guard reads, which a test checks).
- 54f42aa: the entry's item 10: Alex's decision on the laptop's TCP settings (set to 30 s and 1025
  to 65535 by his own admin step before the probe if they differ; else documented), and the
  probe's commit a4d8e89, which replaces item 9's.
- 8815d89: `analysis/` alone, R per host: `pilot.py --fixed-r L=28` keeps L's R; W's R is 4.6
  step 6 over W's resolved cells alone; `analyse.py` gives each cost cell its host's R, Holm over
  all resolved cells as one family; `macros.py` adds CostRL and CostRW. Suite 78 passed, 2 skipped.
  On October's inputs, from a fresh clone: `decisions.csv` and `macros.tex` byte-identical to the
  committed ones, `summary.json` apart only in `versions.analysis_commit`. The ANALYSIS_COMMIT-to-be,
  named in the move's entry (draft item 8). The pilot simulation on real rows was not rerun (hours
  of CPU); the synthetic CLI test covers that path.
- e61e78f: a fresh Opus review of 8815d89 found its `analysis/` logic correct and unchanged without
  the option, and one HIGH: W's cost runner still took the pooled R_C (`cost_run.pilot_values`).
  Fixed: each cost runner takes its host's R; `CostR` is not written when R is per host (the
  paper's `\RC` and `\CostR` must become `CostRL` and `CostRW` in the writing pack); docstrings
  state the departures from 4.1, 5.1 and 4.6 step 7; new tests of the secondary draws and of W at
  another R than L (analysis 78 passed, 2 skipped; `test_wlaptop` 39). October check repeated at
  e61e78f: identical result. e61e78f is both the CHANGE_COMMIT-to-be and the ANALYSIS_COMMIT-to-be.
- 5cc1e06, then b20f415 (the review's fixes), then e183745 (a test that broke once item 9 was
  committed), then a4d8e89 (the probe reads its commit from the entry's last item naming it): the
  runners for the laptop, Python directly under `bench/run` alone. a4d8e89 is the
  probe's commit (e61e78f, above, is the CHANGE_COMMIT-to-be): `wsys.py` (8 cores; section 4.1's rule gives server 14, sibling 15 idle,
  generator 2 to 13, quiet CPUs 2 to 14), `wwindow.py` (open-loop threads 2, 4, ..., 12),
  `wcellwin.py` (the mixed cell takes L's placement), `wpower.py` (the laptop's lab plan b1bcd431
  by GUID, Alex's plan Balanced; inside a lab job, LAB_JOB_ID set, it only verifies), `wjob.py`
  (inside a lab job the lab's quiet check counts, by LAB_QUIET=passed), `wrunlib.py` (a frozen W
  run refuses a gate not made from a `laptop-w` records folder with the laptop's compiler, and
  needs the move's entry), `freeze_guard.py` (`W_LAPTOP_ITEMS`), `wdeps.py` (build_deps.ps1
  copied with one line changed), `wprobe.py` (the probe), tests `test_wlaptop.py` and updates.
  b20f415 also reads the counters of all 16 CPUs (the window code read the desktop's 12), ties
  LAB_QUIET to the lab job (`passed:<LAB_JOB_ID>`), refuses every plan switch inside a lab job
  (`wpower.py restore`, `switch_within_session`, `wnight.py`, `wfreq.py`), makes the probe refuse a
  non-Release or sanitizer build, a clone other than item 9's commit, a run outside a W lab job
  and an unpinned reading, keeps its raw files outside `--out` (deleted and checked), and stores
  the laptop-gate check in the clearance.
- Review (fresh Opus agent, 2026-10-23): 3 HIGH (the 12-CPU reads, the entry's items 6 and 8,
  LAB_QUIET unset), 3 MEDIUM (plan switches inside a lab job, the probe's unenforced conditions,
  silent raw-file deletion), 3 LOW (CRLF in 5cc1e06, the gate identified by folder and compiler,
  item 9 and the guard's word). All fixed in b20f415 or item 9, except the gate's host name: the
  gate file names no host, so the check stays folder and compiler (recorded in the clearance).
- `design/w-laptop-entry-draft.md`: the draft of the move's section 8 entry. It stays a draft
  until the probe's computed time is stated to Alex and the open points are answered.
- Desktop checks (2026-10-23, no timing): Release build with MSVC 19.51.36246 (`-j4`), CTest 165
  of 165 (at 5cc1e06; b20f415 changes no compiled file); `test_wlaptop` 37, `test_wfrozen` 26, `test_frozen` 61 (2 skipped), `test_runner` 63 (13
  skipped), `test_wrunner` 22 of 22; `wdeps.py` built nghttp2 release and asan with the desktop's
  compiler; a clone with a line naming the code commit as CHANGE_COMMIT passed the guard.
- Laptop-only (cannot run on the desktop, never skipped silently): `test_wrunner`'s
  `cycle_rate_reading` (pins CPU 14; the desktop has 12 logical CPUs, so it reports itself skipped);
  OpenSSL's build through `wdeps.py` (only nghttp2 was built on the desktop); the MSVC ASan record
  and `gate-W.json` (citable records are made on the laptop); every window.

### Laptop requests (group a of Papers `lab/laptop/bringup-w-p3p4.md`; one at a time; W)

Every job on the laptop's Windows, from a clone of one-port at this branch's commit named per job,
inside the lab runner (spec `boost` false, `quiet` true). Hours are estimates; the basis is named.

| Job | Runs | Commit | Estimate | Basis |
|---|---|---|---|---|
| a0 `w-read-1` | read only: OS build and UBR, BIOS, microcode, MSVC's ASan runtime (`clang_rt.asan_dynamic-x86_64.dll`, toolset 14.51) present, the copied files' sha256, and the TCP values (`TcpTimedWaitDelay`, `netsh int ipv4 show dynamicport tcp`, `... excludedportrange protocol=tcp`), which decide Lab request 4 before the probe | any | no measured basis; timeout 900 s | none |
| a1 `p3-deps-w` | `python bench\run\wdeps.py --work %LAB_OUT%\deps release asan`, `ONEPORT_VCVARS` = the Community `vcvars64.bat`; archives copied first into `C:\Users\alext\opt\src` from the desktop's checked copies | 63f5c74 (one clone for a1 to a3) | 1,291 s, timeout 3,900 s | desktop build logs 2026-10-03 (OpenSSL release 640 s, asan 591 s, nghttp2 32 s and 29 s), run serially here |
| a2 `p3-records-w` | `bench\records_job_w.ps1 -Out %LAB_OUT%\rec -Records %LAB_OUT%\rec\laptop-w -LabBin <the deployed Papers lab\bin, which holds inputs_hash.py>` (Release build, MSVC ASan record, `gate-W.json` from that folder alone); then each target's inputs hash compared with the desktop's `release.inputs.json` | 63f5c74 (its build serves a3) | 120 s, timeout 900 s | desktop job recw1, 2026-10-05 (120 s) |
| a3 `p3-probe-w` | only after a0's TCP reading: if it is not 30 s and start 1025 with 64,510 ports, Alex's admin step, a restart and a read-back come first (the probe entry's item 10). `python bench\run\wjob.py run --dir %LAB_OUT%\probe --name p3probe -- python bench\run\wprobe.py --build <a2's job dir>\out\rec\build-release --out %LAB_OUT%\probe\out --job p3probe --pilot lab\analysis-inputs\pilot.json`, spec `quiet` true and `boost` false (Lab request 1 landed in Papers d50a7ab: `LAB_QUIET=passed:<LAB_JOB_ID>`, so no `--allow-noisy`; the probe refuses a clone whose frozen paths differ from a4d8e89, a non-Release build and an unpinned host) | exactly 63f5c74: it holds item 10 and the R per host, and its `bench`, `tests` and `CMakeLists.txt` equal a4d8e89's; e61e78f and later change `bench/run`, which the probe refuses | windows 1,139 to 1,625 s, plus 13 session readings with no measured basis (each reads the frequency counter for 3 s, the cycle rate, and Defender and Update through PowerShell); timeout 5,000 s | windows: the proposal's section 4 (desktop window plus TIME-WAIT wait, M6b func2b; the 40 s cap); the laptop's own times are what the probe measures |
| a4 `p3-func-w` | after the move's entry: the suites above on the laptop (with `cycle_rate_reading` on CPU 14), CTest of the Release build, and the freeze night's runner checks wf1 to wf4 | the move's entry's commit | 1,541 s, timeout 4,700 s | desktop run 6, 2026-10-05 (status.md) |

Total a0 to a4: about 4,091 to 4,577 s (1.14 to 1.27 h) plus a0, which has no basis. W's
campaign itself waits for the move's entry; its hours come from the probe (draft item 12).

### First laptop block, 2026-10-23 (run by the coordinator's operator)

- a1 `p3-deps-w`: exit 0 (22:24 to 22:45). `wdeps.json`: clone 63f5c74, `cl` 19.51.36248, one line
  changed; OpenSSL and nghttp2, release and asan, each built (exit 0) into
  `C:\Users\alext\opt\<lib>-<version>-<flavour>`. Reusable: do not run it again (build_deps.ps1
  refuses an existing prefix).
- a2 `p3-records-w`: exit 1 (22:45 to 22:50). The Release build passed. The ASan record
  `oneport-63f5c742c-W-asan` is red: its CTest suite failed 3 of 165, with 0 sanitizer reports.
  Its inputs hashes equal the desktop's for all 10 targets. Two causes, both of the laptop's
  environment, not of the code:
  (1) `run.test_frozen` and `run.test_wfrozen` stop with `ModuleNotFoundError: No module named
  'numpy'`. CMake took `C:/Users/alext/AppData/Local/Programs/Python/Python314/python.exe`, which
  has no numpy; the analysis pins numpy 2.5.0.
  (2) `run.test_competitors`, `test_editing_an_input_changes_the_hash`, fails because the laptop's
  clone is checked out with CRLF endings (Git for Windows' `core.autocrlf=true`). The test turns
  each LF into CRLF and expects the same hash; a file that is already CRLF becomes CR CR LF. The
  desktop and L check out LF.
  Neither test can change: `bench/competitors` is a frozen path, and skipping the analysis tests
  would weaken the record.
- a3: not run.
- The rerun, as queue changes:
  - clone one-port with `core.autocrlf=false`;
  - a venv from Python 3.14.5 with numpy 2.5.0 (wheel `numpy-2.5.0-cp314-cp314-win_amd64.whl`,
    sha256 ebb81d9d5443e0309d6c54894c3fbed74ad7da0714352a67b6d773cd189eae73, PyPI's; the
    desktop's copy is in `C:\Users\alext\lab\p3\confirm1\dl`), activated in a2's command so that
    CMake's FindPython3 takes it;
  - a2 at 632b242, because `sanitize_oneport.ps1` line 50 refuses an existing
    `records-logs\oneport-63f5c742c-W-asan.tar.gz`. The other way is a2 at 63f5c74 again with the
    red run's logs moved aside first. The compiled inputs and pins are the same at both commits.
  - a3 stays at exactly 63f5c74, on a2's new build.
- Void journal lines of the operator's first rerun attempt: `p3-records-w-2` (exit 0, did nothing:
  a cmd `||` and `&&` grouping slip) and `p3-probe-w` (an a3 on a build folder that did not
  exist, failed after 18 s). Neither produced data.
- a2's second rerun, `p3-records-w-3` at 632b242 (2026-10-24, exit 1, 4 min 41 s; archive
  sha256 ca3a4991...): both earlier causes fixed (the venv's Python in both build caches; an LF
  checkout, lab fix 521be7d). The ASan record `oneport-632b24214-W-asan` is red again on one
  check: `run.test_wrunner`, `cycle_rate_reading`, ctest.log line 1921: `{'cycles_per_s': 0.0,
  'cycles': 0, 'wall_s': 0.50, 'cpu_s': 0.0, 'cpus': [14], 'spinner_exit': 0}`. Cause: the
  spinner was started with `sys.executable`, under CTest the venv's `python.exe`, which on
  Windows is a launcher that runs the base interpreter as a child process; the launcher, whose
  cycles and CPU time are read, only waits (shown on the desktop with a throwaway venv: the
  started process and the interpreter have different process ids). Fix, 786058e: the spinner
  runs on `wsys.base_python()` (`sys._base_executable`), also in `wfreq.py`; a test runs
  `cycle_rate` under a fresh venv and reads the spinner's cycles. The frozen runs read this rate
  in every session's reading (W's WL4 in time), so the fix guards them too.
- Rule for every W job from now on: start `wjob.py` and the W runners with the base Python
  (`LAB_PYTHON`), never a venv's `python.exe`. Under the launcher, `wjob.py stop` would set the
  stop event of the launcher's process id, not the runner's. The venv serves CTest alone.
- a2's third rerun, `p3-records-w-4` at 3ae481f (2026-10-24 00:59:28 to 01:04:37, exit 1; archive
  sha256 82e9b534...): the ASan record `oneport-3ae481faa-W-asan` is green (165 of 165 tests, 0
  sanitizer reports, MSVC 19.51.36248.0), and the Release build passed. The gate step failed in
  0 s: `bench/build_inputs.py` line 135 runs `ninja -C <build> -t compdb`, and gate.log ends in
  `FileNotFoundError: [WinError 2] The system cannot find the file specified`. The gate's cmd
  file (written by `records_job_w.ps1`, a frozen path) calls no vcvarsall, so the ninja that the
  release step had on PATH through vcvarsall is not there. The desktop had ninja on PATH
  globally. The overlap the coordinator disclosed (an scp of seven P2 archives at 00:59:14 to
  00:59:34 and a sha256 check of about 1 GB) played no part: the failure is a missing program,
  three minutes later, after the timing-sensitive tests had passed 165 of 165.
- Rule for every W job that runs `build_inputs.py` (the gate, and every frozen W runner through
  `wrunlib.job_provenance`): the folder of the ninja that built the Release build (Visual Studio
  Community's CMake\Ninja, which vcvarsall adds) first on PATH.
- Gate rerun, without a new record: `records_job_w.ps1 -Out %LAB_OUT%\rec -Records <p3-records-w-4's
  out\rec\laptop-w> -Only "release gate" -LabBin <deployed lab\bin>` from a clone at 3ae481f, with
  ninja on PATH. It builds a fresh Release build and gates it against the green record alone, so
  no record is made and the red attempts stay untouched; the old job's folder is only read.
  a3 then at exactly 63f5c74 on this job's build-release, under the base Python.
- Group (a) complete (2026-10-24, queue `gap3-w-q1-p3-gate.json`): `p3-gate-w-5` (gate only, at
  3ae481f) exit 0: gate passed and citable, records folder `...\p3-records-w-4\out\rec\laptop-w`,
  the one record `oneport-3ae481faa-W-asan.json` (green, 165 of 165, 0 reports, MSVC
  19.51.36248.0), all 10 targets covered, `wrunlib.laptop_gate_problems` finds none. The record is
  filed in Papers `lab/sanitizer-records/laptop-w/` (the only file there). Its logs
  (`C:\Users\alext\lab\records-logs\oneport-3ae481faa-W-asan.tar.gz`, sha256 8f3cf426...) come to
  the desktop's archive with their sha256 (D5). `w-gate-tcp-py-4` exit 0. `p3-probe-w-4` (the
  probe, at 63f5c74) exit 0, 01:25:23 to 01:52:39; its hours are in the draft's item 12 and TCP
  values in item 13.
- Earlier plan, now superseded by the green record: next a2 attempt at the docs commit after 786058e (after its push), so its record is named
  `oneport-<that commit's first 9>-W-asan` and the red attempts (`oneport-63f5c742c-W-asan`,
  `oneport-632b24214-W-asan`) and their logs stay untouched. a3 stays at exactly 63f5c74 (its
  probe code is unchanged; it runs under the base Python), on that attempt's build.

### Campaign jobs: a4 and block 1 (Alex approved the campaign 2026-10-24; entry pushed at 165c2dd)

Common to both: a one-port clone at 165c2dd with `core.autocrlf=false` (LF); spec `quiet` true,
`boost` false; `wjob.py` and every runner under `%LAB_PYTHON%` (the base 3.14.5, never the venv's
launcher); the folder of Visual Studio Community's ninja (`...\Common7\IDE\CommonExtensions\
Microsoft\CMake\Ninja`) first on PATH, since `wrunlib.job_provenance` runs `bench\build_inputs.py`;
the build and gate of `p3-gate-w-5` (`C:\lab\jobs\p3-gate-w-5\out\rec\build-release`,
`...\out\rec\gate-W.json`), which the frozen guard binds by each binary's sha256; `--tools` the
deployed Papers `lab\bin` (`C:\lab\src\Papers\lab\bin`). Each job's whole `out` folder is archived.

- a4 `p3-func-w`. Plain: the runners' tests on the laptop, then one short development session of
  the pilot runner, so block 1 starts on code proven on this host. Run, in `%LAB_SRC%`:
  `C:\Users\alext\lab\p3\venv-numpy\Scripts\python.exe` on `bench\run\test_wlaptop.py`,
  `test_wrunner.py` (its cycle-rate check runs on CPU 14 here), `test_wfrozen.py`,
  `test_frozen.py`, `test_runner.py`, then `-m pytest -q analysis`, each into its own log under
  `%LAB_OUT%`, stopping at the first failure; then `%LAB_PYTHON% bench\run\wjob.py run --dir
  %LAB_OUT%\smoke --name p3smoke -- %LAB_PYTHON% bench\run\wpilot_run.py --development
  --dev-seed 52317 --build <p3-gate-w-5 build-release> --out %LAB_OUT%\smoke\out --job p3smoke
  --tools C:\lab\src\Papers\lab\bin --only C1.W.IOCP.http1 --max-sessions 1 --timer-runs 4
  --split-replicates 1 --split-gaps 5`. Seed 52317 is in no journal line and no design file.
  Writes: the six suites' logs; `smoke\out` with development rows (never read for a value; their
  validity counts only). `expected_s` 900 (desktop: the suites about 3 min; one session about
  2.3 min, a warm-up 115 s and the short parts, from the probe's means), `timeout_s` 3,600.
- Block 1 `p3-pilot-w`. Plain: the A/A pilot of W's 12 cost cells on the laptop, 16 sessions each
  in dedicated mode, then its timer and split parts; the frozen run that sizes W's R. Run, in
  `%LAB_SRC%`: `%LAB_PYTHON% bench\run\wjob.py run --dir %LAB_OUT%\pilot --name p3pilotw --
  %LAB_PYTHON% bench\run\wpilot_run.py --build C:\lab\jobs\p3-gate-w-5\out\rec\build-release
  --out %LAB_OUT%\pilot\out --job p3pilotw --seeds design\seeds.json --code-freeze
  ff2679cc89d23e08a817308c9aeba7901e056fef --gate C:\lab\jobs\p3-gate-w-5\out\rec\gate-W.json
  --tools C:\lab\src\Papers\lab\bin`. The guard clears it only from this clone (last change
  6abd28e, the move's entry logged, the laptop's gate). Writes `pilot\out\windows.jsonl` (the
  sessions' rows) and `pilot\out\parts.jsonl` (the timer and split parts), which
  `analysis/pilot.py` reads with L's October pilot rows; also the provenance, the warm-up record
  and the raw folders. During the run only validity counts are read. `expected_s` 22,000 (the
  probe: 5.91 h of sessions plus at least 384 s of timer runs; the split part has no basis),
  `timeout_s` 66,000. Afterwards, on the desktop: `analysis/pilot.py --fixed-r L=28` at
  e61e78f's analysis code (no `analysis/` change since), then the new pilot entry, then block 2.

- Correction after a4 (`p3-func-w`, 2026-10-24 02:33 to 02:48, exit 1: the six suites passed; the
  smoke step stopped on `ModuleNotFoundError: No module named 'numpy'`, since `%LAB_PYTHON%` is the
  per-user 3.14.6 without numpy). Every runner and `wjob.py` run under `C:\Python314\python.exe`
  (3.14.5, a real interpreter, the venv's base), with `PYTHONPATH=C:\Users\alext\lab\p3\venv-numpy\
  Lib\site-packages` (numpy 2.5.0, built for this same interpreter) and `PYTHONNOUSERSITE=1`, in
  place of `%LAB_PYTHON%` in both commands above. The runners record only the Python version
  (`waa.provenance`), never its path or prefix; they do not call `analysis/versions.require`
  (only the analysis's command lines do, and it checks Python 3.14 and numpy 2.5.0, both met);
  `wsys.base_python()` is then the interpreter itself. a4 runs again as its smoke step alone
  (job `p3-func-w-smoke`, `expected_s` 600, `timeout_s` 2,400): the suites passed at 165c2dd.

### The new pilot entry (bcf74b4) and block 2 (2026-10-24)

Block 1 ran (journal lines 474 and 475): `p3-func-w-smoke` 03:25:45 to 03:30:43, exit 0;
`p3-pilot-w` 03:35:53 to 09:24:45, exit 0 (archive sha256 ba01c82f..., checked); 768 windows, 128
timer runs, 80 split replicates, every one valid, no rerun; all 976 rows name change_commit
6abd28e and head 165c2dd. Its 5.81 h against `expected_s` 22,000 (6.11 h): the probe's basis held.

- The simulation (desktop, 09:51:18 to 09:54:34, no timing): `analysis/pilot.py --fixed-r L=28
  --workers 11` from a fresh clone at e61e78f (`analysis_dirty` false), Python 3.14.5 and numpy
  2.5.0 (`C:\Users\alext\lab\p3\confirm1\venv`), on L's pl1 rows (from the October pilot archive,
  019c7986..., the rows' sha256 as entry 7455e28 names them) and the laptop's rows, with
  `lab/gates/gate-L.json` and the laptop's `gate-W.json` (96248c8f..., from `p3-gate-w-5`'s archive
  5a226ebc...). Output `lab/analysis-inputs/laptop-w/pilot.json`, sha256 d31d54cc...: R per host L 28,
  W 18 (pooled `R_C` 18, reported); m_C 31 (24 L, 7 W); W resolved 9, 11, 21, 22, 23, 24, 33; not
  resolved 34, 35 (C3.W.IOCP.tls, 0.582 at 31; resolved on the desktop), 36; cells 10 and 12 stay
  outside (their Power_c is 1.000 at every candidate on the laptop, 0.000 on the desktop; the
  move's entry, item 7, keeps them out); L's 24 cells' pass counts equal October's; joint power
  http1 on IOCP 0.7840 at 18; `G_W` 16 ms; `G_L` 4 ms and `GAP_SPLIT` 5 ms as in October.
- bcf74b4: the new pilot entry (revision log, "The new pilot entry, with W's pilot on the laptop's
  Windows", 13 items) and its output. Checks at bcf74b4 in a fresh clone (desktop, no timing):
  `freeze_guard.check` with the new pilot output and `wrunlib.ENTRIES` clears (pilot logged in
  bcf74b4, change_commit 6abd28e); with October's `rule_e.json` it refuses (logged in 77cedae,
  not after bcf74b4); `test_wlaptop` 41, `test_wfrozen` 26, `test_frozen` 61 (2 skipped) passed.
  The guard reads the log only in UTF-8 mode (the cp1252 bug of section 2); the entry adds no byte
  that cp1252 cannot decode.
- Rule E comes first (the move's entry, item 14; section 8 rule E): every W runner of the cost,
  M1, hard-case and section 10 jobs takes `--rule-e`, and the guard clears that file only if its
  sha256 was first logged after the pilot entry's commit, or, from d22ae16 on, is logged again
  inside the entry "Rule E's choices on the laptop's Windows" after it. So block 2 is 2a (rule E's
  sessions), a desktop step D (the decision and its entry), then 2b.
- The open point on rule E's file (the laptop keeping October's choices, so October's bytes, sha256
  fb50302a..., first logged in 77cedae, before bcf74b4) is closed by Alex's option (a) of
  2026-10-24; option (b), committing CRLF bytes (42299c5d...) to change the hash, is rejected. The
  analysis reads rule E's file and the pilot output by content only (`analyse.py` binds no row to
  their sha256). `--blocks`: `wpilot_run.py` opened the same default file in block 1, so the
  default stands.
- The guard's change (a later change under section 8), entry "Rule E's file logged again after the
  new pilot entry (a later change under section 8)": db52adc (items 1 to 7, committed before the
  code), code 2244a6e, then d22ae16 (the review's fixes), item 8 in 1afcf90 (CHANGE_COMMIT
  d22ae16b8fa5a8fbda5c0b2bbff737241757c8d5, and the corrections). `freeze_guard.py`: rule E's file
  whose sha256 was first logged by a commit that does not come after the pilot entry's is cleared
  only if a commit after it (never a merge) adds a line with "rule E" and the whole sha256 inside an
  entry headed "Rule E's choices on the laptop's Windows" (`RULE_E_LAPTOP_ITEMS`), and HEAD holds
  more such lines than the pilot entry's commit; the clearance names that commit `logged_in` and
  the first logging `first_logged_in`. The pilot output's and M2_RATE's checks are unchanged.
  Python under `bench/run` alone (`freeze_guard.py`, `test_frozen.py`, `test_wlaptop.py`); no
  compiled file, so the laptop's record and `gate-W.json` stand. The entry names no sha256 in full,
  so that it cannot clear October's file itself (a test checks it).
  - Review (fresh Opus agent, given the diff, the entry and the problem text only): 0 CRITICAL;
    1 HIGH, fixed in d22ae16: any later line with "rule E" and October's whole sha256 (a stray
    quote in any later entry) would have cleared that file before the decision, so the line counts
    only inside the entry headed with the title (item 8 (a)); 3 MEDIUM: the real-history test chose
    its state with the function it tests and read the file at HEAD (fixed: it always starts on a
    branch at bcf74b4 with October's bytes read from bcf74b4, and at HEAD accepts a refusal or a
    clearance by a commit after the last change's that holds the rule E entry), a rewrite of the
    file at HEAD would confuse it (fixed by the same), a CRLF checkout refuses the intended case
    (a refusal, never a wrong clearance; block 2's clones are LF; item 8 (f)); 5 LOW, all taken:
    `--no-merges` stated, item 3 (b)'s "still there" overstated (item 8 (c)), the partial-hash test
    is a regression guard (item 8 (d)), the UTF-8 mock only where the locale is cp1252, docstring
    and the 7-character commits (item 8 (g)). Mutation runs on the desktop: removing any one new
    check fails a test, except `--no-merges`, which states git's default for `-S`.
  - Checks (desktop, no timing; fresh LF clone at 1afcf90; the guard in UTF-8 mode, with the
    laptop's `gate-W.json` 96248c8f... from `p3-gate-w-5`'s archive, checked): the guard clears with
    the new pilot output and `wrunlib.ENTRIES`, `change_commit` d22ae16; with October's rule E file
    it refuses (first logged in 77cedae, no line in the rule E entry); a throwaway clone with one
    commit (002dfe3, never pushed, no remote) adding the rule E entry's heading and October's whole
    sha256 clears it, `logged_in` 002dfe3, `first_logged_in` 77cedae. Suites from that clone, in
    UTF-8 mode: `test_wlaptop` 43, `test_wfrozen` 26, `test_frozen` 67 (2 skipped), `test_wrunner`
    22 of 22 (`cycle_rate_reading` laptop-only), `test_runner` 63 (13 skipped). Under Windows'
    cp1252 locale without UTF-8 mode, `test_wlaptop`'s older `test_probe_commit_from_item_9` errors
    at every commit (line 418 of the frozen text holds bytes cp1252 cannot decode, the guard's known
    bug); the new real-history test handles both modes.

Common to every block 2 job: a one-port clone with `core.autocrlf=false`; spec `quiet` true,
`boost` false; the command prefix of block 1 (`cd /d "%LAB_SRC%" && set "PATH=C:\Program
Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;
%PATH%" && set "PYTHONPATH=C:\Users\alext\lab\p3\venv-numpy\Lib\site-packages" && set
"PYTHONNOUSERSITE=1" && `), `wjob.py` and the runner on `C:\Python314\python.exe`; and the
frozen arguments F = `--build C:\lab\jobs\p3-gate-w-5\out\rec\build-release --seeds
design\seeds.json --code-freeze ff2679cc89d23e08a817308c9aeba7901e056fef --gate
C:\lab\jobs\p3-gate-w-5\out\rec\gate-W.json --pilot lab\analysis-inputs\laptop-w\pilot.json --tools
C:\lab\src\Papers\lab\bin` (`--blocks` at its default, as in block 1). `expected_s` from the
probe's means (the move's entry, item 12: churn 34.01 s, open loop 34.06 s, keep-alive 9.09 s a
window, 7.27 s a session's reading, 114.5 s a job's warm-up), reruns not counted; `timeout_s` three
times that, rounded up to 100 s. Each job's whole `out` folder is archived.

- 2a `p3-rule-e-w`, commit bcf74b4, after push 1. Ran (coord., 2026-10-24): exit 0, its command
  10:50:25 to 11:07:00 by `record.json`, the job's end 11:08:30 (coord.); archive
  `C:\Users\alext\lab\laptop-archive\gap6-w-q2-p3-rule-e-607076e4\p3-rule-e-w.tar.gz`, sha256
  5a0d5f09cbac058884ac68cb50e3e90eab832c5bdb18c99c3786f525dd7516f9, checked; 24 windows, every one
  valid, 6 valid sessions, no rerun; every row names change_commit 6abd28e. The evidence keeps replay
  on IOCP (peek over replay 0.928 to 0.941 per session; operations per connection 6.02 against
  4.02). Plain: rule E's 6 development sessions of
  HTTP/1.1 churn on the laptop's IOCP, replay against peek, which decide W's default detection
  mode. Run: prefix, then `C:\Python314\python.exe bench\run\wjob.py run --dir "%LAB_OUT%\rule"
  --name p3rulew -- C:\Python314\python.exe bench\run\wrule_e.py --out "%LAB_OUT%\rule\out" --job
  p3rulew --dev-seed 73619` F. Development seed 73619: in no line of Papers `lab/journal.jsonl`,
  no tracked Papers file, no `design/*.md` and not `hypotheses.md` before this line (checked
  2026-10-24). Writes `rule\out\rule_e_evidence_W.json` (what `decide` reads), `windows.jsonl`
  (development rows), provenance, plan, summary, warm-up and raw folders. Outputs `out/rule/out/
  rule_e_evidence_W.json`, `out/rule/out/windows.jsonl`, `out/rule/out`, `record.json`.
  `expected_s` 975 (6 sessions of 143.31 s plus the warm-up), `timeout_s` 3,000.
- D, on the desktop (no timing), done 2026-10-24: 2a's archive checked (above) and extracted into
  a fresh scratch folder; L's evidence `rule-e-L/rule_e_evidence_L.json` (6787824f..., checked) from
  `p3-raw-2026-10-05-re1-wre1-ff2679cc8.tar.gz` (8f9a93b4..., checked against its `.sha256` and
  `lab/archives.sha256`); `rule_e.py decide` from a fresh LF clone at 1afcf90, run unchanged
  through a scratch wrapper that makes `Path.write_text` write LF (no CRLF file was made): replay
  on every backend, user-space relay buffers, the zero-byte form, so October's choices, and the
  file is byte for byte `lab/analysis-inputs/rule_e.json` (sha256 fb50302a..., 0 CR bytes). RE =
  5091d9f69b9456238872734a02f63ded2322a7b5: the entry "Rule E's choices on the laptop's Windows"
  (4 items; the one line with "rule E" and the file's whole sha256; the evidence by sha256) and
  `lab/analysis-inputs/laptop-w/rule_e.json`. RE descends from the guard's change (d22ae16) and
  its item 8 (1afcf90). Check in a fresh LF clone at 5091d9f (guard in UTF-8 mode, the laptop's
  `gate-W.json`): `freeze_guard.check` with `--rule-e lab/analysis-inputs/laptop-w/rule_e.json`,
  the new pilot output and `wrunlib.ENTRIES` clears; `rule_e.logged_in` 5091d9f,
  `first_logged_in` 77cedae, `change_commit` d22ae16; `test_wlaptop` 43 and `test_frozen` 67 (2
  skipped) pass there.
- `p3-guard-w`, after push 2 and before 2b, at RE 5091d9f (or the branch's later docs commit; both
  hold the change). Plain: the freeze guard's changed tests and the other runner suites on the
  laptop's Windows, and a check that the clone's rule E file has the committed LF bytes, so block
  2b starts on a guard proven on this host. Run: prefix, then `set "PYTHONUTF8=1" &&
  C:\Python314\python.exe bench\run\test_frozen.py > "%LAB_OUT%\test_frozen.log" 2>&1 &&
  C:\Python314\python.exe bench\run\test_wlaptop.py > "%LAB_OUT%\test_wlaptop.log" 2>&1 &&
  C:\Python314\python.exe bench\run\test_wfrozen.py > "%LAB_OUT%\test_wfrozen.log" 2>&1 &&
  C:\Python314\python.exe bench\run\test_wrunner.py > "%LAB_OUT%\test_wrunner.log" 2>&1 &&
  C:\Python314\python.exe bench\run\test_runner.py > "%LAB_OUT%\test_runner.log" 2>&1 &&
  C:\Python314\python.exe -c "import hashlib,sys; d=hashlib.sha256(open(r'lab\analysis-inputs\laptop-w\rule_e.json','rb').read()).hexdigest(); print(d); sys.exit(d != 'fb50302aa4e42fc453e7230ed6472e0010f7ac98f1fab96b3daf7ead5ca2dec5')"
  > "%LAB_OUT%\rule_e_sha256.txt" 2>&1`, all on one line, stopping at the first failure. Spec
  `quiet` true, `boost` false, an LF clone (`core.autocrlf=false`), the block 2 prefix (VS ninja
  first on PATH, `PYTHONPATH` the venv's site-packages, `PYTHONNOUSERSITE=1`); `PYTHONUTF8=1` is
  set in the job's own process only (the guard's cp1252 bug; W's frozen runs use UTF-8 mode). It
  times nothing and needs no build. Writes the six logs under `%LAB_OUT%`. Expected on the laptop:
  `test_frozen` 67 checks (2 skipped), `test_wlaptop` 43, `test_wfrozen` 26, `test_wrunner` 22 of 22
  with `cycle_rate_reading` run on CPU 14, `test_runner` 63 (13 skipped), the sha256 fb50302a....
  `expected_s` 180 (desktop, this session: the five suites 59 s; plus the cycle-rate reading and
  the clone), `timeout_s` 900. Its result goes here before 2b.
- 2b, each at RE 5091d9f (or a later commit of this branch whose frozen paths equal d22ae16's), in
  this order (the move's entry, item 14), after push 2 and `p3-guard-w` exit 0:
  - `p3-cost-w`. Plain: the cost family on the laptop's Windows, W's 10 cost cells, one-port against
    dedicated mode, 18 sessions each; the confirmatory runs of the 7 resolved cells. Run: prefix,
    `C:\Python314\python.exe bench\run\wjob.py run --dir "%LAB_OUT%\cost" --name p3costw --
    C:\Python314\python.exe bench\run\wcost_run.py --out "%LAB_OUT%\cost\out" --job p3costw` F
    `--rule-e lab\analysis-inputs\laptop-w\rule_e.json`. Writes `cost\out\windows.jsonl`,
    `not-run-p3costw.json` (cells 10 and 12), provenance (with R 18), plan, summary, warm-up, raw.
    Outputs `out/cost/out/windows.jsonl`, `out/cost/out`, `record.json`. `expected_s` 18,750
    (1,035.18 s per unit of R: 2 churn, 4 keep-alive and 4 open-loop cells; times 18, plus the
    warm-up), `timeout_s` 56,300.
  - `p3-m1-w`. Plain: M1 on the laptop's IOCP, replay against peek in one-port mode, HTTP/1.1 and
    h2c churn, 16 sessions each. Run: prefix, `C:\Python314\python.exe bench\run\wjob.py run --dir
    "%LAB_OUT%\m" --name p3m1w -- C:\Python314\python.exe bench\run\wm_run.py --out
    "%LAB_OUT%\m\out" --job p3m1w` F `--rule-e lab\analysis-inputs\laptop-w\rule_e.json`. Writes
    `m\out\windows.jsonl` (which `p3-s10-w` reads), provenance, plan, summary, warm-up, raw.
    Outputs `out/m/out/windows.jsonl`, `out/m/out`, `record.json`. `expected_s` 4,700 (32 churn
    sessions of 143.31 s plus the warm-up), `timeout_s` 14,100.
  - `p3-hard-w`. Plain: the hard cases on the laptop's IOCP, B1's table and B2's checks in replay
    and in peek, 16 replicates per case, with `G_W` 16 ms and `GAP_SPLIT` 5 ms. Run: prefix,
    `C:\Python314\python.exe bench\run\wjob.py run --dir "%LAB_OUT%\hard" --name p3hardw --
    C:\Python314\python.exe bench\run\whardcase_run.py --out "%LAB_OUT%\hard\out" --job p3hardw` F
    `--rule-e lab\analysis-inputs\laptop-w\rule_e.json`. Writes `hard\out\hardcases.jsonl`,
    `hardcases-table-p3hardw.json`, provenance, raw. Outputs `out/hard/out/hardcases.jsonl`,
    `out/hard/out`, `record.json`. `expected_s` 1,500 (no probe basis: the desktop's wh1, 1,475 s,
    the move's entry, item 12), `timeout_s` 4,500.
  - `p3-s10-w`. Plain: section 10's 9 W cells on the laptop, SSH C1 to C3, the mixed cell, TLS with
    ALPN h2, the two IOCP forms and M1's TTFB at a fixed load, 16 sessions each. Run: prefix,
    `C:\Python314\python.exe bench\run\wjob.py run --dir "%LAB_OUT%\s10" --name p3s10w --
    C:\Python314\python.exe bench\run\ws_run.py --out "%LAB_OUT%\s10\out" --job p3s10w --m-rows
    C:\lab\jobs\p3-m1-w\out\m\out\windows.jsonl` F `--rule-e
    lab\analysis-inputs\laptop-w\rule_e.json`. Only after `p3-m1-w` exit 0 (never the desktop's
    `m-W`). Writes `s10\out\windows.jsonl`, `not-run-p3s10w.json` (the 2-core cell, TLS
    resumption), `ssh-rates-p3s10w.json`, provenance, plan, summary, warm-up, raw. Outputs
    `out/s10/out/windows.jsonl`, `out/s10/out`, `record.json`. `expected_s` 19,170 (5 churn, 3
    open-loop and 1 keep-alive cell by 16 sessions, plus the warm-up), `timeout_s` 57,600. SSH C2
    is expected to fail every window, as in October (the keep-alive SSH defect), and to spend its
    rerun cap of 4.
- Hours. 2a 0.27 h; 2b 12.25 h (cost 5.21, M1 1.31, hard cases 0.41, section 10 5.32); block 2
  12.52 h, 0.64 calendar days at 19.68 h a day (2a 0.01, 2b 0.62). At most 13.25 h if every
  keep-alive session waits the full 30 s (88 sessions). Campaign: block 1 5.98 h by the journal
  (03:25:45 to 09:24:45; 6.1 h to the archive at 09:42) plus 12.52 h is 18.50 h (18.62 h with
  6.1), at most 19.35 h; inside Alex's 16.5 to 22.3 h. The move's entry's 21.41 h was at R = 28;
  at R = 18 its formula gives 18.54 h.
- Pushes (Alex's yes, through the coordinator): push 1, `laptop-w-bringup` 165c2dd to bf71179,
  done (the new pilot entry's public timestamp before rule E's one-port windows); push 2, approved,
  the coordinator makes it before `p3-guard-w` and 2b: bf71179 to this branch's tip (db52adc,
  2244a6e, d22ae16, 1afcf90, RE 5091d9f and the STATE commit after it).
- Later, not now: `paper/design_macros.py`'s W patterns (λ, `G_W`) and `CHANGE_COMMIT` now match
  more than once in the log; the writing pack takes W's values from this entry. `lab/README.md`
  does not list `analysis-inputs/laptop-w/` yet.

### Lab requests (the coordinator makes them; this session touches nothing in Papers `lab/`)

1. Done (Papers d50a7ab, 2026-10-23). `lab/laptop/win/labjob.py` and `labjob_inner.py` (run phase): drop any `LAB_QUIET` the job's
   environment inherits (`job_env` copies `os.environ`), and set `LAB_QUIET=passed:<LAB_JOB_ID>`
   only after the job-start quiet check passed (never when the spec sets `quiet` false); also
   `LAB_PHASE=run`. P3's frozen W runs need it: without that exact value `wjob.py` refuses the job
   (exit 90) unless `--allow-noisy`, which makes it a functional check, and every frozen W runner
   refuses a functional check. The power plan needs no labrun change: from b20f415, P3's runners
   only verify the lab plan inside a lab job and refuse every switch there (boost must be off).
   Note for the probe's job: the lab sampler records every process's CPU share every 10 s, so the
   job's `samples.jsonl` holds the server's and generator's shares during windows; the probe's
   entry (item 9) says no value of it is read, so collect it but read only host readings and the
   job-start checks from it.
4. If a0 shows TCP values other than the design's (30 s; start 1025 with 64,510 ports): an administrator script
   for Alex, as `alex-admin.ps1`, that sets `TcpTimedWaitDelay` = 30 (REG_DWORD under
   `HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters`) and the IPv4 TCP dynamic range to
   start 1025, 64,510 ports (and IPv6 the same, as on the desktop), reads both back, records the old values and can undo them; then a
   restart of Windows and a read-back job before the probe (the probe's entry, item 10). Recorded
   in `lab/laptop/setup-log.md`.
2. A folder `lab/sanitizer-records/laptop-w/` for P3's laptop record (a2) and its gate, apart
   from the desktop's `oneport-ff2679cc8-W-asan.json`; the coordinator copies a2's records there.
3. Before a1: the two archives (`openssl-3.5.9.tar.gz`, `nghttp2-1.70.0.tar.xz`) from the desktop's
   `C:\Users\alext\opt\src` (sha256 equal to `bench/cmake/pins.cmake`) to the laptop's
   `C:\Users\alext\opt\src`, checked again there. Desktop-only launch files (`m6b\wlaunch.ps1`,
   `chain.py`) are not needed: labrun starts `wjob.py` itself.

### Alex decides

Pending, asked in his format only when it arises:
1. After job a0, and only if it reads TCP values other than 30 s and start 1025 with 64,510 ports: the
   administrator step that sets them (his own run, like `alex-admin.ps1`, a restart, a read-back),
   before the probe.

Answered (Alex, 2026-10-24, relayed by the coordinator): how rule E's file passes the guard when the
laptop keeps October's choices: option (a), a later change of `freeze_guard.py` (the guard accepts
rule E's file whose sha256 is logged again in the entry, made after the new pilot entry, that
records the new decision and its evidence); option (b), the CRLF file, rejected. Both pushes
approved: the pilot entry's, done to bf71179; the rule E entry's, before 2b, which the coordinator
makes (it carries the guard's change, its entry and RE 5091d9f).

Alex's laptop-plan decisions of 2026-10-23 (relayed by the coordinator): D1, no Arch package
upgrades until P4's Arch blocks end, extra versions side by side under `~/opt`. It touches P3 only
if the kernel census runs on L before then, on the present packages. D4 (P4's idle day) does not
touch P3.

Answered (Alex, 2026-10-24, about 02:05, relayed by the coordinator): P3's Windows campaign as
planned, about 21.4 h in two blocks with R by the frozen rule; and the push of the section 8
entry ("W's runs on the laptop's Windows", logged 2026-10-24) to `laptop-w-bringup` before the
first window.

Answered (Alex, 2026-10-24): push 723d784..3ae481f (the a2 fix 786058e and docs) to
`laptop-w-bringup`: yes; pushed to 3ae481f.

Answered (Alex, 2026-10-23):
- Push `laptop-w-bringup` to the public repository: yes; pushed to 6c7be67, then to 632b242.
- The R_C conflict: option (i), R per host in `analysis/` (8815d89, e61e78f).
- The frequency counter on the laptop: not tested.
- The laptop's TCP settings: set to the design's values if they differ, else documented (the
  probe entry's item 10).

The probe's computed hours are laptop time: the coordinator states them to Alex with the other
papers' requests (Laptop requests above; the move's entry, draft item 12).

## 1. Where P3 stands

Code frozen at ff2679c; A/A pilots done on L and W; pilot entry, rule E and M2_RATE logged; the
confirmatory runs are under way. L: cost family, hard cases' server part, mechanism family and B3
(feasibility windows, K_BASE, sessions) done and archived; section 10 stopped after 384 windows
(sl1) on the B1 counting defect. The B1 change is committed (fix 9cae2de, entry 9830457, a later
change under section 8): sl1 is archived as evidence only (moved to `~/lab/p3/evidence/`) and
section 10 runs again from its start. On L that is the chain pc2: sl3 ended 2026-10-07 11:23:38
(exit 0) and is followed up (status.md "L's section 10 job sl3": 2,548 rows, 31 of 38 cells at R = 16,
7 cells with no valid session: sslh-ev's four, SSH C2's two and the mixed cell on io_uring; the mixed
cell on epoll valid, 16 of 16), then the competitors' table hc1 (11:23:38 to 18:47:43, `pc2.done`
exit 0; followed up: status.md "The competitors' table hc1": 8,052 case rows, 7,977 observed, 75 not
observed, a descriptive table); on W, ws1
ended 2026-10-07 07:00:37 (exit 0) and is followed up (status.md "W's section 10 job ws1": 600 rows,
8 of 9 cells at R = 16, SSH C2 with no valid window, the mixed cell valid). W: cost family (wc1, stopped at Alex's request, then wc2), M1's IOCP cells
(wm1) and hard cases on IOCP (wh1) ended 2026-10-06 02:53:16 (wc2, wm1 and wh1 exit 0); the
follow-up is done: every W cell reached its R, the three invalid windows are in status.md, the
hard cases all passed, each out directory archived and journaled; W has no job left (ws1 is done
and followed up, archived and journaled). Freeze order (hypotheses.md section 8): steps 1
to 6 done (hypotheses freeze 64a23f7, engineering, CODE_FREEZE, A/A pilots, simulation, pilot
entry). Step 7: rule E, M2's rates, B3 feasibility windows and K_BASE's windows done; confirmatory,
secondary, hard-case and descriptive runs done and followed up. The frozen analysis ran on W on 2026-10-07
from every confirmatory row file (status.md "The confirmatory analysis on W, 2026-10-07"); its
`summary.json`, `decisions.csv` and `provenance.json` are in `results/` (e5e6724). After the TeX
escaping of `analysis/macros.py` (a later change, ANALYSIS_COMMIT 2045551) `results/macros.tex` is
committed (f4ad14e); B1's and B2's macros (`results/hardcase-macros.tex`) and the cells not run or
short of R (`results/not-run.json`) are committed (5cc0cb2); the competitors' counts joined
`results/hardcase-macros.tex` after hc1's follow-up. Then the paper. On 2026-10-08 the four
descriptive outputs the results half lacked (B2's distributions, operations and copies per
connection, the proxies' system calls, the counter check) were produced: two from archived rows,
the rest from the untimed lab job st1 on L (06:02:43 to 06:14:09, exit 0, 66 rows), under the
revision-log reading of that date.

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
- ANALYSIS_COMMIT = 204555104f0191152d1f4bf392d2a76b0aebc1b5 (entry "The macros' TeX escaping (a
  later change under section 8)", item 6, 0126ca2; replaced 9de26d6 of 2055e63, which replaced
  7364fbb). It differs from 9de26d6 in `analysis/macros.py` and `analysis/test_analyse.py` alone;
  `analyse.py` and its imports are 9de26d6's, whose tree is bf77349b; the pilot ran at 9de26d6.
  Suite at 2045551 on W: 73 passed, 2 skipped. numpy 2.5.0 and Python 3.14.7 in L's venv `~/opt/analysis-numpy-2.5.0/venv` (wheel sha256
  39a0433b..., PyPI's). On W: `C:\Users\alext\lab\p3\confirm1\venv`, numpy 2.5.0 from the
  win_amd64 wheel (sha256 ebb81d9d..., PyPI's) on Python 3.14.5.
- The confirmatory analysis (2026-10-07, on W, clone 7c1310a, run twice, byte-identical):
  `results/summary.json` a94b4bde0eddf2a7ef8bbc16de0e1a256a10a4f5ed64d99ea8d841d5c8bb9af8,
  `results/decisions.csv` 6752c68e472f83379e913a4442a187bbd6bb67f47bf0d5ef0e25577d132c753f,
  `results/provenance.json` 7490b9fb337064a043eb11f130f92d884f21d464fa94ec2ccdfa886b3dbec88c;
  the held-back `macros.tex` cb5e16e7 (on W in `confirm1\out1`). Nothing is run again to change a
  decision (section 13).
- After the escaping (status.md "The macros' TeX escaping and B1's and B2's macros"):
  `results/macros.tex` 408b8ac2d31f863f09d46240e9d54b602d92917402512751b2e4506327048992 (2,168
  macros; six lines differ from cb5e16e7); `results/macros-provenance.json` (ac9daf1; both hosts'
  reruns: W's `decisions.csv` byte-identical and `summary.json` only `versions.analysis_commit`
  apart; L's `macros.tex` byte-identical, its `summary.json` and `decisions.csv` apart from W's in
  floats of at most 1.1e-16 and in `versions.python`, no decision apart);
  `results/hardcase-macros.tex` 9c9e0f38555331cfbba8696220676aca7cde8355c9e1f91819c5d00a65985e28
  (`paper/hardcase_macros.py`; B1 and B2 hold; 235
  macros: the 26 of B1 and B2, byte for byte as in 377a1fa2, and 209 `CompCase...` macros of hc1's
  descriptive table, from `competitor_cases.jsonl` c13b5fd21e0d1d34a69c3927b4a1a2e25cecfb52cde17859c164db6aeeb02f92);
  `results/not-run.json`
  04683cff7002d57117cc417b6e9e418d45625a84bb10e40e8b7dbe8a5f8c1bb6 (`paper/not_run.py`, 19 cells).
- Section 10's four descriptive outputs (2026-10-08; status.md, that section, item 5):
  `results/b2-macros.tex` efa39518d32cf3435f0dc1a80bc97fdaec5ba01e53eabc9305961d79f01c073c,
  `results/ops-macros.tex` 7c682e7a3abdcd5876336cec61dc48f90181a024f570bed99b18c1b6de21c669,
  `results/trace-macros.tex` eda07772f5bf090e7dc78b07504dc5d69544b01d9bc97c72682e885934b09a38; st1's
  `trace.jsonl` 9b0d1d0e8eb8ed9559454255ab264deadd408adacb2061420487bf52eba13200.
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
| 10-07 | The macros' TeX escaping (a later change under section 8) | 90e5138, 0126ca2 | entry before the fix 2045551, item 6 after it: ANALYSIS_COMMIT 2045551; text values TeX-escaped; no decision moves; checks on W and L defined before they ran |
| 10-07 | B1's and B2's decisions from the hard-case runners' outputs (a reading) | 18f97a8, 4ca64bb | B1's hard-case part and B2 read from the runners' rows and tables (not `analysis/`); `paper/hardcase_macros.py` writes them; item 6 after its review |
| 10-08 | Section 10's four descriptive outputs not yet reported, and their untimed windows on the frozen build (a reading) | bd9a720 (item 7 with the outputs' commit) | B2's distributions from hl1 and wh1; WL5 from the cost and M1 windows; the relay's two detection modes, the proxies' system calls and the counter check from st1 (frozen `systrace.py` after the guard, called by a wrapper outside the repo); its rows' `development` true is the runner's constant (item 5 (ii), for Alex to confirm); item 7 lists the descriptions added after the values were seen |

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
- 2026-10-05: W's section 10 run (ws1) waits for the B1 fix (coord.). The fix is in; ws1 ran in
  `m7g\wsfix` on 2026-10-07 (section 4).

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
| Section 10 | L | sl1; sl3 | `s-L` | sl1 stopped 17:53:12 (exit 143), 384 windows, 331 valid; archived (partial; sha256 checked again 2026-10-07); journaled (and the evidence-only line). Under the B1 change: evidence only, never used; moved to `~/lab/p3/evidence/s-L-sl1-b1count`. sl3 (section 10 from its start) ran inside the chain pc2 (job pid 1196837, clone `m7g/post-src8` at 29ae2b6): 2026-10-07 06:55:27 to 11:23:38, exit 0 (`== sl3 exit 0, 16091 s` in `pc2.log`; no `sl3.pid` or `sl3.done`); 2,548 rows in 637 sessions (608 base, 29 reruns), 2,147 valid windows, 496 valid sessions; 31 of 38 cells reached R = 16; 7 cells ended with no valid session after the 4 reruns of their cap (sslh-ev's four cells, S.ssh.C2.L.epoll and S.ssh.C2.L.io_uring, S.mixed.C1.L.io_uring); S.mixed.C1.L.epoll has 16 valid sessions, `misclassified` 0 in all 32 of its one-port windows (and 0 in the 40 of the io_uring cell); one other invalid window (S.two-cores.C1.L.epoll.reuseport.s16, rerun once, valid); not run on L: TLS resumption (2 cells); every row names `change_commit` 9cae2de and `check_rows.py` binds all 2,548 to `gate-L.json`; archived (`~/lab/p3-raw-2026-10-07-sl3-ff2679cc8.tar.gz`, sha256 0f289133058a8e80bba2a8cec202daed815871c11ece340f4bd3fe42476938af; copy on W in `C:\Users\alext\lab\`, checked there); journaled (line 162) |
| Section 10 | W | ws1 | `s-W` | done: 2026-10-07 02:12:32 to 07:00:37, exit 0 (chain `m7g\wsfix`, clone `m7g\ws-src1` at 29ae2b6; 2 refusals before it, one per launch); 600 rows in 150 sessions (144 base, 6 reruns), 517 valid windows, 128 valid sessions; 8 of 9 cells reached R = 16; S.ssh.C2.W.IOCP ran its 16 sessions and the 4 reruns of its cap with no valid window (opgen exit 2, the logged keep-alive SSH defect), so 0 of 16; the mixed cell is valid (64 of 64 windows; not invalid by the generator rule as expected); 3 other invalid windows (one in M1 HTTP/1.1, two in C3 SSH, each session rerun once); not run on W: TLS resumption, 2-core; every row names `change_commit` 9cae2de and `check_rows.py` binds all 600 to `gate-W.json`; archived (`C:\Users\alext\lab\p3-raw-2026-10-07-ws1-ff2679cc8.tar.gz`, sha256 966ce1c61a547241e86da4d5c04ce136c3a193e5a59a121a1f8684e5bbbc2766); journaled (line 161) |
| B3 feasibility (development) | L | bf1 | `b3feas-L` | done: 21 windows, 20 valid; archived (`p3-raw-2026-10-05-bf1-ff2679cc8.tar.gz`, sha256 d7c25c16a849f53ffe9ea76c49aad14a111eeaf20e1620bf5c4a8cce752fe0bd); journaled |
| K_BASE | L | bk1 | `b3-L` | done: 17 windows, 16 valid (window 1 TIME-WAIT); archived with bs1; journaled |
| B3 sessions | L | bs1 | `b3-L` | done 2026-10-07 01:29:57, exit 0: 2,628 windows in 657 sessions (49 reruns), 2,578 valid, 50 invalid (44 TIME-WAIT at both samples, 5 at sample 2 only, 1 not settled); 37 of 38 cells reached R = 16; B3.partial-hello.cmux.epoll ended at 15 valid after its 4 reruns (the cap), no treatment proposed; archived with bk1 (`p3-raw-2026-10-05-bk1-bs1-ff2679cc8.tar.gz`, sha256 3bb796bb9894403505dd49ff026b53c4b1ddd95bcc6876a4cdd0c9473b6106a8); journaled; rows carry no `change_commit` (ran from d29968b) |
| Section 10's untimed windows | L | st1 | `st-L` | done: 2026-10-08 06:02:43 to 06:14:09, exit 0 (`st1.done`); clone `m7g/st-src1` at fe65818; `st_guard.py` cleared it (change_commit 9cae2de); 33 `systrace.py` calls, each exit 0, 66 rows (48 cost rows: the 24 cost cells of L in both modes; 12 rows of the five proxies and the relay on epoll; 6 rows of the relay on io_uring and in peek); perf stat equals the counters in all 360 cost checks and 60 relay checks; archived (`~/lab/p3-raw-2026-10-08-st1-ff2679cc8.tar.gz`, sha256 6aadecd3bd4a0f44930f3d924fbf953250d7b885690db3e2a4fc0d15f61806a1; copy on W in `C:\Users\alext\lab\`, unpacked in `confirm1\unpacked\st1`); journaled (line 167) |
| Competitors' table | L | hc1 | `hardcomp-L` | done: second step of pc2, clone `m7g/post-src9` at 29ae2b6; 2026-10-07 11:23:38 to 18:47:42, exit 0 (`== hc1 exit 0, 26644 s` in `pc2.log`; `pc2.done` exit 0 at 18:47:43); 8,078 lines in `competitor_cases.jsonl` (sha256 c13b5fd2...): 8,052 case rows, 7,977 observed, 75 not observed (opcase did not end), 26 start rows all ok; of the observed rows 3,327 have a reply equal to what the server's frozen table expects and 4,650 do not, a descriptive field that decides nothing; 9 systems, 164 variants, 25 cases; every row names `change_commit` 9cae2de and `check_rows.py` binds all 8,078 to `gate-L.json`; archived (`~/lab/p3-raw-2026-10-07-hc1-ff2679cc8.tar.gz`, sha256 7df1d9af5396f8d24d0fc5edb93f438054a3670f25250b38cb851d0f93120629, with the whole `pc2.log`; copy on W in `C:\Users\alext\lab\`, checked there); journaled (line 166); its counts are in `results/hardcase-macros.tex` (209 `CompCase...` macros) |

sl3 ended 2026-10-07 11:23:38 (16,091 s, 2,548 windows with its 29 reruns). hc1 ended 18:47:42
(26,644 s, 8,052 observations of at most T_OBS = 60 s each); the chain pc2 is done.

Not run by design, with the reason logged: M2's TLS cells (7a63a08); W's churn h2c and MQTT
(2055e63); section 10's 2-core IOCP cell (2055e63) and TLS resumption (13004bc). Expected without
a valid session: sslh-ev's M3 cells and their section 10 cells (logged defect); section 10's SSH C2
cells (opgen has no keep-alive SSH form, status.md section 4 item 3). All of them ran and none is in
a not-run file: on L (sl3) each of the six used its rerun cap and has 0 of 16 valid sessions, as W's
SSH C2 cell did in ws1. Also without a valid session in sl3 after its rerun cap, and not on the
list: S.mixed.C1.L.io_uring
(0 of 16; probe timeouts and error share in both modes, not B1; the io_uring behaviour of status.md
"L after the cost family", section 4 item 2, kept for Alex in item 9; status.md "L's section 10 job
sl3", section 3). W's mixed cell was expected to be invalid by the generator rule (status.md "M7
freeze night" item 7) and is not: all 64 of its windows in ws1 are valid (status.md "W's section 10
job ws1", section 3); L's mixed cell on epoll is valid too, 16 of 16.

## 5. Open items, in order

1. Done: W follow-up for wc1/wc2, wm1, wh1 (status.md, "W's confirmatory jobs, 2026-10-05/06").
   wc1 had 14 refusals (its `chain.done`), not the 2 the earlier W section records; that section
   is not edited, the new one corrects it.
2. Done: the B1 change (fix 9cae2de, entry 9830457, docs after it; status.md, "The B1 change,
   2026-10-06"). The entry was written after the code, since it names the code's commit (as the
   code freeze's entry did); it came before any new data. ANALYSIS_COMMIT unchanged. Reviewed
   adversarially in two rounds before the commits; every finding fixed.
3. Done (2026-10-07, status.md "L after bs1"): bf1, bk1, bs1 journaled; `b3-L` archived; the queued
   commits pushed to the `lab` remote (L's clones see 9cae2de and 9830457).
4. Done: (a) sl1's archive checked, `~/lab/p3/s-L` moved to
   `~/lab/p3/evidence/s-L-sl1-b1count`, journal line written; (b) `m7g/post-src8` at 29ae2b6,
   `test_frozen` (61 checks) and `test_runner` (63 checks) run on L from it as lab job b1chk1, both
   exit 0, written into status.md "L after bs1", section 4; (c) sl3 ran as the first step of the
   chain pc2 (06:55:27 to 11:23:38, exit 0) and is followed up (status.md "L's section 10 job
   sl3": counts per cell, the B1 counts of the mixed cell, provenance and gate checks, archive,
   journal line 162). sl2 is not run.
5. Done (2026-10-07, status.md "The competitors' table hc1"): hc1 on L, the second step of pc2, from
   `m7g/post-src9` at 29ae2b6, 11:23:38 to 18:47:42 (`pc2.done` exit 0), last on L. Followed up as
   for sl3: `l_check.py`, `bench/check_rows.py` against `gate-L.json` (8,078 rows, none refused), the
   provenance check (`change_commit` 9cae2de in every row), the archive with the whole `pc2.log`,
   journal line 166. No job is open on L or W.
6. Done (2026-10-07, status.md "W's section 10 job ws1"): ws1 on W ran from `m7g\ws-src1` at
   29ae2b6 through the chain `m7g\wsfix` and ended 07:00:37 with exit 0; its rows, the provenance
   and gate checks, the archive and the journal line are in that section. The old chain `m7g\ws` is
   retired (its launcher and steps renamed `*.superseded-b1fix`).
7. Done (2026-10-07, status.md "The confirmatory analysis on W, 2026-10-07"): `change_commit`
   9cae2de in every sl3 row (2,548) and ws1 row (600), and in the 7,901 hc1 rows present at 18:07
   (partial; the full check is item 5's); the analysis at ANALYSIS_COMMIT's tree on W from the rows
   of pc1, wc1/wc2, ml1, wm1, bk1/bs1, sl3 and ws1 (never sl1, bf1, mr1 or the pilot's rows),
   twice, byte-identical; reviewed adversarially (no wrong decision; findings in that section,
   section 5). The paper reports sl1's mixed-cell rows as the defect's evidence and names what sl1
   showed (entry 9830457, items 2 and 5).
8. The exploratory io_uring buffer-pool follow-up, labelled exploratory, after the confirmatory
   runs (agent, per Alex's decision).
9. For Alex, undecided: the guard's encoding fix (a later change); Windows `Server::start()`
   returning before the AcceptEx requests are posted; the wider generator placement for W's mixed
   cell; the mixed cell on io_uring starving its churn (status.md section 4 item 2), as the paper
   reports it.
10. Done (2026-10-07, status.md "The macros' TeX escaping and B1's and B2's macros"): the entry
   (90e5138 before the fix, item 6 in 0126ca2), the fix 2045551 (ANALYSIS_COMMIT), reviewed
   adversarially; W's rerun from a fresh clone gives `decisions.csv` byte-identical and
   `summary.json` apart in `versions.analysis_commit` alone; `results/macros.tex` from the committed
   summary (f4ad14e); L's rerun after `pc2.done`: `macros.tex` byte-identical, `summary.json` and
   `decisions.csv` apart from W's only in floats (BCa p-values, at most 1.1e-16) and
   `versions.python`, no decision apart; both hosts in `results/macros-provenance.json` (ac9daf1);
   three journal lines (163 to 165). The draft build ends clean; the submission build stops only on
   the four `\Pending` stubs.
11. Done (same section): the reading on B1 and B2 (18f97a8, item 6 in 4ca64bb);
   `paper/hardcase_macros.py` and `results/hardcase-macros.tex` (B1 and B2 hold), loaded by
   `paper/main.tex`; `paper/not_run.py` and `results/not-run.json` (19 cells, each with its logged
   reason; sl3's two sslh-ev m-ttfb cells ran closed-loop churn windows with no valid session);
   both reviewed adversarially, tests 12 and 7 (5cc0cb2).
12. Done (2026-10-07, status.md "The competitors' table hc1", section 4): hc1's descriptive
   competitors' counts are in `results/hardcase-macros.tex` (the reading, item 4):
   `paper/hardcase_macros.py --competitors hc1 competitor_cases.jsonl` (with `--server L`), 209
   `CompCase...` macros per system and timer setting; "equal" and "differs" describe the field
   `reply_as_the_server_table_expects`, never a pass or a failure of the system; no time of the
   table is used. The paper's text about it is not written.
13. Done (2026-10-07, the paper's results half): `paper/design_macros.py` runs again (each pattern
   matches once); it names SizingCommit 9de26d6 (R_C sized), AnalysisRunCommit 7c1310a (the
   decisions; its `analysis/` tree is 9de26d6's, checked with git in the tests) and AnalysisCommit
   2045551 (the macros). Counts the paper prints from `results/not-run.json`, `decisions.csv` and
   `macros-provenance.json` come from `paper/report_macros.py` (`results/report-macros.tex`, and the
   table bodies `results/tables/*.tex`); two readings of archived W rows (the pilot's CPU shares of
   W's C1 cells, M1's peek-to-replay counts on IOCP) from `paper/w_evidence_macros.py`
   (`results/w-evidence-macros.tex`). Still open: `results/provenance.json`'s held-back note is out
   of date (`macros-provenance.json` follows it).
14. The draft is complete (Results, Deviations and Reproducibility, Discussion with the threats,
   Conclusions, Abstract, appendix of per-cell tables). Decided by Alex on 2026-10-08 (a00e7e0):
   the title "One Port for Many Protocols: The Cost, Robustness and Mechanism of First-Bytes
   Demultiplexing"; no AI-use statement; every decision written as the author's (no "study's
   coordinator"). Holm (1979) is cited and the public links are in (item 16); the DOIs are left for
   Alex. The
   C3.L.io_uring.h2c cell is "equivalence not shown", not a measured cost (its 95% interval's lower
   end, 1.0197, lies inside the margin); only C3.L.epoll.h2c is a measured cost. The io_uring
   ring holds 128 free provided buffers per worker and is refilled from a growable pool as each is
   taken (`worker.hpp`, `uring.cpp`), so "a fixed pool held by busy connections" is not what the
   code does; the paper states the ring as built and the starvation mechanism as a hypothesis.
15. Done (2026-10-08, status.md "Section 10's four descriptive outputs and lab job st1"): the entry
   (bd9a720) before any generator and before st1; st1 on L; `paper/b2_macros.py`,
   `paper/ops_macros.py`, `paper/trace_macros.py` with their tests write `results/b2-macros.tex`,
   `results/ops-macros.tex`, `results/trace-macros.tex` and six table bodies; the paper reports the
   four (Results, Appendix, and 6.7 "Outputs Produced after the Analysis"); one adversarial review
   before the commit, every finding fixed. Open for Alex: agreement with the entry's item 5 (ii).
16. The public material (2026-10-08, status.md "Publication: the public material"): `lab/` holds
   the eight records, the gates, the measured-build files, the compiled-file lists, `pilot.json`,
   `rule_e.json` and `archives.sha256`; 15 archives (the 14 of status.md and rule E's `re1-wre1`) staged as
   the assets of the release `data-2026-10`; the paper's links filled, the DOIs a `\ForAlex` note.
   Not yet public: W's process names and Defender state in W's archives and notes are held for
   Alex's decision before the visibility change, the release and the Papers bump.
## 6. Rules every agent keeps

- The no-connection rule for B3's windows ended with bs1 (2026-10-07 01:29:57); connections to L are
  allowed (coord.). While a job measures, keep them light: reads of files and logs, no build, no test
  run, no archive, no extra server on L, no job of another name (the lab lock would queue it). pc2
  ended 2026-10-07 18:47:43; no job runs on L or W now.
- L jobs: from bash at nice 0 under `SRC/bench/run/lab_job.sh` (lab lock, clock floor, THP madvise,
  NOTRACK), each from a fresh clone of the lab remote; watch pid and done files in `~/lab/p3/m7g/`
  (for sl3 and hc1: `pc2.*`, not `sl3.*` or `hc1.*`); never `pgrep -f` or `pkill -f`. ssh only to
  192.168.1.62 (wired), never 192.168.1.9. L's login shell is zsh: start jobs with `bash -c`.
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
| L job dir | `~/lab/p3/m7g/`: `NAME.pid`, `NAME.done`, `NAME.log`; `l_run.sh`, `l_check.py`, `post_chain.sh`, `post_chain2.sh` (sha256 2ccdb16a8e1abbe1620ad840048b222acec5de513f3a8896eaebfdb2c169f2e1; sl3 then hc1, lab job `pc2`), `b1chk.sh`, `b3feas.sh` |
| L clones | `m7g/post-src2` 77cedae, `post-src3` 86c0283, `post-src4` 7a63a08, `post-src5..7` d29968b, `ana-src` 9de26d6; `post-src8` (sl3, left as it is) and `post-src9` (hc1), both at 29ae2b6 (made 2026-10-07) |
| L evidence | `~/lab/p3/evidence/s-L-sl1-b1count` (sl1's output, moved there 2026-10-07; never analysed) |
| st1 | out `~/lab/p3/st-L`; clone `m7g/st-src1` (fe65818); wrapper `m7g/st_run.sh` (c65dae5b...) and `m7g/st_guard.py` (34b41ce7...); job files `m7g/st1.*` |
| L frozen build | `~/lab/p3/m7g/records-ff2679c/build-release`, `gate-L.json`; pilot output `m7g/pilot-entry/pilot.json` |
| L archives, logs | `~/lab/p3-raw-2026-10-05-<job>-ff2679cc8.tar.gz` (+ `.sha256`; `bk1-bs1` is one archive for both jobs); `~/lab/p3-raw-2026-10-07-sl3-ff2679cc8.tar.gz` (+ `.sha256`; sl3, with `pc2.log`'s sl3 part as a snapshot, staged in `~/lab/stage-sl3/`; copies on W in `C:\Users\alext\lab\`); `~/lab/p3-raw-2026-10-07-hc1-ff2679cc8.tar.gz` (+ `.sha256`; hc1 with `hardcomp-L`, the job files of pc2 and the whole `pc2.log`; copy on W in `C:\Users\alext\lab\`); `~/lab/records-logs/<record>/`; the check of the B1 change `m7g/b1fix-L-test_*.log` |
| L launch | `bash -c '(setsid nohup bash SRC/bench/run/lab_job.sh ~/lab/p3/m7g NAME bash ~/lab/p3/m7g/l_run.sh SRC STEP JOB > /dev/null 2>&1 &)'`; the chain pc2: the same with `NAME` pc2 and `bash ~/lab/p3/m7g/post_chain2.sh` in place of `l_run.sh SRC STEP JOB` |
| W job dirs | `C:\Users\alext\lab\p3\m7g\` `wcost`, `wm`, `whard`, `wnight2` (chain wc2, wm1, wh1; `chain.log`, `chain.done`), `wpilot`, `wrule`; `wsfix` (ws1, done); `ws` retired (B1 change) |
| W clones, files | `m7g\post-src2` 77cedae, `m7g\pilot-src2` f185a8a, `m7g\ws-src1` 29ae2b6 (ws1); `m7g\pilot.json`, `m7g\rule_e.json`, `m7g\stopat.py`; the B1 change's checks `m7g\b1fix\` (`SHA256SUMS` sha256 32418367ea727376f6566a8502f3450183f796e10649429548f0954dc832789e) |
| W frozen build | `C:\Users\alext\lab\p3\m7g\records-ff2679c-W\build-release`, `gate-W.json` |
| W launchers | `run_chain.cmd` per dir, its `chain.py`, `steps.json`, `launches.txt`; WMI launch by `C:\Users\alext\lab\p3\m6b\wlaunch.ps1`; stop with `chain.stop` |
| W Python | `C:\Users\alext\AppData\Local\Python\pythoncore-3.14-64\python.exe` |
| W analysis | `C:\Users\alext\lab\p3\confirm1\`: `archives\`, `unpacked\`, `files-L\`, `files-W\`, `dl\` (wheel), `venv\`, `src\` (clone at 7c1310a), `run_analysis.sh`, `make_provenance.py`, `out1\`, `out2\` (each with `SHA256SUMS`; the held-back `macros.tex`); after the escaping: `src2\` (clone at 2045551), `run_analysis2.sh`, `out3\`, `out4\`, `src2-tests.log`, `from-L\` (L's outputs and logs), `compare-W-out3-L-out1.json`, `make_macros_provenance.py` |
| L analysis | `~/lab/p3/confirm1L/`: `archives/` (W's three), `files-L/`, `files-W/`, `unpacked/`, `src/` (clone of the lab remote at 2045551), `setup_L.sh`, `run_analysis_L.sh`, `l_env.py`, `out1/`, `out2/`, logs; venv `~/opt/analysis-numpy-2.5.0/venv` |
