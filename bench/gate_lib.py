"""The rules of the sanitizer records gate (hypotheses.md, section 11; design/proposal.md, Z4).

Copied from paper-typed-routing bench/gate_lib.py at commit 7c1e248, same author, with the
paths and names of this repository. What changed: the gate takes the host (L or W) and the
sanitizers each host needs; the check of a second, header-only dependency is gone, since oneport
has none.

Records are matched by what they compiled, not by commit (the Papers repo's rule D5):
- target_coverage: for every target of a build and every sanitizer the host needs (L: ASan+UBSan,
  TSan, MSan; W: ASan), a green record of the given name pattern, made on the same host, compiled
  the same first-party inputs for that target, with the same compiler and the same configuration
  (the code-selecting options of lab/bin/inputs_hash.py's project mode). A gap is allowed only
  where `declared` names it for that target, with its reason. A red record that compiled the
  same inputs stops the gate. A record counts only if it was also made with the build's pins:
  the same sha256 of bench/cmake/pins.cmake (pins_sha256, CRLF read as LF) and, for every archive
  both fetched, the same URL and hash as used (third_party.fetched of lab/bin/inputs_hash.py). A
  build whose pins differ from its records' is therefore refused; the error names the records
  left out for that.
Every failure raises GateError with the reason.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# The sanitizers each host's records must cover (hypotheses.md, section 11).
SANITIZERS_BY_HOST = {"L": ("asan", "tsan", "msan"), "W": ("asan",)}


class GateError(Exception):
    pass


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def config_of(info: dict):
    """The build's configuration field of an inputs.json build: "config" (project mode) or
    "<name>_config" (default mode)."""
    for k, v in info.items():
        if k == "config" or k.endswith("_config"):
            return v
    return None


def file_sha256(path: Path) -> str:
    """The sha256 of a text file with CRLF read as LF (as lab/bin/inputs_hash.py reads inputs)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def fetched_of(info: dict) -> dict:
    """The archives a build fetched, as used: {name: {url, url_hash, ...}} (inputs_hash.py)."""
    return (info.get("third_party") or {}).get("fetched") or {}


def pins_differ(r: dict, pins: str, fetched: dict) -> str:
    """Why record R was made with other pins than the build's, or "" if it was not."""
    if r.get("pins_sha256") != pins:
        return f"pins.cmake {str(r.get('pins_sha256') or 'not recorded')[:12]}, the build's {pins[:12]}"
    theirs = fetched_of(r)
    for name in sorted(set(theirs) & set(fetched)):
        if theirs[name] != fetched[name]:
            return f"fetched {name} as {theirs[name]}, the build as {fetched[name]}"
    return ""


def sanitizers_for(host: str) -> tuple[str, ...]:
    if host not in SANITIZERS_BY_HOST:
        raise GateError(f"unknown host {host!r}; the hosts are {', '.join(SANITIZERS_BY_HOST)}")
    return SANITIZERS_BY_HOST[host]


def host_records(records: Path, pattern: str, host: str) -> list[Path]:
    """The records of a name pattern made on HOST (the host part of the name, as in
    oneport-<commit>-L-asan.json)."""
    return [f for f in sorted(records.glob(pattern)) if f"-{host}-" in f.name]


def target_coverage(records: Path, pattern: str, hashes: dict, config, compiler: str,
                    declared: dict | None = None, *, host: str, pins: str,
                    fetched: dict) -> tuple[dict, dict, list[str]]:
    sanitizers = sanitizers_for(host)
    declared = declared or {}
    coverage: dict = {t: {} for t in hashes}
    used: set = set()
    other_pins: list[str] = []
    for f in host_records(records, pattern, host):
        r = load(f)
        san = r.get("sanitizer")
        if san not in sanitizers:
            continue
        theirs = r.get("inputs_hash") or {}
        same = [t for t, h in hashes.items() if theirs.get(t) == h]
        if not same:
            continue
        if r.get("green") is not True:
            raise GateError(f"{f.name} compiled the same inputs for {', '.join(same)} and is red")
        if r.get("compiler") != compiler or config_of(r) != config:
            continue
        why = pins_differ(r, pins, fetched)
        if why:
            other_pins.append(f"{f.name} ({why})")
            continue
        for t in same:
            coverage[t].setdefault(san, []).append(f.name)
            used.add(f.name)
    partial = {}
    for t, by_san in coverage.items():
        missing = [s for s in sanitizers if s not in by_san]
        allowed = (declared.get(t) or {}).get("not_covered_by", [])
        if any(s not in allowed for s in missing):
            raise GateError(f"{t} (inputs {hashes[t][:12]}) has no green "
                            f"{', '.join(s for s in missing if s not in allowed)} record on {host} with compiler "
                            f"{compiler}, its configuration and pins {pins[:12]}, and no declared gap"
                            + (f"; left out for other pins: {'; '.join(other_pins)}" if other_pins else ""))
        if missing:
            partial[t] = {"covered_by": [s for s in sanitizers if s in by_san], "reason": declared[t]["reason"]}
        print(f"covered: {t} {hashes[t][:12]} by " + "; ".join(f"{s} {', '.join(n)}" for s, n in by_san.items()),
              file=sys.stderr)
    return coverage, partial, sorted(used)
