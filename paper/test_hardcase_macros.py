"""Tests of paper/hardcase_macros.py.

    python -m pytest paper/test_hardcase_macros.py

SYNTHETIC rows and tables in pytest's temporary directory, in the forms the hard-case runners write
(bench/run/hardcase_run.py, part server): a run that reached the judge has `b2` and `b2_failed`,
one that did not has a reason in `b1` and no row in the table. The committed
results/hardcase-macros.tex is checked for its names and its inputs, since its archived inputs are
not in the repository.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import hardcase_macros as H  # noqa: E402
import test_design_macros as TD  # noqa: E402  the names analysis/macros.py can emit

FREEZE = {"freeze": {"freeze": {"code_freeze": H.CODE_FREEZE}}}
JOBS = {"hl1": "L", "wh1": "W"}


def tagged(row: dict, job: str) -> dict:
    host = JOBS[job]
    row.update(job=job, development=False, runner=H.RUNNER_OF[host][0], provenance=FREEZE)
    if host == "W":
        row["host"] = "W"
    return row


def run_row(entry: str, vid: str, rep: int, job: str, b1=(), b2_failed=(), judged=True, wakeups=1) -> dict:
    row = {"kind": "hardcase", "entry": entry, "id": vid, "hc": 1, "replicate": rep, "b1": list(b1)}
    if judged:
        row.update(b2={k: (["late"] if k in b2_failed else []) for k in "abcde"}, b2_failed=sorted(b2_failed), wakeups=wakeups,
                   passed=not b1 and not b2_failed)
    else:
        row.update(passed=False, b2={})
    return tagged(row, job)


def server_row(entry: str, job: str, ok=True) -> dict:
    return tagged({"kind": "hardcase-servers", "entry": entry, "server": "one-port plain", "ok": ok,
                   "problems": [] if ok else ["1 connection left open"]}, job)


def table_of(rows: list[dict]) -> dict:
    """The runner's table: the runs that reached the judge, per variant and entry."""
    t: dict = {}
    for r in rows:
        if r.get("kind") != "hardcase" or "b2_failed" not in r:
            continue
        e = t.setdefault(f"{r['entry']}|{r['id']}", {"entry": r["entry"], "id": r["id"], "hc": r["hc"], "runs": 0, "passed": 0,
                                                     "woke_twice": 0})
        e["runs"] += 1
        e["passed"] += int(r["passed"])
        e["woke_twice"] += int(r["wakeups"] >= 2)
    return t


IDS = ("HC01.HTTP", "HC02.TLS.k01")


def clean(job: str, ids=IDS) -> list[dict]:
    entries = H.runner_entries(JOBS[job])
    rows = [run_row(e, v, k, job, wakeups=3 if v.startswith("HC02") else 1) for e in entries for v in ids
            for k in range(1, H.REPLICATES + 1)]
    return rows + [server_row(e, job) for e in entries]


def write(tmp: Path, name: str, rows: list[dict], table: dict | None = None) -> tuple[Path, Path]:
    rp, tp = tmp / f"{name}.jsonl", tmp / f"{name}-table.json"
    rp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tp.write_text(json.dumps(table_of(rows) if table is None else table), encoding="utf-8")
    return rp, tp


def summary(tmp: Path, b1_failures=()) -> Path:
    p = tmp / "summary.json"
    p.write_text(json.dumps({"synthetic": False, "b1_failures": list(b1_failures)}), encoding="utf-8")
    return p


def macros(text: str) -> dict[str, str]:
    return dict(re.findall(r"^\\newcommand\{\\([A-Za-z]+)\}\{((?:[^{}]|\{,\})*)\}", text, flags=re.M))   # a value may hold {,}


def build(tmp: Path, l_rows: list[dict], w_rows: list[dict] | None = None, l_table=None, b1_failures=()) -> dict[str, str]:
    lr, lt = write(tmp, "L", l_rows, l_table)
    servers = [("L", "hl1", lr, lt)]
    if w_rows is not None:
        wr, wt = write(tmp, "W", w_rows)
        servers.append(("W", "wh1", wr, wt))
    return macros(H.build(servers, summary(tmp, b1_failures)))


def replace(rows: list[dict], i: int, **kw) -> list[dict]:
    r = rows[i]
    out = list(rows)
    out[i] = run_row(r["entry"], r["id"], r["replicate"], r["job"], **kw)
    return out


def test_the_runners_entries():
    assert len(H.runner_entries("L")) == 8 and "io_uring.peek.relay" in H.runner_entries("L")
    assert H.runner_entries("W") == ("IOCP.replay.inproc", "IOCP.peek.inproc")


def test_all_runs_pass(tmp_path):
    m = build(tmp_path, clean("hl1"), clean("wh1"))
    assert m["HardcaseLRuns"] == "256" and m["HardcaseLPassed"] == "256" and m["HardcaseWRuns"] == "64"
    assert m["HardcaseLEntries"] == "8" and m["HardcaseLVariantEntries"] == "16" and m["HardcaseLWokeMoreThanOnce"] == "128"
    assert m["HardcaseLServerChecks"] == "8" and m["HardcaseLServerChecksOk"] == "8" and m["HardcaseLIncomplete"] == "0"
    assert m["HardcaseRuns"] == "320" and m["HardcaseBOneDeviations"] == "0" and m["HardcaseBTwoFailures"] == "0"
    assert m["BOneVerdict"] == "holds" and m["BTwoVerdict"] == "holds"


