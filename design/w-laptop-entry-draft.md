# DRAFT: the section 8 entry that moves W's runs to the laptop's Windows

Status: a draft, not part of the revision log, and not to be appended to `hypotheses.md` until (1)
the probe of the entry of 2026-10-23 has run and its computed time (item 12) has been stated to
Alex (Alex answered the open points on 2026-10-23: items 3 (e), 8 and 13), (2) job a0's readings
are in item 13, and (3) a fresh adversarial review of
the final text has passed. Its heading must keep the exact title below: every frozen W run requires
it (`bench/run/freeze_guard.py`, `W_LAPTOP_ITEMS`). Placeholders are marked **[after the probe]**.
Written 2026-10-23. No number below is a result; the hours are estimates with their basis named.

---

### 2026-10-2X: W's runs on the laptop's Windows (a later change under section 8)

A later change under section 8's rule for a later change, recorded here as a deviation, as that
rule requires, and committed before any window of W's runs on the laptop's Windows other than the
probe of the entry "A probe of window times on the laptop's Windows, before the entry that moves
W's runs there (a reading)" (2026-10-23; "the probe's entry" below). It moves W from the desktop
of October to the laptop that L already is, changes W's compiler, records and procedure, and
names the change's commit. Nothing above this log is edited. No rule of sections 1 to 13 changes:
the rules that name the desktop's values (a compiler version, a placement on six cores, a power
plan, a quiet gate) are read here for the new host, item by item. No hard case of Appendix A
changes outcome by it. This entry was written after every W result of October was seen (item 15).
Every figure below is a count, a constant, a sha256 or a time named by its record; none is a result.

1. Alex's decisions (2026-10-23). W's cells run again on the laptop's Windows; L's rows and runs
   stand (L is the laptop's Arch Linux). The desktop (AMD Ryzen 5 3600) is no longer a host of this
   study: no row of it enters any analysis (item 9). The paper says in one sentence, with no
   number, that the Windows cells were run again on the laptop after a first campaign on another
   Windows machine, under an entry written after those results were seen.
2. The host W, from this entry on: the laptop's Windows 11 (ASUS ROG Strix G513QM, AMD Ryzen 7
   5800H, 8 cores, 16 logical processors, core k holding logical processors 2k and 2k + 1, one
   group, one efficiency class), OS build **[a0 reads it]**, MSVC `cl` 19.51.36248 for x64
   (Visual Studio Community 18.7.1, toolset 14.51.36231; CMake reads "MSVC 19.51.36248.0"), the
   Python and tool versions of Papers `lab/laptop/versions.md`. Every W job runs through the lab's
   runner (Papers `lab/bin/labrun.py`) under its procedure (Papers `lab/laptop/README.md`, item 3).
   For W this supersedes "Words" ("W is the Windows host, with MSVC 19.51.36246"), section 11's "on
   W, MSVC 19.51.36246", and `design/w-procedure.md` as the desktop applied it, as items 3 and 4
   read them. The gate still matches the compiler (section 11), so W's records are made again with
   the laptop's compiler (item 10).
