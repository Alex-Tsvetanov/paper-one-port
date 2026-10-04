#!/usr/bin/env python3
"""The session engine of the frozen runners (M7c): order, X per session, reruns, resumption,
fault rows and the rows' common fields, for every family (hypotheses.md 4.1, 4.7, 8).

A cell runs R sessions of four windows each, X Y Y X (4.1). The whole order of a runner is drawn
from its seed before the first window, so a job that stops and a later job that resumes it run the
same order (design choices of M7c, recorded in design/status.md):
- one generator, Python's random.Random(seed): the base sessions (every cell's sessions 1 to R) are
  shuffled group by group, groups in their order (a later group needs the earlier one's data: the
  pilot's C3 cells after its C1 and C2 cells, section 8 step 4; section 10's SSH C3 cells after
  their C1 sessions); then one draw of X per base session, in run order; then one draw of X per
  rerun slot, cell by cell in the runner's cell order, ceil(R/4) slots each (4.1: at most
  ceil(R/4) reruns per cell). No draw depends on which sessions fail;
- a session with an invalid window, or with fewer than four windows (a job stopped in it), is run
  again at the end of its group's order, as a new session, while the cell has rerun slots left; a
  rerun that is invalid is run again the same way (4.1, 8 step 4). Reruns follow the order in
  which the invalid sessions ran;
- a job resumes from the rows already in the output's windows.jsonl, whatever job wrote them: a
  session with any row is never run again under its id, and the rerun slots used are counted
  across jobs, so no cell gets more than R valid sessions (analysis/rows.py refuses more).

Every window yields one row, also a window that crashed (a driver fault: `invalid`, the reason,
the arm's identity fields and provenance, so analysis/rows.py takes its cell from them and
bench/check_rows.py binds it) and a window cut short by a signal to the job (the same, with the
reason, then the job ends). Each row gets: job, session (unique within the job), position, arm,
cell (analysis/cells.py's id), development (false unless the runner runs in development mode),
seed (the order's), order_index, fingerprint (window.pin_fingerprint, once per session), the
arm's provenance, and the arm's identity fields (family and the fields analysis/rows.py reads).

Development mode and one-port mode against dedicated mode (section 8 step 2, "no window, on any
code, times one-port mode against dedicated mode before the pilot entry"). A cell whose arms pair
one-port mode with dedicated mode (`pairs_one_port_with_dedicated`) runs its one-port arm only
with a clearance from bench/run/freeze_guard.py, which is issued only to a frozen run after the
pilot entry. Without one, the engine never calls the window function for that arm: it writes a
stub row (mode one-port, valid false, `stub` true, no binaries, nothing started), so the session's
dedicated windows run and the analysis can read the session, and no one-port timing exists.
"""
from __future__ import annotations

import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent

STUB_REASON = ("development stub: no one-port window runs against dedicated mode before the pilot entry "
               "(hypotheses.md section 8 step 2); nothing was started")
SIGNAL_REASON = "the job was stopped by a signal during this window"


def rerun_cap(r: int) -> int:
    """4.1 and 8 step 4: at most ceil(R/4) reruns per cell."""
    return math.ceil(r / 4)


@dataclass
class Cell:
    """One cell as a runner runs it. `id` is analysis/cells.py's id. `arms` maps the two labels to
    the arm's identity fields (written into every row of the arm, fault rows included) and run
    parameters (`run`, read by the runner's window function, not written). `group` orders the
    groups (0 first). `pairs_one_port_with_dedicated` marks the cells of section 8 step 2's rule."""
    id: str
    r: int
    arms: dict[str, dict]
    group: int = 0
    shared: dict = field(default_factory=dict)
    pairs_one_port_with_dedicated: bool = False

    def identity(self, arm: str) -> dict:
        return {k: v for k, v in self.arms[arm].items() if k != "run"}

    def run_params(self, arm: str) -> dict:
        return dict(self.shared, **self.arms[arm].get("run", {}))

    def one_port_arms(self) -> list[str]:
        return [a for a, f in self.arms.items() if f.get("mode") == "one-port"]


@dataclass
class Plan:
    """The whole order, drawn before the first window (see the module's docstring)."""
    seed: int
    base: list[tuple[str, int]]
    groups: list[list[tuple[str, int]]]
    x_base: dict[tuple[str, int], str]
    x_rerun: dict[tuple[str, int], str]
    caps: dict[str, int]

    def to_json(self) -> dict:
        return {"seed": self.seed, "base": [f"{c}.s{n:02d}:{self.x_base[(c, n)]}" for c, n in self.base],
                "groups": [len(g) for g in self.groups], "caps": self.caps,
                "x_rerun": {f"{c}.r{k}": x for (c, k), x in self.x_rerun.items()}}


