#!/usr/bin/env python3
"""The kernel census table and its macros (results/laptop-w/census-macros.tex, tables/census.tex).

Reads the archives of the two lab jobs that ran paper/laptop_w/census_host.py, one on the laptop's
Arch and one on the laptop's Windows. Each archive is checked against its .sha256 file, and must hold
exactly one <job>/out/census/census.json. A record is refused unless:

- it comes from a lab job (p3-census-l or p3-census-w, with an optional -N) and is not a functional
  test, its host and OS are the archive's, and it says that no load was sent and 127.0.0.1 was bound;
- its gate is the gate the laptop set's analysis read for that host (results/laptop-w/provenance.json)
  and its binary is that gate's oneport; on Linux the repository's lab/gates/gate-L.json names the
  same binary; on Windows the binary is the one W oneport that the analysis's gates cover
  (results/laptop-w/summary.json, gate.covered_binaries, less gate-L.json's); the desktop's W binary
  (lab/gates/gate-W.json) is refused by name;
- its clone's commit is the one its job spec clones (paper/laptop_w/jobs/census-l.json or -w.json);
- it is complete, and every row of census_host.RUNS ran once, on that row's port: ready, stopped as
  the harnesses stop it, both kernel sources agreeing, the kernel's rows at 127.0.0.1 on each of the
  row's ports and on no other, the count equal to its kernel rows, no IPv6 row.

The macros give each count (the kernel's) and the server's own listening lines beside it, and each
system's date (the two jobs run on different days). The table prints paper wording only ("Linux",
"Windows"; never L or W).

    python -X utf8 paper/laptop_w/census_lw.py --l-archive p3-census-l.tar.gz --w-archive p3-census-w.tar.gz [--check]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import census_host as H  # noqa: E402
import lw_common as C  # noqa: E402

OUT_MACROS = C.LW / "census-macros.tex"
OUT_TABLE = C.TABLES / "census.tex"
MEMBER = "out/census/census.json"
JOB_RE = {"L": re.compile(r"^p3-census-l(-\d+)?$"), "W": re.compile(r"^p3-census-w(-\d+)?$")}
PROVENANCE_ROLE = {"L": "--gate (L's rows)", "W": "--gate (the laptop's W rows)"}
OS_OF = {"L": "linux", "W": "windows"}
JOBS = Path(__file__).resolve().parent / "jobs"

# (host, backend, mode, listener, workers) -> macro name, layout words. The rows of census_host.RUNS.
ROWS = (
    ("L", "epoll", "one-port", "shared", 1, "CensusLEpollOnePort", "one-port, shared listener, one worker"),
    ("L", "epoll", "dedicated", "shared", 1, "CensusLEpollDedicated", "dedicated, one socket per protocol"),
    ("L", "epoll", "one-port", "reuseport", 2, "CensusLEpollReuseport", "one-port, SO\\_REUSEPORT, two workers"),
    ("L", "io_uring", "one-port", "shared", 1, "CensusLIouringOnePort", "one-port, shared listener, one worker"),
    ("L", "io_uring", "dedicated", "shared", 1, "CensusLIouringDedicated", "dedicated, one socket per protocol"),
    ("W", "IOCP", "one-port", "shared", 1, "CensusWIocpOnePort", "one-port, shared listener, one worker"),
    ("W", "IOCP", "dedicated", "shared", 1, "CensusWIocpDedicated", "dedicated, one socket per protocol"),
)
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


def spell_date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{int(day)} {MONTHS[int(month) - 1]} {year}"


def covered_oneports(summary: dict) -> set[str]:
    """The oneport binaries that the gates of the laptop set's analysis cover (summary.json)."""
    return {line.split()[1] for line in summary["gate"]["covered_binaries"] if line.split()[0] == "oneport"}


def spec_commit(host: str, jobs_dir: Path) -> str:
    """The commit that the host's census job spec clones (paper/laptop_w/jobs/census-l.json or -w.json)."""
    jobs = json.loads((jobs_dir / f"census-{host.lower()}.json").read_text(encoding="utf-8"))["jobs"]
    if len(jobs) != 1:
        raise ValueError(f"census-{host.lower()}.json holds {len(jobs)} jobs, not one")
    return jobs[0]["commit"]


def gate_sha256(host: str, provenance: dict) -> str:
    hits = [f["sha256"] for f in provenance["files"] if f.get("role") == PROVENANCE_ROLE[host]]
    if len(hits) != 1:
        raise ValueError(f"provenance.json names {len(hits)} gates for {host}'s rows, not one")
    return hits[0]