3. The procedure, which replaces `design/w-procedure.md` and W's job-start quiet gate (90/90/10 of
   the entry "W's quiet gate lowered (Alex's decision), before the code freeze"):
   (a) Per job, the lab runner's run phase: AC power required; the lab plan "lab laptop"
   (b1bcd431-7706-4898-b26a-caeee179f68e, a copy of High performance: minimum and maximum
   processor state 100%, core parking minimum cores 100%) with performance boost mode 0, made
   active and read back, and the plan it found (Alex's Balanced) set back at the end; Defender's
   and Windows Update's state read and recorded, never changed; a sampler on CPUs 0 and 1.
   (b) The job-start quiet check is the lab's (`labrec.quiet_check`): over 10 s, mean idle at least
   90%, each of CPUs 2 to 15 at least 90% idle, no process above 10% of one CPU; retried every 60 s
   up to 1,800 s. It keeps Alex's bounds of 2026-10-05 and judges more: CPUs 2 to 15 (the window's
   2 to 14 and the server's idle sibling 15) and every process. W's own check (`wsys.quiet_check`)
   does not run inside a lab job. The run phase tells the job that its check passed by
   `LAB_QUIET=passed:<the lab job's id>`, set only after its check passed, any inherited value
   dropped first; without that exact value `bench/run/wjob.py` refuses the job unless it runs as a
   functional check, and a frozen W run refuses a functional check, as before.
   (c) Inside a lab job W's power session only verifies: the lab plan active with section 2's four
   values (boost mode 0), or the job refuses; it switches nothing and restores nothing, and every
   other switch of the plan (`wpower.py restore`, `switch_within_session`, `wnight.py`, `wfreq.py`)
   refuses there (`bench/run/wpower.py`). Each window still records the active plan at its start and end, and
   W's procedure's rule (the lab plan at both) still makes a window invalid.
   (d) Unchanged: the timer resolution (Windows' default, recorded); every validity rule of section
   7 as W computes it (the entry "W before the code freeze", item 6 (b)); the TIME-WAIT wait before
   a window (`TW_START_MAX` = 1,000 entries, `TW_WAIT_MAX_S` = 40 s) **[after the probe: unless
   item 13 changes it]**; no TCP setting of either system is ever changed.
   (e) The frequency rule. Section 9.1's fallback, taken on the desktop (the entry "W before the
   code freeze", item 3), stands: W's windows are validated without the frequency rule, and the
   counter is recorded in every row. Alex's decision of 2026-10-23: the counter is not tested on the
   laptop (`wfreq.py` refuses inside a lab job, and its control plan is not created there).
4. The placement. Section 4.1's rule on W, "the server on one logical CPU of the last physical
   core, its sibling idle, `opgen` on the cores between core 0 and the server's", gives on the
   laptop: the server on CPU 14, CPU 15 idle, the generator on CPUs 2 to 13, CPUs 0 and 1 for the
   system and the runner. These are the CPUs of L's in-process cells, so each W cell now runs on
   the same physical cores of the same machine as its L cell. What follows from it, each a reading
   of a frozen design choice on 8 cores:
   (a) closed-loop windows run 12 generator workers (the desktop ran 8), one per generator CPU
   (M6b's choice, `wwindow.gen_threads`);
   (b) open-loop windows run one worker per physical core of the generator's CPUs, on its first
   sibling: CPUs 2, 4, 6, 8, 10 and 12 (the desktop: 2, 4, 6 and 8), as L's `window.OPEN_GEN_THREADS`;
   (c) the hard cases and the pilot's timer and split parts: the server on CPU 14, `opcase` on CPUs
   2 to 13;
   (d) the mixed cell of section 10, a design choice made again: the entry "The job's warm-up and
   W's runners (M7e)", item 4, split the desktop's 8 generator CPUs (2 to 5, 6 and 7, 8 and 9)
   because it lacked L's 12; the laptop has them, so the cell takes L's placement (the entry "M7c's
   open items, before the code freeze", item 7): the cell's `opgen` on CPUs 2 to 9, the TLS
   background on 10 and 11, the MQTT background and the holder on 12 and 13;
   (e) the job-start check of item 3 (b) covers CPUs 2 to 15.
   The two-core IOCP cell of section 10 stays not run (the entry of 2055e63; the server refuses
   more than one IOCP worker).
5. The change, four commits (5cc1e06; b20f415 with an adversarial review's fixes; e183745, a test
   made independent of the probe entry's item 9; a4d8e89, the probe reading its commit from the
   entry's last item that names it), Python directly under `bench/run` alone. The probe ran
   a4d8e89's code (the probe's entry, item 10):
   CHANGE_COMMIT = **[a4d8e89a3b54f59e67e1eefdd8ad51fce62db2c9, unless this entry needs another change]**
   Files: `wsys.py` (the core layout, item 4's placement, and the counters of all 16 CPUs, where the
   window code read the desktop's 12), `wwindow.py` (the open-loop threads),
   `wcellwin.py` (item 4 (d)), `wpower.py` (item 3 (a) and (c): the laptop's plans by GUID; no plan
   is created on the laptop), `wjob.py` (item 3 (b)), `wrunlib.py` (item 10's gate check, and this
   entry's title among the entries a frozen W run requires), `freeze_guard.py` (that title),
   `wfreq.py` and `wnight.py` (the laptop's server CPU and Balanced plan), `whardcase_run.py` and
   `wpilot_run.py` (docstrings), the deps wrapper `wdeps.py` (item 11), the probe's driver
   `wprobe.py`, and the tests `test_wlaptop.py`, `test_wrunner.py`, `test_wfrozen.py`. No compiled
   file, no file under `tests/`, `CMakeLists.txt`, any script, or `analysis/` changes. Checks on the
   desktop (2026-10-23, no timing): a Release build of the change's clone with MSVC 19.51.36246,
   whose CTest suite passed 165 of 165; `test_wlaptop` 37 tests, `test_wfrozen` 26, `test_frozen` 61
   (2 skipped), `test_runner` 63 (13 skipped), `test_wrunner` 22 of 22 (its cycle-rate reading
   reports itself skipped there: CPU 14 does not exist on the desktop; it runs on the laptop in job
   a4); `wdeps.py` built nghttp2 in both flavours with the desktop's compiler (the copy then equals
   the script); a clone with a line naming the commit as above passed the guard, and without it
   was refused. **[a4 adds the laptop's results of the same suites.]**
6. Section 8's rule for a later change, part by part.
   (a) No named failure forces the change, and it comes after the simulation, so the rule applies.
   (b) "the pilot is not run again, and its outputs ... stand": a deviation, by Alex's decision.
   The rule was written for a change of the frozen code on the same two hosts. Here the host W
   itself changes: the desktop's pilot sessions measured a machine that runs no window from now on,
   and its rows may not enter an analysis (item 9). So W's part of the pilot runs again on the
   laptop (item 7); L's part stands.
   (c) "the new build gets new records": the laptop's compiler builds the same compiled inputs, so
   W's records and gate are made again on the laptop (item 10). L's build, records and gate are
   unchanged: no file any L target compiles changes.
   (d) "every confirmatory window of the old build is archived and not used; the runs start again
   on the new build": every W row of the desktop is archived already (the public release
   `data-2026-10`) and is not used (item 9); W's runs start again on the laptop. L's confirmatory
   windows ran on L's build, which does not change, so none of them is archived for this change,
   as the entry "The B1 count of the mixed cell", item 4 (c) and (d), read the same clause.
   (e) This entry records the change as a deviation.
   (f) No one-port window of the laptop's W runs before the new pilot entry (item 7).
7. The new pilot, on the laptop's W, by section 8 step 4 and section 4.6 as frozen: W's 12 cost
   cells, P = 16 sessions each, in dedicated mode, in the order `SEED_PILOT_W` gives, with the
   reruns and the one repeat of step 4; then the timer and split parts on IOCP. Then, on the
   desktop, the simulation of 4.6 at `ANALYSIS_COMMIT` (2045551) with `SEED_SIM`, on L's pilot
   rows of October (job pl1) and the laptop's W pilot rows. Since each cell's runs are seeded by
   (`SEED_SIM`, c, j), L's cells get the Power_c of October. Then a new pilot entry, made from those
   outputs alone and committed before any one-port window of the laptop's W, with section 9.2's
   values: the resolved list, R_C, m_C, G_W, GAP_SPLIT and each W C3 cell's λ. Cells 10 and 12
   (W's churn h2c and churn MQTT) keep their frozen treatment: they run in the pilot only, for λ,
   and `analysis/pilot.py` at `ANALYSIS_COMMIT` never resolves them (`cells.COST_OUTSIDE_FAMILY`).
   The laptop's pilot rows give their server and generator CPU shares; the paper reports them
   beside the desktop's evidence, as a description, and they decide nothing. Moving them into the
   family would change `analysis/`, which this entry does not do.
8. How the analysis and Holm run: a later change of `analysis/`, by Alex's decision of 2026-10-23.
   (a) Why. `analysis/analyse.py` at 2045551 takes one R_C for every cost cell and refuses a cell
   with more valid sessions than R_C (`run_family`), while a cell with fewer is left untested. L's
   24 cost cells hold 28 valid sessions each (job pc1). L's resolved cells reached 0.80 at R = 25
   or below in October (the pilot entry, item 7), so a new R_C over every resolved cell would be set
   by the laptop's W cells, and unless it were exactly 28, the analysis at 2045551 could not run on
   L's rows. Alex chose, of three options (this change; W at the larger of 28 and the new value
   with L topped up to 31; R_C fixed at 28 for W), this change.
   (b) The change, one commit, in `analysis/` alone:
   ANALYSIS_COMMIT = **[8815d89ff537ef3dee75f94298dedf8933e08a41, unless the review changes it]**
   `pilot.py --fixed-r L=28`: L keeps the R its cost runs ran at, the R_C of the pilot entry of
   2026-10-05, refused if any resolved L cell falls short of 0.80 there; W's R is 4.6 step 6 over
   W's resolved cells alone (31 if none is resolved). The output adds `R_C_by_host`; the resolved
   list, m_C and every Power_c are as before; `R_C`, step 6 over every resolved cell, stays
   reported; each joint power is taken at its host's R. `analyse.py` gives each cost cell, and each
   of section 10's intervals drawn from a cost cell, its host's R; Holm runs over the m_C resolved
   cells of L and W together as one family (5.1), as frozen; `macros.py` adds the macros `CostRL`
   and `CostRW`. Without `--fixed-r` every output is as at 2045551.
   (c) The checks (2026-10-23, desktop, no timing): the suite, 78 passed and 2 skipped (73 and 2 at
   2045551; the five new tests fail without the change); and the analysis at the change's commit,
   from a fresh clone, on October's inputs (the seven row files, pilot, rule E, seeds and gates of
   the confirmatory analysis): `decisions.csv` and `macros.tex` byte for byte the committed ones,
   `summary.json` apart only in `versions.analysis_commit`. That run reproduces October's committed
   outputs as a check of the code; it is not an analysis, and nothing from it is kept.
   (d) What it implies, stated before any data. L's rows and R are unchanged, but L's decisions are
   read again from the joint run: Holm's family now holds the laptop's W cells, and the cost
   family's one bootstrap stream (4.7) draws per tested cell in 6.1's order, so W's R and test
   status change the draws of the L cells after the first W cell. Any L decision that differs from
   October's is reported with both. The mechanism family runs as frozen over its 20 cells, M1's two
   IOCP cells now the laptop's. `ANALYSIS_COMMIT` runs unchanged from this commit on, once, on L's
   rows of October and the laptop's W rows, never on a desktop row, with the new pilot entry's
   output.
9. Desktop rows excluded. No row of the desktop enters any analysis: W's pilot wp1, rule E's
   wre1, the cost jobs wc1 and wc2, M1's wm1, the hard cases wh1, and section 10's ws1. Their
   archives stay as published (`data-2026-10`, never edited); `results/summary.json`,
   `results/decisions.csv`, `results/macros.tex` and the other October results stay as committed.
   The laptop's analysis writes into `results/laptop-w/` and its own generated macros file; the
   paper's W numbers come from those alone.
10. Records and gate. The laptop's records job (Papers job a2, from a clone at the change's
    commit) builds the Release build and makes MSVC's ASan record of oneport into a folder named
    `laptop-w` that holds no other record, then `gate-W.json` from that folder alone
    (`bench/gate_lib.py` reads one folder, not its subfolders). A record made on the desktop and
    one made on the laptop at the same commit have the same file name, so they never share a
    folder. Every frozen W run refuses a gate that was not made so: host W, a records folder named
    `laptop-w`, the laptop's compiler (`wrunlib.check_laptop_gates`). Before the gate, each
    target's inputs hash is compared with the desktop's record, target by target; they are
    expected equal, since the compiled inputs and pins are CODE_FREEZE's. Section 11's declared
    gaps for Windows stand (`bench/coverage.json`).
11. OpenSSL 3.5.9 and nghttp2 1.70.0 on the laptop. `bench/third_party/build_deps.ps1` stops
    unless `cl` is 19.51.36246. It is a frozen path and is not edited: `bench/run/wdeps.py` checks
    that the clone's script and `bench/cmake/pins.cmake` are CODE_FREEZE's blobs, copies both out
    of the tree in the script's layout, changes in the copy the one line `$wantCl = '19.51.36246'`
    to the laptop's version, runs it, and records the sha256 of the script, the copy and the pins,
    and of every file each install prefix holds. The archives' sha256 pins, the options and the
    flags are the frozen script's.
12. Machine time on the laptop's W, from the probe **[after the probe]**: churn and open-loop
    windows at the probe's mean length t = ... s, keep-alive windows at k = ... s, the job warm-ups
    at ... s each and the session readings at ... s each; W's windows by family (the new pilot's
    R_C sets the cost family's count): ... ; total ... h, against the plan's estimate of 5.3 to
    21.3 h, which had no laptop basis. Stated to Alex on ... before this entry was committed.
13. The laptop's TCP settings (Alex's decision of 2026-10-23, the probe's entry, item 10): if
    the laptop's `TcpTimedWaitDelay` or dynamic port range differ from the values W's runner was
    designed for (30 s; 1025 to 65535), Alex sets them to those values with an administrator step
    he runs himself, read back, before the probe; if they cannot be set, the probe and W's runs use
    the laptop's own values, documented here. Read by job a0 **[after a0]**: `TcpTimedWaitDelay`
    ...; the dynamic port range ...; the excluded ranges ...; set or not: ... . The probe's
    TIME-WAIT waits **[after the probe]**: ... .
14. The order of W's jobs on the laptop after this entry: the runners' functional checks (a4);
    the A/A pilot with its parts; the simulation and the new pilot entry (desktop); rule E's
    development sessions; the cost family; M1; the hard cases; section 10. Each from a clone at
    this entry's commit or later, each inside a lab job and a W lab job.
15. Written after the data. The desktop's W rows, the October decisions and the paper's drafts
    that report them were read before this entry. Nothing here can be chosen from them: R and the
    family come from the new pilot by the frozen rule (subject to item 8), the analysis code is
    fixed, the placement follows section 4.1's rule, and during the campaign only validity counts
    are read, never a comparison of arms.
