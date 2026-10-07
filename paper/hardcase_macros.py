#!/usr/bin/env python3
"""B1's and B2's counts and decisions from the hard-case runners' outputs (results/hardcase-macros.tex).

    python paper/hardcase_macros.py --server L hl1 HARDCASES.jsonl TABLE.json \
                                    --server W wh1 HARDCASES.jsonl TABLE.json \
                                    --summary results/summary.json [--competitors hc1 COMPETITOR_CASES.jsonl] \
                                    [--out results/hardcase-macros.tex]

B1 and B2 are deterministic (hypotheses.md 5.2): the hard-case runners judge each run with the
frozen suite's checks and write one row per run (kind "hardcase") with its B1 deviations (`b1`)
and the B2 checks that failed (`b2_failed`), one row per server at the end of an entry (kind
"hardcase-servers"), and a table of the runs per variant and entry. analysis/ reads none of them
(its not_produced list). The revision log's entry "B1's and B2's decisions from the hard-case
runners' outputs (a reading)", item 3, says how they are read, and this file applies it:
  B1 holds when no hardcase row of any server part has a non-empty `b1`, every variant and entry
     ran its 16 replicates with one row each, and summary.json's `b1_failures` (the measured
     windows, B1's second sentence) is empty;
  B2 holds when no hardcase row has a non-empty `b2_failed`;
  the server checks are counted beside them.
The table counts only the runs that reached the judge and passed both B1 and B2, so the counts
come from the rows and the table is checked against them. Each row is checked too: `b2_failed`
lists the failed checks of `b2`, `passed` agrees with `b1` and `b2_failed`, and a run that did
not reach the judge fails with its reason in `b1`. A host's entries are its runner's list
(ENTRIES in hardcase_run.py, ENTRIES_W in whardcase_run.py), and each entry must run every
variant the host ran, 16 replicates each. An input that disagrees stops the run.

The competitors' part (--competitors, macros named CompCase...) counts the descriptive table of section 10
(lab job hc1, hardcase_run.py --part competitors; the entry of 1c4193a, item 3): it decides nothing, sets
no competitor against the server and holds no time of the table (first_byte_ms and end_ms are never
read). The one judged field of a row is `reply_as_the_server_table_expects`, whether the reply equals what
the server's frozen table expects; a row that the client did not see to its end ("opcase did not end")
has no such field and is counted apart, as not observed, never as a difference. A variant is one id at
one timer setting with its replicates; it is "as expected" or "differs" only when all its replicates are,
"not observed" when none was, and "mixed" (counted, listed as a deviation, in no list of cases) otherwise.
A case is one of Appendix A's 25. Every row of the table must name CODE_FREEZE and CHANGE_COMMIT (the
entry "The B1 count of the mixed cell (a later change under section 8)", item 6), and the table must be
complete: the systems, timer settings and cases kinds of bench/competitors/competitors.py, R_COMP_CASES
replicates of every variant a system's listener setup covers, a start row for every group, and the same
variants (id, case, setup) as L's hard-case server part, which therefore has to be given (--server L).
The free text of a row (`why`) never reaches the output: only its fixed label does.

Like paper/design_macros.py, this lives outside analysis/, which stays as at ANALYSIS_COMMIT. Names
are letters only and none is a name analysis/macros.py or paper/design_macros.py writes
(paper/test_hardcase_macros.py checks it). Every input is named in the output by its sha256.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPLICATES = 16                     # 5.2, B1: "16 replicates"
CODE_FREEZE = "ff2679cc89d23e08a817308c9aeba7901e056fef"
# Per host: the runner that writes its rows, and the runner's list of entries (backend, detection
# mode, dispatch), read from the runner's source so that a missing entry is seen.
RUNNER_OF = {"L": ("hardcase_run", ROOT / "bench" / "run" / "hardcase_run.py", "ENTRIES"),
             "W": ("whardcase_run", ROOT / "bench" / "run" / "whardcase_run.py", "ENTRIES_W")}
ENTRY_TITLE = "B1's and B2's decisions from the hard-case runners' outputs (a reading)"
# The B1 change (hypotheses.md revision log, "The B1 count of the mixed cell (a later change under
# section 8)", item 6): a frozen run after it names this commit at provenance.freeze.freeze.change_commit.
CHANGE_COMMIT = "9cae2deff2b01896bfab25c5af4c610381dc3c1d"
N_CASES = 25                         # Appendix A
COMPETITORS_PY = ROOT / "bench" / "competitors" / "competitors.py"
COMPETITOR_RUNNER = ("hardcase_run", RUNNER_OF["L"][1])   # part competitors of L's hard-case runner
# A macro name has letters only: the systems' words, as analysis/macros.py's WORDS writes them.
SYSTEM_WORD = {"nginx": "Nginx", "haproxy": "Haproxy", "envoy": "Envoy", "caddy-l4": "CaddyLFour", "sslh-ev": "SslhEv",
               "netty": "Netty", "jetty": "Jetty", "cmux": "Cmux", "hyper-util": "HyperUtil"}
AS_EXPECTED, DIFFERS, NOT_OBSERVED, MIXED = "as expected", "differs", "not observed", "mixed"
REPLY = "reply_as_the_server_table_expects"
VARIANT_ID = re.compile(r"HC(\d\d)(\.[A-Za-z0-9_.]+)?")       # HC01.HTTP, HC05, HC21.none.fallback
NO_RUN = re.compile(r"opcase printed no run \(exit (-?\d+)\):")   # run_variant's second reason; the stderr after it is not kept

HEAD = ("% Generated by paper/hardcase_macros.py from the hard-case runners' outputs and summary.json's\n"
        f"% b1_failures (revision log, \"{ENTRY_TITLE}\"). Do not edit.\n")


class InputRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class HostCounts:
    host: str
    job: str
    entries: int
    variant_entries: int
    runs: int
    passed: int
    b1_deviations: int
    b2_failures: int
    incomplete: int
    woke_more_than_once: int
    server_checks: int
    server_checks_ok: int
    details: tuple[str, ...] = field(default=())


# ---------------------------------------------------------------- reading


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def runner_entries(host: str) -> tuple[str, ...]:
    """The runner's tuple of entries, evaluated from its assignment in the runner's source (a
    comprehension over literals), so this file never imports the runner."""
    _, path, name = RUNNER_OF[host]
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == [name]:
            return tuple(eval(compile(ast.Expression(node.value), str(path), "eval"), {"__builtins__": {"tuple": tuple}}))
    raise InputRefused(f"{path.name} assigns no {name}")


def check_row(row: dict, host: str, job: str) -> None:
    where = f"{row.get('kind')} {row.get('entry')} {row.get('id', row.get('server'))} r{row.get('replicate')}"
    if row.get("kind") not in ("hardcase", "hardcase-servers"):
        raise InputRefused(f"{where}: kind {row.get('kind')!r} is not a server part's")
    if row.get("job") != job:
        raise InputRefused(f"{where}: job {row.get('job')!r}, not {job}")
    if row.get("development") is not False:
        raise InputRefused(f"{where}: not a frozen run (development {row.get('development')!r})")
    if row.get("runner") != RUNNER_OF[host][0] or row.get("host", host) != host:
        raise InputRefused(f"{where}: runner {row.get('runner')!r} on host {row.get('host', host)!r}, not {host}'s")
    cf = (((row.get("provenance") or {}).get("freeze") or {}).get("freeze") or {}).get("code_freeze")
    if cf != CODE_FREEZE:
        raise InputRefused(f"{where}: provenance names code_freeze {cf!r}, not CODE_FREEZE")
    if row["kind"] != "hardcase":
        return
    b1, judged = row.get("b1"), "b2_failed" in row
    if not isinstance(b1, list):
        raise InputRefused(f"{where}: b1 is not a list")
    if judged:
        failed = row["b2_failed"]
        b2 = row.get("b2")
        if not isinstance(failed, list) or not isinstance(b2, dict) or failed != sorted(k for k, v in b2.items() if v):
            raise InputRefused(f"{where}: b2_failed does not list the failed checks of b2")
        if bool(row.get("passed")) != (not b1 and not failed):
            raise InputRefused(f"{where}: passed disagrees with b1 and b2_failed")
    elif not b1 or row.get("passed"):
        raise InputRefused(f"{where}: a run that did not reach the judge must fail with its reason in b1")


def host_counts(host: str, job: str, rows: list[dict], table: dict) -> HostCounts:
    if host not in RUNNER_OF:
        raise InputRefused(f"host {host!r}: the server parts are L's and W's")
    for r in rows:
        check_row(r, host, job)
    runs = [r for r in rows if r["kind"] == "hardcase"]
    servers = [r for r in rows if r["kind"] == "hardcase-servers"]
    seen: dict[str, set[int]] = {}
    for r in runs:
        reps = seen.setdefault(f"{r['entry']}|{r['id']}", set())
        if r["replicate"] in reps:
            raise InputRefused(f"{host}: {r['entry']} {r['id']} r{r['replicate']} has two rows")
        reps.add(r["replicate"])
    judged = [r for r in runs if "b2_failed" in r]   # a run that reached the judge (the runner's table counts these)
    want: dict[str, dict] = {}
    for r in judged:
        t = want.setdefault(f"{r['entry']}|{r['id']}", {"runs": 0, "passed": 0, "woke_twice": 0})
        t["runs"] += 1
        t["passed"] += int(bool(r.get("passed")))
        t["woke_twice"] += int((r.get("wakeups") or 0) >= 2)
    got = {k: {x: v[x] for x in ("runs", "passed", "woke_twice")} for k, v in table.items()}
    if got != want:
        bad = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
        raise InputRefused(f"{host}: the table and the rows disagree at {len(bad)} variant-entries, first {bad[:3]}")
    entries = runner_entries(host)
    unknown = sorted({r["entry"] for r in runs} - set(entries))
    if unknown:
        raise InputRefused(f"{host}: entries {unknown} are not in {RUNNER_OF[host][1].name}'s list")
    # Every entry runs every variant the host ran (5.2: every backend, both detection modes, every
    # dispatch mode); a variant missing on every entry of a host cannot be seen without the frozen
    # case list, which is compiled into opcase.
    variants = sorted({r["id"] for r in runs})
    expected = {f"{e}|{v}" for e in entries for v in variants}
    full = set(range(1, REPLICATES + 1))
    incomplete = sorted(k for k in expected if seen.get(k, set()) != full)
    details = [f"{host} {r['entry']} {r['id']} r{r['replicate']}: b1={r.get('b1')} b2_failed={r.get('b2_failed', [])}"
               for r in runs if r.get("b1") or r.get("b2_failed")]
    details += [f"{host} {k}: replicates {sorted(seen.get(k, set()))}" for k in incomplete]
    details += [f"{host} server {s.get('entry')} {s.get('server')}: {s.get('problems')}" for s in servers if not s.get("ok")]
    return HostCounts(host=host, job=job, entries=len({r["entry"] for r in runs}), variant_entries=len(expected), runs=len(runs),
                      passed=sum(1 for r in runs if r.get("passed")), b1_deviations=sum(1 for r in runs if r.get("b1")),
                      b2_failures=sum(1 for r in runs if r.get("b2_failed")), incomplete=len(incomplete),
                      woke_more_than_once=sum(v["woke_twice"] for v in table.values()), server_checks=len(servers),
                      server_checks_ok=sum(1 for s in servers if s.get("ok") is True),
                      details=tuple(" ".join(d.split()) for d in details))


# ---------------------------------------------------------------- the competitors' table (hc1)


@dataclass(frozen=True)
class TimerView:
    """One system at one timer setting: its variants by status, and the cases by status."""
    timers: str
    variants: int
    as_expected: int
    differ: int
    not_observed: int
    mixed: int
    differ_all: tuple[int, ...]      # cases in which every variant differs
    differ_some: tuple[int, ...]     # cases in which some variants differ, not all
    not_observed_cases: tuple[int, ...]


@dataclass(frozen=True)
class SystemView:
    system: str
    rows: int
    observed: int
    not_observed: int
    as_expected: int
    differ: int
    no_decision: int
    variants: int
    not_covered: tuple[int, ...]     # cases in which the system ran no variant
    timers: tuple[TimerView, ...]


@dataclass(frozen=True)
class CompetitorCounts:
    job: str
    systems: tuple[SystemView, ...]
    cases: int
    variants: int
    starts: int
    mixed: int
    details: tuple[str, ...] = field(default=())         # "% deviation:" lines
    not_observed_units: tuple[str, ...] = field(default=())


def module_constant(path: Path, name: str):
    """A module-level constant assigned a literal (a tuple of strings, an int), read from the source so
    that this file never imports the module."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == [name]:
            return ast.literal_eval(node.value)
    raise InputRefused(f"{path.name} assigns no {name}")


