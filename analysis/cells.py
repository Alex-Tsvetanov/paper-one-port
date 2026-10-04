"""The frozen cell lists (hypotheses.md, section 6) and the order of every resampling draw (4.7,
section 10), as data.

Families and their resampling generators (4.7):
- SEED_BOOT_C: the 36 cost cells of 6.1, numbered c = 1 to 36 in its order; every cell with R_C
  valid sessions draws its 10,000 resamples once, in that order, whether or not the pilot entry
  resolved it.
- SEED_BOOT_B: B3's 18 Holm cells of 6.2, then its 16 descriptive cells, each with R_B = 16
  valid sessions drawing once.
- SEED_BOOT_M: the 20 mechanism cells of 6.3, in its order.
- SEED_BOOT_S: every other interval, section 10's bullets in their order (SECONDARY below).
A cell with fewer than R valid sessions draws nothing (4.7). A cell's draw serves every statistic
of the cell (the ratio's 95% and Holm-level intervals and both one-sided p-values; B3's Q and D).

Cell ids are strings, built here and by analysis/rows.py from the fields the runners write:
  cost       C1.L.epoll.http1     hypothesis, host, backend, protocol
  B3         B3.silent.nginx.epoll   case, competitor, the server's backend
  M1, M2     M1.W.IOCP.h2c        hypothesis, host, backend, protocol
  M3         M3.L.epoll.tls-stub.nginx   protocol, proxy (the server's relay on epoll)
  secondary  S.<bullet>....       below
Field values are the server's own tokens (bench/server/config.cpp): modes "one-port" and
"dedicated", detection "replay" and "peek", dispatch "inproc" and "relay", backends "epoll",
"io_uring" and "IOCP"; protocols and systems as the runners name them (bench/run/window.py
PROTOS, bench/competitors/competitors.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import stats as S

# ---------------------------------------------------------------- frozen names and orders

# hypotheses.md 2.1: epoll and io_uring on L, IOCP on W; 6.1's backend order.
HOST_OF_BACKEND = {"epoll": "L", "io_uring": "L", "IOCP": "W"}
COST_BACKENDS = ("epoll", "io_uring", "IOCP")
# 6.1: within a backend, HTTP/1.1, h2c, TLS with HTTP/1.1, MQTT (bench/run/window.py's names).
COST_PROTOS = ("http1", "h2c", "tls", "mqtt")
# 5.1 and section 3: C1 churn (WL1), C2 keep-alive (WL3), C3 latency at a fixed load (WL2); the
# metric names bench/run/window.py writes for each workload.
COST_HYPS = ("C1", "C2", "C3")
HYP_WORKLOAD = {"C1": "churn", "C2": "keepalive", "C3": "open"}
WORKLOAD_HYP = {v: k for k, v in HYP_WORKLOAD.items()}
HYP_METRIC = {"C1": "conn_per_s", "C2": "req_per_s", "C3": "ttfb_median_us"}
# 2.3's order of the competitors.
PROXIES = ("nginx", "haproxy", "envoy", "caddy-l4", "sslh-ev")
LIBRARIES = ("netty", "jetty", "cmux", "hyper-util")
SYSTEMS_2_3 = ("nginx", "haproxy", "envoy", "caddy-l4", "sslh-ev", "netty", "jetty", "cmux", "hyper-util")
# bench/run/b3.py and bench/run/window.py: the server's arms.
SERVER_RELAY = "one-port-relay"
SERVER_INPROC = "one-port-inproc"
# 6.2 and WL7: the two cases, in WL7's order.
B3_CASES = ("silent", "partial-hello")
B3_BACKENDS = ("epoll", "io_uring")
B3_HOLM_SYSTEMS = {"silent": ("nginx", "haproxy", "envoy", "sslh-ev", "hyper-util"),
                   "partial-hello": ("nginx", "haproxy", "envoy", "sslh-ev")}
# 6.2: "Netty, Jetty, caddy-l4 and cmux, in both cases, on both backends", in that listing's
# order, with the Holm cells' order rule (case, then system, then backend).
B3_DESCRIPTIVE_SYSTEMS = ("netty", "jetty", "caddy-l4", "cmux")
# 6.3.
M1_CELLS = (("http1", "epoll"), ("http1", "io_uring"), ("http1", "IOCP"), ("h2c", "epoll"), ("h2c", "io_uring"), ("h2c", "IOCP"))
M2_CELLS = (("http1", "epoll"), ("http1", "io_uring"), ("tls", "epoll"), ("tls", "io_uring"))
# M3's two protocols as bench/run/handoff.py names them: TLS routed by SNI is the stub exchange.
M3_PROTOS_6_3 = ("tls-stub", "http1")
# The metric M2's runner writes in every window: WL6, the CPU time of the front and the backend
# together (the server alone in-process) per connection completed (analysis/rows.py).
M2_METRIC = "wl6_cpu_us_per_conn"
CHURN_METRIC = "conn_per_s"
# Cost cells outside the confirmatory family by a logged decision, each with why. Alex's decision of
# 2026-10-04 (hypotheses.md, revision log, "W before the code freeze", item 1): on W, WL1's churn
# h2c and churn MQTT measure the generator, not the server. They run in the A/A pilot only, so that
# WL2 has their medians for the open-loop rates of the C3 cells of h2c and MQTT on W (the
# coordinator's decision, logged in M7e's entry); the pilot entry simulates them, as 9.2 asks of
# every cost cell, and never resolves them, so they set neither R_C nor m_C (4.6 steps 5 to 7).
COST_OUTSIDE_FAMILY = {
    cid: ("outside the confirmatory cost family: generator-bound on W (Alex's decision of 2026-10-04; revision log, "
          "entry W before the code freeze, item 1)")
    for cid in ("C1.W.IOCP.h2c", "C1.W.IOCP.mqtt")
}
# WL4's CPU value of a window, by host (analysis/rows.py's window_value): on L the server's utime
# plus stime per exchange (the M3 entry's reading 7); on W the server's cycles per exchange
# (QueryProcessCycleTime; revision log, "W before the code freeze", item 4, a design choice), whose
# ratio of two arms needs no conversion. The tick-based GetProcessTimes value W's rows carry beside
# it (cpu_us_per_exchange) is never read.
CPU_FIELD = {"L": "cpu_us_per_exchange", "W": "cycles_per_exchange"}

# Replicates: 4.1 and 4.5 (R_B = R_M = 16); section 10 (secondary cells at R = 16).
R_B = 16
R_M = 16
R_SECONDARY = 16


def host_of(backend: str) -> str:
    try:
        return HOST_OF_BACKEND[backend]
    except KeyError:
        raise ValueError(f"backend {backend!r}, not one of {sorted(HOST_OF_BACKEND)}") from None


@dataclass(frozen=True)
class Cell:
    """One cell of a family list. `num` and `den` are the roles whose arm values make the session
    ratio num / den, in the direction its hypothesis states (4.1, 5.1 to 5.3). `test` is "tost"
    (4.3), "greater" (median above `bound`: B3, M1, M3) or "less" (M2). `holm` is whether the cell
    is in its family's Holm list (for the cost family the pilot entry decides it; this is the
    frozen list's flag, before the pilot). `r` is None for the cost family (R_C)."""
    id: str
    family: str
    hyp: str
    number: int
    host: str
    backend: str
    proto: str | None
    system: str | None
    case: str | None
    num: str
    den: str
    test: str
    bound: float | None
    holm: bool
    r: int | None
    metric: str


