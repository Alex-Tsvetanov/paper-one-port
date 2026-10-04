#!/usr/bin/env python3
"""Tests of analysis/pilot.py, the R_C rule of hypotheses.md 4.6 and the pilot entry's other
outputs (9.2).

    python -m pytest analysis/test_pilot.py
    ONEPORT_SLOW=1 python -m pytest analysis/test_pilot.py -k appendix   (Appendix A at N_SIM = 1,000)

Known answers:
- the rule of steps 5 to 7 on pass counts made by hand (a cell whose power is not monotone in R,
  a cell short of P sessions, no resolved cell);
- the streams of step 3 and the confirmatory code of step 2;
- G, GAP_SPLIT and lambda on rows made by hand;
- the refusals (one-port rows, another order seed);
- Appendix A's 24 pilots: their standard deviations as design/status.md records them (fast), and
  the chosen R of each at the 80% bound (slow);
- a whole synthetic A/A pilot (SYNTHETIC: written to a temporary directory only).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cells as C  # noqa: E402
import pilot as PL  # noqa: E402
import rows as RW  # noqa: E402
import stats as S  # noqa: E402
import synth as SY  # noqa: E402

SEEDS = {n: 1000 + i for i, n in enumerate(C.SEED_NAMES)}


# ---------------------------------------------------------------- the rule, by hand


def test_rule_on_hand_made_counts():
    n = 1000
    cand = PL.CANDIDATES
    counts = {
        1: dict(zip(cand, (790, 800, 850, 900, 950, 990, 1000), strict=True)),   # R_c = 15
        2: dict(zip(cand, (810, 799, 805, 820, 830, 840, 850), strict=True)),   # meets at 11, not at 15, again at 18
        3: dict(zip(cand, (0, 0, 0, 100, 500, 790, 799), strict=True)),          # not resolved: 0.799 at 31
        4: dict(zip(cand, (1000,) * 7, strict=True)),                             # meets everywhere, but short of P sessions
    }
    valid = {1: True, 2: True, 3: True, 4: False}
    rule = PL.decide(valid, counts, n)
    assert rule["resolved"] == [1, 2]
    assert rule["own_r"] == {1: 15, 2: 11}
    assert rule["R_C"] == 18          # the smallest candidate at which both meet 0.80
    assert rule["m_C"] == 2
    none = PL.decide({1: False}, {1: counts[1]}, n)
    assert none == {"resolved": [], "own_r": {}, "R_C": 31, "m_C": 0}


def test_cells_outside_the_family_never_resolve():
    """W's churn h2c and churn MQTT (c = 10 and 12; revision log, "W before the code freeze", item
    1) meet the target everywhere here, and cell 9 only from R = 15: they are not resolved, so R_C
    is cell 9's own and m_C counts it alone."""
    n = 1000
    cand = PL.CANDIDATES
    assert PL.outside_numbers() == {10, 12}
    everywhere = dict(zip(cand, (1000,) * 7, strict=True))
    late = dict(zip(cand, (0, 0, 0, 0, 0, 0, 900), strict=True))   # if it were resolved, R_C would be 31
    counts = {9: dict(zip(cand, (700, 850, 900, 950, 990, 1000, 1000), strict=True)), 10: late, 12: everywhere}
    rule = PL.decide({9: True, 10: True, 12: True}, counts, n)
    assert rule == {"resolved": [9], "own_r": {9: 15}, "R_C": 15, "m_C": 1}
    assert PL.decide({10: True, 12: True}, {10: everywhere, 12: everywhere}, n) == {"resolved": [], "own_r": {}, "R_C": 31, "m_C": 0}


def test_power_target_is_exact_at_0_80():
    assert PL.meets(800, 1000) and not PL.meets(799, 1000)


