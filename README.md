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