@lru_cache(maxsize=1)
def competitor_constants() -> dict:
    def comp(name: str):
        return module_constant(COMPETITORS_PY, name)
    return {"order": comp("ORDER"), "libraries": comp("LIBRARIES"), "timers": comp("TIMERS"), "kinds": comp("CASES_KINDS"),
            "fallback": comp("FALLBACK_SYSTEMS"), "proxy": comp("PROXY_SYSTEMS"),
            "replicates": module_constant(COMPETITOR_RUNNER[1], "R_COMP_CASES")}


def competitor_systems() -> tuple[str, ...]:
    c = competitor_constants()
    return tuple(c["order"]) + tuple(c["libraries"])


def expected_kind(system: str, setup: str) -> str | None:
    """The cases kind a system runs a variant in, or None when its listener setup does not cover the
    variant (hardcase_run.py's covered())."""
    c = competitor_constants()
    fallback, proxy = "fallback" in setup, "PROXY" in setup
    if (fallback and system not in c["fallback"]) or (proxy and system not in c["proxy"]):
        return None
    return "cases-fallback" if fallback else "cases"


def check_competitor_row(row: dict, job: str) -> None:
    c = competitor_constants()
    where = f"{row.get('kind')} {row.get('system')} {row.get('cases_kind')} {row.get('timers')} {row.get('id')} r{row.get('replicate')}"
    if row.get("kind") not in ("competitor-case", "competitor-start"):
        raise InputRefused(f"{where}: kind {row.get('kind')!r} is not a competitors' table row")
    if row.get("job") != job:
        raise InputRefused(f"{where}: job {row.get('job')!r}, not {job}")
    if row.get("development") is not False:
        raise InputRefused(f"{where}: not a frozen run (development {row.get('development')!r})")
    if row.get("runner") != COMPETITOR_RUNNER[0]:
        raise InputRefused(f"{where}: runner {row.get('runner')!r}, not {COMPETITOR_RUNNER[0]}")
    names = (((row.get("provenance") or {}).get("freeze") or {}).get("freeze") or {})
    if names.get("code_freeze") != CODE_FREEZE:
        raise InputRefused(f"{where}: provenance names code_freeze {names.get('code_freeze')!r}, not CODE_FREEZE")
    if names.get("change_commit") != CHANGE_COMMIT:
        raise InputRefused(f"{where}: provenance names change_commit {names.get('change_commit')!r}, not CHANGE_COMMIT")
    if row.get("system") not in competitor_systems():
        raise InputRefused(f"{where}: system {row.get('system')!r} is not one of competitors.py's")
    if row.get("timers") not in c["timers"]:
        raise InputRefused(f"{where}: timers {row.get('timers')!r} is not one of {c['timers']}")
    if row.get("cases_kind") not in c["kinds"]:
        raise InputRefused(f"{where}: cases kind {row.get('cases_kind')!r} is not one of {c['kinds']}")
    if row["kind"] == "competitor-start":
        if row.get("ok") is not True:
            raise InputRefused(f"{where}: the system did not start ({row.get('why')})")
        return
    hc, reps = row.get("hc"), c["replicates"]
    if isinstance(hc, bool) or not isinstance(hc, int) or not 1 <= hc <= N_CASES:
        raise InputRefused(f"{where}: case {hc!r} is not one of Appendix A's 1 to {N_CASES}")
    shape = VARIANT_ID.fullmatch(row["id"]) if isinstance(row.get("id"), str) else None
    if shape is None or int(shape.group(1)) != hc:
        raise InputRefused(f"{where}: id {row.get('id')!r} is not an id of case {hc}")
    rep = row.get("replicate")
    if isinstance(rep, bool) or not isinstance(rep, int) or not 1 <= rep <= reps:
        raise InputRefused(f"{where}: replicate {rep!r} is not one of 1 to {reps}")
    if not isinstance(row.get("setup"), str):
        raise InputRefused(f"{where}: setup {row.get('setup')!r} is not a string")
    want = expected_kind(row["system"], row["setup"])
    if want != row["cases_kind"]:
        raise InputRefused(f"{where}: cases kind {row['cases_kind']!r}, where {row['system']} runs setup {row.get('setup')!r} in {want!r}")
    if not isinstance(row.get("observed"), bool):
        raise InputRefused(f"{where}: observed {row.get('observed')!r} is not a boolean")
    if row["observed"]:
        if not isinstance(row.get(REPLY), bool):
            raise InputRefused(f"{where}: an observed row needs a boolean {REPLY}")
        if not isinstance(row.get("timed_out"), bool) or row["timed_out"] != row.get("no_decision_within_t_obs"):
            raise InputRefused(f"{where}: timed_out and no_decision_within_t_obs disagree")
    else:
        if REPLY in row:
            raise InputRefused(f"{where}: an unobserved row holds a reply ({REPLY})")
        if not isinstance(row.get("why"), str):
            raise InputRefused(f"{where}: an unobserved row needs its why")
        reason(row["why"], where)


