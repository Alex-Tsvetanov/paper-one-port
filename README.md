# One listener for every protocol

Research code and paper by Alex I. Tsvetanov (Technical University of Sofia): one listening
socket per transport and accept model that serves several protocols by their first bytes.

Status: design. The repository is private until the paper is submitted.

## Layout

- `design/`: the competitor survey and the design notes.
- `hypotheses.md`: the pre-specified hypotheses, frozen before any publication run.
- `bench/`: the paper's own server, the competitor recipes and the load and case generators.
- `results/`: curated results with provenance; raw data is archived with a sha256, never in git.
- `analysis/`: scripts that turn results into `results/macros.tex`. The paper never types a number.
- `paper/`: the manuscript (MDPI Future Internet).

## Licence

Copyright 2026 Alex I. Tsvetanov.

The code in this repository (`CMakeLists.txt`, `.clangd`, `bench/`, `tests/`, `analysis/` and
the Python programs in `paper/`) is licensed under the Apache License, Version 2.0. The full
text is in `LICENSE`. The grant covers the code only. It does not cover the manuscript (the
LaTeX sources in `paper/` and every PDF or Word copy built from them) or the MDPI template
files in `paper/Definitions/`, which are kept in this repository only to build the
manuscript. `NOTICE` lists what the grant covers and what it does not, and gives the
attribution for the code adapted from Netty.