def cost_cells() -> list[Cell]:
    """6.1, c = 1 to 36: C1, C2, C3; L before W; epoll, io_uring, IOCP; HTTP/1.1, h2c, TLS, MQTT.
    Session ratio one-port / dedicated (5.1)."""
    out: list[Cell] = []
    c = 0
    for hyp in COST_HYPS:
        for backend in COST_BACKENDS:
            for proto in COST_PROTOS:
                c += 1
                host = host_of(backend)
                out.append(Cell(f"{hyp}.{host}.{backend}.{proto}", "C", hyp, c, host, backend, proto, None, None,
                                "one-port", "dedicated", "tost", None, True, None, HYP_METRIC[hyp]))
    return out


def b3_cells() -> list[Cell]:
    """6.2: the 18 Holm cells (case, then system, then backend epoll before io_uring), then the 16
    descriptive cells by the same rule. Q = W_comp / W_srv (5.2)."""
    out: list[Cell] = []
    n = 0
    for holm, systems in ((True, B3_HOLM_SYSTEMS), (False, {c: B3_DESCRIPTIVE_SYSTEMS for c in B3_CASES})):
        for case in B3_CASES:
            for system in systems[case]:
                for backend in B3_BACKENDS:
                    n += 1
                    out.append(Cell(f"B3.{case}.{system}.{backend}", "B3", "B3", n, "L", backend, None, system, case,
                                    "competitor", "server", "greater", S.B3_BOUND, holm, R_B, "W"))
    return out


