"""Reading the runners' rows: the refusals, the gate, and sessions.

The contract (what every row of a frozen run must hold; design/status-m7a.md copies it):

Every row is one window, one JSON object per line (windows.jsonl), as bench/run/window.py,
aa.py, handoff.py and b3.py write them, with:
- job, session (unique within the job), position (0 to 3), arm (the runner's label; a session is
  X Y Y X of two labels, 4.1), valid (bool), invalid_reasons (list of strings);
- development: false for a frozen run (analyse.py refuses a row without it or marked true; the
  pilot is development data by 4.6 step 1, so pilot.py takes either); dry_run: absent or false;
  synthetic: absent or false (true only in analysis/synth.py's rows, which analyse.py refuses
  unless told they are synthetic);
- provenance.binaries: {name: sha256} of the first-party binaries the window ran, which
  bench/check_rows.py matches against the gates (b3.py writes none yet: design/status.md, M7
  checklist, item 1);
- misclassified: the count of connections classified other than as their script's protocol, where
  the runner reads it (section 7; a count above 0 in any window is a failure of B1, 5.2);
- family, and the fields that name the cell and the arm's role, by family:
  C   (cost, 5.1)  workload churn|keepalive|open, proto http1|h2c|tls|mqtt, backend
                   epoll|io_uring|IOCP, mode one-port|dedicated; one-port rows also detect (the
                   default of rule E) and dispatch inproc where they carry them; metric
                   {name, value}: conn_per_s, req_per_s or ttfb_median_us (window.py);
  B3  (5.2)        b3.py's rows (kind "b3"): system, case silent|partial-hello; the server's rows
                   (system one-port-relay against a proxy, one-port-inproc against a library) also
                   backend and detect; footprint.sample2 {U, Kq, Ks, W, f_mean, skb_growth,
                   shared_growth}; the cell's backend is the server arm's; kind "ophold" rows give
                   K_BASE (WL7) and need no family;
  M1  (5.3)        workload churn, proto http1|h2c, backend, mode one-port, dispatch inproc, detect
                   replay|peek (the default of rule E is the numerator); metric conn_per_s;
  M2  (5.3)        proto http1|tls, backend epoll|io_uring, dispatch inproc|relay; metric
                   {name: "wl6_cpu_us_per_conn", value}: WL6's CPU time of the front and the
                   backend together (the server alone in-process) per connection completed;
  M3  (5.3)        handoff.py's rows (family "M3"): proto tls-stub|http1, system one-port-relay or
                   the proxy, backend epoll; metric conn_per_s;
  S   (section 10) bullet, and by bullet:
                   ssh, mixed, tls-variants (variant resumption|alpn-h2), two-cores (variant
                   two-cores, role by mode; variant reuseport, role by listener reuseport|shared):
                   the C fields; relay-io_uring: the M3 fields on backend io_uring; iocp-forms:
                   variant acceptex-buffer (role by iocp_accept buffer|no-buffer) or receive-form
                   (role by iocp_receive: rule E's form is the default); m-ttfb: hyp M1|M3 and its
                   fields, metric ttfb_median_us; b3-other-mode: b3.py's server rows, detect.
Window values beyond the metric: cpu_us_per_exchange (WL4), rss_kb and peak_rss_kb (WL4),
opgen.ttfb_ns.p99 (WL2), as window.py writes them.

A row of a driver fault (window.run_window's except branch) carries only the session fields; it
takes its cell from the other rows of its session and its role from the other window of its arm
(or the other arm's complement). It is invalid, so its session is.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cells as C

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent / "bench"


class RowsRefused(Exception):
    """The analysis refuses its input; the message says which rows and why."""


# ---------------------------------------------------------------- reading


def read_rows(paths: list[Path]) -> list[dict]:
    """JSON Lines files (one row per line) or JSON files of one row or a list of rows."""
    out: list[dict] = []
    for p in paths:
        text = Path(p).read_text(encoding="utf-8")
        if Path(p).suffix == ".jsonl":
            out += [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            obj = json.loads(text)
            out += obj if isinstance(obj, list) else [obj]
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def where(row: dict) -> str:
    return " ".join(f"{k}={row.get(k)}" for k in ("job", "session", "position", "arm") if k in row)


# ---------------------------------------------------------------- refusals and the gate


def refuse_flags(rows: list[dict], *, frozen: bool, allow_synthetic: bool) -> None:
    """A dry run never counts; a synthetic row only where the caller says the run is synthetic;
    with `frozen`, every row must say development: false (analyse.py)."""
    bad: list[str] = []
    for i, r in enumerate(rows):
        if r.get("dry_run"):
            bad.append(f"row {i} ({where(r)}): a dry run")
        if r.get("synthetic") and not allow_synthetic:
            bad.append(f"row {i} ({where(r)}): synthetic")
        if allow_synthetic and not r.get("synthetic"):
            bad.append(f"row {i} ({where(r)}): a synthetic run takes synthetic rows only")
        if frozen and r.get("development") is not False:
            bad.append(f"row {i} ({where(r)}): development is {r.get('development')!r}, not false")
    if bad:
        raise RowsRefused(f"{len(bad)} rows refused; " + "; ".join(bad[:10]))


def apply_gate(rows: list[dict], gates: list[Path]) -> dict:
    """bench/check_rows.py's rule, through its own functions: every first-party binary a row
    names must appear, with its sha256, in a gate that passed and is citable, and a row that names
    none is refused. Any refused row refuses the whole input (a design choice: dropping rows would
    change the session counts the decisions rest on)."""
    if not gates:
        raise RowsRefused("no gate given: every row must be checked against bench/check_records.py's outputs")
    sys.path.insert(0, str(BENCH))
    try:
        import check_rows  # noqa: PLC0415 - bench/check_rows.py, unchanged
    finally:
        sys.path.remove(str(BENCH))
    covered, left_out = check_rows.load_gates([Path(g) for g in gates])
    refused = check_rows.check(rows, covered)
    if refused:
        raise RowsRefused(f"the gate refused {len(refused)} of {len(rows)} rows; the first: {refused[0]}")
    return {"rows": len(rows), "gates": sorted(Path(g).name for g in gates), "gates_left_out": sorted(left_out),
            "covered_binaries": sorted(f"{n} {s}" for n, s in covered)}


# ---------------------------------------------------------------- what a row says


class RowError(ValueError):
    pass


def _need(row: dict, key: str, allowed: tuple | None = None):
    if key not in row:
        raise RowError(f"{where(row)}: no field {key!r}")
    v = row[key]
    if allowed is not None and v not in allowed:
        raise RowError(f"{where(row)}: {key} = {v!r}, not one of {allowed}")
    return v


def _has(row: dict, *keys: str) -> bool:
    return all(k in row for k in keys)


@dataclass
class Info:
    """What one row says about its cell (fields) and its arm (role); empty for a fault row."""
    fields: dict = field(default_factory=dict)
    role: str | None = None


def info_cost_like(row: dict, rule_e: dict, *, protos: tuple = C.COST_PROTOS) -> Info:
    if not _has(row, "workload", "proto", "backend"):
        return Info()
    wl = _need(row, "workload", tuple(C.WORKLOAD_HYP))
    proto = _need(row, "proto", protos)
    backend = _need(row, "backend", C.COST_BACKENDS)
    mode = row.get("mode")
    if mode is not None and mode not in ("one-port", "dedicated"):
        raise RowError(f"{where(row)}: mode {mode!r}")
    if mode == "one-port":
        if "dispatch" in row and row["dispatch"] != "inproc":
            raise RowError(f"{where(row)}: the cost family dispatches in-process (2.2), not {row['dispatch']!r}")
        if "detect" in row and rule_e and row["detect"] != rule_e["default"][backend]:
            raise RowError(f"{where(row)}: detect {row['detect']!r}, not the default of rule E on {backend}")
    return Info({"hyp": C.WORKLOAD_HYP[wl], "proto": proto, "backend": backend}, mode)


def info_m1(row: dict, rule_e: dict, workload: str = "churn") -> Info:
    """M1's rows (churn, WL1), or section 10's TTFB at a fixed load of an M1 cell (open loop)."""
    if not _has(row, "proto", "backend", "detect"):
        return Info()
    proto = _need(row, "proto", ("http1", "h2c"))
    backend = _need(row, "backend", C.COST_BACKENDS)
    detect = _need(row, "detect", ("replay", "peek"))
    if row.get("mode", "one-port") != "one-port" or row.get("dispatch", "inproc") != "inproc":
        raise RowError(f"{where(row)}: M1 runs one-port mode in-process (5.3)")
    if row.get("workload", workload) != workload:
        raise RowError(f"{where(row)}: workload {row.get('workload')!r}, not {workload}")
    return Info({"proto": proto, "backend": backend}, "default" if detect == rule_e["default"][backend] else "other")


def info_m2(row: dict) -> Info:
    if not _has(row, "proto", "backend", "dispatch"):
        return Info()
    return Info({"proto": _need(row, "proto", ("http1", "tls")), "backend": _need(row, "backend", ("epoll", "io_uring"))},
                _need(row, "dispatch", ("inproc", "relay")))


def info_relay(row: dict, backend_required: str) -> Info:
    """handoff.py's rows: the server's relay (arm A) against a proxy (arm B)."""
    if not _has(row, "proto", "system"):
        return Info()
    proto = _need(row, "proto", C.M3_PROTOS_6_3)
    system = _need(row, "system", (C.SERVER_RELAY,) + C.PROXIES)
    backend = row.get("backend", "epoll")
    if backend != backend_required:
        raise RowError(f"{where(row)}: backend {backend!r}, not {backend_required}")
    if system == C.SERVER_RELAY:
        return Info({"proto": proto}, "server")
    return Info({"proto": proto, "system": system}, "proxy")


def info_b3(row: dict, rule_e: dict) -> Info:
    if row.get("kind") != "b3" or not _has(row, "system", "case"):
        return Info()
    system = _need(row, "system", (C.SERVER_RELAY, C.SERVER_INPROC) + C.SYSTEMS_2_3)
    case = _need(row, "case", C.B3_CASES)
    if system in (C.SERVER_RELAY, C.SERVER_INPROC):
        backend = _need(row, "backend", C.B3_BACKENDS)
        if rule_e and row.get("detect") != rule_e["default"][backend]:
            raise RowError(f"{where(row)}: the server runs B3 in its default detection mode (5.2)")
        return Info({"case": case, "backend": backend, "server_system": system}, "server")
    return Info({"case": case, "system": system}, "competitor")


def info_b3_other(row: dict, rule_e: dict) -> Info:
    if row.get("kind") != "b3" or not _has(row, "system", "case", "backend", "detect"):
        return Info()
    _need(row, "system", (C.SERVER_RELAY, C.SERVER_INPROC))
    backend = _need(row, "backend", C.B3_BACKENDS)
    detect = _need(row, "detect", ("replay", "peek"))
    return Info({"case": _need(row, "case", C.B3_CASES), "backend": backend},
                "default" if detect == rule_e["default"][backend] else "other")


SECONDARY_BULLETS = ("ssh", "mixed", "tls-variants", "two-cores", "relay-io_uring", "iocp-forms", "m-ttfb", "b3-other-mode")


def _field_or_fault(row: dict, key: str, allowed: tuple):
    """A field the cell needs; None from an invalid row that lacks it (a driver fault's row, which
    takes its cell from its session); an error from a valid row that lacks it."""
    if key not in row and not row.get("valid"):
        return None
    return _need(row, key, allowed)


def info_secondary(row: dict, rule_e: dict) -> tuple[str | None, Info]:
    """Section 10's cells (family "S"), by bullet."""
    bullet = _field_or_fault(row, "bullet", SECONDARY_BULLETS)
    if bullet is None:
        return None, Info()
    kind = f"S.{bullet}"
    if bullet == "ssh":
        return kind, info_cost_like(row, rule_e, protos=("ssh",))
    if bullet == "mixed":
        return kind, info_cost_like(row, rule_e)
    if bullet == "tls-variants":
        inf = info_cost_like(row, rule_e)
        v = _field_or_fault(row, "variant", C.TLS_VARIANTS)
        if v is None or not inf.fields:
            return kind, Info()
        inf.fields["variant"] = v
        return kind, inf
    if bullet == "two-cores":
        v = _field_or_fault(row, "variant", C.TWO_CORE_VARIANTS)
        inf = info_cost_like(row, rule_e)
        if v is None or not inf.fields:
            return kind, Info()
        inf.fields["variant"] = v
        if v == "reuseport":
            inf.role = row.get("listener")
            if inf.role is not None and inf.role not in ("reuseport", "shared"):
                raise RowError(f"{where(row)}: listener {inf.role!r}")
        return kind, inf
    if bullet == "relay-io_uring":
        return kind, info_relay(row, "io_uring")
    if bullet == "iocp-forms":
        form = _field_or_fault(row, "variant", C.IOCP_FORMS)
        if form is None:
            return kind, Info()
        if form == "acceptex-buffer":
            acc = row.get("iocp_accept")
            if acc not in (None, "buffer", "no-buffer"):
                raise RowError(f"{where(row)}: iocp_accept {acc!r}")
            role = None if acc is None else ("variant" if acc == "buffer" else "default")
        else:
            rec = row.get("iocp_receive")
            if rec not in (None, "zero-byte", "posted"):
                raise RowError(f"{where(row)}: iocp_receive {rec!r}")
            role = None if rec is None else ("default" if rec == rule_e["iocp_receive"] else "variant")
        return kind, Info({"variant": form}, role)
    if bullet == "m-ttfb":
        hyp = _field_or_fault(row, "hyp", ("M1", "M3"))
        if hyp is None:
            return kind, Info()
        inf = info_m1(row, rule_e, "open") if hyp == "M1" else info_relay(row, "epoll")
        if inf.fields:
            inf.fields["hyp"] = hyp
        return kind, inf
    return kind, info_b3_other(row, rule_e)