def test_one_b1_deviation_fails_b1_only(tmp_path):
    m = build(tmp_path, replace(clean("hl1"), 5, b1=["reply differs from the dedicated port's"]))
    assert m["HardcaseLBOneDeviations"] == "1" and m["HardcaseLPassed"] == "255"
    assert m["BOneVerdict"] == "does not hold" and m["BTwoVerdict"] == "holds"


def test_one_b2_failure_fails_b2_only(tmp_path):
    rows = replace(clean("hl1"), 7, b2_failed=["d"])
    text = H.build([("L", "hl1", *write(tmp_path, "L", rows))], summary(tmp_path))
    m = macros(text)
    assert m["HardcaseLBTwoFailures"] == "1" and m["BTwoVerdict"] == "does not hold" and m["BOneVerdict"] == "holds"
    assert "% deviation: L epoll.replay.inproc HC01.HTTP r8: b1=[] b2_failed=['d']" in text


def test_a_run_that_never_reached_the_judge_is_a_deviation(tmp_path):
    m = build(tmp_path, replace(clean("hl1"), 0, b1=["connect failed"], judged=False))
    assert m["HardcaseLBOneDeviations"] == "1" and m["HardcaseLRuns"] == "256" and m["BOneVerdict"] == "does not hold"


def test_measured_window_failure_fails_b1(tmp_path):
    m = build(tmp_path, clean("hl1"), b1_failures=[{"cell": "S.mixed.C1.L.epoll", "misclassified": 3}])
    assert m["BOneVerdict"] == "does not hold" and m["HardcaseBOneDeviations"] == "0"


def test_missing_replicate_entry_or_variant_fails_b1(tmp_path):
    rows = clean("hl1")
    one = [r for r in rows if not (r.get("id") == "HC01.HTTP" and r.get("replicate") == 16 and r.get("entry") == "epoll.peek.inproc")]
    m = build(tmp_path, one)
    assert m["HardcaseLIncomplete"] == "1" and m["BOneVerdict"] == "does not hold"
    no_entry = [r for r in rows if r.get("entry") != "io_uring.peek.relay"]
    m = build(tmp_path, no_entry)
    assert m["HardcaseLIncomplete"] == "2" and m["HardcaseLEntries"] == "7" and m["BOneVerdict"] == "does not hold"
    no_variant = [r for r in rows if not (r.get("entry") == "epoll.replay.relay" and r.get("id") == "HC02.TLS.k01")]
    m = build(tmp_path, no_variant)
    assert m["HardcaseLIncomplete"] == "1" and m["BOneVerdict"] == "does not hold"


def test_failed_server_check_is_counted_not_decided(tmp_path):
    rows = clean("hl1")
    rows[-1] = server_row(rows[-1]["entry"], "hl1", ok=False)
    m = build(tmp_path, rows)
    assert m["HardcaseLServerChecksOk"] == "7" and m["BOneVerdict"] == "holds"


def test_refusals(tmp_path):
    rows = clean("hl1")
    bad_table = table_of(rows)
    next(iter(bad_table.values()))["passed"] -= 1
    with pytest.raises(H.InputRefused, match="table and the rows disagree"):
        build(tmp_path, rows, l_table=bad_table)
    for change, msg in (({"development": True}, "not a frozen run"), ({"job": "hl2"}, "job"),
                        ({"provenance": {"freeze": {"freeze": {"code_freeze": "0" * 40}}}}, "code_freeze"),
                        ({"runner": "whardcase_run"}, "runner"), ({"host": "W"}, "runner"),
                        ({"b2_failed": []}, "b2_failed does not list"), ({"passed": False}, "passed disagrees"),
                        ({"b2_failed": ""}, "b2_failed does not list"), ({"entry": "epoll.replay.splice"}, "not in")):
        bad = clean("hl1")
        bad[3] = dict(bad[3], **change)
        if change.get("b2_failed") == []:
            bad[3]["b2"] = dict(bad[3]["b2"], d=["late"])
        with pytest.raises(H.InputRefused, match=msg):
            build(tmp_path, bad, l_table=table_of(clean("hl1")) if "entry" not in change and "passed" not in change else None)
    unjudged = clean("hl1")
    unjudged[2] = run_row(unjudged[2]["entry"], unjudged[2]["id"], unjudged[2]["replicate"], "hl1", judged=False)
    with pytest.raises(H.InputRefused, match="did not reach the judge"):
        build(tmp_path, unjudged)
    dup = clean("hl1")
    dup.append(dict(dup[0]))
    with pytest.raises(H.InputRefused, match="two rows"):
        build(tmp_path, dup, l_table=table_of(dup[:-1]))
    lr, lt = write(tmp_path, "L", clean("hl1"))
    s = tmp_path / "synthetic.json"
    s.write_text(json.dumps({"synthetic": True, "b1_failures": []}), encoding="utf-8")
    with pytest.raises(H.InputRefused, match="synthetic"):
        H.build([("L", "hl1", lr, lt)], s)
    with pytest.raises(H.InputRefused, match="host letter"):
        H.build([("L", "hl1", lr, lt), ("L", "hl1", lr, lt)], summary(tmp_path))


