"""WL7's readings (hypotheses.md, section 3, WL7; section 7, the B3 and ophold rules).

Each sample reads, for the system under test:
  U   the summed VmRSS of its processes (proc_pid_status(5)), in kB as /proc reports it;
  Kq  the `r` field (rmem_alloc) of `ss -tm` over its accepted sockets, with `f` beside it;
  Ks  Slab of /proc/meminfo, and the three skb caches of /proc/slabinfo (read as root): the
      cache "skbuff_head_cache", "skbuff_small_head", and for "skbuff_fclone_cache" the cache
      its /sys/kernel/slab link names, which on L is merged (`:0000512`, listed in
      /proc/slabinfo as "pool_workqueue"), with its co-tenants and its `slabs` and `objects`;
and the host's TIME-WAIT count and the established count of the system's accepted sockets.

A window's footprint per pending connection, from its baseline and a sample:
  U  = (sum VmRSS growth) / N_PEND
  Kq = the mean `r` over the accepted sockets
  Ks = (Slab growth - the skb caches' growth) / N_PEND
  W  = U + Kq + Ks
A cache's size is num_slabs x pagesperslab x the page size (slabinfo(5); WL7's design choice).

The parsers take text, so the tests run them on recorded samples; the readers that run commands
are thin and are exercised on L.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SKB_CACHES = ("skbuff_head_cache", "skbuff_small_head", "skbuff_fclone_cache")
# The rule of section 7: the larger of 2% of sample 2's W and SETTLE_ABS bytes per pending
# connection (both design choices of WL7).
SETTLE_REL = 0.02
SETTLE_ABS = 8.0
N_PEND = 10_000  # WL7, a design choice


# ---------------------------------------------------------------- parsers


def parse_kb_field(text: str, key: str) -> int:
    """The value of `key:` in kB from /proc/meminfo or /proc/<pid>/status text."""
    for line in text.splitlines():
        if line.startswith(key + ":"):
            parts = line.split()
            if len(parts) >= 3 and parts[2] != "kB":
                raise ValueError(f"{key}: unit {parts[2]!r}, not kB")
            return int(parts[1])
    raise KeyError(key)


def parse_slabinfo(text: str) -> dict[str, dict[str, int]]:
    """/proc/slabinfo version 2.1: name, active_objs, num_objs, objsize, objperslab,
    pagesperslab, then ': tunables ...' and ': slabdata active_slabs num_slabs sharedavail'."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("slabinfo - version: 2."):
        raise ValueError("not /proc/slabinfo version 2")
    out: dict[str, dict[str, int]] = {}
    for line in lines[1:]:
        if line.startswith("#") or not line.strip():
            continue
        head, _, rest = line.partition(":")
        h = head.split()
        m = re.search(r"slabdata\s+(\d+)\s+(\d+)\s+(\d+)", rest)
        if len(h) != 6 or m is None:
            raise ValueError(f"slabinfo line not understood: {line!r}")
        out[h[0]] = {
            "active_objs": int(h[1]), "num_objs": int(h[2]), "objsize": int(h[3]),
            "objperslab": int(h[4]), "pagesperslab": int(h[5]),
            "active_slabs": int(m.group(1)), "num_slabs": int(m.group(2)),
        }
    return out


def cache_bytes(entry: dict[str, int], page_size: int) -> int:
    return entry["num_slabs"] * entry["pagesperslab"] * page_size


def parse_first_int(text: str) -> int:
    """A /sys/kernel/slab attribute such as "199 N0=199": its first integer."""
    m = re.match(r"\s*(\d+)", text)
    if m is None:
        raise ValueError(f"no integer in {text!r}")
    return int(m.group(1))


def parse_slab_links(text: str) -> dict[str, str]:
    """Lines "name -> target" (a listing of the links in /sys/kernel/slab)."""
    out = {}
    for line in text.splitlines():
        if " -> " in line:
            name, target = line.split(" -> ", 1)
            out[name.strip()] = os.path.basename(target.strip())
    return out


@dataclass
class SsSocket:
    local: str
    peer: str
    skmem: dict[str, int]


def parse_ss_tm(text: str) -> list[SsSocket]:
    """`ss -tmn state established ...`: a socket line (Recv-Q Send-Q Local Peer), then its
    indented skmem:(r..,rb..,t..,tb..,f..,w..,o..,bl..,d..) line."""
    out: list[SsSocket] = []
    cur: tuple[str, str] | None = None
    for line in text.splitlines():
        if not line.strip() or line.startswith("Recv-Q") or line.startswith("State"):
            continue
        m = re.search(r"skmem:\(([^)]*)\)", line)
        if m is not None:
            if cur is None:
                raise ValueError("skmem line before a socket line")
            fields = {}
            for item in m.group(1).split(","):
                k = re.match(r"([a-z]+)(\d+)", item)
                if k is None:
                    raise ValueError(f"skmem field not understood: {item!r}")
                fields[k.group(1)] = int(k.group(2))
            out.append(SsSocket(cur[0], cur[1], fields))
            cur = None
            continue
        parts = line.split()
        if len(parts) < 4:
            raise ValueError(f"ss line not understood: {line!r}")
        cur = (parts[2], parts[3])
    if cur is not None:
        raise ValueError("a socket line without its skmem line")
    return out