def m_cells() -> list[Cell]:
    """6.3: M1 (6), M2 (4), M3 (10), in that order. M1 default / other mode; M2 in-process /
    relay; M3 server / proxy (5.3)."""
    out: list[Cell] = []
    n = 0
    for proto, backend in M1_CELLS:
        n += 1
        host = host_of(backend)
        out.append(Cell(f"M1.{host}.{backend}.{proto}", "M", "M1", n, host, backend, proto, None, None,
                        "default", "other", "greater", S.M_BOUND, True, R_M, CHURN_METRIC))
    for proto, backend in M2_CELLS:
        n += 1
        out.append(Cell(f"M2.L.{backend}.{proto}", "M", "M2", n, "L", backend, proto, None, None,
                        "inproc", "relay", "less", S.M_BOUND, True, R_M, M2_METRIC))
    for proto in M3_PROTOS_6_3:
        for system in PROXIES:
            n += 1
            out.append(Cell(f"M3.L.epoll.{proto}.{system}", "M", "M3", n, "L", "epoll", proto, system, None,
                            "server", "proxy", "greater", S.M_BOUND, True, R_M, CHURN_METRIC))
    return out


FAMILY_LISTS = {"C": cost_cells, "B3": b3_cells, "M": m_cells}
FAMILY_ORDER = ("C", "B3", "M")


def all_family_cells() -> dict[str, Cell]:
    return {c.id: c for fam in FAMILY_ORDER for c in FAMILY_LISTS[fam]()}


# ---------------------------------------------------------------- section 10, in SEED_BOOT_S's order


@dataclass(frozen=True)
class SecondaryCell:
    """A secondary cell with sessions of its own (section 10), R = 16. `num`/`den` as Cell's; the
    row fields that identify it are in `key`."""
    id: str
    bullet: str
    host: str
    backend: str
    num: str
    den: str
    metric: str | None
    key: tuple = ()
    ratio_rule: str = "ratio"   # "ratio", or "q" (B3's Q: a non-positive denominator gives 0)


@dataclass(frozen=True)
class Draw:
    """One interval of SEED_BOOT_S, in order. `source` names the cell whose sessions it resamples
    (a family cell or a secondary cell); `metric` the window value it takes; `clustered` whether
    the resample draws lab jobs instead of sessions (the analysis clustered by job)."""
    bullet: str
    source: str
    metric: str
    r: int | None
    clustered: bool = False


# Bullet names, in section 10's order. The bullets without intervals are named so the list is
# whole; they draw nothing: "unresolved" and "b3-descriptive" (their intervals come from the
# family's draws, 4.7), "operations" (counts of untimed windows and of the counters, no
# interval), "competitor-cases" and "b2-distributions" (descriptive tables).
BULLETS = ("wl4", "unresolved", "ssh", "mixed", "tls-variants", "two-cores", "relay-io_uring", "iocp-forms",
           "operations", "m-ttfb-cpu", "b3-other-mode", "b3-descriptive", "competitor-cases", "b2-distributions",
           "by-job")