def make_plan(cells: list[Cell], seed: int) -> Plan:
    if len({c.id for c in cells}) != len(cells):
        raise ValueError("a cell is listed twice")
    rng = random.Random(seed)
    groups = []
    for g in sorted({c.group for c in cells}):
        items = [(c.id, n) for c in cells if c.group == g for n in range(1, c.r + 1)]
        rng.shuffle(items)
        groups.append(items)
    base = [s for g in groups for s in g]
    x_base = {s: rng.choice(("A", "B")) for s in base}
    caps = {c.id: rerun_cap(c.r) for c in cells}
    x_rerun = {(c.id, k): rng.choice(("A", "B")) for c in cells for k in range(1, caps[c.id] + 1)}
    return Plan(seed, base, groups, x_base, x_rerun, caps)


def base_id(cell: str, n: int) -> str:
    return f"{cell}.s{n:02d}"


def rerun_id(cell: str, k: int) -> str:
    return f"{cell}.r{k}"


def other(x: str) -> str:
    return "B" if x == "A" else "A"


# ---------------------------------------------------------------- state from the rows


@dataclass
class SessionState:
    id: str
    cell: str
    order_index: int
    rows: list[dict] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return len({r.get("position") for r in self.rows}) == 4

    @property
    def valid(self) -> bool:
        return self.complete and all(r.get("valid") for r in self.rows)

    @property
    def is_rerun(self) -> bool:
        return re.fullmatch(re.escape(self.cell) + r"\.r\d+", self.id) is not None


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def states(rows: list[dict]) -> dict[str, SessionState]:
    """Every session the rows name (any job), by id; sessions ids are unique across the jobs of
    one output, since a session with a row is never run again under its id."""
    out: dict[str, SessionState] = {}
    for r in rows:
        if "session" not in r or r.get("kind") == "ophold":
            continue
        s = out.setdefault(str(r["session"]), SessionState(str(r["session"]), str(r.get("cell")), int(r.get("order_index", 0))))
        s.rows.append(r)
    return out


# ---------------------------------------------------------------- the rows


def fault_row(cell: Cell, session: dict, arm: str, position: int, reason: str) -> dict:
    return {"job": session["job"], "session": session["id"], "position": position, "arm": arm, "valid": False,
            "invalid_reasons": [reason], "driver_fault": True}


def stub_row(cell: Cell, session: dict, arm: str, position: int) -> dict:
    """Development mode only: the one-port arm of a cell that pairs it with dedicated mode."""
    return {"job": session["job"], "session": session["id"], "position": position, "arm": arm, "valid": False,
            "invalid_reasons": [STUB_REASON], "stub": True, "metric": None}


