# Laboratory files

The files from the author's laboratory that the paper's results rest on. The laboratory is the
author's private repository of papers (code comments, the design notes and `hypotheses.md` call it
"the Papers repo") and the two hosts, L (Linux) and W (Windows). Each file here is byte for byte
the laboratory's file, checked by sha256 on 2026-10-08, except three files written on that date for
this repository: `archives.sha256` (from the archives' own `.sha256` files) and the two lists of
compiled files (below). The raw outputs of the pilot and of every job of windows or hard cases
after the pilot entry are not in git: they are the assets of the release `data-2026-10`,
https://github.com/Alex-Tsvetanov/paper-one-port/releases/tag/data-2026-10.

## `archives.sha256`: the raw outputs

Each line is an asset of the release `data-2026-10` with its sha256. Each asset also has a
`.sha256` file beside it. Each value is the one `design/status.md` prints for the archive (and
`results/provenance.json` for the ten it lists), except for `re1-wre1`, which was packed on
2026-10-08 (below).

| Asset (`p3-raw-...-ff2679cc8.tar.gz`) | Jobs | Host | What it holds |
|---|---|---|---|
| `2026-10-05-pilot` | pl1, wp1 | L, W | the A/A pilot (`pilot-L/`, `pilot-W/`), from which the pilot entry's `pilot.json` was computed |
| `2026-10-05-re1-wre1` | re1, wre1 | L, W | rule E's development sessions (`rule-e-L/`, `rule-e-W/`) and job files, with the evidence files the revision log names by sha256 ("Rule E's choices", item 3) |
| `2026-10-05-mr1` | mr1 | L | M2's rate sessions, development data (`m2rate-L/`, with `m2_rates.json`) |
| `2026-10-05-pc1` | pc1 (steps cl1, hl1) | L | the cost family (`cost-L/`) and the hard cases (`hard-L/`) |
| `2026-10-05-ml1` | ml1 | L | the mechanism family (`m-L/`) |
| `2026-10-05-bf1` | bf1 | L | B3's feasibility windows, development data (`b3feas-L/`); no analysis reads them |
| `2026-10-05-bk1-bs1` | bk1, bs1 | L | `K_BASE`'s windows and B3's sessions (`b3-L/`) |
| `2026-10-05-sl1-partial` | sl1 | L | the first job of section 10 on L, stopped; the B1 defect's evidence only, which no analysis reads |
| `2026-10-05-wc1-wc2` | wc1, wc2 | W | the cost family (`cost-W/`) |
| `2026-10-06-wm1` | wm1 | W | M1 on IOCP (`m-W/`) |
| `2026-10-06-wh1` | wh1 | W | the hard cases on IOCP (`hard-W/`) |
| `2026-10-07-sl3` | sl3 (a step of the chain pc2) | L | section 10 (`s-L/`) |
| `2026-10-07-ws1` | ws1 | W | section 10 (`s-W/`) |
| `2026-10-07-hc1` | hc1 (a step of the chain pc2) | L | the competitors' hard-case table (`hardcomp-L/`) |
| `2026-10-08-st1` | st1 | L | section 10's untimed windows (`st-L/`), with the wrapper `m7g/st_run.sh` and the guard `m7g/st_guard.py` that ran them |

Every archive except `re1-wre1` was packed in the laboratory after its job (`design/status.md`).
`re1-wre1` was packed on 2026-10-08 from the jobs' outputs as they lay on L and W; its four
evidence files have the sha256 values that the revision log gives.

To run the analysis or a generator of `paper/` on them, unpack each asset into a directory named
by the part of the asset's name between the date and `ff2679cc8` (for example
`unpacked/pc1/cost-L/windows.jsonl`). `results/provenance.json` holds the analysis command as it
ran, and `paper/README.md` gives each generator's command.

## `sanitizer-records/`: the records that gate the measured builds

The eight records made at the code freeze, commit `ff2679cc89d23e08a817308c9aeba7901e056fef`
(the revision log's entry "The code freeze", item 4): on L `oneport` under ASan with UBSan, TSan
and MSan (Clang 22.1.8), and the Go and Rust harnesses `harness_cmux` and `harness_hyper_util`
under ASan and TSan; on W `oneport` under ASan (MSVC 19.51.36246.0). Each is green and reports 0
sanitizer findings, and each record of `oneport` reports 0 failed tests (of 399 on L and 165 on
W). They are identical to the laboratory repository's
`lab/sanitizer-records/` and to the copies in each gate's records directory. Each record names
the sha256 of an archive of its logs; the logs are not published.

## `gates/`: the gates and what the measured builds compiled

- `gate-L.json` (sha256 `c6517177...`) and `gate-W.json` (sha256 `329d372e...`):
  `bench/check_records.py`'s outputs for the measured Release builds of L and W. Every row is
  bound to its host's gate by `bench/check_rows.py`, and the analysis reads both
  (`results/provenance.json`). `records_dir` names the directory on the host. Beside each gate,
  `measured-L.json` (sha256 `ede490f4...`) and `measured-W.json` (sha256 `82e01e6b...`) name the
  measured build of the host, as the revision log's entry "The code freeze", item 5, gives them;
  the analysis does not read them.
  On 2026-10-08, `bench/check_records.py --records lab/sanitizer-records`, run on W against W's
  measured build and on L against L's (with the harnesses' `build.json`), wrote gates equal to these
  in every field except `records_dir`. Every `*.inputs.json` in the assets names, per target, the
  inputs hash of its host's gate.
