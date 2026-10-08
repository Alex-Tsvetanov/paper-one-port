# Paper

Target: MDPI Future Internet, on MDPI's class (`TEMPLATE.md`).

State: the whole draft is written. The method half was written before the data; the Results,
Deviations and Reproducibility, Discussion (with the threats to validity), Conclusions, the
Abstract and the appendix of per-cell tables were written from the generated macro files and the
results files after the confirmatory analysis. What is left for Alex is marked `\ForAlex`: the
reference for Holm (1979) and the public links.

## Files

- `main.tex`: preamble, title, author block, back matter; inputs the sections.
- `sec-*.tex`: one file per section.
- `references.bib`: only verified entries; how each was verified is in its header.
- `result-placeholders.tex`: stands in for `../results/macros.tex` in a draft build, before the
  frozen analysis writes it; a submission build never loads it.
- `design_macros.py`: writes `../results/design-macros.tex`, every design constant the text states,
  read from `hypotheses.md` (frozen text and revision log, with the values set after the freeze and
  the counts of the logged deviations), `bench/cmake/pins.cmake`, two host readings, the versions
  block of `../results/summary.json` (where the confirmatory analysis ran) and one constant of the
  frozen server (`bench/server/worker.hpp`, the io_uring pool of provided buffers). It names the
  three commits of the analysis code: the one whose simulation sized R_C, the clone the decisions
  were computed from (its `analysis/` tree is the first's, which the tests check with git), and
  `ANALYSIS_COMMIT`, which wrote the macros. It lives here, not in `analysis/`, because the revision log records that `analysis/`
  is unchanged since `ANALYSIS_COMMIT`. `--check-code` compares the frozen values with the code's
  constants.
- `test_design_macros.py`: its tests.
- `hardcase_macros.py`: writes `../results/hardcase-macros.tex`, B1's and B2's counts and
  decisions, from the hard-case runners' archived outputs (each `hardcases.jsonl` checked against
  its `hardcases-table-<job>.json`) and `summary.json`'s `b1_failures`, naming each input by its
  sha256. With `--competitors JOB competitor_cases.jsonl` it adds the competitors' table of
  section 10 (lab job hc1; macros `CompCase...`): per system and per timer setting, the rows and
  variants whose reply equals what the server's frozen table expects, those that differ, those not
  observed, and the cases of each. It is descriptive and holds no time; it needs `--server L`, whose
  variants the table must match. It lives here for the same reason as `design_macros.py` (the
  revision log's entry "B1's and B2's decisions from the hard-case runners' outputs (a reading)").
- `test_hardcase_macros.py`: its tests.
- `not_run.py`: writes `../results/not-run.json`, every cell that `summary.json` has short of its
  R, with its not-run file's reason or, for a cell that ran, its rows' counts and invalid reasons,
  and the logged entries and quotes that give the reason (each checked against its source).
- `test_not_run.py`: its tests.
- `report_macros.py`: writes `../results/report-macros.tex` (counts over the results files: per
  hypothesis the cells in Holm and those that pass, the cells not run or short of R, the reruns of
  the analysis) and `../results/tables/*.tex` (the bodies of the results' tables, citing the macros of
  `../results/macros.tex` and `../results/hardcase-macros.tex` by name). It reads only committed
  results files and decides nothing; `--check` compares with the committed outputs.
- `test_report_macros.py`: its tests.
- `w_evidence_macros.py`: writes `../results/w-evidence-macros.tex`, two readings of archived W rows
  that the revision log and the frozen text promise: the CPU shares of W's pilot cells of C1 (why
  W's churn of h2c and MQTT is generator-bound) and how often M1's peek on IOCP switched to replay.
  Each input is checked against the sha256 the repository names for it (the pilot entry; the
  inputs of `../results/summary.json`). Run on W with `--pilot-w ~/lab/p3/pilot-W/windows.jsonl
  --m-w ~/lab/p3/m-W/windows.jsonl`.
- `test_w_evidence_macros.py`: its tests; the check of the committed file is skipped where the
  archived rows are not at hand.
- `b2_macros.py`, `ops_macros.py`, `trace_macros.py`: section 10's four descriptive outputs, as the
  revision log's entry "Section 10's four descriptive outputs not yet reported, and their untimed
  windows on the frozen build (a reading)" reads them. `b2_macros.py` writes
  `../results/b2-macros.tex` and `../results/tables/b2.tex`, B2's distributions of lateness and
  decision latency per backend, from hl1's and wh1's `hardcases.jsonl` (the files
  `../results/hardcase-macros.tex` names). `ops_macros.py` writes `../results/ops-macros.tex`,
  `../results/tables/ops-cost.tex` and `../results/tables/ops-m1.tex`, the operations and copies per
  connection (WL5) of the cost family's and M1's valid windows (the files `summary.json` names).
  `trace_macros.py` writes `../results/trace-macros.tex` and the tables `counter-check.tex`,
  `syscalls.tex` and `ops-relay.tex` from the untimed lab job st1 (`systrace.py` on L after the
  analysis): the check of the server's system-call counters, the proxies' system calls per
  connection and the relay's operations per relayed connection, each input checked against the
  sha256 `design/status.md` names. Each takes `--check`. On W:
  `python paper/b2_macros.py --l ~/lab/p3/confirm1/unpacked/pc1/hard-L/hardcases.jsonl --w ~/lab/p3/confirm1/unpacked/wh1/hard-W/hardcases.jsonl`;
  `python paper/ops_macros.py --cost-l ~/lab/p3/confirm1/unpacked/pc1/cost-L/windows.jsonl --cost-w ~/lab/p3/confirm1/unpacked/wc1-wc2/cost-W/windows.jsonl --m-l ~/lab/p3/confirm1/unpacked/ml1/m-L/windows.jsonl --m-w ~/lab/p3/confirm1/unpacked/wm1/m-W/windows.jsonl`;
  `python paper/trace_macros.py --trace ~/lab/p3/confirm1/unpacked/st1/st-L/trace.jsonl --calls ~/lab/p3/confirm1/unpacked/st1/st-L/calls-st1.jsonl --clearance ~/lab/p3/confirm1/unpacked/st1/st-L/clearance-st1.json`.
- `test_b2_macros.py`, `test_ops_macros.py`, `test_trace_macros.py`: their tests; the checks of the
  committed files are skipped where the archived rows are not at hand.
- `check_text.py`: the writing rules (no dashes, no digit outside the macros, sentences of at most
  30 words); it scans every generated macro file and table for dashes.

## Build

    python paper/design_macros.py --check-code
    python -m pytest -q paper/test_design_macros.py
    python -m pytest -q paper/test_hardcase_macros.py paper/test_not_run.py
    python paper/report_macros.py --check
    python -m pytest -q paper/test_report_macros.py
    python -m pytest -q paper/test_b2_macros.py paper/test_ops_macros.py paper/test_trace_macros.py
    python paper/check_text.py
    cd paper && latexmk -pdf main.tex

A draft build prints notes for Alex in blue (`\ForAlex`), open items in red (`\TODO`) and results
not yet computed as `[pending: ...]`. Set `\submissiontrue` in `main.tex` for a submission build:
it then stops on any pending result or a missing `../results/macros.tex`.

The paper carries no statement on the use of generative AI: that is the author's decision of
2026-10-08.