def test_joint_power_is_the_product_at_r_c():
    trio = [c.number for c in C.cost_cells() if c.backend == "epoll" and c.proto == "http1"]
    assert trio == [1, 13, 25]
    counts = {c: {31: 1000, 11: 900} for c in trio}
    counts[13] = {31: 1000, 11: 800}
    jp = PL.joint_powers(trio, counts, 11, 1000)
    assert len(jp) == 1 and jp[0]["power_exact"] == "81/125" and jp[0]["power"] == 0.648  # 0.9 x 0.8 x 0.9
    assert PL.joint_powers(trio[:2], counts, 11, 1000) == []


# ---------------------------------------------------------------- the streams and the confirmatory code


def test_run_draws_are_one_stream_per_run():
    idx, nrm = PL.run_draws(77, 5, 9, 0.3)
    rng = np.random.default_rng([77, 5, 9])
    assert np.array_equal(idx, rng.integers(0, 16, size=31))
    assert np.array_equal(nrm, rng.normal(0.0, 0.3, size=31))
    assert len(idx) == len(nrm) == PL.DRAWS_PER_RUN


def test_simulation_runs_the_confirmatory_code():
    rng = np.random.default_rng(3)
    ratios = SY.lognormal(rng, 1.0, 0.008, 16)
    m = PL.cell_model(ratios)
    scale = m["s_u"] / np.sqrt(1 + m["b"] ** 2)
    n_sim = 30
    want = {r: 0 for r in PL.CANDIDATES}
    for j in range(1, n_sim + 1):
        idx, nrm = PL.run_draws(42, 7, j, m["b"])
        for r in PL.CANDIDATES:
            vals = np.exp(scale * (m["z"][idx[:r]] + nrm[:r]))
            full = S.cost_tost(vals, S.draw_clusters(np.random.default_rng([42, 7, j, r]), r))
            want[r] += full.p_sign <= PL.THRESHOLD and full.p_boot <= PL.THRESHOLD
    got = PL.simulate_cell((42, 7, ratios, n_sim, PL.CANDIDATES))
    assert got == want
    assert m["q"] == S.chi2_ppf(0.20, 15)
    assert m["s_u"] == pytest.approx(m["s"] * 1.2063695181246945, rel=1e-15)


def test_workers_do_not_change_the_powers():
    rng = np.random.default_rng(5)
    cells = {c: SY.lognormal(rng, 1.0, 0.006 + 0.002 * c, 16) for c in (2, 9, 30)}
    one = PL.powers(cells, 11, n_sim=15, workers=1)
    two = PL.powers(cells, 11, n_sim=15, workers=2)
    assert one == two


# ---------------------------------------------------------------- lambda, G and GAP_SPLIT


def timer(backend, run, lateness_ns, valid=True):
    return {"part": "timer", "backend": backend, "mode": "dedicated", "run": run, "valid": valid,
            "invalid_reasons": [] if valid else ["opcase failed"], "lateness_ns": lateness_ns, "synthetic": True,
            "provenance": SY.provenance()}


def split(backend, gap, rep, recv, valid=True):
    return {"part": "split", "backend": backend, "mode": "dedicated", "gap_ms": gap, "replicate": rep, "valid": valid,
            "invalid_reasons": [] if valid else ["server failed"], "recv_data": recv, "synthetic": True,
            "provenance": SY.provenance()}


def test_g_per_host():
    parts = [timer("epoll", 1, 1_200_000), timer("io_uring", 1, 2_345_678), timer("io_uring", 2, 9_999_999_999, valid=False),
             timer("IOCP", 1, 2_000_000)]
    g = PL.g_values(parts)
    assert g["L"]["G_ms"] == 3 and g["L"]["hc7_runs"] and g["L"]["max_lateness_ns"] == 2_345_678
    assert g["L"]["excluded"] == [{"backend": "io_uring", "run": 2, "reasons": ["opcase failed"]}]
    assert g["W"]["G_ms"] == 3        # exactly 2 ms: the smallest whole number of ms above it is 3
    g = PL.g_values([timer("IOCP", 1, 5, valid=False), timer("epoll", 1, 3_000_000_000)])
    assert g["W"]["G_ms"] is None and not g["W"]["hc7_runs"]
    assert g["L"]["G_ms"] == 3001 and not g["L"]["hc7_runs"]     # not below T_fb


