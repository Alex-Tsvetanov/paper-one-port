#!/usr/bin/env python3
"""OpenSSL and nghttp2 for oneport on the laptop's Windows (W since 2026-10-23), built by
bench/third_party/build_deps.ps1 as frozen, with only the line that names the compiler changed.

build_deps.ps1 stops unless `cl` is 19.51.36246 (its `$wantCl`), the desktop's compiler, which
"Words" and section 11 name for W. The laptop's is 19.51.36248. The script is a frozen path, so this
wrapper never edits it. It checks that the clone's build_deps.ps1 and bench/cmake/pins.cmake are
CODE_FREEZE's (their git blobs), copies both into WORK in the script's relative layout
(WORK/third_party/build_deps.ps1 reads WORK/cmake/pins.cmake as the script reads ..\\cmake\\pins.cmake),
replaces in the copy the one line `$wantCl = '19.51.36246'` with the given version, and runs the copy
with powershell, the flavours given and the environment passed through (ONEPORT_OPT, ONEPORT_VCVARS,
ONEPORT_LIBS, ONEPORT_PERL_ROOT, ONEPORT_NASM, as build_deps.ps1 reads them). Everything else is the
frozen script's: the URLs and sha256 pins, the options and flags, the install prefixes. If the
version given is the frozen one, the copy equals the script.

WORK/wdeps.json records CODE_FREEZE, the blobs, the sha256 of the frozen script, of its copy and of
pins.cmake, the line before and after, the command and its exit status, and then, for each library
and flavour the run built, the sha256 of every file under its install prefix
(ONEPORT_OPT\\<lib>-<version>-<flavour>, the names build_deps.ps1 installs into and CMakeLists.txt
finds) and of its log and done file. WORK must be new or empty.

    wdeps.py --work DIR [--cl 19.51.36248] [--prepare-only] [release|asan ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

CODE_FREEZE = "ff2679cc89d23e08a817308c9aeba7901e056fef"
SCRIPT = "bench/third_party/build_deps.ps1"
PINS = "bench/cmake/pins.cmake"
FROZEN_CL = "19.51.36246"
LAPTOP_CL = "19.51.36248"  # Papers lab/laptop/versions.md: `cl` 19.51.36248 for x64
WANT_LINE = re.compile(r"^\$wantCl = '([0-9.]+)'$", re.M)
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
LIBS = ("nghttp2", "openssl")  # build_deps.ps1's default order
FLAVOURS = ("release", "asan")
PIN_VERSION = {"openssl": "ONEPORT_OPENSSL_VERSION", "nghttp2": "ONEPORT_NGHTTP2_VERSION"}
EXIT_REFUSED = 2


class Refused(Exception):
    pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str, repo: Path = REPO) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise Refused(f"git {' '.join(args)}: {p.stderr.strip()[-300:]}")
    return p.stdout.strip()


def frozen_blob_check(rel: str, repo: Path = REPO) -> dict:
    """The working file `rel` is CODE_FREEZE's: its git blob (with the checkout's filters undone)
    equals the blob at CODE_FREEZE."""
    want = git("rev-parse", f"{CODE_FREEZE}:{rel}", repo=repo)
    got = git("hash-object", rel, repo=repo)
    if got != want:
        raise Refused(f"{rel} is not CODE_FREEZE's (blob {got[:12]}, CODE_FREEZE's {want[:12]})")
    return {"path": rel, "blob": got, "sha256": sha256_file(repo / rel)}


def patch_cl(text: str, cl: str) -> tuple[str, dict]:
    """The script with its one `$wantCl` line naming `cl`; refuses unless that line occurs once and
    names the frozen version."""
    if not VERSION.fullmatch(cl):
        raise Refused(f"{cl!r} is not a compiler version such as {LAPTOP_CL}")
    found = WANT_LINE.findall(text)
    if len(found) != 1 or found[0] != FROZEN_CL:
        raise Refused(f"build_deps.ps1 holds {len(found)} `$wantCl` lines {found}, not one naming {FROZEN_CL}")
    before = f"$wantCl = '{FROZEN_CL}'"
    after = f"$wantCl = '{cl}'"
    new = WANT_LINE.sub(after, text, count=1)
    changed = [(a, b) for a, b in zip(text.split("\n"), new.split("\n")) if a != b]
    if len(text.split("\n")) != len(new.split("\n")) or len(changed) != (0 if cl == FROZEN_CL else 1):
        raise Refused("the copy differs from the script in more than the `$wantCl` line")
    return new, {"before": before, "after": after, "lines_changed": len(changed)}


def pin(pins_text: str, name: str) -> str:
    m = re.search(r'^set\(' + re.escape(name) + r' "([^"]*)"\)$', pins_text, re.M)
    if not m:
        raise Refused(f"no {name} in pins.cmake")
    return m.group(1)


def opt_dir(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env["ONEPORT_OPT"]) if env.get("ONEPORT_OPT") else Path(env.get("USERPROFILE", str(Path.home()))) / "opt"


def libs_of(env=None) -> list[str]:
    env = os.environ if env is None else env
    return env["ONEPORT_LIBS"].split() if env.get("ONEPORT_LIBS") else list(LIBS)


def prepare(work: Path, cl: str, repo: Path = REPO) -> dict:
    """Checks the two frozen files and writes the copy (see the docstring). Returns the record."""
    if work.exists() and any(work.iterdir()):
        raise Refused(f"{work} is not empty")
    rec: dict = {"code_freeze": CODE_FREEZE, "clone_head": git("rev-parse", "HEAD", repo=repo), "cl": cl,
                 "script": frozen_blob_check(SCRIPT, repo), "pins": frozen_blob_check(PINS, repo)}
    raw = (repo / SCRIPT).read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    new, rec["change"] = patch_cl(text, cl)
    out = new.replace("\n", "\r\n") if crlf else new
    (work / "third_party").mkdir(parents=True)
    (work / "cmake").mkdir()
    copy = work / "third_party" / "build_deps.ps1"
    copy.write_bytes(out.encode("utf-8"))
    pins = work / "cmake" / "pins.cmake"
    pins.write_bytes((repo / PINS).read_bytes())
    rec["copy"] = {"path": str(copy), "sha256": sha256_file(copy)}
    rec["pins_copy"] = {"path": str(pins), "sha256": sha256_file(pins)}
    if rec["pins_copy"]["sha256"] != rec["pins"]["sha256"]:
        raise Refused("the copy of pins.cmake differs from the clone's")
    return rec


def prefix_manifest(prefix: Path) -> dict:
    return {str(p.relative_to(prefix)).replace("\\", "/"): sha256_file(p) for p in sorted(prefix.rglob("*")) if p.is_file()}


def built(rec: dict, flavours: list[str], env=None) -> dict:
    """After the run: per library and flavour, its install prefix's files, log and done file."""
    opt = opt_dir(env)
    pins_text = Path(rec["pins_copy"]["path"]).read_text(encoding="utf-8")
    logs = opt / "build" / "logs"
    out = {}
    for f in flavours:
        for lib in libs_of(env):
            prefix = opt / f"{lib}-{pin(pins_text, PIN_VERSION[lib])}-{f}"
            item: dict = {"prefix": str(prefix), "exists": prefix.is_dir()}
            if prefix.is_dir():
                item["files"] = prefix_manifest(prefix)
            for k, p in (("log", logs / f"{lib}-{f}.log"), ("done", logs / f"{lib}-{f}.done")):
                if p.is_file():
                    item[k] = {"path": str(p), "sha256": sha256_file(p)}
            if (logs / f"{lib}-{f}.done").is_file():
                item["exit"] = (logs / f"{lib}-{f}.done").read_text(encoding="utf-8", errors="replace").strip()
            out[f"{lib}-{f}"] = item
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, required=True, help="a new or empty folder for the copy and the record")
    ap.add_argument("--cl", default=LAPTOP_CL, help=f"the compiler version the copy checks (default {LAPTOP_CL}, the laptop's)")
    ap.add_argument("--prepare-only", action="store_true", help="check and copy; do not build")
    ap.add_argument("flavours", nargs="*", default=list(FLAVOURS))
    a = ap.parse_args(argv)
    bad = [f for f in a.flavours if f not in FLAVOURS]
    if bad:
        print(f"wdeps: unknown flavours {bad}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        rec = prepare(a.work, a.cl)
    except Refused as e:
        print(f"wdeps: refused: {e}", file=sys.stderr)
        return EXIT_REFUSED
    record = a.work / "wdeps.json"
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", rec["copy"]["path"], *a.flavours]
    rec.update(command=cmd, flavours=a.flavours, libs=libs_of(), opt=str(opt_dir()),
               env={k: os.environ.get(k) for k in ("ONEPORT_OPT", "ONEPORT_VCVARS", "ONEPORT_LIBS", "ONEPORT_PERL_ROOT", "ONEPORT_NASM")})
    record.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    if a.prepare_only:
        print(f"wdeps: prepared {rec['copy']['path']} ({rec['change']['after']}); not built")
        return 0
    rec["start"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    # Windows PowerShell 5.1 started from PowerShell 7 inherits 7's PSModulePath and then finds no
    # Get-FileHash (the desktop, 2026-10-23); without the variable it uses its own module paths.
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    rc = subprocess.run(cmd, env=env).returncode
    rec.update(end=time.strftime("%Y-%m-%dT%H:%M:%S%z"), exit=rc, built=built(rec, a.flavours))
    record.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(f"wdeps: build_deps copy exit {rc}; record {record}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