def row_info(row: dict, rule_e: dict) -> tuple[str | None, Info]:
    """(the family or bullet key, what the row says). Fault rows give an empty Info."""
    fam = row.get("family")
    if fam is None and row.get("kind") == "b3":
        fam = "B3"
    if fam == "C":
        return "C", info_cost_like(row, rule_e)
    if fam == "B3":
        return "B3", info_b3(row, rule_e)
    if fam == "M1":
        return "M1", info_m1(row, rule_e)
    if fam == "M2":
        return "M2", info_m2(row)
    if fam == "M3":
        return "M3", info_relay(row, "epoll")
    if fam == "S":
        return info_secondary(row, rule_e)
    if fam is None and row.get("kind") == "ophold":
        return "ophold", Info()
    if fam is None and not row.get("valid"):
        return None, Info()   # a driver fault's row: its session names the cell
    raise RowError(f"{where(row)}: family {fam!r} is not one of C, B3, M1, M2, M3, S")


def cell_id(kind: str, f: dict) -> str:
    """The canonical cell id (analysis/cells.py) from a session's merged fields."""
    if kind == "C":
        return f"{f['hyp']}.{C.host_of(f['backend'])}.{f['backend']}.{f['proto']}"
    if kind == "B3":
        system = f["system"]
        want = C.SERVER_RELAY if system in C.PROXIES else C.SERVER_INPROC
        if f.get("server_system") not in (None, want):
            raise RowError(f"B3 against {system}: the server's arm is {f.get('server_system')}, not {want} (5.2)")
        return f"B3.{f['case']}.{system}.{f['backend']}"
    if kind == "M1":
        return f"M1.{C.host_of(f['backend'])}.{f['backend']}.{f['proto']}"
    if kind == "M2":
        return f"M2.L.{f['backend']}.{f['proto']}"
    if kind == "M3":
        return f"M3.L.epoll.{f['proto']}.{f['system']}"
    if kind == "S.ssh":
        return f"S.ssh.{f['hyp']}.{C.host_of(f['backend'])}.{f['backend']}"
    if kind == "S.mixed":
        if (f["hyp"], f["proto"]) != ("C1", "http1"):
            raise RowError("the mixed-protocol cell is C1's HTTP/1.1 churn (section 10)")
        return f"S.mixed.C1.{C.host_of(f['backend'])}.{f['backend']}"
    if kind == "S.tls-variants":
        if (f["hyp"], f["proto"]) != ("C1", "tls"):
            raise RowError("the TLS variants are C1's TLS churn (section 10)")
        return f"S.tls-variants.C1.{C.host_of(f['backend'])}.{f['backend']}.{f['variant']}"
    if kind == "S.two-cores":
        if (f["hyp"], f["proto"]) != ("C1", "http1"):
            raise RowError("the 2-core cells are C1's HTTP/1.1 churn (section 10)")
        return f"S.two-cores.C1.{C.host_of(f['backend'])}.{f['backend']}.{f['variant']}"
    if kind == "S.relay-io_uring":
        return f"S.relay-io_uring.L.io_uring.{f['proto']}.{f['system']}"
    if kind == "S.iocp-forms":
        return f"S.iocp-forms.W.IOCP.{f['variant']}"
    if kind == "S.m-ttfb":
        if f["hyp"] == "M1":
            return f"S.m-ttfb.M1.{C.host_of(f['backend'])}.{f['backend']}.{f['proto']}"
        return f"S.m-ttfb.M3.L.epoll.{f['proto']}.{f['system']}"
    if kind == "S.b3-other-mode":
        return f"S.b3-other-mode.{f['backend']}.{f['case']}"
    raise RowError(f"no cell for {kind}")


