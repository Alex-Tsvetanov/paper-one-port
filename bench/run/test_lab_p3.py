#!/usr/bin/env python3
"""Tests of lab_p3.py, the quick jobs' entry point (quick-plan.md): the checks before a build or a run, the commands it
builds for L and for W, and the records it writes. Pure: the commands are not run.

    python3 bench/run/test_lab_p3.py          (exit 0 when every check passes)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import lab_p3 as LP  # noqa: E402
import quick_guard  # noqa: E402

COMMIT = "51fa55f073fa075f49f43a72e2d3518cc3509936"
C12 = COMMIT[:12]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p3lab-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.out = self.tmp / "job" / "out"
        self.env = {"LAB_OUT": str(self.out), "LAB_JOB": str(self.tmp / "job")}
        self.calls = []
        self.rc = 0

    def runner(self, argv, **kw):
        self.calls.append(argv)
        return SimpleNamespace(returncode=self.rc)

    def clone_ok(self):
        return mock.patch.object(LP, "check_clone", lambda c: c[:12])

    def host(self, h):
        return mock.patch.object(LP, "host_here", lambda: h)

    def mark(self, ok=True):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / f"build-{C12}.prepare.json").write_text(json.dumps({"ok": ok, "commit": COMMIT, "source_dir": str(LP.REPO)}))


class TestChecks(Base):
    def test_commit_must_be_full_and_the_clones_head(self):
        for bad in ("abc", COMMIT[:12], "g" * 40):
            with self.assertRaises(LP.Refused):
                LP.check_clone(bad)
        with mock.patch.object(LP, "git", lambda *a: "f" * 40), self.assertRaises(LP.Refused):
            LP.check_clone(COMMIT)

    def test_tracked_changes_are_refused(self):
        def fake_git(*a):
            return COMMIT if a[0] == "rev-parse" else " M bench/run/x.py"
        with mock.patch.object(LP, "git", fake_git), self.assertRaises(LP.Refused):
            LP.check_clone(COMMIT)

    def test_a_clean_clone_at_the_commit_passes(self):
        def fake_git(*a):
            return COMMIT if a[0] == "rev-parse" else ""
        with mock.patch.object(LP, "git", fake_git):
            self.assertEqual(LP.check_clone(COMMIT), C12)

    def test_the_home_may_not_be_inside_the_jobs_folder(self):
        with self.assertRaises(LP.Refused):
            LP.check_home(self.tmp / "job" / "out" / "home", self.env)
        LP.check_home(self.home, self.env)

    def test_plan_names(self):
        for bad in ("../x", "a/b", "", "..", "quick-L-nothing", "quick\\x"):
            with self.assertRaises(LP.Refused, msg=bad):
                LP.plan_file(bad)
        self.assertEqual(LP.plan_file("quick-L-aa")[1], "quick-L-aa")
        self.assertEqual(LP.plan_file("quick-L-aa.json")[1], "quick-L-aa")


class TestQuick(Base):
    def go(self, host, name, seed=77):
        with self.clone_ok(), self.host(host):
            return LP.quick(COMMIT, self.home, name, seed, self.env, self.runner)

    def test_a_run_before_prepare_is_refused(self):
        with self.assertRaises(LP.Refused):
            self.go("L", "quick-L-aa")
        self.mark(ok=False)
        with self.assertRaises(LP.Refused):
            self.go("L", "quick-L-aa")

    def test_the_other_hosts_plan_is_refused(self):
        self.mark()
        with self.assertRaises(LP.Refused):
            self.go("L", "quick-W-aa")
        with self.assertRaises(LP.Refused):
            self.go("W", "quick-L-aa")

    def test_l_command_and_record(self):
        self.mark()
        self.assertEqual(self.go("L", "quick-L-epoll-c1-tls"), 0)
        (cmd,) = self.calls
        path = quick_guard.QUICK_DIR / "quick-L-epoll-c1-tls.json"
        sha = quick_guard.sha256_file(path)
        self.assertEqual(cmd[0], "bash")
        self.assertTrue(cmd[1].endswith("l_quick.sh"))
        self.assertEqual(cmd[2:], [str(self.home), str(path), str(self.out / "quick-L-epoll-c1-tls"), sha, str(self.home / f"build-{C12}"), "77"])
        rec = json.loads((self.out / "run.json").read_text())
        self.assertEqual((rec["exit"], rec["plan"], rec["plan_sha256"], rec["seed"], rec["commit"]), (0, "quick-L-epoll-c1-tls", sha, 77, COMMIT))

    def test_w_command_runs_inside_wjob(self):
        self.mark()
        self.assertEqual(self.go("W", "quick-W-iocp-c2-http1"), 0)
        (cmd,) = self.calls
        self.assertTrue(cmd[1].endswith("wjob.py"))
        self.assertEqual(cmd[2], "run")
        self.assertIn("--", cmd)
        inner = cmd[cmd.index("--") + 1:]
        self.assertTrue(inner[1].endswith("quick_run.py"))
        for flag in ("--plan", "--build", "--out", "--quick", "--seed", "--blocks"):
            self.assertIn(flag, inner)
        self.assertEqual(inner[inner.index("--blocks") + 1], str(self.home / "src-blocks-w.json"))
        self.assertEqual(cmd[cmd.index("--name") + 1], "p3q-quick-w-iocp-c2-http1")

    def test_the_exit_status_is_passed_on(self):
        self.mark()
        self.rc = 3
        self.assertEqual(self.go("L", "quick-L-aa"), 3)
        self.assertEqual(json.loads((self.out / "run.json").read_text())["exit"], 3)

    def test_a_used_output_folder_is_refused(self):
        self.mark()
        d = self.out / "quick-L-aa"
        d.mkdir(parents=True)
        (d / "windows.jsonl").write_text("{}\n")
        with self.assertRaises(LP.Refused):
            self.go("L", "quick-L-aa")

    def test_main_returns_2_on_a_refusal(self):
        with mock.patch.object(LP, "check_clone", side_effect=LP.Refused("x")):
            self.assertEqual(LP.main(["quick", "--commit", COMMIT, "--home", str(self.home), "--plan", "quick-L-aa", "--seed", "1"], self.env), 2)
        with self.assertRaises(SystemExit):
            LP.main(["quick", "--commit", COMMIT, "--home", str(self.home), "--plan", "quick-L-aa", "--seed", "x"], self.env)


class TestPrepare(Base):
    def make_release(self, build, kind="Release"):
        build.mkdir(parents=True, exist_ok=True)
        (build / "CMakeCache.txt").write_text(f"CMAKE_BUILD_TYPE:STRING={kind}\nONEPORT_SANITIZER:STRING=\n")

    def test_l_builds_release_with_clang_and_ninja_and_marks_it(self):
        build = self.home / f"build-{C12}"

        def runner(argv, **kw):
            self.calls.append(argv)
            if argv[0] == "cmake":
                self.make_release(build)
            return SimpleNamespace(returncode=0)
        with self.clone_ok(), self.host("L"), mock.patch("build_inputs.BINARIES", {"L": {}}):
            self.assertEqual(LP.prepare(COMMIT, self.home, self.env, runner), 0)
        cmake, ninja = self.calls
        self.assertIn("-DCMAKE_BUILD_TYPE=Release", cmake)
        self.assertIn("-DCMAKE_CXX_COMPILER=clang++", cmake)
        self.assertEqual(ninja[0], "ninja")
        self.assertTrue(json.loads((self.home / f"build-{C12}.prepare.json").read_text())["ok"])
        # a second prepare at the same commit reuses the build
        self.calls.clear()
        with self.clone_ok(), self.host("L"):
            self.assertEqual(LP.prepare(COMMIT, self.home, self.env, runner), 0)
        self.assertEqual(self.calls, [])

    def test_a_failed_build_is_marked_not_ok_and_exits_1(self):
        def runner(argv, **kw):
            self.calls.append(argv)
            return SimpleNamespace(returncode=1)
        with self.clone_ok(), self.host("L"):
            self.assertEqual(LP.prepare(COMMIT, self.home, self.env, runner), 1)
        self.assertFalse(json.loads((self.home / f"build-{C12}.prepare.json").read_text())["ok"])
        self.assertEqual(len(self.calls), 1)   # ninja did not run after a failed configure

    def test_a_debug_build_is_refused_by_prepare(self):
        build = self.home / f"build-{C12}"

        def runner(argv, **kw):
            self.make_release(build, "Debug")
            return SimpleNamespace(returncode=0)
        with self.clone_ok(), self.host("L"), self.assertRaises(quick_guard.QuickRefused):
            LP.prepare(COMMIT, self.home, self.env, runner)

    def test_w_build_script_uses_vcvars_cmake_ninja_and_cl_in_release(self):
        vc = self.tmp / "vcvarsall.bat"
        vc.write_text("@echo off\n")
        env = dict(self.env, LAB_VCVARS=str(vc))
        build = self.home / f"build-{C12}"
        self.home.mkdir(parents=True)
        cmd = LP.build_commands("W", build, env)
        text = cmd.read_text(encoding="ascii")
        self.assertIn(f'call "{vc}" x64', text)
        self.assertIn("-G Ninja", text)
        self.assertIn("-DCMAKE_CXX_COMPILER=cl", text)
        self.assertIn("-DCMAKE_BUILD_TYPE=Release", text)
        self.assertIn("ninja -C", text)
        self.assertEqual(cmd.name, f"build-{C12}.cmd")
        v64 = self.tmp / "vcvars64.bat"
        v64.write_text("@echo off")
        text = LP.build_commands("W", build, dict(self.env, LAB_VCVARS=str(v64))).read_text(encoding="ascii")
        self.assertIn(f'call "{v64}" >nul', text)
        with self.assertRaises(LP.Refused):
            LP.build_commands("W", build, dict(self.env, LAB_VCVARS=str(self.tmp / "none.bat")))


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=1)
    print(f"{r.result.testsRun} checks, {len(r.result.failures)} failures, {len(r.result.errors)} errors")
    sys.exit(0 if r.result.wasSuccessful() else 1)
