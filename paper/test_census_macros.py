"""The kernel census macros match the committed JSON and the gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import census_macros as C  # noqa: E402


def test_committed_files_match():
    w_doc, l_doc = C.load(C.W_JSON), C.load(C.L_JSON)
    w_gate = C.load(C.ROOT / "lab" / "gates" / "measured-W.json")
    l_gate = C.load(C.ROOT / "lab" / "gates" / "measured-L.json")
    macros, table = C.render(w_doc, l_doc, w_gate, l_gate)
    assert C.MACROS.read_text(encoding="utf-8") == macros
    assert C.TABLE.read_text(encoding="utf-8") == table


def test_shared_listener_is_one_socket_and_reuseport_follows_the_workers():
    """sec-census.tex says the shared listener is one accept model on one transport,
    and the reuseport row used two workers. Those words have to match the JSON."""
    w_doc, l_doc = C.load(C.W_JSON), C.load(C.L_JSON)
    counts = {}
    counts.update(C.index_runs(w_doc))
    counts.update(C.index_runs(l_doc))
    for key, count in counts.items():
        host, _backend, mode, listener, workers = key
        if listener == "shared" and mode == "one-port":
            assert count == 1
        if listener == "shared" and mode == "dedicated":
            assert count == 6
        if listener == "reuseport":
            assert workers == 2 and count == 2


def test_a_wrong_binary_hash_is_refused():
    w_doc, l_doc = C.load(C.W_JSON), C.load(C.L_JSON)
    w_gate = json.loads((C.ROOT / "lab" / "gates" / "measured-W.json").read_text(encoding="utf-8"))
    l_gate = C.load(C.ROOT / "lab" / "gates" / "measured-L.json")
    w_gate["binaries"]["oneport"] = "0" * 64
    try:
        C.render(w_doc, l_doc, w_gate, l_gate)
    except SystemExit:
        return
    raise AssertionError("a binary hash outside the gate was accepted")