def read_archive(archive: Path) -> tuple[dict, str, str]:
    """The record, its job folder and the archive's sha256."""
    sums = Path(str(archive) + ".sha256").read_text(encoding="utf-8").split()
    digest = C.sha256_file(archive)
    if not sums or sums[0] != digest:
        raise ValueError(f"{archive.name}: its sha256 does not equal its .sha256 file's")
    with tarfile.open(archive, "r:gz") as tf:
        hits = [m for m in tf.getmembers() if m.isfile() and m.name.replace("\\", "/").endswith(MEMBER)]
        if len(hits) != 1:
            raise ValueError(f"{archive.name}: {len(hits)} files {MEMBER}, not one")
        name = hits[0].name.replace("\\", "/")
        rec = json.loads(tf.extractfile(hits[0]).read().decode("utf-8-sig"))
    folder = name[: -len(MEMBER)].strip("/").split("/")[-1] if name != MEMBER else ""
    return rec, folder, digest


def check_record(host: str, rec: dict, folder: str, provenance: dict, gates_dir: Path,
                 summary: dict | None = None, jobs_dir: Path = JOBS) -> dict:
    """The rows of one host's record, by (host, backend, mode, listener, workers), after every check."""
    where = f"the census of {host}"
    if summary is None:
        summary = json.loads((C.LW / "summary.json").read_text(encoding="utf-8"))
    job = rec.get("job")
    if not job or not JOB_RE[host].match(str(job)):
        raise ValueError(f"{where}: job {job!r} is not a lab job p3-census-{host.lower()}")
    if folder and folder != job:
        raise ValueError(f"{where}: the archive's job folder {folder!r} is not the record's job {job!r}")
    if rec.get("functional_test") is not False:
        raise ValueError(f"{where}: a functional test, never a result")
    if rec.get("host") != host or rec.get("os") != OS_OF[host]:
        raise ValueError(f"{where}: the record names host {rec.get('host')!r} on {rec.get('os')!r}")
    if rec.get("load") is not False or rec.get("bind") != H.LOOPBACK:
        raise ValueError(f"{where}: the record does not say no load and a {H.LOOPBACK} bind")
    if rec.get("refused") or rec.get("complete") is not True:
        raise ValueError(f"{where}: not complete ({rec.get('refused') or 'a run failed'})")
    desktop = json.loads((gates_dir / "gate-W.json").read_text(encoding="utf-8"))["binaries"]["oneport"]
    if rec.get("binary_sha256") == desktop:
        raise ValueError(f"{where}: the desktop's W binary {desktop[:8]}; no desktop build is read")
    want_gate = gate_sha256(host, provenance)
    if rec.get("gate_sha256") != want_gate:
        raise ValueError(f"{where}: gate {str(rec.get('gate_sha256'))[:8]}, not the analysis's {want_gate[:8]}")
    if rec.get("binary_sha256") != rec.get("gate_oneport_sha256"):
        raise ValueError(f"{where}: the binary is not its gate's oneport")
    gate_l = gates_dir / "gate-L.json"
    l_oneport = json.loads(gate_l.read_text(encoding="utf-8"))["binaries"]["oneport"]
    if host == "L":
        if C.sha256_file(gate_l) != want_gate:
            raise ValueError(f"{where}: lab/gates/gate-L.json is not the analysis's gate")
        if l_oneport != rec["binary_sha256"]:
            raise ValueError(f"{where}: the binary is not lab/gates/gate-L.json's oneport")
    else:
        w_oneports = covered_oneports(summary) - {l_oneport}
        if len(w_oneports) != 1 or rec.get("binary_sha256") not in w_oneports:
            raise ValueError(f"{where}: the binary {str(rec.get('binary_sha256'))[:8]} is not the W oneport that "
                             "the analysis's gates cover (results/laptop-w/summary.json)")
    want_commit = spec_commit(host, jobs_dir)
    if rec.get("src_commit") != want_commit:
        raise ValueError(f"{where}: the clone's commit {str(rec.get('src_commit'))[:12]} is not the job spec's {want_commit[:12]}")
    expected = {(host, r.backend, r.mode, r.listener, r.workers): r for r in H.RUNS[OS_OF[host]]}
    rows = {}
    for run in rec.get("runs", []):
        key = (host, run["backend"], run["mode"], run["listener"], run["workers"])
        kernel = run.get("ss" if host == "L" else "netstat", [])
        problems = []
        if key in rows:
            problems.append("ran twice")
        spec = expected.get(key)
        if spec is not None and run.get("port") != spec.port:
            problems.append(f"port {run.get('port')}, not {spec.port}")
        if spec is not None:
            allowed = {f"{H.LOOPBACK}:{p}" for p in spec.ports()}
            locals_ = {r.get("local") for r in kernel}
            ports = sorted({int(str(a).rsplit(":", 1)[1]) for a in locals_ if a in allowed})
            if not locals_ <= allowed:
                problems.append(f"kernel addresses outside {H.LOOPBACK} and its ports: {sorted(map(str, locals_ - allowed))}")
            elif ports != spec.ports():
                problems.append(f"the kernel lists the ports {ports}, not each of {spec.ports()}")
        if not run.get("ok") or run.get("problem") or run.get("exit_code") != 0:
            problems.append(f"failed ({run.get('problem')}, exit {run.get('exit_code')})")
        if run.get("stopped_by") not in ("SIGTERM", "stop event"):
            problems.append(f"stopped by {run.get('stopped_by')!r}")
        if run.get("agree") is not True:
            problems.append("its kernel sources disagree")
        if run.get("kernel_listen_count") != len(kernel):
            problems.append("its count is not its kernel rows")
        if run.get("v6_rows"):
            problems.append("IPv6 rows")
        if run.get("server_listening_lines") != len(run.get("server_lines", [])):
            problems.append("its server line count is not its lines")
        if problems:
            raise ValueError(f"{where}: row {key}: " + "; ".join(problems))
        rows[key] = (run["kernel_listen_count"], run["server_listening_lines"])
    want = {r[:5] for r in ROWS if r[0] == host}
    if set(rows) != want:
        raise ValueError(f"{where}: rows missing {sorted(want - set(rows))}, extra {sorted(set(rows) - want)}")
    return rows