def local_port(addr: str) -> int:
    return int(addr.rsplit(":", 1)[1])


# ---------------------------------------------------------------- one reading


@dataclass
class Reading:
    """One sample of WL7 (or the baseline). Sizes in bytes unless named in kB."""
    t_ns: int
    rss_kb: dict[int, int]            # VmRSS per process of the system
    slab_kb: int                      # Slab of /proc/meminfo
    caches: dict[str, int]            # the skb caches' sizes, by the name WL7 gives them
    fclone_target: str                # the directory skbuff_fclone_cache links to
    fclone_cotenants: list[str]       # every name linked to that directory
    fclone_listed_as: str             # the /proc/slabinfo name the shared cache carries
    fclone_slabs: int                 # /sys/kernel/slab/<target>/slabs
    fclone_objects: int               # /sys/kernel/slab/<target>/objects
    sockets: list[SsSocket]           # the system's established accepted sockets
    time_wait: int                    # the host's TIME-WAIT count
    problems: list[str] = field(default_factory=list)  # a cache that could not be found or read

    @property
    def rss_total_kb(self) -> int:
        return sum(self.rss_kb.values())

    @property
    def skb_bytes(self) -> int:
        return sum(self.caches.values())


def skb_caches_from(slab: dict[str, dict[str, int]], links: dict[str, str], page_size: int,
                    fclone_attrs: dict[str, str]) -> tuple[dict[str, int], str, list[str], str, int, int, list[str]]:
    """The skb caches of WL7 from parsed /proc/slabinfo, the /sys/kernel/slab links, and the
    merged cache's attribute files. Returns (sizes by WL7's name, target, co-tenants, listed
    name, slabs, objects, problems)."""
    problems: list[str] = []
    sizes: dict[str, int] = {}
    for name in ("skbuff_head_cache", "skbuff_small_head"):
        if name in slab:
            sizes[name] = cache_bytes(slab[name], page_size)
        else:
            problems.append(f"{name} not in /proc/slabinfo")
    target = links.get("skbuff_fclone_cache", "")
    cotenants = sorted(n for n, t in links.items() if t == target) if target else []
    listed = ""
    if not target:
        if "skbuff_fclone_cache" in slab:  # not merged: its own line
            sizes["skbuff_fclone_cache"] = cache_bytes(slab["skbuff_fclone_cache"], page_size)
            listed = "skbuff_fclone_cache"
        else:
            problems.append("skbuff_fclone_cache: no link and no slabinfo line")
    else:
        present = [n for n in cotenants if n in slab]
        if len(present) != 1:
            problems.append(f"skbuff_fclone_cache: {len(present)} of its co-tenants {cotenants} in /proc/slabinfo")
        else:
            listed = present[0]
            sizes["skbuff_fclone_cache"] = cache_bytes(slab[listed], page_size)
    try:
        slabs = parse_first_int(fclone_attrs.get("slabs", ""))
        objects = parse_first_int(fclone_attrs.get("objects", ""))
    except ValueError:
        slabs = objects = -1
        problems.append("the shared cache's slabs or objects unreadable")
    return sizes, target, cotenants, listed, slabs, objects, problems


# ---------------------------------------------------------------- the footprint


@dataclass
class Footprint:
    n: int
    U: float          # bytes per pending connection
    Kq: float
    Ks: float
    W: float
    f_mean: float     # the `f` field, reported, not added
    slab_growth: int  # bytes
    skb_growth: int   # bytes, the three caches
    shared_growth: int  # bytes, the merged cache's shared cache
    established: int


def footprint(base: Reading, s: Reading, n_pend: int) -> Footprint:
    rss_growth = (s.rss_total_kb - base.rss_total_kb) * 1024
    slab_growth = (s.slab_kb - base.slab_kb) * 1024
    skb_growth = s.skb_bytes - base.skb_bytes
    shared = s.caches.get("skbuff_fclone_cache", 0) - base.caches.get("skbuff_fclone_cache", 0)
    kq = sum(x.skmem.get("r", 0) for x in s.sockets) / len(s.sockets) if s.sockets else 0.0
    f = sum(x.skmem.get("f", 0) for x in s.sockets) / len(s.sockets) if s.sockets else 0.0
    U = rss_growth / n_pend
    Ks = (slab_growth - skb_growth) / n_pend
    return Footprint(n=n_pend, U=U, Kq=kq, Ks=Ks, W=U + kq + Ks, f_mean=f, slab_growth=slab_growth,
                     skb_growth=skb_growth, shared_growth=shared, established=len(s.sockets))