def test_cli_writes_inputs_with_sha256(tmp_path):
    lr, lt = write(tmp_path, "L", clean("hl1"))
    out = tmp_path / "hardcase-macros.tex"
    assert H.main(["--server", "L", "hl1", str(lr), str(lt), "--summary", str(summary(tmp_path)), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith(H.HEAD)
    assert f"% input: L hl1 L.jsonl sha256 {H.sha256_file(lr)}" in text
    assert f"% input: L hl1 L-table.json sha256 {H.sha256_file(lt)}" in text
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(dict(clean("hl1")[0], development=True)) + "\n", encoding="utf-8")
    assert H.main(["--server", "L", "hl1", str(bad), str(lt), "--summary", str(summary(tmp_path)), "--out", str(out)]) == 2


def emitted_names(text: str) -> list[str]:
    return re.findall(r"^\\newcommand\{\\([^}]*)\}", text, flags=re.M)


def design_names() -> set[str]:
    """paper/design_macros.py's names: from the generator when it runs against the current log, else
    from its committed file (the generator stops when a pattern matches the log twice)."""
    try:
        return {n for n, _, _ in TD.items()}
    except Exception:  # noqa: BLE001
        return set(emitted_names((HERE.parent / "results" / "design-macros.tex").read_text(encoding="utf-8")))


def test_names_collide_with_no_other_generator(tmp_path):
    text = H.build([("L", "hl1", *write(tmp_path, "L", clean("hl1"))), ("W", "wh1", *write(tmp_path, "W", clean("wh1")))],
                   summary(tmp_path))
    names = emitted_names(text)
    assert names and all(re.fullmatch(r"[A-Za-z]+", n) for n in names) and len(names) == len(set(names))
    fixed, prefixes = TD.macros_py_names()
    design = design_names()
    results = HERE.parent / "results" / "macros.tex"
    emitted = set(emitted_names(results.read_text(encoding="utf-8"))) if results.exists() else set()
    for n in names:
        assert n not in fixed and not n.startswith(prefixes) and n not in design and n not in emitted, n


def test_committed_file_names_and_inputs():
    path = HERE.parent / "results" / "hardcase-macros.tex"
    if not path.exists():
        pytest.skip("results/hardcase-macros.tex is not written yet")
    text = path.read_text(encoding="utf-8")
    assert text.startswith(H.HEAD)
    names = emitted_names(text)
    assert all(re.fullmatch(r"[A-Za-z]+", n) for n in names) and len(names) == len(set(names))
    inputs = re.findall(r"^% input: (.+) sha256 ([0-9a-f]{64})$", text, flags=re.M)
    competitors = 1 if "CompCaseRows" in names else 0   # the competitors' rows, one file
    assert len(inputs) == 2 * sum(1 for n in names if re.fullmatch(r"Hardcase[A-Z]Runs", n)) + 1 + competitors
    m = macros(text)
    assert m["BOneVerdict"] in ("holds", "does not hold") and m["BTwoVerdict"] in ("holds", "does not hold")


def test_committed_competitor_macros_add_up():
    path = HERE.parent / "results" / "hardcase-macros.tex"
    text = path.read_text(encoding="utf-8")
    assert "CompCaseRows" in text, "results/hardcase-macros.tex must hold the competitors' part (--competitors)"
    m = {k: v.replace("{,}", "") for k, v in macros(text).items()}
    words = [H.SYSTEM_WORD[s] for s in H.competitor_systems()]
    assert m["CompCaseSystems"] == str(len(words)) and m["CompCaseCases"] == str(H.N_CASES) and m["CompCaseUnitsMixed"] == "0"
    for total in ("Rows", "RowsObserved", "RowsNotObserved", "RowsAsExpected", "RowsDiffer", "RowsNoDecision"):
        assert int(m[f"CompCase{total}"]) == sum(int(m[f"CompCase{w}{total}"]) for w in words), total
    assert int(m["CompCaseRows"]) == int(m["CompCaseRowsObserved"]) + int(m["CompCaseRowsNotObserved"])
    assert int(m["CompCaseRowsObserved"]) == int(m["CompCaseRowsAsExpected"]) + int(m["CompCaseRowsDiffer"])
    not_observed = re.findall(r"^% not observed: ", text, flags=re.M)
    assert len(not_observed) * H.competitor_constants()["replicates"] == int(m["CompCaseRowsNotObserved"])
    for w in words:
        assert int(m[f"CompCase{w}Rows"]) == 2 * H.competitor_constants()["replicates"] * int(m[f"CompCase{w}Variants"])
        for t in ("Matched", "Default"):
            parts = [int(m[f"CompCase{w}{t}Variants{k}"]) for k in ("AsExpected", "Differ", "NotObserved")]
            assert sum(parts) == int(m[f"CompCase{w}{t}Variants"])   # no mixed variant in the committed table
        for t in ("Matched", "Default"):
            assert int(m[f"CompCase{w}{t}Variants"]) == int(m[f"CompCase{w}Variants"])
    assert m["CompCaseStarts"] == "26"


# ---------------------------------------------------------------- the competitors' table (hc1)
#
# SYNTHETIC rows in the forms hardcase_run.py --part competitors writes: a "competitor-case" row per
# (system, cases kind, timers, variant, replicate) and a "competitor-start" row per (system, cases
# kind, timers). The generator re-derives which kind a system's variants run in from competitors.py.

FALLBACK = ("haproxy", "envoy", "sslh-ev", "cmux")
PROXY = ("nginx", "haproxy", "envoy", "caddy-l4", "netty", "jetty")
SYSTEMS = ("nginx", "haproxy", "envoy", "caddy-l4", "sslh-ev", "netty", "jetty", "cmux", "hyper-util")
COMP_FREEZE = {"freeze": {"freeze": {"code_freeze": H.CODE_FREEZE, "change_commit": H.CHANGE_COMMIT}}}
# (id, Appendix A case number, listener setup)
VARIANTS = (("HC01.HTTP", 1, "plain"), ("HC01.SSH", 1, "plain"), ("HC02.TLS.k01", 2, "plain"), ("HC05", 5, "SMTP fallback"),
            ("HC09", 9, "PROXY"), ("HC15", 15, "PROXY, SMTP fallback"))


def kind_of(system: str, setup: str) -> str | None:
    if "fallback" in setup and system not in FALLBACK:
        return None
    if "PROXY" in setup and system not in PROXY:
        return None
    return "cases-fallback" if "fallback" in setup else "cases"


def comp_tag(row: dict, job: str = "hc1") -> dict:
    row.update(job=job, development=False, runner="hardcase_run", provenance=COMP_FREEZE, recorded="2026-10-07T12:00:00+0300")
    return row


def comp_row(system: str, timers: str, vid: str, hc: int, setup: str, rep: int, reply: bool | None = True, **kw) -> dict:
    """reply None: not observed (opcase did not end)."""
    kind = kind_of(system, setup)
    row = {"kind": "competitor-case", "system": system, "cases_kind": kind, "timers": timers, "hc": hc, "id": vid, "replicate": rep,
           "setup": setup, "server_expects": "classified"}
    if reply is None:
        row.update(observed=False, why="opcase did not end")
    else:
        row.update(observed=True, connected=True, received_bytes=78, first_line="HTTP/1.1 200 OK", eof=True, reset=False, timed_out=False,
                   end_ms=0.38, first_byte_ms=0.35, tls=None, no_decision_within_t_obs=False, reply_as_the_server_table_expects=reply)
    row.update(kw)
    return comp_tag(row)


def comp_start(system: str, kind: str, timers: str, ok: bool = True) -> dict:
    row = {"kind": "competitor-start", "system": system, "cases_kind": kind, "timers": timers, "ok": ok}
    row.update({"exit": 0} if ok else {"why": "RuntimeError('no port')"})
    return comp_tag(row)


def comp_clean(reply=lambda system, timers, vid: True, variants=VARIANTS) -> list[dict]:
    """Every system, both timers, every variant its listener setup covers, three replicates, and the start rows."""
    rows = []
    for s in SYSTEMS:
        for t in ("matched", "default"):
            kinds = ["cases"] + (["cases-fallback"] if s in FALLBACK else [])
            for k in kinds:
                for vid, hc, setup in variants:
                    if kind_of(s, setup) == k:
                        rows += [comp_row(s, t, vid, hc, setup, rep, reply(s, t, vid)) for rep in (1, 2, 3)]
                rows.append(comp_start(s, k, t))
    return rows


def comp_write(tmp: Path, rows: list[dict], name: str = "competitor_cases") -> Path:
    p = tmp / f"{name}.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def server_rows(variants=VARIANTS) -> list[dict]:
    """L's hard-case server part over the same variants, with each variant's case and setup, as the runner writes them."""
    info = {v[0]: v for v in variants}
    return [dict(r, hc=info[r["id"]][1], setup=info[r["id"]][2]) if r["kind"] == "hardcase" else r
            for r in clean("hl1", ids=[v[0] for v in variants])]


def comp_build(tmp: Path, rows: list[dict], job: str = "hc1", server: list[dict] | None = None) -> tuple[str, dict[str, str]]:
    text = H.build([("L", "hl1", *write(tmp, "L", server_rows() if server is None else server))], summary(tmp),
                   competitors=(job, comp_write(tmp, rows)))
    return text, macros(text)


def m_rows(m: dict, word: str) -> int:
    return int(m[f"CompCase{word}Rows"])


def test_the_competitors_come_from_the_module_and_the_runner():
    assert H.competitor_systems() == SYSTEMS
    consts = H.competitor_constants()
    assert consts["fallback"] == FALLBACK and consts["proxy"] == PROXY
    assert consts["timers"] == ("matched", "default") and consts["replicates"] == 3
    assert set(H.SYSTEM_WORD) == set(SYSTEMS)


def test_which_kind_a_system_runs_a_variant_in():
    assert H.expected_kind("nginx", "plain") == "cases" and H.expected_kind("nginx", "PROXY") == "cases"
    assert H.expected_kind("nginx", "SMTP fallback") is None and H.expected_kind("sslh-ev", "PROXY") is None
    assert H.expected_kind("cmux", "SMTP fallback") == "cases-fallback" and H.expected_kind("cmux", "PROXY, SMTP fallback") is None
    assert H.expected_kind("haproxy", "PROXY, SMTP fallback") == "cases-fallback" and H.expected_kind("jetty", "PROXY, SMTP fallback") is None


def test_a_clean_table_counts_rows_variants_and_starts(tmp_path):
    text, m = comp_build(tmp_path, comp_clean())
    per = {s: sum(1 for v in VARIANTS if kind_of(s, v[2])) for s in SYSTEMS}   # variants each system covers
    assert per["nginx"] == 4 and per["sslh-ev"] == 4 and per["hyper-util"] == 3
    assert m["CompCaseNginxVariants"] == "4" and m["CompCaseSslhEvVariants"] == "4" and m["CompCaseHyperUtilVariants"] == "3"
    for s in SYSTEMS:
        w = H.SYSTEM_WORD[s]
        assert m[f"CompCase{w}Rows"] == str(per[s] * 6) and m[f"CompCase{w}RowsObserved"] == str(per[s] * 6)
        assert m[f"CompCase{w}RowsNotObserved"] == "0" and m[f"CompCase{w}RowsDiffer"] == "0"
        assert m[f"CompCase{w}RowsAsExpected"] == str(per[s] * 6)
        for t in ("Matched", "Default"):
            assert m[f"CompCase{w}{t}Variants"] == str(per[s]) and m[f"CompCase{w}{t}VariantsAsExpected"] == str(per[s])
            assert m[f"CompCase{w}{t}VariantsDiffer"] == "0" and m[f"CompCase{w}{t}VariantsNotObserved"] == "0"
            assert m[f"CompCase{w}{t}CasesDifferAll"] == "none" and m[f"CompCase{w}{t}CasesDifferSome"] == "none"
            assert m[f"CompCase{w}{t}CasesNotObserved"] == "none"
    assert m["CompCaseSystems"] == "9" and m["CompCaseRows"] == str(6 * sum(per.values())) and m["CompCaseStarts"] == "26"
    assert m["CompCaseVariants"] == "6" and m["CompCaseCases"] == "5" and m["CompCaseUnitsMixed"] == "0"
    assert m["CompCaseRowsNoDecision"] == "0"
    assert m["CompCaseRowsAsExpected"] == m["CompCaseRows"] and m["CompCaseRowsDiffer"] == "0"


def test_a_system_that_does_not_cover_a_case_lists_it_as_not_covered(tmp_path):
    _, m = comp_build(tmp_path, comp_clean())
    assert m["CompCaseNginxCasesNotCovered"] == "HC5, HC15" and m["CompCaseHaproxyCasesNotCovered"] == "none"
    assert m["CompCaseSslhEvCasesNotCovered"] == "HC9, HC15" and m["CompCaseCmuxCasesNotCovered"] == "HC9, HC15"
    assert m["CompCaseHyperUtilCasesNotCovered"] == "HC5, HC9, HC15"


def test_a_reply_that_differs_is_counted_by_row_variant_and_case(tmp_path):
    def reply(s, t, vid):
        return not (s == "jetty" and vid in ("HC01.HTTP", "HC02.TLS.k01") and t == "matched")
    _, m = comp_build(tmp_path, comp_clean(reply))
    assert m["CompCaseJettyRowsDiffer"] == "6" and m["CompCaseJettyRowsAsExpected"] == str(m_rows(m, "Jetty") - 6)
    assert m["CompCaseJettyMatchedVariantsDiffer"] == "2" and m["CompCaseJettyDefaultVariantsDiffer"] == "0"
    assert m["CompCaseJettyMatchedVariantsAsExpected"] == str(int(m["CompCaseJettyMatchedVariants"]) - 2)
    # HC2 has one variant and it differs: every variant of the case differs. HC1 has two and one differs: some do.
    assert m["CompCaseJettyMatchedCasesDifferAll"] == "HC2" and m["CompCaseJettyMatchedCasesDifferSome"] == "HC1"
    assert m["CompCaseJettyDefaultCasesDifferAll"] == "none" and m["CompCaseJettyDefaultCasesDifferSome"] == "none"
    assert m["CompCaseNginxRowsDiffer"] == "0" and m["CompCaseRowsDiffer"] == "6"


def test_a_reply_that_was_not_observed_is_neither_as_expected_nor_different(tmp_path):
    def reply(s, t, vid):
        return None if (s == "netty" and t == "default" and vid == "HC01.SSH") else True
    text, m = comp_build(tmp_path, comp_clean(reply))
    assert m["CompCaseNettyRowsNotObserved"] == "3" and m["CompCaseNettyRowsDiffer"] == "0"
    assert m["CompCaseNettyRowsObserved"] == str(m_rows(m, "Netty") - 3)
    assert int(m["CompCaseNettyRowsAsExpected"]) == m_rows(m, "Netty") - 3
    assert m["CompCaseNettyDefaultVariantsNotObserved"] == "1" and m["CompCaseNettyDefaultVariantsDiffer"] == "0"
    assert m["CompCaseNettyDefaultVariantsAsExpected"] == str(int(m["CompCaseNettyDefaultVariants"]) - 1)
    assert m["CompCaseNettyDefaultCasesNotObserved"] == "HC1" and m["CompCaseNettyMatchedCasesNotObserved"] == "none"
    assert m["CompCaseRowsNotObserved"] == "3" and m["CompCaseUnitsMixed"] == "0"
    assert "% not observed: netty default HC01.SSH: opcase did not end" in text


def test_replicates_that_disagree_make_a_mixed_variant_that_is_in_no_list(tmp_path):
    rows = comp_clean()
    i = next(n for n, r in enumerate(rows) if r.get("system") == "envoy" and r.get("timers") == "matched" and r.get("id") == "HC01.HTTP"
             and r.get("replicate") == 2)
    rows[i] = comp_row("envoy", "matched", "HC01.HTTP", 1, "plain", 2, reply=False)
    text, m = comp_build(tmp_path, rows)
    assert m["CompCaseUnitsMixed"] == "1" and m["CompCaseEnvoyRowsDiffer"] == "1"
    assert m["CompCaseEnvoyMatchedVariantsDiffer"] == "0" and m["CompCaseEnvoyMatchedCasesDifferAll"] == "none"
    assert m["CompCaseEnvoyMatchedCasesDifferSome"] == "none"
    assert ("% deviation: envoy matched HC01.HTTP: the replicates are not alike (as expected 2, differ 1, not observed 0)") in text


def test_the_two_timer_settings_are_kept_apart(tmp_path):
    _, m = comp_build(tmp_path, comp_clean(lambda s, t, vid: not (s == "haproxy" and t == "default" and vid.startswith("HC01"))))
    assert m["CompCaseHaproxyMatchedVariantsDiffer"] == "0" and m["CompCaseHaproxyDefaultVariantsDiffer"] == "2"
    assert m["CompCaseHaproxyDefaultCasesDifferAll"] == "HC1" and m["CompCaseHaproxyMatchedCasesDifferAll"] == "none"
    assert m["CompCaseHaproxyRowsDiffer"] == "6"


def test_rows_with_no_decision_within_t_obs_are_counted(tmp_path):
    rows = comp_clean()
    for i, r in enumerate(rows):
        if r.get("system") == "caddy-l4" and r.get("id") == "HC01.SSH":
            rows[i] = comp_row("caddy-l4", r["timers"], "HC01.SSH", 1, "plain", r["replicate"], True, timed_out=True,
                               no_decision_within_t_obs=True)
    _, m = comp_build(tmp_path, rows)
    assert m["CompCaseCaddyLFourRowsNoDecision"] == "6" and m["CompCaseRowsNoDecision"] == "6" and m["CompCaseNginxRowsNoDecision"] == "0"


def test_no_time_of_the_table_reaches_the_macros(tmp_path):
    rows = [dict(r, end_ms=123456.789, first_byte_ms=654321.987) if r.get("kind") == "competitor-case" and r.get("observed") else r
            for r in comp_clean()]
    text, m = comp_build(tmp_path, rows)
    assert "123456" not in text and "654321" not in text
    assert not [n for n in m if re.search(r"(Ms|Time|Latency|Delay|Seconds)", n)]


def test_the_part_is_off_without_competitors(tmp_path):
    lr, lt = write(tmp_path, "L", server_rows())
    without = H.build([("L", "hl1", lr, lt)], summary(tmp_path))
    assert "CompCase" not in without
    text, _ = comp_build(tmp_path, comp_clean())
    rest = iter(text.splitlines(keepends=True))
    assert all(line in rest for line in without.splitlines(keepends=True))   # every old line, in its old order


@pytest.mark.parametrize("change, msg", [
    ({"development": True}, "not a frozen run"), ({"job": "hc2"}, "job"), ({"runner": "cost_run"}, "runner"),
    ({"provenance": {"freeze": {"freeze": {"code_freeze": "0" * 40, "change_commit": H.CHANGE_COMMIT}}}}, "code_freeze"),
    ({"provenance": {"freeze": {"freeze": {"code_freeze": H.CODE_FREEZE}}}}, "change_commit"),
    ({"provenance": {"freeze": {"freeze": {"code_freeze": H.CODE_FREEZE, "change_commit": "1" * 40}}}}, "change_commit"),
    ({"system": "traefik"}, "system"), ({"timers": "slow"}, "timers"), ({"cases_kind": "cases-fallback"}, "cases kind"),
    ({"hc": 26}, "case"), ({"hc": 2}, "case"), ({"replicate": 4}, "replicate"), ({"replicate": 0}, "replicate"),
    ({"observed": 1}, "observed"), ({"reply_as_the_server_table_expects": "yes"}, "reply"), ({"timed_out": True}, "timed_out"),
    ({"kind": "hardcase"}, "kind"), ({"setup": "PROXY"}, "setup"), ({"setup": None}, "setup"),
    ({"hc": True}, "case"), ({"replicate": True}, "replicate"), ({"hc": 1.0}, "case"),
    ({"id": "HC011.HTTP"}, "id"), ({"id": "HC10.HTTP"}, "id"), ({"id": "HC01.HTTP\r"}, "id"), ({"id": "hc01.HTTP"}, "id"),
])
def test_a_row_that_disagrees_is_refused(tmp_path, change, msg):
    rows = comp_clean()
    i = next(n for n, r in enumerate(rows) if r.get("system") == "nginx" and r.get("kind") == "competitor-case")
    rows[i] = dict(rows[i], **change)
    with pytest.raises(H.InputRefused, match=msg):
        comp_build(tmp_path, rows)


def test_a_table_that_is_incomplete_or_repeated_is_refused(tmp_path):
    rows = comp_clean()
    nginx = [n for n, r in enumerate(rows) if r.get("system") == "nginx" and r.get("kind") == "competitor-case"]
    with pytest.raises(H.InputRefused, match="two rows"):
        comp_build(tmp_path, rows + [dict(rows[nginx[0]])])
    with pytest.raises(H.InputRefused, match="replicates"):
        comp_build(tmp_path, [r for n, r in enumerate(rows) if n != nginx[0]])
    with pytest.raises(H.InputRefused, match="lacks"):
        comp_build(tmp_path, [r for r in rows if not (r.get("system") == "jetty" and r.get("id") == "HC02.TLS.k01")])
    with pytest.raises(H.InputRefused, match="lacks"):
        comp_build(tmp_path, [r for r in rows if not (r.get("system") == "hyper-util" and r.get("timers") == "default"
                                                      and r.get("id") == "HC01.SSH")])
    with pytest.raises(H.InputRefused, match="system"):
        comp_build(tmp_path, [r for r in rows if r.get("system") != "cmux"])
    with pytest.raises(H.InputRefused, match="id"):
        comp_build(tmp_path, rows + [comp_row("nginx", "matched", "HC01.HTTP", 2, "plain", 1)])


def test_the_observed_and_unobserved_forms_are_checked(tmp_path):
    rows = comp_clean()
    i = next(n for n, r in enumerate(rows) if r.get("system") == "nginx" and r.get("kind") == "competitor-case")
    no_reply = {k: v for k, v in rows[i].items() if k != "reply_as_the_server_table_expects"}
    with pytest.raises(H.InputRefused, match="reply"):
        comp_build(tmp_path, rows[:i] + [no_reply] + rows[i + 1:])
    gone = comp_row("nginx", "matched", "HC01.HTTP", 1, "plain", 1, reply=None)
    for bad, msg in ((dict(gone, why=""), "why"), (dict(gone, reply_as_the_server_table_expects=True), "reply")):
        with pytest.raises(H.InputRefused, match=msg):
            comp_build(tmp_path, rows[:i] + [bad] + rows[i + 1:])


def test_the_start_rows_are_checked(tmp_path):
    rows = comp_clean()
    starts = [n for n, r in enumerate(rows) if r.get("kind") == "competitor-start"]
    with pytest.raises(H.InputRefused, match="start"):
        comp_build(tmp_path, [r for n, r in enumerate(rows) if n != starts[0]])
    with pytest.raises(H.InputRefused, match="start"):
        comp_build(tmp_path, rows + [dict(rows[starts[0]])])
    with pytest.raises(H.InputRefused, match="did not start"):
        comp_build(tmp_path, rows[:starts[1]] + [comp_start("nginx", "cases", "default", ok=False)] + rows[starts[1] + 1:])
    with pytest.raises(H.InputRefused, match="start"):
        comp_build(tmp_path, rows + [comp_start("nginx", "cases-fallback", "matched")])


def test_cli_names_the_competitors_input_by_its_sha256(tmp_path):
    lr, lt = write(tmp_path, "L", server_rows())
    cr = comp_write(tmp_path, comp_clean())
    out = tmp_path / "hardcase-macros.tex"
    argv = ["--server", "L", "hl1", str(lr), str(lt), "--summary", str(summary(tmp_path)), "--out", str(out)]
    assert H.main(argv + ["--competitors", "hc1", str(cr)]) == 0
    text = out.read_text(encoding="utf-8")
    assert f"% input: L hc1 competitor_cases.jsonl sha256 {H.sha256_file(cr)}" in text
    assert text.index("% input: L hl1") < text.index("% input: summary.json") < text.index("% input: L hc1")
    bad = comp_write(tmp_path, [dict(r, development=True) for r in comp_clean()], "bad")
    assert H.main(argv + ["--competitors", "hc1", str(bad)]) == 2
    assert H.main(argv) == 0 and "CompCase" not in out.read_text(encoding="utf-8")


def test_competitor_names_collide_with_no_other_generator(tmp_path):
    text, _ = comp_build(tmp_path, comp_clean())
    names = emitted_names(text)
    comp = [n for n in names if n.startswith("CompCase")]
    assert len(comp) > 200 and len(names) == len(set(names)) and all(re.fullmatch(r"[A-Za-z]+", n) for n in names)
    fixed, prefixes = TD.macros_py_names()
    design = design_names()
    results = HERE.parent / "results" / "macros.tex"
    emitted = set(emitted_names(results.read_text(encoding="utf-8"))) if results.exists() else set()
    for n in comp:
        assert n not in fixed and not n.startswith(prefixes) and n not in design and n not in emitted, n


def test_a_partly_observed_variant_is_mixed_and_named_with_its_split(tmp_path):
    rows = comp_clean()
    i = next(n for n, r in enumerate(rows) if r.get("system") == "cmux" and r.get("timers") == "default" and r.get("id") == "HC01.SSH"
             and r.get("replicate") == 3)
    rows[i] = comp_row("cmux", "default", "HC01.SSH", 1, "plain", 3, reply=None)
    text, m = comp_build(tmp_path, rows)
    assert m["CompCaseUnitsMixed"] == "1" and m["CompCaseCmuxRowsNotObserved"] == "1" and m["CompCaseCmuxRowsDiffer"] == "0"
    assert m["CompCaseCmuxDefaultVariantsNotObserved"] == "0" and m["CompCaseCmuxDefaultCasesNotObserved"] == "none"
    assert m["CompCaseCmuxDefaultVariantsAsExpected"] == str(int(m["CompCaseCmuxDefaultVariants"]) - 1)
    assert "% deviation: cmux default HC01.SSH: the replicates are not alike (as expected 2, differ 0, not observed 1)" in text
    rows[i] = comp_row("cmux", "default", "HC01.SSH", 1, "plain", 3, reply=False)
    rows[i - 1] = comp_row("cmux", "default", "HC01.SSH", 1, "plain", 2, reply=None)
    text, m = comp_build(tmp_path, rows)
    assert "(as expected 1, differ 1, not observed 1)" in text and m["CompCaseCmuxDefaultVariantsDiffer"] == "0"


def test_free_text_of_a_row_never_reaches_the_output(tmp_path):
    hostile = "opcase printed no run (exit 2): bad option\n\\input{/etc/passwd} 50% & x_y\r\\end{document}"
    rows = comp_clean()
    for i, r in enumerate(rows):
        if (r.get("system"), r.get("timers"), r.get("id")) == ("nginx", "matched", "HC01.HTTP"):
            rows[i] = comp_row("nginx", "matched", "HC01.HTTP", 1, "plain", r["replicate"], reply=None, why=hostile)
    text, m = comp_build(tmp_path, rows)
    assert "% not observed: nginx matched HC01.HTTP: opcase printed no run (exit 2)\n" in text
    assert "passwd" not in text and "end{document}" not in text and "\r" not in text
    assert all(line.startswith(("%", "\\newcommand")) for line in text.splitlines())
    assert m["CompCaseNginxRowsNotObserved"] == "3"


@pytest.mark.parametrize("why", ["", "   ", "something else", "opcase did not end\n\\input{x}", "opcase printed no run: x", "Opcase did not end"])
def test_a_reason_run_variant_does_not_write_is_refused(tmp_path, why):
    rows = comp_clean()
    i = next(n for n, r in enumerate(rows) if r.get("system") == "nginx" and r.get("kind") == "competitor-case")
    rows[i] = comp_row("nginx", "matched", "HC01.HTTP", 1, "plain", 1, reply=None, why=why)
    with pytest.raises(H.InputRefused, match="why"):
        comp_build(tmp_path, rows)


def test_the_table_must_hold_the_server_parts_variants(tmp_path):
    rows = comp_clean()
    # a frozen competitors run narrowed to some cases: every row of one variant is missing
    narrowed = [r for r in rows if r.get("id") != "HC02.TLS.k01"]
    with pytest.raises(H.InputRefused, match=r"only in the server part"):
        comp_build(tmp_path, narrowed)
    # a variant that the server part does not have
    with pytest.raises(H.InputRefused, match=r"only in the table"):
        comp_build(tmp_path, rows, server=server_rows([v for v in VARIANTS if v[0] != "HC05"]))
    # another case or setup than the server part's
    other = [(vid, hc, "PROXY" if vid == "HC01.HTTP" else setup) for vid, hc, setup in VARIANTS]
    with pytest.raises(H.InputRefused, match=r"another case or setup"):
        comp_build(tmp_path, rows, server=server_rows(other))
    twice = server_rows()
    j = next(n for n, r in enumerate(twice) if r["kind"] == "hardcase" and r["id"] == "HC01.HTTP")
    twice[j] = dict(twice[j], setup="PROXY")
    with pytest.raises(H.InputRefused, match="two cases or setups"):
        comp_build(tmp_path, rows, server=twice)


def test_the_competitors_need_l_server_part(tmp_path):
    wr, wt = write(tmp_path, "W", clean("wh1"))
    with pytest.raises(H.InputRefused, match="--server L"):
        H.build([("W", "wh1", wr, wt)], summary(tmp_path), competitors=("hc1", comp_write(tmp_path, comp_clean())))


def test_the_order_of_the_rows_does_not_matter(tmp_path):
    def reply(s, t, vid):
        return not ((s == "jetty" and vid in ("HC02.TLS.k01", "HC01.SSH") and t == "default")
                    or (s == "nginx" and vid in ("HC01.HTTP", "HC01.SSH", "HC02.TLS.k01", "HC09") and t == "matched"))
    rows = comp_clean(reply)
    t1, a = comp_build(tmp_path, rows)
    t2, b = comp_build(tmp_path, rows[::-1])
    own = ("% input: L hc1",)   # the input line names the file, whose bytes follow the row order
    assert [x for x in t1.splitlines() if not x.startswith(own)] == [x for x in t2.splitlines() if not x.startswith(own)]
    assert a == b and a["CompCaseJettyDefaultCasesDifferAll"] == "HC2" and a["CompCaseJettyDefaultCasesDifferSome"] == "HC1"
    assert a["CompCaseNginxMatchedCasesDifferAll"] == "HC1, HC2, HC9" and a["CompCaseNginxMatchedCasesDifferSome"] == "none"
    more = VARIANTS + (("HC02.TLS.k02", 2, "plain"),)   # cases 1 and 2 then hold two variants each
    rows = comp_clean(lambda s, t, vid: not (s == "nginx" and t == "matched" and vid in ("HC01.HTTP", "HC02.TLS.k01")), more)
    for order in (rows, rows[::-1]):
        m = comp_build(tmp_path, order, server=server_rows(more))[1]
        assert m["CompCaseNginxMatchedCasesDifferSome"] == "HC1, HC2" and m["CompCaseNginxMatchedCasesDifferAll"] == "none"
