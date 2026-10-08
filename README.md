# One listener for every protocol

Research code and paper by Alex I. Tsvetanov (Technical University of Sofia): one listening
socket per transport and accept model that serves several protocols by their first bytes.

Status: the paper is written and not yet submitted (`paper/`).

## Layout

- `design/`: the competitor survey and the design notes.
- `hypotheses.md`: the pre-specified hypotheses, frozen before any publication run.
- `bench/`: the paper's own server, the competitor recipes and the load and case generators.
- `results/`: curated results with provenance; the raw data are never in git (below).
- `analysis/`: scripts that turn results into `results/macros.tex`. The paper never types a number.
- `paper/`: the manuscript (MDPI Future Internet). `paper/main.pdf` is its PDF, the submission
  build, rebuilt from the sources and committed with them: change `\submissionfalse` to
  `\submissiontrue` in `paper/main.tex` (the notes for the author are then not printed), run
  `cd paper && latexmk -pdf main.tex`, and change it back. A draft build, the file's default,
  overwrites the committed PDF.
- `lab/`: the laboratory files the results rest on, copied: the sanitizer records, the gates and
  the analysis's other inputs; and two lists written for this repository: what the measured
  builds compiled, and the raw archives (`lab/README.md`).

## Public material

The paper's results rest only on public material: this repository, whose history is the one the
work was done in (the code freeze `ff2679c`, the later change `9cae2de` and the analysis commit
`2045551` are commits of it), the files in `lab/`, and the raw outputs of the pilot and of every
job of windows or hard cases after the pilot entry. Those are the assets of the release
`data-2026-10`, each with a `.sha256` file beside it:
https://github.com/Alex-Tsvetanov/paper-one-port/releases/tag/data-2026-10.
`lab/README.md` lists the assets and says how to unpack them for the analysis and the generators
of `paper/`. The development runs before the pilot entry are described in the revision log and the
design notes; their raw outputs are not published.

Some files name laboratory material that is not published. Code comments, the design notes and
`hypotheses.md` call the author's private repository of papers "the Papers repo". The scripts of
`bench/` call three of its programs, `lab/bin/inputs_hash.py`, `lab/bin/pin.sh` and the lab lock
`lab/bin/lablock`, and read `lab/bin/test_report_pattern.sh` where it is present; their defaults
point at its `lab/bin`. To check a gate, run `bench/check_records.py --records
lab/sanitizer-records`. Never give that directory to `bench/records_job.sh` or
`bench/sanitize_oneport.sh`, which write records. `lab/README.md` states the rule of the inputs
hash, with the files each measured target compiled, so the hashes can be checked with Python.
The laboratory journal (`lab/journal.jsonl` of that repository) also logs the author's other work
and is not published; the frozen `hypotheses.md` and the design notes cite it, and the seeds of
`design/seeds.json` were drawn with every integer it named excluded. Paths such as `~/lab/p3/...`
(on L) and `C:\Users\alext\lab\p3\...` (on W) are the hosts' working directories. The frozen code
under `bench/`, `tests/` and `analysis/` is left as it ran.

## Licence

Copyright 2026 Alex I. Tsvetanov.

This repository is licensed under the Apache License, Version 2.0. The full text is in
`LICENSE`. The licence covers every file except the manuscript (the LaTeX and BibTeX sources
in `paper/` and every PDF or Word copy built from them) and the MDPI template files in
`paper/Definitions/`, which are kept in this repository only to build the manuscript.
`NOTICE` lists what the licence covers and what it does not, and gives the attribution for
the code adapted from Netty.
