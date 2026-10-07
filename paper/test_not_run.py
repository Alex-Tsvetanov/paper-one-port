"""Tests of paper/not_run.py.

    python -m pytest paper/test_not_run.py

SYNTHETIC summary, not-run files and rows in pytest's temporary directory, with cell ids of the
real cell lists so that the logged entries (read from the real hypotheses.md and status.md) apply.
The committed results/not-run.json is checked for its form, since its archived inputs are not in
the repository.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import not_run as N  # noqa: E402


def summary(tmp: Path, fam_cells=(), sec=(), synthetic=False) -> Path:
    s = {"synthetic": synthetic, "families": {"M": {"cells": list(fam_cells)}}, "secondary": list(sec)}
    p = tmp / f"summary-{len(list(tmp.glob('summary-*.json')))}.json"   # a new file each time
    p.write_text(json.dumps(s), encoding="utf-8")
    return p


def fam(cell: str, valid: int, R: int = 16, verdict: str = "untested") -> dict:
    return {"cell": cell, "valid_sessions": valid, "R": R, "verdict": verdict}


def sec(cell: str, valid: int, bullet: str, R: int = 16, interval=None) -> dict:
    return {"cell": cell, "valid_sessions": valid, "R": R, "bullet": bullet, "metric": "value", "interval": interval,
            "why": f"{valid} valid sessions, fewer than R = {R}: no draw (4.7)"}


def window(cell: str, session: str, arm: str, valid: bool, reasons=(), workload="churn", rate=None, metric="conn_per_s") -> dict:
    return {"cell": cell, "session": session, "arm": arm, "valid": valid, "invalid_reasons": list(reasons), "job": "sl3", "development": False,
            "workload": workload, "rate": rate, "metric": {"name": metric, "value": 1.0}}


def write_json(tmp: Path, name: str, obj) -> Path:
    p = tmp / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def write_rows(tmp: Path, rows: list[dict]) -> Path:
    p = tmp / f"windows-{len(list(tmp.glob('windows-*.jsonl')))}.jsonl"   # a new file each time
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


SSLH = "S.m-ttfb.M3.L.epoll.http1.sslh-ev"
NGINX = "S.m-ttfb.M3.L.epoll.http1.nginx"


def dataset(tmp: Path):
    s = summary(tmp, fam_cells=[fam("M2.L.epoll.tls", 0), fam("M1.L.epoll.http1", 16)],
                sec=[sec("S.ssh.C2.L.epoll", 0, "ssh"), sec(SSLH, 0, "m-ttfb-cpu"), sec(NGINX, 16, "m-ttfb-cpu", interval=[1, 2]),
                     sec("S.tls-variants.C1.L.epoll.resumption", 0, "tls-variants")])
    nr1 = write_json(tmp, "not-run-ml1.json", {"M2.L.epoll.tls": "not run: no M2_RATE"})
    nr2 = write_json(tmp, "not-run-sl3.json", {"S.tls-variants.C1.L.epoll.resumption": "not run: no session tickets",
                                               "S.ssh.C1.W.IOCP": "W's cell, run by W's runner (bench/run/ws_run.py)"})
    nr3 = write_json(tmp, "not-run-ws1.json", {"S.tls-variants.C1.L.epoll.resumption": "not run: no session tickets",
                                               "S.ssh.C2.L.epoll": "L's cell, run by L's runner (bench/run/s_run.py)"})
    rows = [window("S.ssh.C2.L.epoll", f"s{k}", arm, False, ["opgen wrote no report (exit 2)"], workload="keepalive", metric=None)
            for k in range(2) for arm in "AB"]
    rows += [window(SSLH, f"s{k}", "A", True) for k in range(2)]
    rows += [window(SSLH, f"s{k}", "B", False, [f"errors 0.{k}6% > 0.1%"]) for k in range(2)]
    rows += [window(NGINX, f"s{k}", arm, True, workload="open", rate=6000.5, metric="ttfb_median_us") for k in range(2) for arm in "AB"]
    rows += [window("M1.L.epoll.http1", "s1", "A", True)]
    return s, [nr1, nr2, nr3], [write_rows(tmp, rows)]


def test_cells_reasons_and_counts(tmp_path):
    s, nr, rows = dataset(tmp_path)
    out = N.build(s, nr, rows)
    cells = {c["cell"]: c for c in out["cells"]}
    assert sorted(cells) == ["M2.L.epoll.tls", "S.m-ttfb.M3.L.epoll.http1.sslh-ev", "S.ssh.C2.L.epoll",
                             "S.tls-variants.C1.L.epoll.resumption"]
    assert cells["M2.L.epoll.tls"]["status"] == "not run"
    assert cells["M2.L.epoll.tls"]["not_run_reason"] == [{"text": "not run: no M2_RATE", "files": ["not-run-ml1.json"]}]
    assert cells["S.tls-variants.C1.L.epoll.resumption"]["not_run_reason"] == [
        {"text": "not run: no session tickets", "files": ["not-run-sl3.json", "not-run-ws1.json"]}]
    ssh = cells["S.ssh.C2.L.epoll"]
    assert ssh["status"] == "ran, short of R" and ssh["rows"]["windows"] == 4 and ssh["rows"]["sessions"] == 2
    assert ssh["rows"]["invalid_reasons_numbers_as_N"] == {"opgen wrote no report (exit N)": 4}
    assert any(r.get("entry") == N.B1_ENTRY for r in ssh["logged_in"]) and ssh["quotes"]
    sl = cells[SSLH]
    assert sl["rows"]["by_arm"] == {"A": {"windows": 2, "valid_windows": 2}, "B": {"windows": 2, "valid_windows": 0}}
    assert sl["rows"]["invalid_reasons_numbers_as_N"] == {"errors N% > N%": 2}
    assert {r.get("entry") for r in sl["logged_in"]} >= {N.SSLH_ENTRY}
    for c in cells.values():
        assert c["logged_in"], c["cell"]


def test_m_ttfb_cell_without_a_rate_is_noted(tmp_path):
    s, nr, rows = dataset(tmp_path)
    notes = N.build(s, nr, rows)["m_ttfb_cells_that_ran_without_a_rate"]
    assert notes == [{"cell": SSLH, "windows": 4, "sessions": 2, "valid_sessions": 0,
                      "its_workloads": {"workload churn, no rate, metric conn_per_s": 4},
                      "other_cells": {"prefix": "S.m-ttfb.M3.L.epoll.", "workloads": {"workload open, a rate, metric ttfb_median_us": 4}}}]


def test_refusals(tmp_path, monkeypatch):
    s, nr, rows = dataset(tmp_path)
    both = write_json(tmp_path, "not-run-x.json", {"S.ssh.C2.L.epoll": "not run: x"})
    with pytest.raises(N.InputRefused, match="both rows and a not-run reason"):
        N.build(s, nr + [both], rows)
    with pytest.raises(N.InputRefused, match="neither rows nor a not-run reason"):
        N.build(s, nr[1:], rows)
    with pytest.raises(N.InputRefused, match="synthetic"):
        N.build(summary(tmp_path, synthetic=True), nr, rows)
    with pytest.raises(N.InputRefused, match="given twice"):
        N.build(s, nr, rows + rows)
    lines = rows[0].read_text(encoding="utf-8").splitlines()
    dev = write_rows(tmp_path, [dict(json.loads(lines[0]), development=True)] + [json.loads(x) for x in lines[1:]])
    with pytest.raises(N.InputRefused, match="not of a frozen run"):
        N.build(s, nr, [dev])
    twice = write_rows(tmp_path, [json.loads(x) for x in lines + lines[:1]])
    with pytest.raises(N.InputRefused, match="two rows of"):
        N.build(s, nr, [twice])
    with pytest.raises(N.InputRefused, match="an interval with"):
        N.build(summary(tmp_path, sec=[sec("S.ssh.C2.L.epoll", 3, "ssh", interval=[0.9, 1.1])]), nr, rows)
    s2 = summary(tmp_path, fam_cells=[fam("M1.L.epoll.http1", 3)])
    with pytest.raises(N.InputRefused, match="no logged entry"):
        N.build(s2, nr, rows)
    s3 = summary(tmp_path, fam_cells=[fam("M2.L.epoll.tls", 0)])
    monkeypatch.setattr(N, "LOGGED", [(r"^M2\.", [N.H("2026-10-04: no such entry", "item 1")], [])])
    with pytest.raises(N.InputRefused, match="no single entry"):
        N.build(s3, nr, rows)
    monkeypatch.setattr(N, "LOGGED", [(r"^M2\.", [N.H(N.W_ENTRY, "item 2")], [("hypotheses.md", "a sentence the log never wrote")])])
    with pytest.raises(N.InputRefused, match="occurs 0 times"):
        N.build(s3, nr, rows)
    monkeypatch.setattr(N, "LOGGED", [(r"^M2\.", [N.S(N.COST_L, "9. No such subsection")], [])])
    with pytest.raises(N.InputRefused, match="no single subsection"):
        N.build(s3, nr, rows)


def test_numbers_are_written_n():
    assert N.number_free("errors 0.572% > 0.1%") == "errors N% > N%"
    assert N.number_free("TIME-WAIT count 12 at sample 2, 3 at the baseline") == "TIME-WAIT count N at sample N, N at the baseline"
    assert N.number_free("probe failed: http1: failed (timeout)") == "probe failed: http1: failed (timeout)"
    assert N.number_free("opgen wrote no report (exit 2) for h2c") == "opgen wrote no report (exit N) for h2c"


def test_every_logged_reference_and_quote_exists():
    texts = {k: p.read_text(encoding="utf-8") for k, p in N.SOURCES.items()}
    for _, refs, quotes in N.LOGGED:
        for r in refs:
            N.check_reference(r, texts)
        for src, q in quotes:
            assert N.normalised(texts[src]).count(q) == 1, q[:60]


def test_cli(tmp_path):
    s, nr, rows = dataset(tmp_path)
    out = tmp_path / "not-run.json"
    args = ["--summary", str(s), "--out", str(out)] + [x for p in nr for x in ("--not-run", str(p))] + ["--rows", str(rows[0])]
    assert N.main(args) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert [i["role"] for i in d["inputs"]] == ["summary", "not-run", "not-run", "not-run", "rows"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", i["sha256"]) for i in d["inputs"])
    assert N.main(["--summary", str(s), "--out", str(out), "--rows", str(rows[0])]) == 2


def test_committed_file_form():
    path = HERE.parent / "results" / "not-run.json"
    if not path.exists():
        pytest.skip("results/not-run.json is not written yet")
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d["made_by"] == "paper/not_run.py" and d["cells"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", i["sha256"]) for i in d["inputs"])
    assert re.fullmatch(r"[0-9a-f]{40}", d["logged_entries_read_at"]["commit"])
    for c in d["cells"]:
        assert c["status"] in ("not run", "ran, short of R") and c["logged_in"] and c["valid_sessions"] < c["R"]
        assert ("rows" in c) == (c["status"] == "ran, short of R") and ("not_run_reason" in c) == (c["status"] == "not run")
