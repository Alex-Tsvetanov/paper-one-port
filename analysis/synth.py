"""Synthetic rows in the runners' formats, for the tests only.

SYNTHETIC DATA. Every row this module makes carries "synthetic": true; analyse.py and pilot.py
refuse such rows unless told the run is synthetic (--allow-synthetic), and then refuse any output
path under results/ (analysis/versions.py). No synthetic row, summary or macro is ever written
under results/: the tests write into temporary directories.

The rows follow bench/run/window.py (cost and mechanism windows; aa.py's provenance, fingerprint
and seed), bench/run/b3.py (B3 and ophold windows) and bench/run/handoff.py (M3 windows), plus
the fields analysis/rows.py's contract names for the runners that do not exist yet. Values are
drawn from a generator seeded by the caller, so a test's rows are the same on every run.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

import cells as C

BINARIES = {name: hashlib.sha256(f"synthetic {name}".encode()).hexdigest() for name in ("oneport", "opgen", "opcase", "ophold")}


def gate_json(binaries: dict | None = None) -> dict:
    """A gate in bench/check_records.py's output shape that passed and is citable, naming the
    synthetic binaries (a mock of the records gate for the tests)."""
    return {"passed": True, "citable": True, "dry_run": False, "host": "L", "binaries": dict(binaries or BINARIES),
            "synthetic": True}


def provenance() -> dict:
    return {"commit": "0" * 40, "dirty": False, "binaries": {k: BINARIES[k] for k in ("oneport", "opgen")}, "synthetic": True}


def _base(job: str, session: str, arm: str, position: int, valid: bool, reasons: list[str] | None, development: bool) -> dict:
    return {"job": job, "session": session, "arm": arm, "position": position, "development": development,
            "valid": valid, "invalid_reasons": list(reasons or ([] if valid else ["synthetic invalid window"])),
            "provenance": provenance(), "synthetic": True}


def x_first(rng: np.random.Generator, labels: tuple[str, str]) -> list[str]:
    """X Y Y X, X drawn per session (4.1)."""
    x = labels[int(rng.integers(0, 2))]
    y = labels[1] if x == labels[0] else labels[0]
    return [x, y, y, x]


# ---------------------------------------------------------------- cost windows (window.py)


def cost_window(job: str, session: str, arm: str, position: int, *, workload: str, proto: str, backend: str, mode: str,
                value: float, valid: bool = True, reasons: list[str] | None = None, family: str | None = "C",
                development: bool = False, seed: int | None = None, extra: dict | None = None, rate: float | None = None) -> dict:
    hyp = C.WORKLOAD_HYP[workload]
    row = _base(job, session, arm, position, valid, reasons, development)
    row.update({"cell": f"{workload}.{proto}.{backend}", "workload": workload, "proto": proto, "backend": backend,
                "mode": mode, "metric": {"name": C.HYP_METRIC[hyp], "value": value},
                "cpu_us_per_exchange": 20.0 + value / 1e4, "rss_kb": 4000 + int(value) % 97, "peak_rss_kb": 4100 + int(value) % 89,
                "opgen": {"ttfb_ns": {"median": value * 1000.0, "p99": value * 1500.0}}, "rate": rate})
    if mode == "one-port":
        row.update({"detect": "replay", "dispatch": "inproc"})
    if family is not None:
        row["family"] = family
    if seed is not None:
        row["seed"] = seed
    row.update(extra or {})
    return row


def cost_session(rng: np.random.Generator, job: str, session: str, *, hyp: str, proto: str, backend: str, ratio: float,
                 base: float = 40000.0, invalid_position: int | None = None, pilot: bool = False, seed: int | None = None,
                 family: str | None = "C", extra: dict | None = None, rate: float | None = None,
                 roles: tuple[str, str] = ("one-port", "dedicated")) -> list[dict]:
    """One session of four windows whose arm means give `ratio` = num / den exactly. In the pilot
    the arms are A and B, both dedicated, and the ratio is B / A (aa.py)."""
    labels = ("A", "B")
    order = x_first(rng, labels)
    out = []
    for pos, arm in enumerate(order):
        if pilot:
            mode, num = "dedicated", arm == "B"
        else:
            mode = roles[0] if arm == "A" else roles[1]
            num = arm == "A"
        value = base * ratio if num else base
        valid = pos != invalid_position
        out.append(cost_window(job, session, arm, pos, workload=C.HYP_WORKLOAD[hyp], proto=proto, backend=backend, mode=mode,
                               value=value, valid=valid, family=None if pilot else family, development=pilot, seed=seed,
                               extra=extra, rate=rate))
    return out


def fault_row(job: str, session: str, arm: str, position: int, cell: str, development: bool = False) -> dict:
    """window.run_window's row for a driver fault: the session fields only."""
    row = _base(job, session, arm, position, False, ["driver error: synthetic"], development)
    row["cell"] = cell
    return row


# ---------------------------------------------------------------- B3 windows (b3.py)


def b3_window(job: str, session: str, arm: str, position: int, *, system: str, case: str, backend: str | None,
              W: float, valid: bool = True, kind: str = "b3", detect: str = "replay", family: str | None = None,
              bullet: str | None = None, with_binaries: bool = True) -> dict:
    row = _base(job, session, arm, position, valid, None, False)
    u, kq = 0.1 * W, 0.05 * W
    ks = W - u - kq
    row.update({"kind": kind, "system": system, "case": case, "n_pend": 10000,
                "footprint": {"sample1": {"U": u, "Kq": kq, "Ks": ks, "W": W},
                              "sample2": {"U": u, "Kq": kq, "Ks": ks, "W": W, "f_mean": 3.0, "skb_growth": 1000,
                                          "shared_growth": 400}},
                "readings": {"sample2": {"fclone_cotenants": ["pool_workqueue", "sgpool-16"]}}})
    if backend is not None:
        row.update({"backend": backend, "detect": detect})
    if family is not None:
        row["family"] = family
    if bullet is not None:
        row["bullet"] = bullet
    if not with_binaries:
        row["provenance"] = {"commit": "0" * 40}
    return row


