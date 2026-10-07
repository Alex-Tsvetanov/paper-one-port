# Paper

Target: MDPI Future Internet, on MDPI's class (`TEMPLATE.md`).

State: the method half is drafted before any confirmatory data. Introduction, Background and
Related Work, the Server, Method and Threats to Validity are written; the Abstract, Results,
Discussion and Conclusions are stubs marked pending.

## Files

- `main.tex`: preamble, title, author block, back matter; inputs the sections.
- `sec-*.tex`: one file per section.
- `references.bib`: only verified entries; how each was verified is in its header.
- `result-placeholders.tex`: stands in for `../results/macros.tex` in a draft build, before the
  frozen analysis writes it; a submission build never loads it.
- `design_macros.py`: writes `../results/design-macros.tex`, every design constant the text states,
  read from `hypotheses.md` (frozen text and revision log), `bench/cmake/pins.cmake` and two host
  readings. It lives here, not in `analysis/`, because the revision log records that `analysis/`
  is unchanged since `ANALYSIS_COMMIT`. `--check-code` compares the frozen values with the code's
  constants.
- `test_design_macros.py`: its tests.
- `hardcase_macros.py`: writes `../results/hardcase-macros.tex`, B1's and B2's counts and
  decisions, from the hard-case runners' archived outputs (each `hardcases.jsonl` checked against
  its `hardcases-table-<job>.json`) and `summary.json`'s `b1_failures`, naming each input by its
  sha256. It lives here for the same reason as `design_macros.py` (the revision log's entry "B1's
  and B2's decisions from the hard-case runners' outputs (a reading)").
- `test_hardcase_macros.py`: its tests.
- `not_run.py`: writes `../results/not-run.json`, every cell that `summary.json` has short of its
  R, with its not-run file's reason or, for a cell that ran, its rows' counts and invalid reasons,
  and the logged entries and quotes that give the reason (each checked against its source).
- `test_not_run.py`: its tests.
- `check_text.py`: the writing rules (no dashes, no digit outside the macros, sentences of at most
  30 words).

## Build

    python paper/design_macros.py --check-code
    python -m pytest -q paper/test_design_macros.py
    python -m pytest -q paper/test_hardcase_macros.py paper/test_not_run.py
    python paper/check_text.py
    cd paper && latexmk -pdf main.tex

A draft build prints notes for Alex in blue (`\ForAlex`), open items in red (`\TODO`) and results
not yet computed as `[pending: ...]`. Set `\submissiontrue` in `main.tex` for a submission build:
it then stops on any pending result or a missing `../results/macros.tex`.

The Acknowledgments carry a note for the author: MDPI asks for a statement on the use of
generative AI, and its wording is the author's to decide.