def reason(why: str, where: str = "") -> str:
    """The fixed label of a failure that run_variant writes (hardcase_run.py). The text that follows
    'printed no run' is opcase's stderr; it is free text and never reaches the output."""
    if why == "opcase did not end":
        return why
    m = NO_RUN.match(why)
    if m:
        return f"opcase printed no run (exit {m.group(1)})"
    raise InputRefused(f"{where}: why {why[:40]!r} is not a reason that run_variant writes")


def unit_status(rows: list[dict]) -> str:
    """One variant at one timer setting, over its replicates."""
    observed = [r for r in rows if r["observed"]]
    if not observed:
        return NOT_OBSERVED
    if len(observed) < len(rows):
        return MIXED
    verdicts = {r[REPLY] for r in observed}
    return AS_EXPECTED if verdicts == {True} else DIFFERS if verdicts == {False} else MIXED


def case_lists(statuses: dict[int, list[str]]) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    """(cases in which every variant differs, cases in which some do, cases with a variant not observed)."""
    every = tuple(sorted(hc for hc, st in statuses.items() if st and all(x == DIFFERS for x in st)))
    some = tuple(sorted(hc for hc, st in statuses.items() if DIFFERS in st and not all(x == DIFFERS for x in st)))
    gone = tuple(sorted(hc for hc, st in statuses.items() if NOT_OBSERVED in st))
    return every, some, gone