def test_gap_split():
    reps = []
    for b in PL.SPLIT_BACKENDS:
        for gap in PL.GAPS_MS:
            for k in range(16):
                reps.append(split(b, gap, k, 2))
    # 5 ms: one io_uring replicate read the two writes in one receive
    reps[[i for i, r in enumerate(reps) if r["backend"] == "io_uring" and r["gap_ms"] == 5][0]]["recv_data"] = 1
    # 10 ms: no valid IOCP replicate
    for r in reps:
        if r["backend"] == "IOCP" and r["gap_ms"] == 10:
            r["valid"] = False
    gs = PL.gap_split(reps)
    assert gs["GAP_SPLIT_ms"] == 20 and not gs["fallback"]
    for r in reps:
        if r["gap_ms"] >= 20 and r["backend"] == "epoll" and r["replicate"] == 3:
            r["recv_data"] = 1
    gs = PL.gap_split(reps)
    assert gs["GAP_SPLIT_ms"] == 100 and gs["fallback"]
    gs = PL.gap_split([r for r in reps if r["backend"] != "IOCP"])
    assert gs["GAP_SPLIT_ms"] is None and not gs["computable"]


def aa_rows(cells: dict[str, float], sessions: int = 16, seed: int = 1, job: str = "pilot-L", invalid: dict | None = None) -> list[dict]:
    """A/A sessions per cell id with log-ratio standard deviation sigma (SYNTHETIC)."""
    return SY.aa_pilot_rows(cells, SEEDS, sessions=sessions, seed=seed, job=job, invalid=invalid)


def test_rates_from_the_c1_sessions():
    rows = aa_rows({"C1.L.epoll.http1": 0.0, "C3.L.epoll.http1": 0.0}, sessions=4)
    sessions = RW.assemble(rows, PL.pilot_info, lambda k, c: PL.PILOT_ROLES)
    r = PL.rates(sessions)["C3.L.epoll.http1"]
    # each session's four windows: base and base at ratio 1, base = 30000 + 1000 k
    assert r["sessions"] == 4 and r["median_conn_per_s"] == 32500.0 and r["rate"] == 16250.0
    assert r["rates_the_pilot_c3_sessions_ran"] == [20000.0]
    assert PL.rates(sessions)["C3.W.IOCP.mqtt"]["rate"] is None


# ---------------------------------------------------------------- refusals


def test_refuses_one_port_rows():
    rows = aa_rows({"C1.L.epoll.http1": 0.01}, sessions=1)
    rows[2]["mode"] = "one-port"
    with pytest.raises(PL.PilotRefused, match="one-port"):
        PL.pilot_entry(rows, [], SEEDS, n_sim=5)
    parts = [timer("epoll", 1, 10)]
    parts[0]["mode"] = "one-port"
    with pytest.raises(PL.PilotRefused):
        PL.pilot_entry(aa_rows({"C1.L.epoll.http1": 0.01}, sessions=1), parts, SEEDS, n_sim=5)


def test_refuses_another_order_seed():
    rows = aa_rows({"C1.L.epoll.http1": 0.01}, sessions=1)
    rows[0]["seed"] = 5
    with pytest.raises(PL.PilotRefused, match="order seed"):
        PL.pilot_entry(rows, [], SEEDS, n_sim=5)


# ---------------------------------------------------------------- Appendix A


def appendix_pilots():
    """design/proposal.md Appendix A: master seed 43, eight pilots per sigma in {0.010, 0.0125,
    0.015}, drawn first, in this order (appendix_a_r_rule.py's main)."""
    master = np.random.default_rng(43)
    sigmas = [0.010, 0.0125, 0.015]
    return {s: [master.normal(0.0, s, size=16) for _ in range(8)] for s in sigmas}