@dataclass
class Engine:
    """Runs a plan's sessions. `window(cell, arm, session, position, clearance)` returns a row;
    `provenance(cell, arm)` gives the arm's provenance (with "binaries"); `clearance` is
    freeze_guard's, or None (development, or a runner that needs none)."""
    runner: str
    job: str
    out: Path
    cells: list[Cell]
    plan: Plan
    window: Callable[[Cell, str, dict, int, object], dict]
    provenance: Callable[[Cell, str], dict]
    development: bool
    clearance: object | None = None
    fingerprint: Callable[[], dict] | None = None
    before_group: Callable[[int, "Engine"], None] | None = None
    log: Callable[[str], None] = lambda s: print(s, flush=True)
    stop_after_sessions: int | None = None  # a development limit: run at most this many sessions in this job
    sessions_run: int = 0

    @property
    def rows_path(self) -> Path:
        return self.out / "windows.jsonl"

    def cell(self, cid: str) -> Cell:
        return next(c for c in self.cells if c.id == cid)

    def rows(self) -> list[dict]:
        return read_rows(self.rows_path)

    def _write(self, row: dict) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        with open(self.rows_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def finalize(self, row: dict, cell: Cell, session: dict, arm: str, position: int, order_index: int) -> dict:
        """The fields every row carries; the runner's own fields stay, the engine's win."""
        stub = bool(row.get("stub"))
        for k, v in cell.identity(arm).items():
            row.setdefault(k, v)
        if stub:
            row["mode"] = "one-port"
        prov = {} if stub else self.provenance(cell, arm)
        if stub:
            prov = {"binaries": {}, "stub": True}
        row.update(job=self.job, session=session["id"], position=position, arm=arm, cell=cell.id, development=self.development,
                   seed=self.plan.seed, order_index=order_index, runner=self.runner)
        row.setdefault("fingerprint", session.get("fingerprint"))  # b3.py reads its own per window
        if "provenance" not in row or stub or row.get("driver_fault"):
            row["provenance"] = prov
        elif not row["provenance"].get("binaries"):
            row["provenance"] = dict(row["provenance"], **{k: v for k, v in prov.items() if k in ("binaries", "binary_paths")})
        if self.clearance is not None:
            row["provenance"] = dict(row["provenance"], freeze=getattr(self.clearance, "record", None))
        row.setdefault("valid", False)
        row.setdefault("invalid_reasons", [] if row["valid"] else ["no validity recorded"])
        return row

    def one_window(self, cell: Cell, session: dict, arm: str, position: int) -> dict:
        if cell.pairs_one_port_with_dedicated and arm in cell.one_port_arms() and self.clearance is None:
            if not self.development:
                raise RuntimeError(f"{cell.id}: a frozen run of a one-port against dedicated cell needs the freeze guard's clearance")
            return stub_row(cell, session, arm, position)
        try:
            return self.window(cell, arm, session, position, self.clearance)
        except SystemExit:
            self._write(self.finalize(fault_row(cell, session, arm, position, SIGNAL_REASON), cell, session, arm, position,
                                      session["order_index"]))
            raise
        except Exception as e:  # noqa: BLE001 - a crashed window is recorded as a row (t1.py's rule)
            return fault_row(cell, session, arm, position, f"driver error: {e!r}")

    def run_session(self, cell: Cell, sid: str, x: str, order_index: int) -> SessionState:
        try:
            fp = self.fingerprint() if self.fingerprint else {}
        except Exception as e:  # noqa: BLE001 - the session's windows record it
            fp = {"error": repr(e)}
        session = {"job": self.job, "id": sid, "mhz": fp.get("mean_mhz"), "fingerprint": fp, "x": x, "order_index": order_index,
                   "cell": cell.id}
        st = SessionState(sid, cell.id, order_index)
        y = other(x)
        for pos, arm in enumerate((x, y, y, x)):
            row = self.finalize(self.one_window(cell, session, arm, pos), cell, session, arm, pos, order_index)
            self._write(row)
            st.rows.append(row)
            m = (row.get("metric") or {}).get("value")
            self.log(f"{sid} p{pos} {arm}: {m if m is None else round(float(m), 2)} valid={row.get('valid')} "
                     f"{'; '.join(row.get('invalid_reasons') or [])}")
        self.sessions_run += 1
        return st

    def _limit(self) -> bool:
        return self.stop_after_sessions is not None and self.sessions_run >= self.stop_after_sessions

    def run(self) -> dict:
        """Every group: its base sessions not yet run, then its reruns. Returns a summary."""
        (self.out / f"plan-{self.runner}.json").write_text(json.dumps(self.plan.to_json(), indent=1), encoding="utf-8")
        offset = 0
        for gi, group in enumerate(self.plan.groups):
            if self.before_group is not None:
                self.before_group(gi, self)
            done = states(self.rows())
            for i, (cid, n) in enumerate(group):
                if self._limit():
                    return self.summary()
                sid = base_id(cid, n)
                if sid in done:
                    continue
                self.run_session(self.cell(cid), sid, self.plan.x_base[(cid, n)], offset + i)
            offset += len(group)
            self.reruns({cid for cid, _ in group})
        return self.summary()

    def reruns(self, cells: set[str]) -> None:
        """At the end of a group: each invalid session of its cells, in the order they ran, gets
        one rerun while its cell has slots left (4.1)."""
        while not self._limit():
            st = states(self.rows())
            pick = None
            for cid in sorted(cells, key=lambda c: [x.id for x in self.cells].index(c)):
                ss = sorted((s for s in st.values() if s.cell == cid), key=lambda s: s.order_index)
                invalid = [s for s in ss if not s.valid]
                used = sum(1 for s in ss if s.is_rerun)
                if used >= min(self.plan.caps[cid], len(invalid)):
                    continue
                if sum(1 for s in ss if s.valid) >= self.cell(cid).r:
                    continue
                at = invalid[used].order_index
                if pick is None or at < pick[1]:
                    pick = (cid, at, used + 1)
            if pick is None:
                return
            cid, _, k = pick
            index = 100_000 + sum(1 for s in st.values() if s.is_rerun)
            self.run_session(self.cell(cid), rerun_id(cid, k), self.plan.x_rerun[(cid, k)], index)

    def summary(self) -> dict:
        st = states(self.rows())
        out = {}
        for c in self.cells:
            ss = [s for s in st.values() if s.cell == c.id]
            out[c.id] = {"R": c.r, "sessions": len(ss), "valid": sum(1 for s in ss if s.valid),
                         "reruns": sum(1 for s in ss if s.is_rerun), "cap": self.plan.caps[c.id],
                         "stub_windows": sum(1 for s in ss for r in s.rows if r.get("stub")),
                         "invalid_windows": [{"session": s.id, "position": r.get("position"), "arm": r.get("arm"),
                                              "reasons": r.get("invalid_reasons")} for s in ss for r in s.rows if not r.get("valid")]}
        summ = {"runner": self.runner, "job": self.job, "development": self.development, "seed": self.plan.seed,
                "sessions_run_this_job": self.sessions_run, "cells": out, "written": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        (self.out / f"summary-{self.runner}-{self.job}.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
        return summ
