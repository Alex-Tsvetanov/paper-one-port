"""Tests of paper/hardcase_macros.py.

    python -m pytest paper/test_hardcase_macros.py

SYNTHETIC rows and tables in pytest's temporary directory, in the forms the hard-case runners write
(bench/run/hardcase_run.py, part server): a run that reached the judge has `b2` and `b2_failed`,
one that did not has a reason in `b1` and no row in the table. The committed
results/hardcase-macros.tex is checked for its names and its inputs, since its archived inputs are
not in the repository.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import hardcase_macros as H  # noqa: E402
import test_design_macros as TD  # noqa: E402  the names analysis/macros.py can emit

FREEZE = {"freeze": {"freeze": {"code_freeze": H.CODE_FREEZE}}}
JOBS = {"hl1": "L", "wh1": "W"}


def tagged(row: dict, job: str) -> dict:
    host = JOBS[job]
    row.update(job=job, development=False, runner=H.RUNNER_OF[host][0], provenance=FREEZE)
    if host == "W":
        row["host"] = "W"
    return row


def run_row(entry: str, vid: str, rep: int, job: str, b1=(), b2_failed=(), judged=True, wakeups=1) -> dict:
    row = {"kind": "hardcase", "entry": entry, "id": vid, "hc": 1, "replicate": rep, "b1": list(b1)}
    if judged:
        row.update(b2={k: (["late"] if k in b2_failed else []) for k in "abcde"}, b2_failed=sorted(b2_failed), wakeups=wakeups,
                   passed=not b1 and not b2_failed)
    else:
        row.update(passed=False, b2={})
    return tagged(row, job)


def server_row(entry: str, job: str, ok=True) -> dict:
    return tagged({"kind": "hardcase-servers", "entry": entry, "server": "one-port plain", "ok": ok,
                   "problems": [] if ok else ["1 connection left open"]}, job)


def table_of(rows: list[dict]) -> dict:
    """The runner's table: the runs that reached the judge, per variant and entry."""
    t: dict = {}
    for r in rows:
        if r.get("kind") != "hardcase" or "b2_failed" not in r:
            continue
        e = t.setdefault(f"{r['entry']}|{r['id']}", {"entry": r["entry"], "id": r["id"], "hc": r["hc"], "runs": 0, "passed": 0,
                                                     "woke_twice": 0})
        e["runs"] += 1
        e["passed"] += int(r["passed"])
        e["woke_twice"] += int(r["wakeups"] >= 2)
    return t


IDS = ("HC01.HTTP", "HC02.TLS.k01")


def clean(job: str, ids=IDS) -> list[dict]:
    entries = H.runner_entries(JOBS[job])
    rows = [run_row(e, v, k, job, wakeups=3 if v.startswith("HC02") else 1) for e in entries for v in ids
            for k in range(1, H.REPLICATES + 1)]
    return rows + [server_row(e, job) for e in entries]


def write(tmp: Path, name: str, rows: list[dict], table: dict | None = None) -> tuple[Path, Path]:
    rp, tp = tmp / f"{name}.jsonl", tmp / f"{name}-table.json"
    rp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tp.write_text(json.dumps(table_of(rows) if table is None else table), encoding="utf-8")
    return rp, tp


def summary(tmp: Path, b1_failures=()) -> Path:
    p = tmp / "summary.json"
    p.write_text(json.dumps({"synthetic": False, "b1_failures": list(b1_failures)}), encoding="utf-8")
    return p


def macros(text: str) -> dict[str, str]:
    return dict(re.findall(r"^\\newcommand\{\\([A-Za-z]+)\}\{([^}]*(?:\{,\}[^}]*)*)\}", text, flags=re.M))


def build(tmp: Path, l_rows: list[dict], w_rows: list[dict] | None = None, l_table=None, b1_failures=()) -> dict[str, str]:
    lr, lt = write(tmp, "L", l_rows, l_table)
    servers = [("L", "hl1", lr, lt)]
    if w_rows is not None:
        wr, wt = write(tmp, "W", w_rows)
        servers.append(("W", "wh1", wr, wt))
    return macros(H.build(servers, summary(tmp, b1_failures)))


def replace(rows: list[dict], i: int, **kw) -> list[dict]:
    r = rows[i]
    out = list(rows)
    out[i] = run_row(r["entry"], r["id"], r["replicate"], r["job"], **kw)
    return out


def test_the_runners_entries():
    assert len(H.runner_entries("L")) == 8 and "io_uring.peek.relay" in H.runner_entries("L")
    assert H.runner_entries("W") == ("IOCP.replay.inproc", "IOCP.peek.inproc")


