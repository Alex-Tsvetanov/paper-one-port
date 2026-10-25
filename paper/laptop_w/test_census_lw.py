"""Tests of the kernel census: the collector (census_host.py) and the generator (census_lw.py).

    python -X utf8 -m pytest -q paper/laptop_w/test_census_lw.py

They run on the desktop from fixtures (paper/laptop_w/fixtures/census/). On Windows one test runs
the collector end to end against a stand-in server (fake_oneport.py) and the real netstat and
GetExtendedTcpTable. Set P3_CENSUS_W_REC to a laptop gate job's out/rec folder (build-release and
gate-W.json) to run it once more against the gated oneport.exe. Every such run is a functional test:
the generator refuses its output, as the last tests check.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import struct
import sys
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import census_host as H  # noqa: E402
import census_lw as G  # noqa: E402
import lw_common as C  # noqa: E402

FIX = HERE / "fixtures" / "census"
FAKE = FIX / "fake_oneport.py"
L_GATE = C.ROOT / "lab" / "gates" / "gate-L.json"
L_GATE_SHA = "c6517177d497dc7f6951d2860926e950618a17cd6b1fc9568e0f8375ccfc1ab9"
L_ONEPORT = "4c64edc25f7689dab95c90218ae50d3d7e92960d3e4e08bb826b1239e252b179"
W_GATE_SHA = "96248c8fecbf5595ba9b99ced158317c4bb793f23176e3d87df31bc7a8371e03"
W_ONEPORT = "eb810f4e932887803bd96f965b84384618df7e10428c67429041405fdb53a9ab"
DESKTOP_W_ONEPORT = "749d0209c112fb8fa2689b632f635f32364d46827de243c28398ab647adf328c"
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the Windows collector needs Windows")


# ---- the collector's parsers --------------------------------------------------------------

def test_ss_rows_are_the_pid_exactly():
    rows = H.parse_ss((FIX / "ss-dedicated.txt").read_text(encoding="utf-8"), 2737423)
    assert sorted(r["local"] for r in rows) == [f"127.0.0.1:{p}" for p in range(19100, 19106)]
    assert all("pid=2737423," in r["line"] for r in rows)  # not pid 27374230, not sshd


def test_proc_net_rows_are_listen_state_and_the_process_inodes():
    v4 = (FIX / "proc-net-tcp.txt").read_text(encoding="utf-8")
    v6 = (FIX / "proc-net-tcp6.txt").read_text(encoding="utf-8")
    inodes = {41001, 41002, 41003, 41004, 41005, 41006, 41007}
    rows = H.parse_proc_net(v4, inodes) + H.parse_proc_net(v6, inodes)
    # 41007 is not in state 0A; sshd's 7001 and 7002 are not the process's; the TIME-WAIT row has inode 0
    assert sorted(r["local"] for r in rows) == [f"127.0.0.1:{p}" for p in range(19100, 19106)]
    assert H.parse_proc_net(v6, {41099}) == [{"local": "[::1]:19100", "inode": 41099}]


def test_both_linux_sources_agree_on_the_fixture():
    ss = sorted(r["local"] for r in H.parse_ss((FIX / "ss-dedicated.txt").read_text(encoding="utf-8"), 2737423))
    proc = sorted(r["local"] for r in H.parse_proc_net((FIX / "proc-net-tcp.txt").read_text(encoding="utf-8"),
                                                        set(range(41001, 41007))))
    assert ss == proc


def test_addresses_are_normalised():
    assert H.norm_local("127.0.0.1:19080") == "127.0.0.1:19080"
    assert H.norm_local("127.0.0.1%lo:19080") == "127.0.0.1:19080"
    assert H.norm_local("[::1]:19080") == "[::1]:19080"
    assert H.decode_proc_addr("0100007F:4A38") == "127.0.0.1:19000"


def test_netstat_rows_of_the_pid_and_a_localised_state():
    listening, other = H.parse_netstat((FIX / "netstat-tcp.txt").read_text(encoding="utf-8"), 4242)
    assert [r["local"] for r in listening] == ["127.0.0.1:19080"] and other == []
    listening, other = H.parse_netstat((FIX / "netstat-tcp-localized.txt").read_text(encoding="utf-8"), 4242)
    assert listening == [] and [r["state"] for r in other] == ["ABHOEREN"]  # a disagreement, not a pass


def tcp_table_v4(rows):
    out = struct.pack("<I", len(rows))
    for state, addr, port, pid in rows:
        out += struct.pack("<I", state) + bytes(map(int, addr.split("."))) + struct.pack(">H", port) + b"\0\0"
        out += b"\0" * 8 + struct.pack("<I", pid)
    return out


def tcp_table_v6(rows):
    import ipaddress
    out = struct.pack("<I", len(rows))
    for state, addr, port, pid in rows:
        out += ipaddress.IPv6Address(addr).packed + b"\0" * 4 + struct.pack(">H", port) + b"\0\0"
        out += b"\0" * 24 + struct.pack("<II", state, pid)
    return out


def test_tcp_tables_are_read_by_row():
    raw = tcp_table_v4([(2, "127.0.0.1", 19080, 4242), (2, "127.0.0.1", 19081, 7), (5, "127.0.0.1", 19082, 4242)])
    assert H.parse_tcp_table(raw, 2, 4242) == [{"local": "127.0.0.1:19080", "state": "LISTEN"}]
    raw6 = tcp_table_v6([(2, "::1", 19080, 4242), (2, "::", 135, 9)])
    assert H.parse_tcp_table(raw6, 23, 4242) == [{"local": "[::1]:19080", "state": "LISTEN"}]


def test_read_head_of_this_checkout_is_a_commit():
    head = H.read_head(C.ROOT)
    assert head is None or (len(head) == 40 and int(head, 16) >= 0)


# ---- the collector's refusals -------------------------------------------------------------

def fake_gate(tmp_path: Path, host: str, binary: Path, **over) -> tuple[Path, str]:
    doc = {"host": host, "passed": True, "dry_run": False, "citable": True, "records_dir": "x",
           "binaries": {"oneport": H.sha256_file(binary)}, "oneport": {"binaries": {"oneport": H.sha256_file(binary)}}}
    doc.update(over)
    path = tmp_path / f"gate-{host}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path, H.sha256_file(path)


def test_a_wrong_gate_or_binary_is_refused_before_any_run(tmp_path):
    gate, sha = fake_gate(tmp_path, "W", FAKE)
    assert H.census("windows", FAKE, gate, "0" * 64, tmp_path / "a", skip_os_check=True) == 2
    doc = json.loads((tmp_path / "a" / "census.json").read_text(encoding="utf-8"))
    assert "sha256" in doc["refused"] and doc["runs"] == []
    other = tmp_path / "other.py"
    other.write_text("print(1)\n", encoding="utf-8")
    assert H.census("windows", other, gate, sha, tmp_path / "b", skip_os_check=True) == 2
    gate_l, sha_l = fake_gate(tmp_path, "L", FAKE)
    assert H.census("windows", FAKE, gate_l, sha_l, tmp_path / "c", skip_os_check=True) == 2
    gate_d, sha_d = fake_gate(tmp_path, "W", FAKE, citable=False)
    assert H.census("windows", FAKE, gate_d, sha_d, tmp_path / "d", skip_os_check=True) == 2


def test_the_wrong_os_is_refused(tmp_path):
    gate, sha = fake_gate(tmp_path, "L", FAKE)
    os_name = "linux" if sys.platform == "win32" else "windows"
    assert H.census(os_name, FAKE, gate, sha, tmp_path / "o") == 2
    assert "not" in json.loads((tmp_path / "o" / "census.json").read_text(encoding="utf-8"))["refused"]


def test_an_existing_record_is_never_overwritten(tmp_path):
    (tmp_path / "census.json").write_text("{}", encoding="utf-8")
    gate, sha = fake_gate(tmp_path, "W", FAKE)
    assert H.census("windows", FAKE, gate, sha, tmp_path, skip_os_check=True) == 2
    assert (tmp_path / "census.json").read_text(encoding="utf-8") == "{}"


# ---- the collector end to end on Windows, against the stand-in --------------------------

@windows_only
def test_windows_collector_with_the_stand_in(tmp_path, monkeypatch):
    monkeypatch.delenv("LAB_JOB_ID", raising=False)
    monkeypatch.delenv("FAKE_ONEPORT", raising=False)
    gate, sha = fake_gate(tmp_path, "W", FAKE)
    runs = (H.Run("one-port", "IOCP", "shared", 1, 19580), H.Run("dedicated", "IOCP", "shared", 1, 19600))
    rc = H.census("windows", FAKE, gate, sha, tmp_path / "out", runs=runs, launcher=(sys.executable,))
    doc = json.loads((tmp_path / "out" / "census.json").read_text(encoding="utf-8"))
    assert rc == 0, doc
    assert doc["functional_test"] is True and doc["complete"] is True
    assert [r["kernel_listen_count"] for r in doc["runs"]] == [1, 6]
    assert [r["server_listening_lines"] for r in doc["runs"]] == [1, 6]
    assert all(r["agree"] and r["stopped_by"] == "stop event" and r["exit_code"] == 0 for r in doc["runs"])
    assert (tmp_path / "out" / "raw" / "IOCP-dedicated-shared-1.netstat-tcp.txt").exists()


@windows_only
@pytest.mark.parametrize("how", ["silent", "exit"])
def test_a_server_that_never_gets_ready_fails_its_run(tmp_path, monkeypatch, how):
    monkeypatch.setenv("FAKE_ONEPORT", how)
    monkeypatch.setattr(H, "READY_TIMEOUT_S", 1.0)
    gate, sha = fake_gate(tmp_path, "W", FAKE)
    runs = (H.Run("one-port", "IOCP", "shared", 1, 19680),)
    rc = H.census("windows", FAKE, gate, sha, tmp_path / "out", runs=runs, launcher=(sys.executable,))
    doc = json.loads((tmp_path / "out" / "census.json").read_text(encoding="utf-8"))
    assert rc == 3 and doc["complete"] is False
    assert doc["runs"][0]["ok"] is False and "ready" in doc["runs"][0]["problem"]


W_REC = Path(os.environ["P3_CENSUS_W_REC"]) if os.environ.get("P3_CENSUS_W_REC") else None


@windows_only
@pytest.mark.skipif(W_REC is None, reason="P3_CENSUS_W_REC not set: no gated oneport.exe on this machine")
def test_windows_collector_with_the_gated_binary_is_a_functional_test(tmp_path, monkeypatch):
    monkeypatch.delenv("LAB_JOB_ID", raising=False)
    binary = W_REC / "build-release" / "bench" / "server" / "oneport.exe"
    rc = H.census("windows", binary, W_REC / "gate-W.json", W_GATE_SHA, tmp_path / "out")
    doc = json.loads((tmp_path / "out" / "census.json").read_text(encoding="utf-8"))
    assert rc == 0, doc
    assert doc["functional_test"] is True and doc["binary_sha256"] == W_ONEPORT
    assert [r["kernel_listen_count"] for r in doc["runs"]] == [1, 6]
    archive = pack(tmp_path, "p3-census-w", doc)
    with pytest.raises(ValueError, match="not a lab job"):
        G.check_record("W", G.read_archive(archive)[0], "p3-census-w", provenance(), C.ROOT / "lab" / "gates")


# ---- the generator ------------------------------------------------------------------------

def provenance() -> dict:
    return json.loads((C.LW / "provenance.json").read_text(encoding="utf-8"))


def run_record(backend, mode, listener, workers, port, kernel_key, count, lines=None):
    n_lines = lines if lines is not None else (6 if mode == "dedicated" else 1)
    rows = [{"local": f"127.0.0.1:{port + (i if mode == 'dedicated' else 0)}"} for i in range(count)]
    rec = {"mode": mode, "backend": backend, "listener": listener, "workers": workers, "port": port,
           "pid": 100, "stopped_by": "SIGTERM" if kernel_key == "ss" else "stop event", "exit_code": 0,
           "server_lines": [f"oneport: listening x 127.0.0.1:{port + i}" for i in range(n_lines)],
           "server_listening_lines": n_lines, kernel_key: rows, "kernel_listen_count": count,
           "agree": True, "v6_rows": [], "problem": None, "ok": True}
    return rec


def record(host: str) -> dict:
    if host == "L":
        runs = [run_record("epoll", "one-port", "shared", 1, 19080, "ss", 1),
                run_record("epoll", "dedicated", "shared", 1, 19100, "ss", 6),
                run_record("epoll", "one-port", "reuseport", 2, 19200, "ss", 2, lines=1),
                run_record("io_uring", "one-port", "shared", 1, 19300, "ss", 1),
                run_record("io_uring", "dedicated", "shared", 1, 19400, "ss", 6)]
        gate, binary, job, date = L_GATE_SHA, L_ONEPORT, "p3-census-l", "2026-10-25"
    else:
        runs = [run_record("IOCP", "one-port", "shared", 1, 19080, "netstat", 1),
                run_record("IOCP", "dedicated", "shared", 1, 19100, "netstat", 6)]
        gate, binary, job, date = W_GATE_SHA, W_ONEPORT, "p3-census-w-2", "2026-10-27"
    return {"host": host, "os": G.OS_OF[host], "job": job, "functional_test": False, "load": False,
            "bind": "127.0.0.1", "date": date, "gate_sha256": gate, "binary_sha256": binary,
            "gate_oneport_sha256": binary, "runs": runs, "complete": True}


def pack(tmp_path: Path, job: str, doc: dict) -> Path:
    archive = tmp_path / f"{job}-{hashlib.sha256(json.dumps(doc).encode()).hexdigest()[:6]}.tar.gz"
    data = json.dumps(doc, indent=1).encode("utf-8")
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(f"{job}/out/census/census.json")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    Path(str(archive) + ".sha256").write_text(f"{H.sha256_file(archive)}  {archive.name}\n", encoding="utf-8")
    return archive


def test_the_fixture_gates_are_the_analysis_gates():
    assert H.sha256_file(L_GATE) == L_GATE_SHA == G.gate_sha256("L", provenance())
    assert G.gate_sha256("W", provenance()) == W_GATE_SHA
    assert json.loads(L_GATE.read_text(encoding="utf-8"))["binaries"]["oneport"] == L_ONEPORT


def test_the_generator_writes_the_table_and_macros(tmp_path):
    out = G.build(pack(tmp_path, "p3-census-l", record("L")), pack(tmp_path, "p3-census-w-2", record("W")))
    macros, table = out[G.OUT_MACROS], out[G.OUT_TABLE]
    assert "\\newcommand{\\CensusDateL}{25 October 2026}" in macros
    assert "\\newcommand{\\CensusDateW}{27 October 2026}" in macros
    assert "\\newcommand{\\CensusLEpollReuseport}{2}" in macros
    assert "\\newcommand{\\CensusLEpollReuseportLines}{1}" in macros
    assert "\\newcommand{\\CensusWIocpDedicated}{6}" in macros
    body = [ln for ln in table.splitlines() if not ln.startswith("%")]
    assert len(body) == len(G.ROWS) and body[0].startswith("Linux & epoll & ")
    assert body[-1].startswith("Windows & IOCP & dedicated")
    assert C.printed_label_hits(table) == []
    assert not any(chr(c) in macros + table for c in (0x2012, 0x2013, 0x2014, 0x2015))  # no dash


def mutate(host: str, fn):
    rec = record(host)
    fn(rec)
    return rec


@pytest.mark.parametrize("host,fn,match", [
    ("L", lambda r: r.update(functional_test=True), "functional test"),
    ("L", lambda r: r.update(job=None), "not a lab job"),
    ("W", lambda r: r.update(job="p3-cost-w"), "not a lab job"),
    ("L", lambda r: r.update(load=True), "no load"),
    ("L", lambda r: r.update(complete=False), "not complete"),
    ("W", lambda r: r.update(binary_sha256=DESKTOP_W_ONEPORT, gate_oneport_sha256=DESKTOP_W_ONEPORT), "desktop"),
    ("W", lambda r: r.update(gate_sha256="0" * 64), "not the analysis"),
    ("L", lambda r: r.update(binary_sha256="1" * 64, gate_oneport_sha256="1" * 64), "gate-L.json's oneport"),
    ("L", lambda r: r["runs"].pop(), "rows missing"),
    ("L", lambda r: r["runs"].append(copy.deepcopy(r["runs"][0])), "ran twice"),
    ("L", lambda r: r["runs"][1].update(kernel_listen_count=5), "not its kernel rows"),
    ("W", lambda r: r["runs"][0].update(agree=False), "disagree"),
    ("W", lambda r: r["runs"][0].update(stopped_by="killed"), "stopped by"),
    ("W", lambda r: r["runs"][0].update(v6_rows=[{"local": "[::1]:19080"}]), "IPv6"),
    ("L", lambda r: r.update(host="W"), "names host"),
])
def test_the_generator_refuses(tmp_path, host, fn, match):
    rec = mutate(host, fn)
    job = rec["job"] or f"p3-census-{host.lower()}"
    with pytest.raises(ValueError, match=match):
        G.check_record(host, G.read_archive(pack(tmp_path, job, rec))[0], job, provenance(), C.ROOT / "lab" / "gates")


def test_an_archive_whose_sidecar_differs_is_refused(tmp_path):
    archive = pack(tmp_path, "p3-census-l", record("L"))
    Path(str(archive) + ".sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        G.read_archive(archive)


def test_a_record_from_another_job_folder_is_refused(tmp_path):
    rec, folder, _ = G.read_archive(pack(tmp_path, "p3-census-l-3", record("L")))
    with pytest.raises(ValueError, match="job folder"):
        G.check_record("L", rec, folder, provenance(), C.ROOT / "lab" / "gates")


@windows_only
def test_a_functional_run_of_the_collector_is_refused_by_the_generator(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_JOB_ID", "p3-census-w")  # even with a job id: the stand-in run is a functional test
    gate, sha = fake_gate(tmp_path, "W", FAKE)
    runs = (H.Run("one-port", "IOCP", "shared", 1, 19780),)
    assert H.census("windows", FAKE, gate, sha, tmp_path / "out", runs=runs, launcher=(sys.executable,)) == 0
    doc = json.loads((tmp_path / "out" / "census.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="functional test"):
        G.check_record("W", G.read_archive(pack(tmp_path, "p3-census-w", doc))[0], "p3-census-w", provenance(),
                       C.ROOT / "lab" / "gates")
