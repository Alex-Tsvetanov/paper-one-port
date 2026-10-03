#!/usr/bin/env python3
"""The whole pipeline on synthetic rows: pilot.py, analyse.py, macros.py, with known answers.

    python -m pytest analysis/test_analyse.py

SYNTHETIC DATA (analysis/synth.py). Every file this test writes lies in pytest's temporary
directory; the test also checks that the tools refuse to write synthetic outputs under results/.

Known answers, by construction of the session values:
- cost (R_C = 11 from the synthetic pilot; m_C = 9): HTTP/1.1 on epoll equivalent in C1, C2 and C3
  (the claim); h2c's C1 at 0.95 and C3 at 1.05 a measured cost; h2c's C2 at 1.05 outside the
  margin in one-port mode's favour; TLS's C1 noisy, not shown; MQTT's C1 with an invalid window,
  run again, equivalent; HTTP/1.1 on io_uring with its reruns spent, untested; HTTP/1.1 on IOCP
  not resolved by the pilot, reported as such with its interval;
- B3 (R_B = 16): nginx at Q = 1.5 shown; sslh-ev at 0.93 not shown, a loss; HAProxy at 1.0 not
  shown, no loss; nginx's partial-ClientHello cell with one session whose W_srv is 0 (Q = 0),
  still shown with 15 of 16; Envoy on io_uring with an invalid window run again, shown; Netty
  descriptive;
- M (R_M = 16): M1 at 1.05 shown, M1 on IOCP at 0.98 not; M2 at 0.70 shown, M2 TLS at 1.03 not;
  M3 nginx at 1.2 shown; M3 HAProxy at 0.9 a loss; M3 sslh-ev with every session invalid,
  untested;
- the gate refuses a B3 row without binaries; development, dry-run and unmarked rows are refused;
- the draws follow 4.7's order; the same inputs give the same bytes.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import analyse as AN  # noqa: E402
import cells as C  # noqa: E402
import macros as MC  # noqa: E402
import pilot as PL  # noqa: E402
import rows as RW  # noqa: E402
import stats as S  # noqa: E402
import synth as SY  # noqa: E402

SEEDS = {n: 5000 + 7 * i for i, n in enumerate(C.SEED_NAMES)}
RULE_E = {"default": {"epoll": "replay", "io_uring": "replay", "IOCP": "replay"}, "relay_copy": "user-space",
          "iocp_receive": "zero-byte"}
RESOLVED = ["C1.L.epoll.http1", "C1.L.epoll.h2c", "C1.L.epoll.tls", "C1.L.epoll.mqtt", "C1.L.io_uring.http1",
            "C2.L.epoll.http1", "C2.L.epoll.h2c", "C3.L.epoll.http1", "C3.L.epoll.h2c"]


# ---------------------------------------------------------------- the dataset (SYNTHETIC)


def pilot_rows() -> list[dict]:
    low = {cid: 0.002 for cid in RESOLVED}
    rows = SY.aa_pilot_rows(low, SEEDS, seed=10, job="pilot")
    rows += SY.aa_pilot_rows({"C1.W.IOCP.http1": 0.06}, SEEDS, seed=11, job="pilot")
    return rows


def pilot_parts() -> list[dict]:
    parts = []
    for b in PL.SPLIT_BACKENDS:
        for k in range(1, 4):
            parts.append({"part": "timer", "backend": b, "mode": "dedicated", "run": k, "valid": True, "invalid_reasons": [],
                          "lateness_ns": 400_000 * k, "synthetic": True, "provenance": SY.provenance()})
        for g in PL.GAPS_MS:
            parts.append({"part": "split", "backend": b, "mode": "dedicated", "gap_ms": g, "replicate": 0, "valid": True,
                          "invalid_reasons": [], "recv_data": 2, "synthetic": True, "provenance": SY.provenance()})
    return parts


def cost_cell_rows(rng, cid: str, values: list[float], job: str = "c", invalid_first: int = 0, extra_invalid: int = 0) -> list[dict]:
    """Sessions of one cost cell with the given ratios; the first `invalid_first` sessions get an
    invalid window and are run again at the end (a rerun takes the same ratio); `extra_invalid`
    more sessions are invalid with no rerun (the cap spent)."""
    hyp, host, backend, proto = cid.split(".")
    out = []
    base = 120.0 if hyp == "C3" else 40000.0
    for k, v in enumerate(values, 1):
        jb = f"{job}-{host}" + ("-b" if k > len(values) // 2 else "")
        bad = k <= invalid_first
        out += SY.cost_session(rng, jb, f"{cid}-s{k:02d}", hyp=hyp, proto=proto, backend=backend, ratio=v, base=base,
                               invalid_position=2 if bad else None)
        if bad:
            out += SY.cost_session(rng, jb, f"{cid}-s{k:02d}-rerun", hyp=hyp, proto=proto, backend=backend, ratio=v, base=base)
    for k in range(extra_invalid):
        out += SY.cost_session(rng, f"{job}-{host}", f"{cid}-x{k:02d}", hyp=hyp, proto=proto, backend=backend, ratio=1.0,
                               base=base, invalid_position=0)
    return out


def b3_cell_rows(rng, cid: str, qs: list[float], invalid_first: int = 0, zero_server: int | None = None) -> list[dict]:
    _, case, system, backend = cid.split(".")
    out = []
    for k, q in enumerate(qs, 1):
        w_srv = 0.0 if k == zero_server else 7000.0
        out += SY.b3_session(rng, "b3", f"{cid}-s{k:02d}", system=system, case=case, backend=backend, q=q, w_srv=w_srv,
                             invalid_position=1 if k <= invalid_first else None)
        if k <= invalid_first:
            out += SY.b3_session(rng, "b3", f"{cid}-s{k:02d}-rerun", system=system, case=case, backend=backend, q=q)
    return out


def m_cell_rows(rng, cid: str, ratios: list[float], all_invalid: bool = False, bullet: str | None = None) -> list[dict]:
    cell = C.all_family_cells()[cid]
    out = []
    for k, r in enumerate(ratios, 1):
        out += SY.m_session(rng, "m", f"{bullet or 'm'}-{cid}-s{k:02d}", cell, r, invalid_position=0 if all_invalid else None,
                            bullet=bullet)
    return out


def dataset() -> list[dict]:
    rng = np.random.default_rng(2026)
    r = 11
    rows: list[dict] = []
    eq = lambda: SY.spread(rng, 1.0, 0.004, r)  # noqa: E731
    for cid in ("C1.L.epoll.http1", "C2.L.epoll.http1", "C3.L.epoll.http1"):
        rows += cost_cell_rows(rng, cid, eq())
    rows += cost_cell_rows(rng, "C1.L.epoll.h2c", SY.spread(rng, 0.95, 0.004, r))
    rows += cost_cell_rows(rng, "C3.L.epoll.h2c", SY.spread(rng, 1.05, 0.004, r))
    rows += cost_cell_rows(rng, "C2.L.epoll.h2c", SY.spread(rng, 1.05, 0.004, r))
    rows += cost_cell_rows(rng, "C1.L.epoll.tls", SY.spread(rng, 1.0, 0.05, r))
    rows += cost_cell_rows(rng, "C1.L.epoll.mqtt", eq(), invalid_first=1)
    rows += cost_cell_rows(rng, "C1.L.io_uring.http1", eq()[:8], extra_invalid=3)
    rows += cost_cell_rows(rng, "C1.W.IOCP.http1", SY.spread(rng, 1.01, 0.01, r))
    # a fault row in place of one window: the session is invalid and is run again
    fault = cost_cell_rows(rng, "C2.L.epoll.h2c", [1.05], job="fault")
    fault[1] = SY.fault_row(fault[1]["job"], "C2.L.epoll.h2c-fault", fault[1]["arm"], 1, "keepalive.h2c.epoll")
    for w in fault:
        w["session"] = "C2.L.epoll.h2c-fault"
    rows += fault
    # B3
    rows += b3_cell_rows(rng, "B3.silent.nginx.epoll", SY.spread(rng, 1.5, 0.05, 16))
    rows += b3_cell_rows(rng, "B3.silent.sslh-ev.epoll", SY.spread(rng, 0.93, 0.01, 16))
    rows += b3_cell_rows(rng, "B3.silent.haproxy.epoll", SY.spread(rng, 1.0, 0.05, 16))
    rows += b3_cell_rows(rng, "B3.partial-hello.nginx.epoll", SY.spread(rng, 1.4, 0.05, 16), zero_server=3)
    rows += b3_cell_rows(rng, "B3.silent.envoy.io_uring", SY.spread(rng, 1.3, 0.05, 16), invalid_first=2)
    rows += b3_cell_rows(rng, "B3.silent.netty.epoll", SY.spread(rng, 2.0, 0.05, 16))
    rows += [SY.ophold_window("ophold", k, 6000.0 + 10 * k) for k in range(16)]
    # M
    rows += m_cell_rows(rng, "M1.L.epoll.http1", SY.spread(rng, 1.05, 0.01, 16))
    rows += m_cell_rows(rng, "M1.W.IOCP.h2c", SY.spread(rng, 0.98, 0.01, 16))
    rows += m_cell_rows(rng, "M2.L.epoll.http1", SY.spread(rng, 0.70, 0.02, 16))
    rows += m_cell_rows(rng, "M2.L.epoll.tls", SY.spread(rng, 1.03, 0.01, 16))
    rows += m_cell_rows(rng, "M3.L.epoll.tls-stub.nginx", SY.spread(rng, 1.2, 0.02, 16))
    rows += m_cell_rows(rng, "M3.L.epoll.http1.haproxy", SY.spread(rng, 0.9, 0.01, 16))
    rows += m_cell_rows(rng, "M3.L.epoll.tls-stub.sslh-ev", [1.1] * 16, all_invalid=True)
    # secondary cells with sessions of their own
    for k, v in enumerate(SY.spread(rng, 1.01, 0.01, 16), 1):
        rows += SY.cost_session(rng, "s", f"ssh-s{k:02d}", hyp="C1", proto="ssh", backend="epoll", ratio=v, family="S",
                                extra={"bullet": "ssh"})
    rows += m_cell_rows(rng, "M1.L.epoll.http1", SY.spread(rng, 0.97, 0.01, 16), bullet="m-ttfb")
    for k, q in enumerate(SY.spread(rng, 1.1, 0.02, 16), 1):
        sess = []
        for pos, arm in enumerate(SY.x_first(rng, ("A", "B"))):
            sess.append(SY.b3_window("b3s", f"other-s{k:02d}", arm, pos, system=C.SERVER_RELAY, case="silent", backend="epoll",
                                     W=7000.0 * (q if arm == "B" else 1.0), detect="peek" if arm == "B" else "replay",
                                     family="S", bullet="b3-other-mode"))
        rows += sess
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    return path


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """The whole pipeline through the command-line tools, twice, into a temporary directory."""
    d = tmp_path_factory.mktemp("synthetic")
    write_jsonl(d / "pilot.jsonl", pilot_rows())
    write_jsonl(d / "parts.jsonl", pilot_parts())
    write_jsonl(d / "windows.jsonl", dataset())
    (d / "seeds.json").write_text(json.dumps(SEEDS), encoding="utf-8")
    (d / "rule_e.json").write_text(json.dumps(RULE_E), encoding="utf-8")
    (d / "gate.json").write_text(json.dumps(SY.gate_json()), encoding="utf-8")
    py = sys.executable
    r = subprocess.run([py, str(HERE / "pilot.py"), "--seeds", str(d / "seeds.json"), "--gate", str(d / "gate.json"), "--rows",
                        str(d / "pilot.jsonl"), "--parts", str(d / "parts.jsonl"), "--out", str(d / "pilot.json"),
                        "--allow-synthetic", "--n-sim", "20", "--workers", "2"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    outs = []
    for k in (1, 2):
        out = d / f"out{k}"
        cmd = [py, str(HERE / "analyse.py"), "--seeds", str(d / "seeds.json"), "--pilot", str(d / "pilot.json"), "--rule-e",
               str(d / "rule_e.json"), "--gate", str(d / "gate.json"), "--rows", str(d / "windows.jsonl"), "--out", str(out),
               "--allow-synthetic"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "SYNTHETIC" in r.stdout
        r = subprocess.run([py, str(HERE / "macros.py"), str(out / "summary.json"), "--out", str(out / "macros.tex")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        outs.append(out)
    return {"dir": d, "outs": outs, "summary": json.loads((outs[0] / "summary.json").read_text(encoding="utf-8")),
            "pilot": json.loads((d / "pilot.json").read_text(encoding="utf-8"))}


def cells_of(summary: dict) -> dict:
    return {x["cell"]: x for f in summary["families"].values() for x in f["cells"]}


# ---------------------------------------------------------------- the pilot


def test_pilot_known_answers(run):
    p = run["pilot"]
    assert p["synthetic"] and p["complete"]
    assert p["resolved"] == RESOLVED and p["R_C"] == 11 and p["m_C"] == 9
    assert [(j["backend"], j["proto"]) for j in p["joint_powers"]] == [("epoll", "http1"), ("epoll", "h2c")]
    assert p["G"]["L"]["G_ms"] == 2 and p["gap_split"]["GAP_SPLIT_ms"] == 5


# ---------------------------------------------------------------- cost


def test_cost_known_answers(run):
    s = run["summary"]
    x = cells_of(s)
    assert s["families"]["C"]["m"] == 9
    for cid in ("C1.L.epoll.http1", "C2.L.epoll.http1", "C3.L.epoll.http1"):
        assert x[cid]["passes"], x[cid]
        assert x[cid]["verdict"] == "equivalent within [0.98, 1.02]"
        lo, hi = x[cid]["ci_holm"]
        assert 0.98 <= lo <= hi <= 1.02
        assert x[cid]["holm_alpha"] == pytest.approx(0.025 / (9 - x[cid]["holm_rank"] + 1))
    assert x["C1.L.epoll.h2c"]["verdict"].startswith("equivalence not shown; a measured cost")
    assert x["C3.L.epoll.h2c"]["verdict"].startswith("equivalence not shown; a measured cost")
    assert "in one-port mode's favour" in x["C2.L.epoll.h2c"]["verdict"]
    assert not x["C1.L.epoll.tls"]["passes"] and x["C1.L.epoll.tls"]["verdict"].startswith("equivalence not shown")
    assert "measured cost" not in x["C1.L.epoll.tls"]["verdict"]
    mq = x["C1.L.epoll.mqtt"]
    assert mq["passes"] and mq["valid_sessions"] == 11 and mq["sessions"] == 12
    assert sum(len(v) for v in mq["invalid_windows"].values()) == 1
    io = x["C1.L.io_uring.http1"]
    assert not io["tested"] and not io["passes"] and io["p_boot_holm"] == 1.0 and "fewer than R = 11" in io["verdict"]
    w = x["C1.W.IOCP.http1"]
    assert not w["holm"] and w["verdict"] == "not resolved at R <= 32" and w["ci95"][0] is not None and "passes" not in w
    rates = {e["cell"]: e for e in s["c3_rates"]}
    assert len(rates) == 12 and rates["C3.L.epoll.http1"]["lambda"] == run["pilot"]["rates"]["C3.L.epoll.http1"]["rate"]
    assert not rates["C3.L.epoll.http1"]["matches"]   # the synthetic C3 windows carry no rate
    h2 = x["C2.L.epoll.h2c"]
    assert h2["sessions"] == 12 and h2["valid_sessions"] == 11
    assert s["claims"]["C"] == [{"host": "L", "backend": "epoll", "proto": "http1",
                                 "joint_power": run["pilot"]["joint_powers"][0]["power"],
                                 "ci_holm": {h: x[f"{h}.L.epoll.http1"]["ci_holm"] for h in ("C1", "C2", "C3")}}]


# ---------------------------------------------------------------- B3


def test_b3_known_answers(run):
    s = run["summary"]
    x = cells_of(s)
    assert s["families"]["B3"]["m"] == 18
    assert x["B3.silent.nginx.epoll"]["passes"] and x["B3.silent.nginx.epoll"]["verdict"].startswith("shown:")
    assert x["B3.silent.nginx.epoll"]["sign_x"] == 16
    assert x["B3.silent.sslh-ev.epoll"]["verdict"] == "not shown; loss (the 95% interval of Q lies wholly below 1.00)"
    assert x["B3.silent.haproxy.epoll"]["verdict"] == "not shown"
    ph = x["B3.partial-hello.nginx.epoll"]
    assert ph["passes"] and ph["sign_x"] == 15 and 0.0 in ph["values"]
    assert x["B3.silent.envoy.io_uring"]["passes"] and x["B3.silent.envoy.io_uring"]["sessions"] == 18
    assert x["B3.silent.netty.epoll"]["verdict"] == "descriptive" and x["B3.silent.netty.epoll"]["ci95"][0] > 1.9
    d = x["B3.silent.nginx.epoll"]["D"]
    assert d["ci95"][0] > 3000 and d["median"] == pytest.approx(3500.0, rel=0.05)
    assert s["k_base"]["K_BASE"] == pytest.approx(6075.0)
    parts = x["B3.silent.nginx.epoll"]["parts"]
    assert parts["server"]["W"] == 7000.0 and parts["server"]["Ks_minus_K_BASE"] == pytest.approx(0.85 * 7000 - 6075.0)
    assert parts["competitor"]["shared_cache_cotenants"] == ["pool_workqueue", "sgpool-16"]


# ---------------------------------------------------------------- M


def test_m_known_answers(run):
    x = cells_of(run["summary"])
    assert x["M1.L.epoll.http1"]["verdict"] == "shown"
    assert x["M1.W.IOCP.h2c"]["verdict"] == "a difference was not shown"
    assert x["M2.L.epoll.http1"]["verdict"] == "shown" and x["M2.L.epoll.http1"]["sign_x"] == 16
    assert x["M2.L.epoll.tls"]["verdict"] == "a difference was not shown"
    assert x["M3.L.epoll.tls-stub.nginx"]["verdict"] == "shown"
    assert x["M3.L.epoll.http1.haproxy"]["verdict"] == "not shown; loss (the 95% interval of the ratio lies wholly below 1.00)"
    sl = x["M3.L.epoll.tls-stub.sslh-ev"]
    assert not sl["tested"] and sl["valid_sessions"] == 0
    assert sum(len(v) for v in sl["invalid_windows"].values()) == 16
    assert x["M3.L.epoll.tls-stub.nginx"]["listen_overflows"] == {"proxy": 64, "server": 0}
    assert run["summary"]["families"]["M"]["m"] == 20


# ---------------------------------------------------------------- secondary and the draws


def test_secondary_cells(run):
    sec = run["summary"]["secondary"]
    by = {(e["bullet"], e["cell"], e["metric"], e["clustered_by_job"]): e for e in sec}
    assert by[("ssh", "S.ssh.C1.L.epoll", "value", False)]["interval"] is not None
    assert by[("b3-other-mode", "S.b3-other-mode.epoll.silent", "value", False)]["median"] == pytest.approx(1.1, rel=0.01)
    assert by[("m-ttfb-cpu", "S.m-ttfb.M1.L.epoll.http1", "value", False)]["median"] == pytest.approx(0.97, rel=0.01)
    assert by[("m-ttfb-cpu", "M1.L.epoll.http1", "cpu", False)]["median"] == pytest.approx(30 / 31)
    assert by[("wl4", "C1.L.epoll.http1", "cpu", False)]["interval"] is not None
    assert by[("wl4", "C3.L.epoll.http1", "ttfb_p99", False)]["interval"] is not None
    assert by[("wl4", "C1.L.io_uring.http1", "cpu", False)]["interval"] is None
    job = by[("by-job", "C1.L.epoll.http1", "value", True)]
    assert job["jobs"] == 2 and job["interval"] is not None and job["a"] == 0.0
    assert by[("by-job", "B3.silent.nginx.epoll", "value", True)]["why"] == "fewer than 2 lab jobs"
    assert all(e["secondary"] for e in sec)
    assert len(sec) == len(C.secondary_draws())


def test_family_draws_follow_4_7(run, tmp_path):
    """Recompute two cost cells' intervals by drawing from SEED_BOOT_C in 6.1's order, cells
    with fewer than R_C valid sessions drawing nothing (4.7)."""
    s = run["summary"]
    x = cells_of(s)
    rng = np.random.default_rng(SEEDS["SEED_BOOT_C"])
    for c in C.cost_cells():
        if x[c.id]["valid_sessions"] != 11:
            continue
        draws = S.draw_clusters(rng, 11)
        if c.id in ("C1.L.epoll.mqtt", "C1.W.IOCP.http1"):
            boot = S.bca_fit(x[c.id]["values"], draws)
            iv = S.bca_interval(boot, 0.95)
            assert [iv.low, iv.high] == x[c.id]["ci95"]


def test_macros_letters_only_and_synthetic_head(run):
    text = (run["outs"][0] / "macros.tex").read_text(encoding="utf-8")
    assert text.startswith(MC.SYNTHETIC_HEAD)
    names = re.findall(r"\\newcommand\{\\([^}]*)\}", text)
    assert names and all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    assert len(names) == len(set(names))
    assert "\\newcommand{\\COneLEpollHttpHolds}{holds}" in text
    assert "\\newcommand{\\CostR}{11}" in text
    with pytest.raises(ValueError):
        MC.Macros().add("COne2", "x")


def test_byte_identical(run):
    a, b = run["outs"]
    for name in ("summary.json", "decisions.csv", "macros.tex"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    assert b"\r\n" not in (a / "summary.json").read_bytes()


# ---------------------------------------------------------------- refusals


def analyse_cli(d: Path, rows: list[dict], out: Path, *extra: str) -> subprocess.CompletedProcess:
    write_jsonl(d / "bad.jsonl", rows)
    return subprocess.run([sys.executable, str(HERE / "analyse.py"), "--seeds", str(d / "seeds.json"), "--pilot", str(d / "pilot.json"),
                           "--rule-e", str(d / "rule_e.json"), "--gate", str(d / "gate.json"), "--rows", str(d / "bad.jsonl"),
                           "--out", str(out), *extra], capture_output=True, text=True)


def test_refusals(run, tmp_path):
    d = run["dir"]
    good = dataset()
    no_bin = [dict(r) for r in good]
    k = next(i for i, r in enumerate(no_bin) if r.get("kind") == "b3")
    no_bin[k] = SY.b3_window("b3", no_bin[k]["session"], no_bin[k]["arm"], no_bin[k]["position"], system=no_bin[k]["system"],
                             case=no_bin[k]["case"], backend=no_bin[k].get("backend"), W=7000.0, with_binaries=False)
    r = analyse_cli(d, no_bin, tmp_path / "o1", "--allow-synthetic")
    assert r.returncode == 2 and "the gate refused 1 of" in r.stderr
    dev = [dict(r) for r in good]
    dev[5]["development"] = True
    r = analyse_cli(d, dev, tmp_path / "o2", "--allow-synthetic")
    assert r.returncode == 2 and "development is True" in r.stderr
    dry = [dict(r) for r in good]
    dry[7]["dry_run"] = True
    r = analyse_cli(d, dry, tmp_path / "o3", "--allow-synthetic")
    assert r.returncode == 2 and "a dry run" in r.stderr
    r = analyse_cli(d, good, tmp_path / "o4")
    assert r.returncode == 2 and "synthetic" in r.stderr
    r = analyse_cli(d, good, HERE.parent / "results" / "synthetic-test", "--allow-synthetic")
    assert r.returncode != 0 and "never written under results/" in r.stderr
    assert not (HERE.parent / "results" / "synthetic-test").exists()
    r = subprocess.run([sys.executable, str(HERE / "macros.py"), str(run["outs"][0] / "summary.json"), "--out",
                        str(HERE.parent / "results" / "macros.tex")], capture_output=True, text=True)
    assert r.returncode != 0 and "never written under results/" in r.stderr


def test_one_port_against_dedicated_shape_errors():
    rng = np.random.default_rng(1)
    rows = SY.cost_session(rng, "j", "s1", hyp="C1", proto="http1", backend="epoll", ratio=1.0)
    rows[1]["position"], rows[3]["position"] = 3, 1
    with pytest.raises(RW.RowError, match="X Y Y X"):
        RW.assemble(rows, lambda r: RW.row_info(r, RULE_E), AN.roles_for)
    rows = SY.cost_session(rng, "j", "s1", hyp="C1", proto="http1", backend="epoll", ratio=1.0)
    rows[0]["detect"] = "peek"
    for r in rows:
        r["detect"] = "peek" if r["mode"] == "one-port" else None
        if r["detect"] is None:
            del r["detect"]
    with pytest.raises(RW.RowError, match="default of rule E"):
        RW.assemble(rows, lambda r: RW.row_info(r, RULE_E), AN.roles_for)


def main() -> int:
    return pytest.main([__file__, "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
