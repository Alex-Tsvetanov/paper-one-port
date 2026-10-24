"""Shared paths, words and checks of the laptop's generated files (results/laptop-w/).

The frozen analysis on L's October rows and the laptop's W rows wrote results/laptop-w/summary.json,
decisions.csv, macros.tex and hardcase-macros.tex (status.md, "The frozen analysis on the laptop's
W rows, 2026-10-25"). The generators in this folder write the other files the paper prints from,
into results/laptop-w/ as well, and never touch October's files under results/. They read the
laptop's archived rows, each checked against the sha256 a results file or the revision log names
for it, and the frozen inputs. No desktop row is read: the desktop's jobs (wp1, wre1, wc1, wc2, wm1,
wh1, ws1) are refused by name wherever a row names its job.

The tables of this folder print paper wording, never an internal label: "Linux" and "Windows",
never L or W; the comparison in words, never C1 to C3 or M1 to M3; a cell in words, never its key.
Every word comes from a fixed map, and a key the map does not hold stops the run.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER = HERE.parent
ROOT = PAPER.parent
RESULTS = ROOT / "results"
LW = RESULTS / "laptop-w"
TABLES = LW / "tables"
HYP = ROOT / "hypotheses.md"
STATUS = ROOT / "design" / "status.md"

sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(PAPER))

import macros as AM  # noqa: E402  analysis/macros.py, read only: its formatters and store

DESKTOP_JOBS = frozenset({"wp1", "wre1", "wc1", "wc2", "wm1", "wh1", "ws1"})

HOST = {"L": "Linux", "W": "Windows"}
BACKEND = {"epoll": "epoll", "io_uring": "io\\_uring", "IOCP": "IOCP"}
PROTO = {"http1": "HTTP/1.1", "h2c": "h2c", "tls": "TLS", "mqtt": "MQTT", "ssh": "SSH", "tls-stub": "TLS (SNI)"}
SYSTEM = {"nginx": "nginx", "haproxy": "HAProxy", "envoy": "Envoy", "caddy-l4": "caddy-l4", "sslh-ev": "sslh-ev",
          "netty": "Netty", "jetty": "Jetty", "cmux": "cmux", "hyper-util": "hyper-util"}
CASE = {"silent": "silent", "partial-hello": "partial ClientHello"}
# The comparison of each hypothesis, in the words a table prints.
COMPARISON = {
    "C1": "churn",
    "C2": "keep-alive",
    "C3": "fixed load",
    "M1": "detection mode",
    "M2": "dispatch",
    "M3": "relay against proxy",
    "B3": "pending footprint",
}
# Section 10's variants, in words.
VARIANT = {"resumption": "TLS, resumption", "alpn-h2": "TLS, ALPN h2", "two-cores": "two server cores",
           "reuseport": "SO\\_REUSEPORT group", "acceptex-buffer": "AcceptEx with a buffer",
           "receive-form": "the other receive form"}


def need(table: dict, key: str, what: str) -> str:
    if key not in table:
        raise ValueError(f"no paper wording for the {what} {key!r}")
    return table[key]


def where(host: str, backend: str) -> str:
    """L, epoll -> Linux, epoll."""
    return f"{need(HOST, host, 'host')}, {need(BACKEND, backend, 'backend')}"


def family_cell_columns(cell: str) -> tuple[str, str, str]:
    """C1.L.epoll.http1 -> (churn, Linux, epoll, HTTP/1.1) as three table columns."""
    p = cell.split(".")
    if len(p) != 4 or p[0] not in ("C1", "C2", "C3"):
        raise ValueError(f"not a cost cell: {cell}")
    return need(COMPARISON, p[0], "comparison"), where(p[1], p[2]), need(PROTO, p[3], "protocol")


def cell_phrase(cell: str) -> str:
    """Any family cell in words, as one table column."""
    p = cell.split(".")
    if p[0] in ("C1", "C2", "C3") and len(p) == 4:
        return f"{COMPARISON[p[0]]}, {where(p[1], p[2])}, {need(PROTO, p[3], 'protocol')}"
    if p[0] in ("M1", "M2") and len(p) == 4:
        return f"{COMPARISON[p[0]]}, {where(p[1], p[2])}, {need(PROTO, p[3], 'protocol')}"
    if p[0] == "M3" and len(p) == 5:
        return (f"{COMPARISON['M3']}, {where(p[1], p[2])}, {need(PROTO, p[3], 'protocol')}, "
                f"{need(SYSTEM, p[4], 'system')}")
    if p[0] == "B3" and len(p) == 4:
        return (f"{COMPARISON['B3']}, {need(CASE, p[1], 'case')}, {need(SYSTEM, p[2], 'system')}, "
                f"Linux, {need(BACKEND, p[3], 'backend')}")
    raise ValueError(f"no paper wording for the cell {cell}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_checked(path: Path, allowed: set[str], what: str) -> tuple[str, str]:
    """The file's text and sha256, if its sha256 is one the repository names."""
    digest = sha256_file(path)
    if digest not in allowed:
        raise ValueError(f"{what}: {path} has sha256 {digest}, which the repository does not name for it")
    return Path(path).read_text(encoding="utf-8"), digest


def macro_names(path: Path) -> set[str]:
    return set(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", Path(path).read_text(encoding="utf-8")))


def refuse_desktop_rows(rows: list[dict], what: str) -> None:
    jobs = {str(r.get("job")) for r in rows} & DESKTOP_JOBS
    if jobs:
        raise ValueError(f"{what}: rows of the desktop's jobs {sorted(jobs)}; no desktop row is read")


def write_all(out: dict[Path, str], check: bool) -> int:
    """Write every output with LF endings, or with check compare and write nothing."""
    if check:
        stale = [p for p, t in out.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        for p in stale:
            print("differs:", p.relative_to(ROOT).as_posix())
        return 1 if stale else 0
    for p, t in out.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(t)
    return 0


# The internal tokens of Papers lab/bin/check_manuscript_terms.py that a table body must not print,
# read on the table's text with every macro call removed (a macro name is not printed).
PRINTED_TOKENS = re.compile(
    r"(?<![\w.\-/])[WL](?![\w\-/])"            # a host label
    r"|(?<![\w.\-/])[BCMH]\d+[a-z]?(?![\w\-.])"  # a hypothesis or family label
    r"|(?<![\w./])[A-Za-z][\w-]*(?:\.[\w-]+)*\.[LW]\.[\w-]+"  # a cell key
    r"|[\u2012\u2013\u2014\u2015]"              # a dash
)


def printed_label_hits(table_text: str) -> list[str]:
    body = "\n".join(ln for ln in table_text.splitlines() if not ln.startswith("%"))
    body = re.sub(r"\\[A-Za-z]+(\{\})?", "", body)
    return PRINTED_TOKENS.findall(body)