# WL4 and WL2 metrics of the first bullet, in the order the bullet names them: CPU per connection
# or request, resident memory at the end and its peak (WL4), then p99 TTFB (WL2, C3 cells).
WL4_METRICS = ("cpu", "rss", "rss_peak")
WL2_P99 = "ttfb_p99"
TLS_VARIANTS = ("resumption", "alpn-h2")
TWO_CORE_VARIANTS = ("two-cores", "reuseport")
IOCP_FORMS = ("acceptex-buffer", "receive-form")
# 6.1's protocol order, which section 10's bullets follow (4.7), for the relay on io_uring.
RELAY_IO_URING_PROTOS = ("http1", "tls-stub")


def secondary_cells() -> list[SecondaryCell]:
    """The secondary cells that need sessions of their own (section 10), each bullet's cells in
    4.7's order (hypothesis, host, backend, protocol; then the system in 2.3's order; a case,
    variant or form after the protocol, in the order the bullet names it)."""
    out: list[SecondaryCell] = []
    # SSH in the cost family: C1 to C3 on three backends, one-port / dedicated.
    for hyp in COST_HYPS:
        for backend in COST_BACKENDS:
            out.append(SecondaryCell(f"S.ssh.{hyp}.{host_of(backend)}.{backend}", "ssh", host_of(backend), backend,
                                     "one-port", "dedicated", HYP_METRIC[hyp], (hyp, "ssh")))
    # The mixed-protocol cell: C1's HTTP/1.1 churn with the fixed background, on each backend.
    for backend in COST_BACKENDS:
        out.append(SecondaryCell(f"S.mixed.C1.{host_of(backend)}.{backend}", "mixed", host_of(backend), backend,
                                 "one-port", "dedicated", CHURN_METRIC, ("C1", "http1")))
    # TLS with session resumption, and TLS with ALPN h2: C1 on each backend.
    for backend in COST_BACKENDS:
        for v in TLS_VARIANTS:
            out.append(SecondaryCell(f"S.tls-variants.C1.{host_of(backend)}.{backend}.{v}", "tls-variants", host_of(backend),
                                     backend, "one-port", "dedicated", CHURN_METRIC, ("C1", "tls", v)))
    # 2 server cores: C1 HTTP/1.1 one-port / dedicated on each backend; the SO_REUSEPORT group
    # against the shared listener, both one-port, on epoll and io_uring.
    for backend in COST_BACKENDS:
        out.append(SecondaryCell(f"S.two-cores.C1.{host_of(backend)}.{backend}.two-cores", "two-cores", host_of(backend),
                                 backend, "one-port", "dedicated", CHURN_METRIC, ("C1", "http1", "two-cores")))
        if backend != "IOCP":
            out.append(SecondaryCell(f"S.two-cores.C1.{host_of(backend)}.{backend}.reuseport", "two-cores", host_of(backend),
                                     backend, "reuseport", "shared", CHURN_METRIC, ("C1", "http1", "reuseport")))
    # The server's relay on io_uring against the proxies, server / proxy.
    for proto in RELAY_IO_URING_PROTOS:
        for system in PROXIES:
            out.append(SecondaryCell(f"S.relay-io_uring.L.io_uring.{proto}.{system}", "relay-io_uring", "L", "io_uring",
                                     "server", "proxy", CHURN_METRIC, (proto, system)))
    # On IOCP: AcceptEx with a receive buffer; the receive form rule E did not choose; each
    # against the default form. The metric is the windows' own (section 10 names none).
    for form in IOCP_FORMS:
        out.append(SecondaryCell(f"S.iocp-forms.W.IOCP.{form}", "iocp-forms", "W", "IOCP", "variant", "default", None, (form,)))
    # M1 and M3, TTFB at a fixed load: cells of their own (open-loop sessions).
    for c in m_cells():
        if c.hyp in ("M1", "M3"):
            out.append(SecondaryCell(f"S.m-ttfb.{c.id}", "m-ttfb-cpu", c.host, c.backend, c.num, c.den, "ttfb_median_us",
                                     (c.id,)))
    # B3 with the server in its other detection mode against its default mode, Q = other / default.
    for backend in B3_BACKENDS:
        for case in B3_CASES:
            out.append(SecondaryCell(f"S.b3-other-mode.{backend}.{case}", "b3-other-mode", "L", backend, "other", "default",
                                     "W", (case,), "q"))
    return out


