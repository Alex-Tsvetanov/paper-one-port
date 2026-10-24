#!/usr/bin/env python3
"""The writing pack's one macros file for the laptop set (results/laptop-w/pack-macros.tex), and the
manifest of the files this folder's generators wrote (results/laptop-w/SHA256SUMS-pack).

    python paper/laptop_w/pack_lw.py [--check]

Papers' lab/bin/writing_pack.py pull copies one macros file into the pack. The paper's numbers are
in eight generated files, so this file concatenates them, in a fixed order, each after a comment line
that names it and its sha256:
  results/laptop-w/design-macros.tex, hardcase-macros.tex, macros.tex, report-macros.tex,
  w-evidence-macros.tex, b2-macros.tex, ops-macros.tex, and October's results/trace-macros.tex
  (lab job st1 on L alone, no W input).
results/laptop-w/macros.tex and hardcase-macros.tex replace October's results/macros.tex and
results/hardcase-macros.tex: the two sets are never loaded together, and this file refuses October's
two. It also refuses a name defined twice, the macro CostR (R is per host: CostRL and CostRW), a
missing CostRL or CostRW, an input line that names a desktop job, a source whose sha256 differs from
results/laptop-w/SHA256SUMS where that file lists it, and a value that names the desktop's
processor or compiler. It changes no byte of any source.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lw_common as C  # noqa: E402

OUT = C.LW / "pack-macros.tex"
MANIFEST = C.LW / "SHA256SUMS-pack"
SOURCES = [C.LW / f for f in ("design-macros.tex", "hardcase-macros.tex", "macros.tex", "report-macros.tex",
                              "w-evidence-macros.tex", "b2-macros.tex", "ops-macros.tex")] + [C.RESULTS / "trace-macros.tex"]
REFUSED = (C.RESULTS / "macros.tex", C.RESULTS / "hardcase-macros.tex")
# The files of results/laptop-w/ that this folder's generators write, for the manifest.
GENERATED = ("not-run.json", "report-macros.tex", "w-evidence-macros.tex", "b2-macros.tex", "ops-macros.tex",
             "design-macros.tex", "pack-macros.tex")
HEAD = ("% macros.tex of P3's writing pack: the laptop set's generated macro files, concatenated by\n"
        "% paper/laptop_w/pack_lw.py (one-port repository). Every number of the paper is one of these macros.\n"
        "% Do not edit. Each part starts with a line naming its source file and that file's sha256.\n")
DESKTOP_VALUES = re.compile(r"36246|Ryzen 5|3600")


def listed_sums() -> dict[str, str]:
    out = {}
    for ln in (C.LW / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, _, name = ln.partition("  ")
        out[name.strip()] = digest
    return out


def build_pack() -> str:
    if any(p in REFUSED for p in SOURCES):
        raise ValueError("October's macros.tex or hardcase-macros.tex is among the sources")
    sums = listed_sums()
    seen: dict[str, str] = {}
    parts = [HEAD]
    for p in SOURCES:
        rel = p.relative_to(C.ROOT).as_posix()
        text = p.read_text(encoding="utf-8")
        digest = C.sha256_file(p)
        if p.parent == C.LW and p.name in sums and sums[p.name] != digest:
            raise ValueError(f"{rel}: sha256 {digest}, but results/laptop-w/SHA256SUMS lists {sums[p.name]}")
        for ln in text.splitlines():
            if ln.startswith("% input:") and re.search(r"\b(wp1|wre1|wc1|wc2|wm1|wh1|ws1)\b", ln):
                raise ValueError(f"{rel}: an input line names a desktop job: {ln}")
            m = re.match(r"\\newcommand\{\\([A-Za-z]+)\}\{(.*)\}", ln)
            if m:
                if m.group(1) in seen:
                    raise ValueError(f"\\{m.group(1)} is defined in {seen[m.group(1)]} and in {rel}")
                seen[m.group(1)] = rel
                if DESKTOP_VALUES.search(m.group(2)):
                    raise ValueError(f"{rel}: \\{m.group(1)} names the desktop's processor or compiler")
        parts.append(f"% ---- source: {rel} sha256 {digest}\n")
        parts.append(text if text.endswith("\n") else text + "\n")
    if "CostR" in seen or not {"CostRL", "CostRW"} <= set(seen):
        raise ValueError("the pack must hold CostRL and CostRW and not CostR")
    return "".join(parts)


def build() -> dict[Path, str]:
    pack = build_pack()
    lines = []
    for name in GENERATED:
        if name == "pack-macros.tex":
            digest = hashlib.sha256(pack.encode("utf-8")).hexdigest()
        else:
            digest = C.sha256_file(C.LW / name)
        lines.append(f"{digest}  {name}")
    for p in sorted(C.TABLES.glob("*.tex")):
        lines.append(f"{C.sha256_file(p)}  tables/{p.name}")
    return {OUT: pack, MANIFEST: "\n".join(lines) + "\n"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare with the committed files, write nothing")
    a = ap.parse_args(argv)
    out = build()
    rc = C.write_all(out, a.check)
    if not a.check:
        n = out[OUT].count("\\newcommand{")
        print(f"pack macros: {n} macros from {len(SOURCES)} files to {OUT.relative_to(C.ROOT).as_posix()}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