# ---------------------------------------------------------------- sessions (4.1)


@dataclass
class Session:
    """Four windows of a cell's two arms in mirrored order, X Y Y X (4.1)."""
    job: str
    id: str
    kind: str
    cell: str
    windows: list[dict]
    roles: dict[str, str]
    valid: bool
    problems: list[str]

    def by_role(self, role: str) -> list[dict]:
        labels = [a for a, r in self.roles.items() if r == role]
        return [w for w in self.windows if str(w.get("arm")) in labels]


def _merge(into: dict, more: dict, what: str) -> None:
    for k, v in more.items():
        if k in into and into[k] != v:
            raise RowError(f"{what}: {k} is {into[k]!r} in one window and {v!r} in another")
        into[k] = v


def assemble(rows: list[dict], info_fn: Callable[[dict], tuple[str, Info]],
             roles_for: Callable[[str, str], tuple[str, str]]) -> list[Session]:
    """Group the rows by (job, session) and check each session's shape. A session is valid when
    it has its four windows at positions 0 to 3, arms X Y Y X, both roles of its cell, and every
    window valid. A session missing windows (a stopped job) is invalid; a session of another shape
    is a fault of the runner and refuses the input. `info_fn` reads a row (row_info, or the
    pilot's); `roles_for(kind, cell)` gives the cell's two roles (num, den). An arm whose windows
    name no role (fault rows) takes the role the other arm leaves."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if r.get("kind") == "ophold":
            continue
        if "job" not in r or "session" not in r:
            raise RowError(f"a row without job or session: {where(r)}")
        groups.setdefault((str(r["job"]), str(r["session"])), []).append(r)
    out: list[Session] = []
    for (job, sid), rs in sorted(groups.items()):
        what = f"session {job}/{sid}"
        kinds, fields, roles = set(), {}, {}
        for r in rs:
            kind, inf = info_fn(r)
            if kind is not None:
                kinds.add(kind)
            _merge(fields, inf.fields, what)
            if inf.role is not None:
                arm = str(r.get("arm"))
                if roles.get(arm, inf.role) != inf.role:
                    raise RowError(f"{what}: arm {arm} has two roles")
                roles[arm] = inf.role
        if len(kinds) != 1:
            raise RowError(f"{what}: rows of {'several families ' + str(sorted(kinds)) if kinds else 'no family'}")
        kind = kinds.pop()
        if not fields:
            raise RowError(f"{what}: no window names its cell")
        cid = cell_id(kind, fields)
        rs = sorted(rs, key=lambda r: r.get("position", -1))
        problems: list[str] = []
        positions = [r.get("position") for r in rs]
        if len(set(positions)) != len(positions) or any(p not in (0, 1, 2, 3) for p in positions):
            raise RowError(f"{what}: positions {positions}")
        if len(rs) < 4:
            problems.append(f"{len(rs)} of 4 windows")
        else:
            arms = [str(r.get("arm")) for r in rs]
            if not (arms[0] == arms[3] and arms[1] == arms[2] and arms[0] != arms[1]):
                raise RowError(f"{what}: arms {arms}, not X Y Y X")
        want = roles_for(kind, cid)
        labels = sorted({str(r.get("arm")) for r in rs})
        known = {a: roles[a] for a in labels if a in roles}
        if len(labels) == 2 and len(known) == 1:
            (a, ra), = known.items()
            other = [x for x in labels if x != a][0]
            known[other] = want[1] if ra == want[0] else want[0]
        if any(r not in want for r in known.values()) or len(set(known.values())) != len(known):
            raise RowError(f"{what}: roles {known}, not {want}")
        if len(rs) == 4 and sorted(known.values()) != sorted(want):
            problems.append(f"roles {known}, not both of {want}")
        invalid = [r for r in rs if not r.get("valid")]
        if invalid:
            problems.append(f"{len(invalid)} invalid windows")
        out.append(Session(job, sid, kind, cid, rs, known, not problems, problems))
    return out


# ---------------------------------------------------------------- values


def metric_value(row: dict, name: str | None) -> float | None:
    m = row.get("metric") or {}
    if name is not None and m.get("name") != name:
        raise RowError(f"{where(row)}: metric {m.get('name')!r}, not {name!r}")
    v = m.get("value")
    return float(v) if v is not None else None


def window_value(row: dict, what: str, metric_name: str | None = None) -> float | None:
    """One window's value: "metric" (the row's metric, checked against `metric_name`), "W" (B3's
    footprint at sample 2), "cpu", "rss", "rss_peak" (WL4) or "ttfb_p99" (WL2)."""
    if what == "metric":
        return metric_value(row, metric_name)
    if what == "W":
        f = ((row.get("footprint") or {}).get("sample2") or {})
        return float(f["W"]) if f.get("W") is not None else None
    if what == "cpu":
        v = row.get("cpu_us_per_exchange")
    elif what == "rss":
        v = row.get("rss_kb")
    elif what == "rss_peak":
        v = row.get("peak_rss_kb")
    elif what == "ttfb_p99":
        v = ((row.get("opgen") or {}).get("ttfb_ns") or {}).get("p99")
    else:
        raise ValueError(what)
    return float(v) if v is not None else None


def arm_mean(windows: list[dict], what: str, metric_name: str | None = None) -> float | None:
    """4.1: an arm's value in a session is the mean of its two windows."""
    vals = [window_value(w, what, metric_name) for w in windows]
    if len(vals) != 2 or any(v is None or not math.isfinite(v) for v in vals):
        return None
    return (vals[0] + vals[1]) / 2.0


def session_ratio(s: Session, num: str, den: str, what: str, metric_name: str | None = None,
                  q_rule: bool = False) -> float | None:
    """The session's statistic, num / den (4.1). With q_rule (B3, 5.2; section 10's B3 cells), a
    denominator of 0 or less gives 0. Otherwise a session whose ratio cannot be formed has no
    value (None)."""
    a = arm_mean(s.by_role(num), what, metric_name)
    b = arm_mean(s.by_role(den), what, metric_name)
    if a is None or b is None:
        return None
    if b <= 0:
        return 0.0 if q_rule else None
    return a / b


def invalid_windows(sessions: list[Session]) -> dict[str, list[dict]]:
    """Per role, every invalid window with its reasons (4.1: reported beside every decision)."""
    out: dict[str, list[dict]] = {}
    for s in sessions:
        for w in s.windows:
            if not w.get("valid"):
                role = s.roles.get(str(w.get("arm")), "unknown")
                out.setdefault(role, []).append({"job": s.job, "session": s.id, "position": w.get("position"),
                                                 "reasons": list(w.get("invalid_reasons") or [])})
    return {k: out[k] for k in sorted(out)}