- `compiled-L.tsv` and `compiled-W.tsv`: per target of the measured build, every first-party file
  it compiled, with the file's sha256 (columns: build, target, path, sha256). They were written on
  2026-10-08 from the measured builds' Ninja trees by the laboratory's `lab/bin/inputs_hash.py`
  (sha256 `f9d526641e3ba34311ff80e395644eb26305a3266ce35629e3a1c0c7409908e7`, the version that
  every run's inputs file in the assets names). That program is not published: it also serves the
  author's other work, which it names.

The inputs hash of a target is the sha256 of the text made of one line `<path>\t<sha256>\n` per
first-party file the target compiled, sorted. The files are the translation units of the
target's objects (Ninja's compile database) and every file Ninja's dependency log records for
them. First-party means under the repository root, labelled `oneport/`, or generated into the
build tree outside FetchContent's `_deps`, labelled `build/`. Paths use forward slashes and are
lower-cased on Windows, and a file is hashed with CRLF read as LF. With the lists, the hashes can
be recomputed with Python alone. Every file under `oneport/` in both lists has the sha256 of the
code freeze's file, and the hash of every target equals its gate's. The two `build/` files are made
by CMake's `configure_file` from `bench/tls/test_material.cpp.in` and
`bench/cases/clienthello_hex.cpp.in`, so their lines are checked by running CMake's configure step
at the code freeze. From a checkout, for L's list (W's list runs the same way):

```python
import collections, hashlib, subprocess

def blob(path):  # the file at the code freeze, CRLF read as LF
    data = subprocess.run(["git", "show", "ff2679cc89d23e08a817308c9aeba7901e056fef:" + path],
                          capture_output=True, check=True).stdout
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()

lines = collections.defaultdict(list)
for row in open("lab/gates/compiled-L.tsv", encoding="utf-8"):
    build, target, path, sha = row.rstrip("\n").split("\t")
    if path.startswith("oneport/"):
        assert blob(path[len("oneport/"):]) == sha, path
    lines[target].append(f"{path}\t{sha}\n")
for target, rows in sorted(lines.items()):
    print(target, hashlib.sha256("".join(sorted(rows)).encode()).hexdigest())
```

The harnesses' inputs hashes come from `bench/competitors/harness_inputs.py`, which is in this
repository.

## `analysis-inputs/`: the other files the analysis read

- `pilot.json` (sha256 `bc48a736...`): the simulation's output that the pilot entry was made
  from (the revision log's entry "The pilot entry", item 3); `analysis/analyse.py --pilot`.
- `rule_e.json` (sha256 `fb50302a...`): rule E's choices (the entry "Rule E's choices", item 3);
  `analysis/analyse.py --rule-e`. The sessions behind it are the asset `re1-wre1`.

The analysis also read `design/seeds.json` and the two gates above.

## Not published

- The laboratory repository's programs that the scripts of `bench/` call: `lab/bin/inputs_hash.py`
  (its rule is above), `lab/bin/pin.sh` (the host settings it sets are recorded in each row's
  fingerprint) and the lab lock `lab/bin/lablock`; and `lab/bin/test_report_pattern.sh` and
  `lab/bin/sanitize.sh`, which a test and a comment name. The scripts' defaults point at that
  repository. Its `lab/t1/t1.py`, which comments cite for the generator's rules, is published byte
  for byte in `lab/t1/` of https://github.com/Alex-Tsvetanov/paper-typed-routing.
- The laboratory journal, `lab/journal.jsonl` of that repository. It logs the runs of this and of
  the author's other work. The seeds of `design/seeds.json` were drawn with every integer it named
  excluded (the revision log's entry "The seeds of section 4.7 (M7d)").
- The archives of the records' logs, and the hosts' working directories outside the archived ones.
- Other host files that the revision log, the design notes or the results files name by sha256 and
  that no asset holds, for example the seeds draw's script and log, the logs of the simulation and
  analysis jobs, the checks of the B1 change on W and the job scripts of the earlier jobs.
- The raw outputs of the development runs before the pilot entry.