def test_all_runs_pass(tmp_path):
    m = build(tmp_path, clean("hl1"), clean("wh1"))
    assert m["HardcaseLRuns"] == "256" and m["HardcaseLPassed"] == "256" and m["HardcaseWRuns"] == "64"
    assert m["HardcaseLEntries"] == "8" and m["HardcaseLVariantEntries"] == "16" and m["HardcaseLWokeMoreThanOnce"] == "128"
    assert m["HardcaseLServerChecks"] == "8" and m["HardcaseLServerChecksOk"] == "8" and m["HardcaseLIncomplete"] == "0"
    assert m["HardcaseRuns"] == "320" and m["HardcaseBOneDeviations"] == "0" and m["HardcaseBTwoFailures"] == "0"
    assert m["BOneVerdict"] == "holds" and m["BTwoVerdict"] == "holds"


def test_one_b1_deviation_fails_b1_only(tmp_path):
    m = build(tmp_path, replace(clean("hl1"), 5, b1=["reply differs from the dedicated port's"]))
    assert m["HardcaseLBOneDeviations"] == "1" and m["HardcaseLPassed"] == "255"
    assert m["BOneVerdict"] == "does not hold" and m["BTwoVerdict"] == "holds"


def test_one_b2_failure_fails_b2_only(tmp_path):
    rows = replace(clean("hl1"), 7, b2_failed=["d"])
    text = H.build([("L", "hl1", *write(tmp_path, "L", rows))], summary(tmp_path))
    m = macros(text)
    assert m["HardcaseLBTwoFailures"] == "1" and m["BTwoVerdict"] == "does not hold" and m["BOneVerdict"] == "holds"
    assert "% deviation: L epoll.replay.inproc HC01.HTTP r8: b1=[] b2_failed=['d']" in text


def test_a_run_that_never_reached_the_judge_is_a_deviation(tmp_path):
    m = build(tmp_path, replace(clean("hl1"), 0, b1=["connect failed"], judged=False))
    assert m["HardcaseLBOneDeviations"] == "1" and m["HardcaseLRuns"] == "256" and m["BOneVerdict"] == "does not hold"


def test_measured_window_failure_fails_b1(tmp_path):
    m = build(tmp_path, clean("hl1"), b1_failures=[{"cell": "S.mixed.C1.L.epoll", "misclassified": 3}])
    assert m["BOneVerdict"] == "does not hold" and m["HardcaseBOneDeviations"] == "0"


def test_missing_replicate_entry_or_variant_fails_b1(tmp_path):
    rows = clean("hl1")
    one = [r for r in rows if not (r.get("id") == "HC01.HTTP" and r.get("replicate") == 16 and r.get("entry") == "epoll.peek.inproc")]
    m = build(tmp_path, one)
    assert m["HardcaseLIncomplete"] == "1" and m["BOneVerdict"] == "does not hold"
    no_entry = [r for r in rows if r.get("entry") != "io_uring.peek.relay"]
    m = build(tmp_path, no_entry)
    assert m["HardcaseLIncomplete"] == "2" and m["HardcaseLEntries"] == "7" and m["BOneVerdict"] == "does not hold"
    no_variant = [r for r in rows if not (r.get("entry") == "epoll.replay.relay" and r.get("id") == "HC02.TLS.k01")]
    m = build(tmp_path, no_variant)
    assert m["HardcaseLIncomplete"] == "1" and m["BOneVerdict"] == "does not hold"


def test_failed_server_check_is_counted_not_decided(tmp_path):
    rows = clean("hl1")
    rows[-1] = server_row(rows[-1]["entry"], "hl1", ok=False)
    m = build(tmp_path, rows)
    assert m["HardcaseLServerChecksOk"] == "7" and m["BOneVerdict"] == "holds"