def check_table(cases: list[dict], starts: list[dict]) -> dict[str, tuple]:
    """The table is whole and its rows agree with each other; returns each id's (case, setup, expectation)."""
    c = competitor_constants()
    systems = competitor_systems()
    first: dict[str, tuple] = {}
    for r in cases:
        sig = (r["hc"], r["setup"], r.get("server_expects"))
        if first.setdefault(r["id"], sig) != sig:
            raise InputRefused(f"id {r['id']} is listed with two setups, cases or expectations")
    seen: set[tuple] = set()
    for r in cases:
        key = (r["system"], r["cases_kind"], r["timers"], r["id"], r["replicate"])
        if key in seen:
            raise InputRefused(f"{key} has two rows")
        seen.add(key)
    units: dict[tuple, list[int]] = defaultdict(list)
    for r in cases:
        units[(r["system"], r["timers"], r["id"])].append(r["replicate"])
    for (system, timers, vid), reps in units.items():
        if sorted(reps) != list(range(1, c["replicates"] + 1)):
            raise InputRefused(f"{system} {timers} {vid}: replicates {sorted(reps)}, not 1 to {c['replicates']}")
    for system in systems:
        if not any(r["system"] == system for r in cases):
            raise InputRefused(f"no rows for system {system}")
    for system in systems:
        for timers in c["timers"]:
            have = {vid for (s, t, vid) in units if s == system and t == timers}
            lacks = sorted(vid for vid, (_, setup, _) in first.items() if expected_kind(system, setup) and vid not in have)
            if lacks:
                raise InputRefused(f"{system} {timers} lacks {len(lacks)} variants its listener setup covers, first {lacks[:3]}")
    groups = {(s, k, t) for s in systems for t in c["timers"] for k in c["kinds"] if k != "cases-fallback" or s in c["fallback"]}
    got = Counter((r["system"], r["cases_kind"], r["timers"]) for r in starts)
    for g in sorted(set(got) - groups):
        raise InputRefused(f"a start row for {g} is not one the runner writes")
    for g in sorted(groups):
        if got.get(g, 0) != 1:
            raise InputRefused(f"{got.get(g, 0)} start rows for {g}, where there is one")
    return first


