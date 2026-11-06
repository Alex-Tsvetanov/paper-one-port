#!/usr/bin/env python3
"""The entry point of P3's quick-benchmark jobs for Papers lab/bin/labrun.py (quick-plan.md). labrun deploys one commit of
this repository to the laptop's src/one-port and runs a job's build command in that clone and its run command inside its
wrappers (the lab lock, AC power, the quiet check, the clock floor, THP and NOTRACK on L, the lab power plan on W).

    lab_p3.py prepare --commit C --home DIR      (the build phase)
    lab_p3.py quick   --commit C --home DIR --plan NAME --seed N      (the run phase)

DIR, the home, is a fixed folder of the quick runs on the laptop (~/lab/p3/quick-L, C:\\Users\\alext\\lab\\p3\\quick-W), never
inside a job's folder and never the frozen runs' folders. It holds build-<C12>, the Release build of the commit, its log
and build-<C12>.prepare.json, and the quick runs' source-block file. Nothing else of the laptop's state is written.

prepare makes the Release build of this clone at C: on L CMake with Ninja and clang (CMAKE_BUILD_TYPE=Release, no
sanitizer, the root CMakeLists.txt's flag line, -O3), on W vcvarsall x64 (LAB_VCVARS, else vswhere), CMake with Ninja and cl
(MSVC, /O2). It needs the pinned OpenSSL and nghttp2 the build finds (L: ~/opt, W: %USERPROFILE%\\opt, made by
bench/third_party/build_deps.sh and wdeps.py for the frozen runs). A build that passed for the same commit and source
folder is reused, so the 11 jobs of one OS at one commit build once. It runs no test: the quick results are not gated
by the records (quick-plan.md). prepare exits 0 only if the build passed and is a Release build.

quick runs one plan of bench/run/plans/quick/ (NAME, with or without .json) whose host is this machine's: it computes the
plan's sha256 and runs quick_run.py with the build, the seed and --out LAB_OUT/<stem>. On L the command is l_quick.sh; on
W it is wjob.py run (the W lab lock, the lab plan, the quiet check) around quick_run.py. LAB_OUT/run.json records the
command, its exit status, the plan, its sha256 and the seed.

Refused (exit 2): a commit that is not the clone's HEAD; a clone with tracked changes; a home inside the job's folder; a plan
that is no file of plans/quick/ or whose host is the other; a run before a passing prepare; a seed that is not an integer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))   # bench/build_inputs.py

import quick_guard  # noqa: E402

REFUSED = 2
W_TOOLS = Path(r"C:\lab\src\Papers\lab\bin")   # gap84's W jobs pass this as --tools
W_NINJA = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja")
BUILD_TAIL = 40


class Refused(Exception):
    pass


def host_here() -> str:
    return "W" if sys.platform == "win32" else "L"


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise Refused(f"git {' '.join(args)}: {r.stderr.strip()[-200:]}")
    return r.stdout.strip()


def check_clone(commit: str) -> str:
    """The clone is at `commit` with no tracked change. Returns the 12-digit short commit."""
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise Refused(f"--commit {commit!r} is not a full 40-character commit")
    head = git("rev-parse", "HEAD")
    if head != commit:
        raise Refused(f"the clone is at {head}, not at {commit}")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise Refused(f"the clone {REPO} has tracked changes")
    return commit[:12]


def check_home(home: Path, env: dict) -> Path:
    home = Path(home).resolve()
    job = env.get("LAB_JOB")
    if job and (home == Path(job).resolve() or Path(job).resolve() in home.parents):
        raise Refused(f"the home {home} is inside the job's folder")
    return home


def marker_path(home: Path, c12: str) -> Path:
    return home / f"build-{c12}.prepare.json"


# ---------------------------------------------------------------- prepare


def build_commands(host: str, build: Path, env: dict) -> list[list[str]] | Path:
    """L: the argv lists to run. W: a .cmd file to run with cmd.exe (vcvars, then CMake and Ninja)."""
    jobs = str(int(env.get("JOBS", "8")))
    if host == "L":
        return [["cmake", "-S", str(REPO), "-B", str(build), "-G", "Ninja", "-DCMAKE_CXX_COMPILER=clang++", "-DCMAKE_BUILD_TYPE=Release"],
                ["ninja", "-C", str(build), "-j", jobs]]
    vcvars = env.get("LAB_VCVARS")
    if not vcvars:
        vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        base = subprocess.run([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"], capture_output=True, text=True).stdout.strip()
        vcvars = str(Path(base) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat")
    if not Path(vcvars).exists():
        raise Refused(f"vcvarsall.bat not found at {vcvars} (LAB_VCVARS)")
    extra = [str(Path(env[k]).parent if Path(env[k]).is_file() else env[k]) for k in ("LAB_CMAKE", "LAB_NINJA") if env.get(k)]
    if W_NINJA.exists():
        extra.append(str(W_NINJA))
    path = ";".join(extra)
    cmd = build.parent / f"build-{build.name.split('-', 1)[1]}.cmd"
    lines = ["@echo off", f'call "{vcvars}" x64 >nul || exit /b 1']
    if path:
        lines.append(f'set "PATH={path};%PATH%"')
    lines += [f'cmake -S "{REPO}" -B "{build}" -G Ninja -DCMAKE_CXX_COMPILER=cl -DCMAKE_BUILD_TYPE=Release || exit /b 2',
              f'ninja -C "{build}" || exit /b 3', "exit /b 0"]
    cmd.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    return cmd


def prepare(commit: str, home: Path, env: dict, runner=subprocess.run) -> int:
    c12 = check_clone(commit)
    home = check_home(home, env)
    host = host_here()
    home.mkdir(parents=True, exist_ok=True)
    build = home / f"build-{c12}"
    marker = marker_path(home, c12)
    if marker.exists():
        old = json.loads(marker.read_text(encoding="utf-8"))
        if old.get("ok") and old.get("commit") == commit and old.get("source_dir") == str(REPO):
            quick_guard.check_release(build)
            print(f"prepare: the build {build} passed before; reused")
            record(env, {"prepare": old, "reused": True})
            return 0
    if build.exists():
        shutil.rmtree(build)   # this tool's own tree of an earlier attempt that did not pass
    marker.unlink(missing_ok=True)
    log = home / f"build-{c12}.log"
    steps = []
    plan = build_commands(host, build, env)
    argvs = plan if host == "L" else [["cmd.exe", "/c", str(plan)]]
    ok = True
    with open(log, "wb") as lf:
        for argv in argvs:
            t0 = time.time()
            r = runner(argv, stdout=lf, stderr=subprocess.STDOUT)
            steps.append({"argv": argv, "exit": r.returncode, "seconds": round(time.time() - t0, 1)})
            if r.returncode != 0:
                ok = False
                break
    info = {"ok": False, "commit": commit, "source_dir": str(REPO), "build": str(build), "host": host, "steps": steps, "log": str(log)}
    if ok:
        info["release"] = quick_guard.check_release(build)
        import build_inputs  # noqa: PLC0415
        missing = [n for n, rel in build_inputs.BINARIES[host].items() if n in ("oneport", "opgen", "opcase") and not (build / rel).exists()]
        if missing:
            info["missing_binaries"] = missing
            ok = False
    info["ok"] = ok
    marker.write_text(json.dumps(info, indent=1), encoding="utf-8")
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-BUILD_TAIL:]
    print("\n".join(tail))
    print(f"prepare: {'ok' if ok else 'FAILED'}; {marker}")
    record(env, {"prepare": info})
    return 0 if ok else 1


def record(env: dict, data: dict, name: str = "prepare.json") -> None:
    out = env.get("LAB_OUT")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / name).write_text(json.dumps(data, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- quick


def plan_file(name: str) -> tuple[Path, str]:
    stem = name[:-5] if name.endswith(".json") else name
    if not stem or "/" in stem or "\\" in stem or stem.startswith("."):
        raise Refused(f"--plan {name!r} is not a file name of bench/run/plans/quick/")
    p = quick_guard.QUICK_DIR / f"{stem}.json"
    if not p.is_file():
        raise Refused(f"--plan {name!r}: no such file in bench/run/plans/quick/")
    return p, stem


def quick_command(host: str, home: Path, build: Path, path: Path, out: Path, sha: str, seed: int, job_name: str) -> list[str]:
    run = HERE / "quick_run.py"
    if host == "L":
        return ["bash", str(HERE / "l_quick.sh"), str(home), str(path), str(out), sha, str(build), str(seed)]
    inner = [sys.executable, str(run), "--plan", str(path), "--build", str(build), "--out", str(out), "--quick", sha, "--seed", str(seed),
             "--blocks", str(home / "src-blocks-w.json")]
    if W_TOOLS.exists():
        inner += ["--tools", str(W_TOOLS)]
    return [sys.executable, str(HERE / "wjob.py"), "run", "--dir", str(out.parent / "wjob"), "--name", job_name, "--"] + inner


def quick(commit: str, home: Path, name: str, seed: int, env: dict, runner=subprocess.run) -> int:
    c12 = check_clone(commit)
    home = check_home(home, env)
    host = host_here()
    path, stem = plan_file(name)
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["host"] != host:
        raise Refused(f"the plan {stem} is for host {plan['host']}, this machine is {host}")
    marker = marker_path(home, c12)
    if not marker.exists() or not json.loads(marker.read_text(encoding="utf-8")).get("ok"):
        raise Refused(f"no passing prepare for {c12} in {home} (run lab_p3.py prepare first)")
    build = home / f"build-{c12}"
    lab_out = env.get("LAB_OUT")
    if not lab_out:
        raise Refused("the job's environment lacks LAB_OUT (labrun's wrappers set it)")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    out = Path(lab_out) / stem
    if out.exists() and any(out.iterdir()):
        raise Refused(f"{out} holds files: a quick run writes into a folder that holds none")
    out.mkdir(parents=True, exist_ok=True)
    cmd = quick_command(host, home, build, path, out, sha, seed, f"p3q-{stem.lower()}")
    t0 = time.time()
    r = runner(cmd)
    rec = {"command": cmd, "exit": r.returncode, "plan": stem, "plan_sha256": sha, "seed": seed, "commit": commit, "host": host,
           "seconds": round(time.time() - t0, 1), "expected_worst_case_s": plan["expected_worst_case_s"]}
    record(env, rec, "run.json")
    return r.returncode


def main(argv=None, env: dict | None = None, runner=subprocess.run) -> int:
    env = dict(os.environ if env is None else env)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--commit", required=True)
    p.add_argument("--home", type=Path, required=True)
    q = sub.add_parser("quick")
    q.add_argument("--commit", required=True)
    q.add_argument("--home", type=Path, required=True)
    q.add_argument("--plan", required=True)
    q.add_argument("--seed", type=int, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "prepare":
            return prepare(a.commit, a.home, env, runner)
        return quick(a.commit, a.home, a.plan, a.seed, env, runner)
    except (Refused, quick_guard.QuickRefused) as e:
        print(f"lab_p3: refused: {e}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