def b3_session(rng: np.random.Generator, job: str, session: str, *, system: str, case: str, backend: str, q: float,
               w_srv: float = 7000.0, invalid_position: int | None = None) -> list[dict]:
    """Q = W_comp / W_srv exactly (5.2): arm A is the server (relay against a proxy, in-process
    against a library), arm B the competitor, whose rows name no backend (b3.py)."""
    server = C.SERVER_RELAY if system in C.PROXIES else C.SERVER_INPROC
    out = []
    for pos, arm in enumerate(x_first(rng, ("A", "B"))):
        valid = pos != invalid_position
        if arm == "A":
            out.append(b3_window(job, session, arm, pos, system=server, case=case, backend=backend, W=w_srv, valid=valid))
        else:
            out.append(b3_window(job, session, arm, pos, system=system, case=case, backend=None, W=q * w_srv if w_srv > 0 else q,
                                 valid=valid))
    return out


def ophold_window(job: str, n: int, ks: float) -> dict:
    row = _base(job, f"ophold-{n:02d}", "H", 0, True, None, False)
    row.update({"kind": "ophold", "system": "ophold", "case": "silent",
                "footprint": {"sample2": {"U": 0.0, "Kq": 0.0, "Ks": ks, "W": ks}}})
    return row


# ---------------------------------------------------------------- mechanism windows


def m_session(rng: np.random.Generator, job: str, session: str, cell: C.Cell, ratio: float, *, base: float = 40000.0,
              invalid_position: int | None = None, rule_default: str = "replay", bullet: str | None = None) -> list[dict]:
    """M1 (window.py's in-process rows with detect), M2 (dispatch, WL6's metric), M3 (handoff.py's
    rows). Arm A is the numerator's role."""
    out = []
    other = "peek" if rule_default == "replay" else "replay"
    for pos, arm in enumerate(x_first(rng, ("A", "B"))):
        num = arm == "A"
        valid = pos != invalid_position
        row = _base(job, session, arm, pos, valid, None, False)
        value = base * ratio if num else base
        if cell.hyp == "M1":
            row.update({"family": "M1", "workload": "churn", "proto": cell.proto, "backend": cell.backend, "mode": "one-port",
                        "dispatch": "inproc", "detect": rule_default if num else other,
                        "metric": {"name": "conn_per_s", "value": value}, "cpu_us_per_exchange": 30.0 if num else 31.0})
        elif cell.hyp == "M2":
            row.update({"family": "M2", "workload": "open", "proto": cell.proto, "backend": cell.backend, "mode": "one-port",
                        "dispatch": "inproc" if num else "relay",
                        "metric": {"name": C.M2_METRIC, "value": value / 1000.0}, "cpu_us_per_exchange": 40.0 if num else 45.0})
        else:
            row.update({"family": "M3", "workload": "churn", "proto": cell.proto, "backend": "epoll",
                        "system": C.SERVER_RELAY if num else cell.system, "metric": {"name": "conn_per_s", "value": value},
                        "cpu_us_per_exchange": 25.0 if num else 27.0, "nstat_delta": {"TcpExtListenOverflows": 0 if num else 2}})
        if bullet is not None:
            row["family"] = "S"
            row["bullet"] = bullet
            row["hyp"] = cell.hyp
            row["workload"] = "open"
            row["metric"] = {"name": "ttfb_median_us", "value": value / 100.0}
        out.append(row)
    return out


def lognormal(rng: np.random.Generator, centre: float, sigma: float, n: int) -> list[float]:
    return [float(centre * math.exp(x)) for x in rng.normal(0.0, sigma, size=n)]


# ---------------------------------------------------------------- the A/A pilot (aa.py)


def aa_pilot_rows(cells: dict[str, float], seeds: dict, sessions: int = 16, seed: int = 1, job: str = "pilot",
                  invalid: dict | None = None) -> list[dict]:
    """A/A sessions (both arms dedicated, ratio B / A) per cost cell id, log ratios normal with
    the given sigma; `invalid` gives a cell the number of its first sessions that hold an invalid
    window; every row carries its host's order seed (SEED_PILOT_L or SEED_PILOT_W)."""
    rng = np.random.default_rng(seed)
    out = []
    for cid, sigma in cells.items():
        hyp, host, backend, proto = cid.split(".")
        for k in range(1, sessions + 1):
            bad = (invalid or {}).get(cid, 0) >= k
            ratio = float(np.exp(rng.normal(0.0, sigma)))
            base = 30000.0 + 1000 * k if hyp != "C3" else 120.0
            out += cost_session(rng, f"{job}-{host}", f"{cid}-s{k:02d}", hyp=hyp, proto=proto, backend=backend, ratio=ratio,
                                base=base, pilot=True, seed=seeds["SEED_PILOT_" + host],
                                invalid_position=1 if bad else None, rate=None if hyp != "C3" else 0.5 * 40000)
    return out


def spread(rng: np.random.Generator, centre: float, half_log_width: float, n: int) -> list[float]:
    """n values centre x exp(t), t evenly spaced over [-w, w], in a random order: a cell whose
    median is the centre and whose bootstrap is symmetric about it."""
    vals = [float(centre * math.exp(x)) for x in np.linspace(-half_log_width, half_log_width, n)]
    return [vals[i] for i in rng.permutation(n)]