def check_variants(ids: dict[str, tuple], reference: dict[str, tuple]) -> None:
    """The table holds the variants of L's hard-case server part, no more and no fewer (id, case, setup)."""
    ours = {vid: (hc, setup) for vid, (hc, setup, _) in ids.items()}
    if ours == reference:
        return
    extra, absent = sorted(set(ours) - set(reference)), sorted(set(reference) - set(ours))
    other = sorted(v for v in set(ours) & set(reference) if ours[v] != reference[v])
    raise InputRefused(f"the table's variants differ from L's hard-case server part's: {len(extra)} only in the table {extra[:3]}, "
                       f"{len(absent)} only in the server part {absent[:3]}, {len(other)} with another case or setup {other[:3]}")


def competitor_counts(job: str, rows: list[dict], reference: dict[str, tuple] | None = None) -> CompetitorCounts:
    """`reference`: each variant id of L's hard-case server part with its (case, setup); build() gives it."""
    for r in rows:
        check_competitor_row(r, job)
    cases = [r for r in rows if r["kind"] == "competitor-case"]
    starts = [r for r in rows if r["kind"] == "competitor-start"]
    ids = check_table(cases, starts)
    if reference is not None:
        check_variants(ids, reference)
    all_cases = {hc for hc, _, _ in ids.values()}
    views, mixed_total, details, gone = [], 0, [], []
    for system in competitor_systems():
        mine = [r for r in cases if r["system"] == system]
        observed = [r for r in mine if r["observed"]]
        timer_views = []
        for timers in competitor_constants()["timers"]:
            by_id: dict[str, list[dict]] = defaultdict(list)
            for r in mine:
                if r["timers"] == timers:
                    by_id[r["id"]].append(r)
            status = {vid: unit_status(rs) for vid, rs in by_id.items()}
            per_case: dict[int, list[str]] = defaultdict(list)
            for vid, st in status.items():
                per_case[ids[vid][0]].append(st)
            every, some, absent = case_lists(per_case)
            counts = Counter(status.values())
            timer_views.append(TimerView(timers, len(status), counts[AS_EXPECTED], counts[DIFFERS], counts[NOT_OBSERVED], counts[MIXED],
                                         every, some, absent))
            for vid in sorted(status):
                if status[vid] == MIXED:
                    split = Counter(AS_EXPECTED if r["observed"] and r[REPLY] else DIFFERS if r["observed"] else NOT_OBSERVED for r in by_id[vid])
                    details.append(f"{system} {timers} {vid}: the replicates are not alike (as expected {split[AS_EXPECTED]}, "
                                   f"differ {split[DIFFERS]}, not observed {split[NOT_OBSERVED]})")
                elif status[vid] == NOT_OBSERVED:
                    gone.append(f"not observed: {system} {timers} {vid}: " + "; ".join(sorted({reason(r['why']) for r in by_id[vid]})))
            mixed_total += counts[MIXED]
        views.append(SystemView(system, len(mine), len(observed), len(mine) - len(observed),
                                sum(1 for r in observed if r[REPLY]), sum(1 for r in observed if not r[REPLY]),
                                sum(1 for r in observed if r["no_decision_within_t_obs"]), len({r["id"] for r in mine}),
                                tuple(sorted(all_cases - {r["hc"] for r in mine})), tuple(timer_views)))
    return CompetitorCounts(job, tuple(views), len(all_cases), len(ids), len(starts), mixed_total, tuple(details), tuple(gone))