def _m_bullet_order(c: Cell) -> tuple:
    """4.7's order within a bullet for the mechanism cells: hypothesis, host, backend, protocol
    (6.1's order), then the system in 2.3's order."""
    protos = ("http1", "h2c", "tls", "tls-stub", "mqtt")
    return (("M1", "M2", "M3").index(c.hyp), c.host, COST_BACKENDS.index(c.backend), protos.index(c.proto),
            SYSTEMS_2_3.index(c.system) if c.system else -1)


def secondary_draws() -> list[Draw]:
    """Every interval drawn from SEED_BOOT_S, in order (4.7, section 10). R None means the cost
    family's R_C."""
    sec = {c.id: c for c in secondary_cells()}
    out: list[Draw] = []
    # 1. CPU and resident memory for every cost cell (WL4); p99 TTFB (WL2): the cost cells in
    #    6.1's order, the metrics in the bullet's order.
    for c in cost_cells():
        for m in WL4_METRICS:
            out.append(Draw("wl4", c.id, m, None))
        if c.hyp == "C3":
            out.append(Draw("wl4", c.id, WL2_P99, None))
    # 2. Cost cells not resolved: nothing (their family's draws).
    # 3 to 8: the cells of their own, bullet by bullet.
    for bullet in ("ssh", "mixed", "tls-variants", "two-cores", "relay-io_uring", "iocp-forms"):
        for s in secondary_cells():
            if s.bullet == bullet:
                out.append(Draw(bullet, s.id, "value", R_SECONDARY))
    # 9. Operations and copies: nothing.
    # 10. For M1 and M3, TTFB at a fixed load; for every M cell, CPU per connection: per cell in
    #     4.7's order, TTFB then CPU.
    for c in sorted(m_cells(), key=_m_bullet_order):
        if c.hyp in ("M1", "M3"):
            out.append(Draw("m-ttfb-cpu", f"S.m-ttfb.{c.id}", "value", R_SECONDARY))
        out.append(Draw("m-ttfb-cpu", c.id, "cpu", R_M))
    # 11. B3 in the other detection mode.
    for s in secondary_cells():
        if s.bullet == "b3-other-mode":
            out.append(Draw("b3-other-mode", s.id, "value", R_SECONDARY))
    # 12 to 14: nothing.
    # 15. Every family clustered by lab job: the cells of section 6, family by family.
    for fam in FAMILY_ORDER:
        for c in FAMILY_LISTS[fam]():
            out.append(Draw("by-job", c.id, "value", c.r, clustered=True))
    assert all(d.source in sec or d.source in all_family_cells() for d in out)
    return out


# ---------------------------------------------------------------- seeds (4.7, 9.1)

SEED_NAMES = ("SEED_ORDER_C_L", "SEED_ORDER_C_W", "SEED_ORDER_B_L", "SEED_ORDER_M_L", "SEED_ORDER_M_W",
              "SEED_ORDER_S_L", "SEED_ORDER_S_W", "SEED_BOOT_C", "SEED_BOOT_B", "SEED_BOOT_M", "SEED_BOOT_S",
              "SEED_PILOT_L", "SEED_PILOT_W", "SEED_SIM")
FAMILY_BOOT_SEED = {"C": "SEED_BOOT_C", "B3": "SEED_BOOT_B", "M": "SEED_BOOT_M"}


def check_seeds(seeds: dict) -> dict[str, int]:
    """The seeds file: exactly the 14 names of 4.7, each a non-negative integer (the revision-log
    entry of section 8 step 2 fixes their values; this code holds none)."""
    names = set(seeds)
    missing = [n for n in SEED_NAMES if n not in names]
    extra = sorted(names - set(SEED_NAMES))
    if missing or extra:
        raise ValueError(f"seeds: missing {missing}, unknown {extra}")
    out = {}
    for n in SEED_NAMES:
        v = seeds[n]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(f"seed {n} = {v!r} is not a non-negative integer")
        out[n] = v
    return out
