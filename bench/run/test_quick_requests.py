#!/usr/bin/env python3
"""Tests of quick_requests.py: the labrun jobs of P3's quick benchmarks (quick-plan.md). Pure.

    python3 bench/run/test_quick_requests.py          (exit 0 when every check passes)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import quick_plans  # noqa: E402
import quick_requests as QR  # noqa: E402

COMMIT = "51fa55f073fa075f49f43a72e2d3518cc3509936"
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
PAPERS_BIN = Path(os.environ.get("ONEPORT_PAPERS_LAB_BIN", r"D:\Dev\GitHub\Papers\lab\bin"))
REQUIRED = ("id", "paper", "os", "repo", "commit", "run", "expected_s", "timeout_s")


class TestRequests(unittest.TestCase):
    def test_counts_and_stems(self):
        l, w = QR.jobs(COMMIT, "L"), QR.jobs(COMMIT, "W")
        self.assertEqual((len(l), len(w)), (17, 7))
        stems = [QR.stem_of(j) for j in l[:-1] + w[:-1]]
        self.assertEqual(sorted(stems), sorted(quick_plans.build_all()))
        for j in l[:-1]:
            self.assertTrue(QR.stem_of(j).startswith("quick-L-"))
        for j in w[:-1]:
            self.assertTrue(QR.stem_of(j).startswith("quick-W-"))
        for jobs_, h in ((l, "l"), (w, "w")):   # the last job of each OS is the cleanup (rule 9)
            c = jobs_[-1]
            self.assertEqual(c["id"], f"p3-quick-cleanup-{h}")
            self.assertTrue(ID_RE.fullmatch(c["id"]))
            self.assertEqual((c["paper"], c["build"]), ("P3", ""))
            self.assertIn(f"lab_p3.py cleanup --commit {COMMIT}", c["run"])
            self.assertNotIn("--plan", c["run"])
            self.assertLessEqual(c["expected_s"], 120)

    def test_job_shape(self):
        for host in ("L", "W"):
            for j in QR.jobs(COMMIT, host)[:-1]:
                self.assertTrue(ID_RE.fullmatch(j["id"]), j["id"])
                for k in REQUIRED:
                    self.assertIn(k, j)
                self.assertEqual(j["paper"], "P3")
                self.assertEqual(j["os"], {"L": "linux", "W": "windows"}[host])
                self.assertEqual(j["repo"], {"name": "one-port", "path": "p3-one-port/one-port"})
                self.assertEqual(j["commit"], COMMIT)
                self.assertIs(j["quiet"], True)
                self.assertIs(j["boost"], False)
                self.assertEqual((j["expected_s"], j["poll_s"], j["timeout_s"]), (600, 60, 1800))
                self.assertEqual(j["record_name"], "id")
                self.assertEqual(j["outputs"], ["out", "record.json"])
                self.assertIn(COMMIT[:12], j["run_label"])
                self.assertTrue(j["note"] and j["plain"])
                self.assertIn(f"--commit {COMMIT}", j["build"])
                self.assertIn(f"--commit {COMMIT}", j["run"])
                self.assertIn("lab_p3.py prepare", j["build"])
                self.assertIn("lab_p3.py quick", j["run"])
                if host == "L":
                    self.assertIs(j["uring"], True)
                    self.assertIs(j["cgdeleg"], False)
                    self.assertIn("quick-L", j["run"])
                    self.assertIn("lab/p3/quick-L", j["run"])
                    self.assertIn('ONEPORT_CLOCK_RECORD="$IOCORE_CLOCK_RECORD"', j["run"])
                else:
                    self.assertNotIn("uring", j)
                    self.assertIn(r"C:\Users\alext\lab\p3\quick-W", j["run"])
                    self.assertIn("venv-numpy", j["run"])
                    self.assertIn("PYTHONNOUSERSITE", j["run"])
                    self.assertIn(r"C:\Python314\python.exe", j["run"])

    def test_ids_are_unique_and_lowercase_and_name_the_plan(self):
        ids = [j["id"] for h in ("L", "W") for j in QR.jobs(COMMIT, h)]
        self.assertEqual(len(ids), len(set(ids)))
        for h in ("L", "W"):
            for j in QR.jobs(COMMIT, h)[:-1]:
                self.assertEqual(j["id"], f"p3-{QR.stem_of(j)}".lower())

    def test_the_seed_is_in_the_command_and_is_the_stems_hash(self):
        for j in QR.jobs(COMMIT, "L")[:-1] + QR.jobs(COMMIT, "W")[:-1]:
            stem = QR.stem_of(j)
            self.assertTrue(j["run"].endswith(f"--plan {stem} --seed {QR.seed_of(stem)}"))
        self.assertEqual(len({QR.seed_of(s) for s in quick_plans.build_all()}), 22)

    def test_homes_are_the_quick_homes_and_touch_no_frozen_state(self):
        for j in QR.jobs(COMMIT, "L")[:-1] + QR.jobs(COMMIT, "W")[:-1]:
            text = j["build"] + j["run"]
            for frozen in ("cost-L", "hard-L", "m7g", "rec/build-release", "gate-L", "gate-W", "p3-rec"):
                self.assertNotIn(frozen, text)
            self.assertTrue("lab/p3/quick-L" in text or r"lab\p3\quick-W" in text)

    def test_a_bad_commit_or_os_is_refused(self):
        for bad in ("abc", COMMIT[:12], COMMIT.upper() + "0", "g" * 40):
            with self.assertRaises(ValueError):
                QR.jobs(bad, "L")
        with self.assertRaises(ValueError):
            QR.jobs(COMMIT, "X")

    def test_the_command_line_prints_json(self):
        p = subprocess.run([sys.executable, str(HERE / "quick_requests.py"), "--commit", COMMIT, "--os", "windows"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(json.loads(p.stdout)), 7)
        p = subprocess.run([sys.executable, str(HERE / "quick_requests.py"), "--commit", "nope", "--os", "L"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_no_dash_characters_in_the_jobs(self):
        text = json.dumps(QR.jobs(COMMIT, "L") + QR.jobs(COMMIT, "W"), ensure_ascii=False)
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)

    @unittest.skipUnless((PAPERS_BIN / "labqueue.py").exists(), "Papers lab/bin is not here")
    def test_labqueue_accepts_the_jobs(self):
        sys.path.insert(0, str(PAPERS_BIN))
        try:
            import labqueue
        finally:
            sys.path.remove(str(PAPERS_BIN))
        for host in ("L", "W"):
            out = labqueue.validate_queue(QR.jobs(COMMIT, host))
            self.assertEqual(len(out), len(QR.jobs(COMMIT, host)))


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=1)
    print(f"{r.result.testsRun} checks, {len(r.result.failures)} failures, {len(r.result.errors)} errors")
    sys.exit(0 if r.result.wasSuccessful() else 1)