# design/status.md, "Power simulation": the pilots' sd and the R chosen at the 80% bound (None: not resolved)
APPENDIX = {
    0.010: [(0.0084, 15), (0.0103, 25), (0.0110, 18), (0.0077, 11), (0.0117, 22), (0.0133, 28), (0.0103, 18), (0.0094, 15)],
    0.0125: [(0.0109, 22), (0.0158, None), (0.0161, None), (0.0091, 18), (0.0130, 28), (0.0136, 28), (0.0128, 25), (0.0121, 25)],
    0.015: [(0.0126, 25), (0.0130, 25), (0.0115, 22), (0.0144, None), (0.0114, 22), (0.0142, 28), (0.0118, 25), (0.0144, None)],
}


def test_appendix_a_pilots_and_their_sd():
    pilots = appendix_pilots()
    for s, rows in APPENDIX.items():
        for i, (sd, _) in enumerate(rows):
            m = PL.cell_model(np.exp(pilots[s][i]).tolist())
            assert f"{m['s']:.4f}" == f"{sd:.4f}", (s, i)


@pytest.mark.skipif(os.environ.get("ONEPORT_SLOW") != "1", reason="slow: set ONEPORT_SLOW=1 (24 cells at N_SIM = 1,000)")
def test_appendix_a_rule_choices():
    """The rule as frozen, with its own streams (SEED_SIM = 43 here), on Appendix A's 24 pilots.
    The streams differ from the script's, so a choice can differ where a candidate's power lies
    within Monte Carlo noise of 0.80 (standard error 0.0126). The outcome is recorded in
    design/status-m7a.md; the test asserts that every difference is such a case."""
    pilots = appendix_pilots()
    cells = {}
    want = {}
    c = 0
    for s, rows in APPENDIX.items():
        for i, (_, r) in enumerate(rows):
            c += 1
            cells[c] = np.exp(pilots[s][i]).tolist()
            want[c] = r
    counts = PL.powers(cells, 43, n_sim=PL.N_SIM, workers=max(1, (os.cpu_count() or 2) - 1))
    report = []
    for c in sorted(cells):
        got = None
        if PL.meets(counts[c][31], PL.N_SIM):
            got = next(r for r in PL.CANDIDATES if PL.meets(counts[c][r], PL.N_SIM))
        report.append({"cell": c, "appendix": want[c], "here": got, "counts": counts[c]})
        if got != want[c]:
            near = [r for r in PL.CANDIDATES if abs(counts[c][r] / PL.N_SIM - 0.80) <= 3 * 0.0126]
            assert near, report[-1]
    out = Path(os.environ.get("ONEPORT_APPENDIX_OUT", HERE / "__pycache__" / "appendix_a_rule.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------- a whole synthetic pilot (SYNTHETIC)


def synthetic_pilot_rows():
    low = {f"{h}.L.epoll.http1": 0.002 for h in C.COST_HYPS}
    low.update({f"{h}.W.IOCP.mqtt": 0.002 for h in C.COST_HYPS})
    high = {"C1.L.io_uring.tls": 0.05, "C2.L.io_uring.tls": 0.05}
    rows = aa_rows(low, seed=2, job="pilot")
    rows += aa_rows(high, seed=3, job="pilot2")
    rows += aa_rows({"C3.L.io_uring.h2c": 0.002}, seed=4, job="pilot3", invalid={"C3.L.io_uring.h2c": 3})
    return rows


def synthetic_parts():
    parts = [timer(b, k, 1_000_000 + 1000 * k) for b in PL.SPLIT_BACKENDS for k in range(1, 4)]
    parts += [split(b, g, k, 2) for b in PL.SPLIT_BACKENDS for g in PL.GAPS_MS for k in range(2)]
    return parts


def test_synthetic_pilot_entry(tmp_path):
    rows = synthetic_pilot_rows()
    entry = PL.pilot_entry(rows, synthetic_parts(), SEEDS, n_sim=20)
    by = {e["cell"]: e for e in entry["cells"]}
    # C1.W.IOCP.mqtt is outside the family (cells.COST_OUTSIDE_FAMILY): simulated, never resolved.
    want = sorted([f"{h}.L.epoll.http1" for h in C.COST_HYPS] + [f"{h}.W.IOCP.mqtt" for h in ("C2", "C3")],
                  key=lambda x: [c.id for c in C.cost_cells()].index(x))
    assert entry["resolved"] == want
    assert entry["R_C"] == 11 and entry["m_C"] == 5
    assert entry["complete"]
    w_mqtt = by["C1.W.IOCP.mqtt"]
    assert not w_mqtt["resolved"] and w_mqtt["R_c"] is None and w_mqtt["pass_counts"]["31"] >= 16
    assert w_mqtt["outside_family"] == C.COST_OUTSIDE_FAMILY["C1.W.IOCP.mqtt"]
    assert sorted(entry["outside_family"]) == ["C1.W.IOCP.h2c", "C1.W.IOCP.mqtt"]
    assert "outside_family" not in by["C1.L.epoll.http1"]
    assert not by["C1.L.io_uring.tls"]["resolved"] and by["C1.L.io_uring.tls"]["pass_counts"]["31"] < 16
    assert by["C3.L.io_uring.h2c"]["valid_sessions"] == 13 and "why_not_simulated" in by["C3.L.io_uring.h2c"]
    assert len(by["C3.L.io_uring.h2c"]["invalid_windows"]["A"]) + len(by["C3.L.io_uring.h2c"]["invalid_windows"].get("B", [])) == 3
    # MQTT on W has no joint power: its C1 cell is not resolved (the entry's item 1).
    assert [j["proto"] for j in entry["joint_powers"]] == ["http1"]
    # WL2's lambda for C3 MQTT on W still comes from the C1 pilot sessions.
    assert entry["rates"]["C3.W.IOCP.mqtt"]["rate"] is not None and entry["rates"]["C3.W.IOCP.mqtt"]["c1_cell"] == "C1.W.IOCP.mqtt"
    assert entry["G"]["L"]["G_ms"] == 2 and entry["G"]["W"]["G_ms"] == 2
    assert entry["gap_split"]["GAP_SPLIT_ms"] == 5
    assert entry["rates"]["C3.L.epoll.http1"]["rate"] is not None


def test_cli_byte_identical_and_never_under_results(tmp_path):
    rows = synthetic_pilot_rows()
    (tmp_path / "w.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "p.jsonl").write_text("".join(json.dumps(r) + "\n" for r in synthetic_parts()), encoding="utf-8")
    (tmp_path / "seeds.json").write_text(json.dumps(SEEDS), encoding="utf-8")
    (tmp_path / "gate.json").write_text(json.dumps(SY.gate_json()), encoding="utf-8")
    base = [sys.executable, str(HERE / "pilot.py"), "--seeds", str(tmp_path / "seeds.json"), "--gate", str(tmp_path / "gate.json"),
            "--rows", str(tmp_path / "w.jsonl"), "--parts", str(tmp_path / "p.jsonl"), "--allow-synthetic", "--n-sim", "10"]
    outs = []
    for k in (1, 2):
        out = tmp_path / f"pilot{k}.json"
        r = subprocess.run(base + ["--out", str(out), "--workers", str(k)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "SYNTHETIC" in r.stdout
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]
    r = subprocess.run(base + ["--out", str(HERE.parent / "results" / "pilot.json")], capture_output=True, text=True)
    assert r.returncode != 0 and "never written under results/" in r.stderr
    assert not (HERE.parent / "results" / "pilot.json").exists()
    r = subprocess.run([a for a in base if a != "--allow-synthetic"] + ["--out", str(tmp_path / "x.json")], capture_output=True, text=True)
    assert r.returncode != 0


def main() -> int:
    return pytest.main([__file__, "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