# ---------------------------------------------------------------- writing


def grouped(n: int) -> str:
    """Thousands grouped by a thin comma, as analysis/macros.py groups them."""
    s = str(int(n))
    parts = []
    while len(s) > 3:
        parts.insert(0, s[-3:])
        s = s[:-3]
    return "{,}".join([s] + parts)


def items(hosts: list[HostCounts], b1_measured: int) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for h in hosts:
        p = f"Hardcase{h.host}"
        out += [(f"{p}Entries", grouped(h.entries), f"{h.job}: backend, detection mode and dispatch"),
                (f"{p}VariantEntries", grouped(h.variant_entries), "the host's variants of Appendix A's cases times the runner's entries"),
                (f"{p}Runs", grouped(h.runs), "rows of kind hardcase"),
                (f"{p}Passed", grouped(h.passed), "runs that passed B1 and B2"),
                (f"{p}BOneDeviations", grouped(h.b1_deviations), "runs with a B1 deviation"),
                (f"{p}BTwoFailures", grouped(h.b2_failures), "runs with a failed B2 check"),
                (f"{p}Incomplete", grouped(h.incomplete), "variant-entries without their 16 replicates"),
                (f"{p}WokeMoreThanOnce", grouped(h.woke_more_than_once), "runs whose detection woke more than once (the table's woke_twice)"),
                (f"{p}ServerChecks", grouped(h.server_checks), "rows of kind hardcase-servers"),
                (f"{p}ServerChecksOk", grouped(h.server_checks_ok), "server checks that are ok")]
    out += [("HardcaseRuns", grouped(sum(h.runs for h in hosts)), "all hosts"),
            ("HardcasePassed", grouped(sum(h.passed for h in hosts)), "all hosts"),
            ("HardcaseBOneDeviations", grouped(sum(h.b1_deviations for h in hosts)), "all hosts"),
            ("HardcaseBTwoFailures", grouped(sum(h.b2_failures for h in hosts)), "all hosts")]
    b1 = all(h.b1_deviations == 0 and h.incomplete == 0 for h in hosts) and b1_measured == 0
    b2 = all(h.b2_failures == 0 for h in hosts)
    out += [("BOneVerdict", "holds" if b1 else "does not hold", "hard cases and summary.json's b1_failures (5.2)"),
            ("BTwoVerdict", "holds" if b2 else "does not hold", "hard cases (5.2)")]
    return out