def test_refusals(tmp_path):
    rows = clean("hl1")
    bad_table = table_of(rows)
    next(iter(bad_table.values()))["passed"] -= 1
    with pytest.raises(H.InputRefused, match="table and the rows disagree"):
        build(tmp_path, rows, l_table=bad_table)
    for change, msg in (({"development": True}, "not a frozen run"), ({"job": "hl2"}, "job"),
                        ({"provenance": {"freeze": {"freeze": {"code_freeze": "0" * 40}}}}, "code_freeze"),
                        ({"runner": "whardcase_run"}, "runner"), ({"host": "W"}, "runner"),
                        ({"b2_failed": []}, "b2_failed does not list"), ({"passed": False}, "passed disagrees"),
                        ({"b2_failed": ""}, "b2_failed does not list"), ({"entry": "epoll.replay.splice"}, "not in")):
        bad = clean("hl1")
        bad[3] = dict(bad[3], **change)
        if change.get("b2_failed") == []:
            bad[3]["b2"] = dict(bad[3]["b2"], d=["late"])
        with pytest.raises(H.InputRefused, match=msg):
            build(tmp_path, bad, l_table=table_of(clean("hl1")) if "entry" not in change and "passed" not in change else None)
    unjudged = clean("hl1")
    unjudged[2] = run_row(unjudged[2]["entry"], unjudged[2]["id"], unjudged[2]["replicate"], "hl1", judged=False)
    with pytest.raises(H.InputRefused, match="did not reach the judge"):
        build(tmp_path, unjudged)
    dup = clean("hl1")
    dup.append(dict(dup[0]))
    with pytest.raises(H.InputRefused, match="two rows"):
        build(tmp_path, dup, l_table=table_of(dup[:-1]))
    lr, lt = write(tmp_path, "L", clean("hl1"))
    s = tmp_path / "synthetic.json"
    s.write_text(json.dumps({"synthetic": True, "b1_failures": []}), encoding="utf-8")
    with pytest.raises(H.InputRefused, match="synthetic"):
        H.build([("L", "hl1", lr, lt)], s)
    with pytest.raises(H.InputRefused, match="host letter"):
        H.build([("L", "hl1", lr, lt), ("L", "hl1", lr, lt)], summary(tmp_path))


def test_cli_writes_inputs_with_sha256(tmp_path):
    lr, lt = write(tmp_path, "L", clean("hl1"))
    out = tmp_path / "hardcase-macros.tex"
    assert H.main(["--server", "L", "hl1", str(lr), str(lt), "--summary", str(summary(tmp_path)), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith(H.HEAD)
    assert f"% input: L hl1 L.jsonl sha256 {H.sha256_file(lr)}" in text
    assert f"% input: L hl1 L-table.json sha256 {H.sha256_file(lt)}" in text
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(dict(clean("hl1")[0], development=True)) + "\n", encoding="utf-8")
    assert H.main(["--server", "L", "hl1", str(bad), str(lt), "--summary", str(summary(tmp_path)), "--out", str(out)]) == 2


def emitted_names(text: str) -> list[str]:
    return re.findall(r"^\\newcommand\{\\([^}]*)\}", text, flags=re.M)


def design_names() -> set[str]:
    """paper/design_macros.py's names: from the generator when it runs against the current log, else
    from its committed file (the generator stops when a pattern matches the log twice)."""
    try:
        return {n for n, _, _ in TD.items()}
    except Exception:  # noqa: BLE001
        return set(emitted_names((HERE.parent / "results" / "design-macros.tex").read_text(encoding="utf-8")))


def test_names_collide_with_no_other_generator(tmp_path):
    text = H.build([("L", "hl1", *write(tmp_path, "L", clean("hl1"))), ("W", "wh1", *write(tmp_path, "W", clean("wh1")))],
                   summary(tmp_path))
    names = emitted_names(text)
    assert names and all(re.fullmatch(r"[A-Za-z]+", n) for n in names) and len(names) == len(set(names))
    fixed, prefixes = TD.macros_py_names()
    design = design_names()
    results = HERE.parent / "results" / "macros.tex"
    emitted = set(emitted_names(results.read_text(encoding="utf-8"))) if results.exists() else set()
    for n in names:
        assert n not in fixed and not n.startswith(prefixes) and n not in design and n not in emitted, n


def test_committed_file_names_and_inputs():
    path = HERE.parent / "results" / "hardcase-macros.tex"
    if not path.exists():
        pytest.skip("results/hardcase-macros.tex is not written yet")
    text = path.read_text(encoding="utf-8")
    assert text.startswith(H.HEAD)
    names = emitted_names(text)
    assert all(re.fullmatch(r"[A-Za-z]+", n) for n in names) and len(names) == len(set(names))
    inputs = re.findall(r"^% input: (.+) sha256 ([0-9a-f]{64})$", text, flags=re.M)
    assert len(inputs) == 2 * sum(1 for n in names if re.fullmatch(r"Hardcase[A-Z]Runs", n)) + 1
    m = macros(text)
    assert m["BOneVerdict"] in ("holds", "does not hold") and m["BTwoVerdict"] in ("holds", "does not hold")
