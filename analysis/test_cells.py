#!/usr/bin/env python3
"""Tests of analysis/cells.py: the frozen cell lists (hypotheses.md section 6), the order of the
resampling draws (4.7, section 10), the seeds file, the macro words; and the text rule that no
file of analysis/ or design/status-m7a.md holds an en or em dash.

    python -m pytest analysis/test_cells.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cells as C  # noqa: E402
import macros as MC  # noqa: E402


def test_cost_cells_of_6_1():
    cc = C.cost_cells()
    assert [c.number for c in cc] == list(range(1, 37))
    ids = {c.number: c.id for c in cc}
    assert ids[1] == "C1.L.epoll.http1" and ids[4] == "C1.L.epoll.mqtt" and ids[5] == "C1.L.io_uring.http1"
    assert ids[9] == "C1.W.IOCP.http1" and ids[12] == "C1.W.IOCP.mqtt" and ids[13] == "C2.L.epoll.http1"
    assert ids[25] == "C3.L.epoll.http1" and ids[36] == "C3.W.IOCP.mqtt"
    assert all(c.num == "one-port" and c.den == "dedicated" and c.test == "tost" and c.r is None for c in cc)


def test_b3_cells_of_6_2():
    bb = C.b3_cells()
    holm = [c for c in bb if c.holm]
    desc = [c for c in bb if not c.holm]
    assert len(holm) == 18 and len(desc) == 16 and bb[:18] == holm
    assert [c.id for c in holm[:4]] == ["B3.silent.nginx.epoll", "B3.silent.nginx.io_uring", "B3.silent.haproxy.epoll",
                                        "B3.silent.haproxy.io_uring"]
    assert holm[9].id == "B3.silent.hyper-util.io_uring" and holm[10].id == "B3.partial-hello.nginx.epoll"
    assert not any(c.system == "hyper-util" and c.case == "partial-hello" for c in bb)
    assert [c.system for c in desc[:8:2]] == ["netty", "jetty", "caddy-l4", "cmux"]
    assert all(c.bound == 1.10 and c.num == "competitor" and c.den == "server" and c.r == 16 for c in bb)


def test_m_cells_of_6_3():
    mm = C.m_cells()
    assert len(mm) == 20
    assert [c.id for c in mm[:6]] == ["M1.L.epoll.http1", "M1.L.io_uring.http1", "M1.W.IOCP.http1", "M1.L.epoll.h2c",
                                      "M1.L.io_uring.h2c", "M1.W.IOCP.h2c"]
    assert [c.id for c in mm[6:10]] == ["M2.L.epoll.http1", "M2.L.io_uring.http1", "M2.L.epoll.tls", "M2.L.io_uring.tls"]
    assert [c.system for c in mm[10:15]] == list(C.PROXIES) and all(c.proto == "tls-stub" for c in mm[10:15])
    assert all(c.proto == "http1" for c in mm[15:])
    assert [c.test for c in mm] == ["greater"] * 6 + ["less"] * 4 + ["greater"] * 10


def test_secondary_draws_in_the_order_of_4_7():
    d = C.secondary_draws()
    assert len(d) == 36 * 3 + 12 + 9 + 3 + 6 + 5 + 10 + 2 + (16 + 20) + 4 + (36 + 34 + 20)
    assert [(x.source, x.metric) for x in d[:4]] == [("C1.L.epoll.http1", "cpu"), ("C1.L.epoll.http1", "rss"),
                                                     ("C1.L.epoll.http1", "rss_peak"), ("C1.L.epoll.h2c", "cpu")]
    c3 = [x for x in d if x.bullet == "wl4" and x.source == "C3.L.epoll.http1"]
    assert [x.metric for x in c3] == ["cpu", "rss", "rss_peak", "ttfb_p99"]
    assert [x.bullet for x in d if x.bullet != "wl4"][:1] == ["ssh"]
    two = [x.source for x in d if x.bullet == "two-cores"]
    assert two == ["S.two-cores.C1.L.epoll.two-cores", "S.two-cores.C1.L.epoll.reuseport", "S.two-cores.C1.L.io_uring.two-cores",
                   "S.two-cores.C1.L.io_uring.reuseport", "S.two-cores.C1.W.IOCP.two-cores"]
    relay = [x.source for x in d if x.bullet == "relay-io_uring"]
    assert relay[0] == "S.relay-io_uring.L.io_uring.http1.nginx" and relay[5] == "S.relay-io_uring.L.io_uring.tls-stub.nginx"
    m = [(x.source, x.metric) for x in d if x.bullet == "m-ttfb-cpu"]
    assert m[:4] == [("S.m-ttfb.M1.L.epoll.http1", "value"), ("M1.L.epoll.http1", "cpu"), ("S.m-ttfb.M1.L.epoll.h2c", "value"),
                     ("M1.L.epoll.h2c", "cpu")]
    assert ("M2.L.epoll.http1", "cpu") in m and ("S.m-ttfb.M2.L.epoll.http1", "value") not in m
    m3 = [s for s, _ in m if s.startswith("S.m-ttfb.M3")]
    assert m3[0] == "S.m-ttfb.M3.L.epoll.http1.nginx" and m3[5] == "S.m-ttfb.M3.L.epoll.tls-stub.nginx"
    b3o = [x.source for x in d if x.bullet == "b3-other-mode"]
    assert b3o == ["S.b3-other-mode.epoll.silent", "S.b3-other-mode.epoll.partial-hello", "S.b3-other-mode.io_uring.silent",
                   "S.b3-other-mode.io_uring.partial-hello"]
    job = [x for x in d if x.bullet == "by-job"]
    assert all(x.clustered for x in job) and job[0].source == "C1.L.epoll.http1" and job[36].source == "B3.silent.nginx.epoll"
    assert job[-1].source == "M3.L.epoll.http1.sslh-ev"
    assert d[-1] is job[-1]


def test_seeds_file():
    good = {n: i for i, n in enumerate(C.SEED_NAMES)}
    assert C.check_seeds(good) == good
    for bad in ({**good, "SEED_X": 1}, {k: v for k, v in good.items() if k != "SEED_SIM"}, {**good, "SEED_SIM": -1},
                {**good, "SEED_SIM": True}, {**good, "SEED_SIM": 1.5}):
        with pytest.raises(ValueError):
            C.check_seeds(bad)


def test_every_cell_has_a_macro_word_without_digits():
    ids = [c.id for c in C.cost_cells() + C.b3_cells() + C.m_cells()] + [s.id for s in C.secondary_cells()]
    for i in ids:
        w = MC.word(i)
        assert re.fullmatch(r"[A-Za-z]+", w), (i, w)
    words = [MC.word(i) for i in ids]
    assert len(words) == len(set(words))
    for d in C.secondary_draws():
        assert re.fullmatch(r"[A-Za-z]+", "Sec" + MC.word(d.bullet) + MC.word(d.source) + MC.word(d.metric))


def test_no_en_or_em_dash():
    files = sorted(HERE.glob("*.py")) + [HERE / "requirements.txt"]
    status = HERE.parent / "design" / "status-m7a.md"
    if status.exists():
        files.append(status)
    for p in files:
        text = p.read_text(encoding="utf-8")
        assert chr(0x2013) not in text and chr(0x2014) not in text, p.name


def main() -> int:
    return pytest.main([__file__, "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