def case_list(cases: tuple[int, ...]) -> str:
    """Appendix A's case numbers as the paper names them: HC1, HC2; none when there is no case."""
    return ", ".join(f"HC{n}" for n in cases) if cases else "none"


COMPETITOR_NOTES = (
    "The CompCase macros count section 10's competitors' table. It is descriptive: it decides nothing and holds no time.",
    f"As expected: the row's {REPLY} is true, the reply equals what the server's frozen table expects.",
    "Differs: it is false. That also holds a row whose reference run on the dedicated port failed, which the row does not record.",
    "Not observed: opcase gave no outcome (it did not end, or printed no run), so no reply was judged; such a row is neither.",
    "A variant is one id at one timer setting with its replicates. A case is one of Appendix A's 25, holding one or more variants.",
    "Cases listed under DifferAll: every variant of the case differs. DifferSome: some do, not all. NotCovered: no variant run.",
    "A row with no decision within T_OBS is also counted as expected or as differing, by its reply.",
    "A variant whose replicates are not alike is counted in UnitsMixed, in none of AsExpected, Differ or NotObserved, and named in a deviation line.",
)


def competitor_items(c: CompetitorCounts) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for sv in c.systems:
        p, who = f"CompCase{SYSTEM_WORD[sv.system]}", sv.system
        out += [(f"{p}Rows", grouped(sv.rows), f"{who}: rows of kind competitor-case"),
                (f"{p}RowsObserved", grouped(sv.observed), f"{who}: rows with an outcome"),
                (f"{p}RowsNotObserved", grouped(sv.not_observed), f"{who}: rows where opcase did not end"),
                (f"{p}RowsAsExpected", grouped(sv.as_expected), f"{who}: observed rows whose reply equals what the server's table expects"),
                (f"{p}RowsDiffer", grouped(sv.differ), f"{who}: observed rows whose reply does not"),
                (f"{p}RowsNoDecision", grouped(sv.no_decision), f"{who}: observed rows with no decision within T_OBS, also counted by their reply"),
                (f"{p}Variants", grouped(sv.variants), f"{who}: variants run, those its listener setup covers"),
                (f"{p}CasesNotCovered", case_list(sv.not_covered), f"{who}: cases in which it ran no variant")]
        for tv in sv.timers:
            q = f"{p}{tv.timers.capitalize()}"
            at = f"{who} at {tv.timers} timers"
            out += [(f"{q}Variants", grouped(tv.variants), f"{at}: variants"),
                    (f"{q}VariantsAsExpected", grouped(tv.as_expected), f"{at}: variants whose replicates all equal what the server's table expects"),
                    (f"{q}VariantsDiffer", grouped(tv.differ), f"{at}: variants whose replicates all differ"),
                    (f"{q}VariantsNotObserved", grouped(tv.not_observed), f"{at}: variants with no replicate observed"),
                    (f"{q}CasesDifferAll", case_list(tv.differ_all), f"{at}: cases in which every variant differs"),
                    (f"{q}CasesDifferSome", case_list(tv.differ_some), f"{at}: cases in which some variants differ, not all"),
                    (f"{q}CasesNotObserved", case_list(tv.not_observed_cases), f"{at}: cases with a variant not observed")]
    total = {"Rows": sum(v.rows for v in c.systems), "RowsObserved": sum(v.observed for v in c.systems),
             "RowsNotObserved": sum(v.not_observed for v in c.systems), "RowsAsExpected": sum(v.as_expected for v in c.systems),
             "RowsDiffer": sum(v.differ for v in c.systems), "RowsNoDecision": sum(v.no_decision for v in c.systems)}
    out += [("CompCaseSystems", grouped(len(c.systems)), "systems in the table"),
            ("CompCaseCases", grouped(c.cases), "Appendix A's cases that some system ran"),
            ("CompCaseVariants", grouped(c.variants), "distinct variants (ids) in the table"),
            ("CompCaseStarts", grouped(c.starts), f"{c.job}: starts of a system in a cases kind at a timer setting, all ok"),
            ("CompCaseUnitsMixed", grouped(c.mixed), "variants at a timer setting whose replicates are not alike (each named in a deviation line)")]
    out += [(f"CompCase{k}", grouped(v), f"all systems: {k}") for k, v in total.items()]
    return out