def render(recs: dict[str, tuple[dict, str, str]], names: dict[str, str]) -> tuple[str, str]:
    counts = {}
    for host, (rec, _folder, _digest) in recs.items():
        counts.update(rec["_rows"])
    src = " and ".join(f"{names[h]} (sha256 {recs[h][2][:8]})" for h in ("L", "W"))
    mac = [
        f"% Generated by paper/laptop_w/census_lw.py from the lab jobs' archives {src}.",
        "% Each count is the kernel's (ss on Linux, netstat on Windows); each Lines macro is the server's own",
        "% listening lines, which are not the count. No client connected. Do not edit.",
        f"\\newcommand{{\\CensusDateL}}{{{spell_date(recs['L'][0]['date'])}}}",
        f"\\newcommand{{\\CensusDateW}}{{{spell_date(recs['W'][0]['date'])}}}",
    ]
    tab = ["% Generated by paper/laptop_w/census_lw.py. Do not edit."]
    for host, backend, mode, listener, workers, name, layout in ROWS:
        count, lines = counts[(host, backend, mode, listener, workers)]
        mac.append(f"\\newcommand{{\\{name}}}{{{int(count)}}}")
        mac.append(f"\\newcommand{{\\{name}Lines}}{{{int(lines)}}}")
        tab.append(f"{C.need(C.HOST, host, 'host')} & {C.need(C.BACKEND, backend, 'backend')} & {layout} "
                   f"& \\{name} & \\{name}Lines \\\\")
    return "\n".join(mac) + "\n", "\n".join(tab) + "\n"


def build(l_archive: Path, w_archive: Path) -> dict[Path, str]:
    provenance = json.loads((C.LW / "provenance.json").read_text(encoding="utf-8"))
    gates_dir = C.ROOT / "lab" / "gates"
    recs = {}
    for host, archive in (("L", l_archive), ("W", w_archive)):
        rec, folder, digest = read_archive(archive)
        rec["_rows"] = check_record(host, rec, folder, provenance, gates_dir)
        recs[host] = (rec, folder, digest)
    macros, table = render(recs, {"L": l_archive.name, "W": w_archive.name})
    others = set()
    for f in sorted(C.LW.glob("*macros.tex")):
        if f.name not in (OUT_MACROS.name, "pack-macros.tex"):
            others |= C.macro_names(f)
    others |= C.macro_names(C.RESULTS / "trace-macros.tex")
    clash = set(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", macros)) & others
    if clash:
        raise ValueError(f"names another file of the laptop set holds: {sorted(clash)}")
    hits = C.printed_label_hits(table)
    if hits:
        raise ValueError(f"the table prints internal labels: {hits}")
    return {OUT_MACROS: macros, OUT_TABLE: table}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--l-archive", type=Path, required=True, help="the Arch census job's archive")
    ap.add_argument("--w-archive", type=Path, required=True, help="the Windows census job's archive")
    ap.add_argument("--check", action="store_true", help="compare with the committed files, write nothing")
    a = ap.parse_args(argv)
    out = build(a.l_archive, a.w_archive)
    rc = C.write_all(out, a.check)
    if not a.check:
        print(f"census: {len(ROWS)} rows to {OUT_TABLE.relative_to(C.ROOT).as_posix()} and "
              f"{OUT_MACROS.relative_to(C.ROOT).as_posix()}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