def window_problems(base: Reading, s1: Reading, s2: Reading, n_pend: int) -> list[str]:
    """Section 7's reasons a B3 or ophold window is invalid, from its three readings."""
    out: list[str] = []
    f1, f2 = footprint(base, s1, n_pend), footprint(base, s2, n_pend)
    tol = max(SETTLE_REL * abs(f2.W), SETTLE_ABS)
    if abs(f2.W - f1.W) > tol:
        out.append(f"not settled: W {f1.W:.1f} then {f2.W:.1f} bytes per pending connection (tolerance {tol:.1f})")
    for name, r in (("sample 1", s1), ("sample 2", s2)):
        if r.time_wait != base.time_wait:
            out.append(f"TIME-WAIT count {r.time_wait} at {name}, {base.time_wait} at the baseline")
        if len(r.sockets) < n_pend:
            out.append(f"{len(r.sockets)} accepted sockets established at {name}, fewer than {n_pend}")
    for name, r in (("baseline", base), ("sample 1", s1), ("sample 2", s2)):
        for p in r.problems:
            out.append(f"{name}: {p}")
        if sorted(r.fclone_cotenants) != sorted(base.fclone_cotenants):
            out.append(f"{name}: the shared cache's co-tenants {r.fclone_cotenants} differ from the baseline's {base.fclone_cotenants}")
    return out


# ---------------------------------------------------------------- readers (L)


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def read_slab_links(root: Path = Path("/sys/kernel/slab")) -> dict[str, str]:
    out = {}
    for e in root.iterdir():
        if e.is_symlink():
            out[e.name] = os.path.basename(os.readlink(e))
    return out


def read(pids: list[int], port: int) -> Reading:
    """One reading on this host: VmRSS of `pids`, Slab, the skb caches (sudo), the system's
    established sockets on `port`, and the host's TIME-WAIT count."""
    import time
    t = time.monotonic_ns()
    rss = {p: parse_kb_field(Path(f"/proc/{p}/status").read_text(), "VmRSS") for p in pids}
    slab_kb = parse_kb_field(Path("/proc/meminfo").read_text(), "Slab")
    page = os.sysconf("SC_PAGE_SIZE")
    problems: list[str] = []
    try:
        slab = parse_slabinfo(_run(["sudo", "-n", "cat", "/proc/slabinfo"]))
    except (subprocess.CalledProcessError, ValueError) as e:
        slab = {}
        problems.append(f"/proc/slabinfo unreadable: {e}")
    links = read_slab_links()
    attrs = {}
    target = links.get("skbuff_fclone_cache")
    if target:
        for name in ("slabs", "objects"):
            try:
                attrs[name] = _run(["sudo", "-n", "cat", f"/sys/kernel/slab/{target}/{name}"])
            except subprocess.CalledProcessError:
                pass
    sizes, target, cot, listed, slabs, objects, more = skb_caches_from(slab, links, page, attrs)
    problems += more
    socks = [x for x in parse_ss_tm(_run(["ss", "-tmn", "state", "established", f"( sport = :{port} )"]))
             if local_port(x.local) == port]
    tw = len([ln for ln in _run(["ss", "-Htan", "state", "time-wait"]).splitlines() if ln.strip()])
    return Reading(t_ns=t, rss_kb=rss, slab_kb=slab_kb, caches=sizes, fclone_target=target or "",
                   fclone_cotenants=cot, fclone_listed_as=listed, fclone_slabs=slabs, fclone_objects=objects,
                   sockets=socks, time_wait=tw, problems=problems)


def reading_dict(r: Reading) -> dict:
    """A reading for the window's row, without the per-socket list (its count and sums kept)."""
    return {
        "t_ns": r.t_ns, "rss_kb": {str(k): v for k, v in r.rss_kb.items()}, "slab_kb": r.slab_kb,
        "caches": r.caches, "fclone_target": r.fclone_target, "fclone_cotenants": r.fclone_cotenants,
        "fclone_listed_as": r.fclone_listed_as, "fclone_slabs": r.fclone_slabs, "fclone_objects": r.fclone_objects,
        "established": len(r.sockets), "r_sum": sum(x.skmem.get("r", 0) for x in r.sockets),
        "f_sum": sum(x.skmem.get("f", 0) for x in r.sockets), "time_wait": r.time_wait, "problems": r.problems,
    }