def render(entries: list[tuple[str, str, str]], inputs: list[tuple[str, str]], details: list[str], notes: tuple[str, ...] = ()) -> str:
    seen: set[str] = set()
    lines = [HEAD] + [f"% input: {what} sha256 {digest}\n" for what, digest in inputs]
    lines += [f"% deviation: {d}\n" for d in details]
    lines += [f"% {n}\n" for n in notes]
    for name, value, note in entries:
        if not re.fullmatch(r"[A-Za-z]+", name):
            raise ValueError(f"macro name {name!r} is not letters only")
        if name in seen:
            raise ValueError(f"macro {name} defined twice")
        seen.add(name)
        lines.append(f"\\newcommand{{\\{name}}}{{{value}}}  % {note}\n")
    return "".join(lines)


def server_variants(rows: list[dict]) -> dict[str, tuple]:
    """Each variant id of a hard-case server part with its (case, setup)."""
    ref: dict[str, tuple] = {}
    for r in rows:
        if r["kind"] == "hardcase":
            sig = (r.get("hc"), r.get("setup"))
            if ref.setdefault(r["id"], sig) != sig:
                raise InputRefused(f"server part: id {r['id']} is listed with two cases or setups")
    return ref


def build(servers: list[tuple[str, str, Path, Path]], summary: Path, competitors: tuple[str, Path] | None = None) -> str:
    hosts, inputs, details, reference = [], [], [], None
    if len({h for h, _, _, _ in servers}) != len(servers) or not all(re.fullmatch(r"[A-Z]", h) for h, _, _, _ in servers):
        raise InputRefused("each --server needs its own host letter (L, W)")
    for host, job, rows_path, table_path in servers:
        table = json.loads(Path(table_path).read_text(encoding="utf-8"))
        rows = read_rows(rows_path)
        hc = host_counts(host, job, rows, table)
        if host == "L":
            reference = server_variants(rows)
        hosts.append(hc)
        details += list(hc.details)
        inputs += [(f"{host} {job} {Path(rows_path).name}", sha256_file(rows_path)),
                   (f"{host} {job} {Path(table_path).name}", sha256_file(table_path))]
    s = json.loads(Path(summary).read_text(encoding="utf-8"))
    if s.get("synthetic") is not False or not isinstance(s.get("b1_failures"), list):
        raise InputRefused("summary.json is synthetic or has no b1_failures list")
    inputs.append((f"{Path(summary).name} (b1_failures)", sha256_file(summary)))
    entries, notes = items(hosts, len(s["b1_failures"])), ()
    if competitors is not None:
        job, rows_path = competitors
        if reference is None:
            raise InputRefused("the competitors' table is checked against L's hard-case server part: give --server L")
        cc = competitor_counts(job, read_rows(rows_path), reference)
        entries += competitor_items(cc)
        inputs.append((f"L {job} {Path(rows_path).name}", sha256_file(rows_path)))   # the table is L's (hardcase_run.py)
        details += list(cc.details)
        notes = COMPETITOR_NOTES + cc.not_observed_units
    return render(entries, inputs, details, notes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", nargs=4, action="append", required=True, metavar=("HOST", "JOB", "ROWS", "TABLE"),
                    help="a server part: host letter, lab job, its hardcases.jsonl and hardcases-table-JOB.json")
    ap.add_argument("--summary", type=Path, required=True, help="the confirmatory analysis's summary.json (b1_failures)")
    ap.add_argument("--competitors", nargs=2, metavar=("JOB", "ROWS"),
                    help="the competitors' table (descriptive): its lab job and competitor_cases.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "hardcase-macros.tex")
    a = ap.parse_args(argv)
    try:
        text = build([(h, j, Path(r), Path(t)) for h, j, r, t in a.server], a.summary,
                     (a.competitors[0], Path(a.competitors[1])) if a.competitors else None)
    except InputRefused as e:
        print(f"hardcase_macros.py: refused: {e}", file=sys.stderr)
        return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"hardcase macros: {text.count(chr(92) + 'newcommand')} to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
