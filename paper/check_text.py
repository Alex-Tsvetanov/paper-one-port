#!/usr/bin/env python3
"""Checks the paper's sources against the writing rules (Papers CLAUDE.md, D4 and the numbers rule).

    python paper/check_text.py

Adapted from the previous paper's paper/check_text.py (papers/typed-routing, same author).

1. No en dash, em dash or other dash character, and no "--" or "---" (which LaTeX sets as
   dashes), in any .tex file of paper/, in references.bib, in paper/*.py, or in the generated
   macro files results/*macros.tex (results/design-macros.tex always, the others as they exist)
   and the generated tables results/tables/*.tex, comments included.
2. No digit in the prose of paper/*.tex: every number comes from the macro files. The arguments
   of \\ForAlex, \\TODO and \\Pending are notes, not prose, and are left out. Commands whose
   arguments are not prose (cite, ref, label, input, url, lengths) are removed first, and a short
   list of names that contain digits is allowed: the hypothesis, workload and hard-case names (C1
   to C3, B1 to B3, M1 to M3, WL1 to WL8, HC1 to HC25), RFC numbers, HTTP/1.1 and HTTP/2, TLS 1.3,
   MQTT 3.1.1 and 5.0, PROXY v1 and v2, C++23, X25519, IPv4 and IPv6, SHA-256, UTF-8, h2, the postal
   address, the ORCID, hexadecimal bytes and status codes in texttt, and file names in texttt.
3. No sentence of more than 30 words, in the prose and the captions of paper/*.tex. A macro
   counts as one word. Tables, notes (TODO, ForAlex, Pending) and MDPI's fixed forms (author
   contributions, conflicts of interest, acknowledgments, data availability) are left out.
4. Reported, not failed: sentences with two or more passive verbs.
Prints every problem and exits 1 if a check of 1 to 3 fails.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"
ALLOWED = [r"\b(?:HC|WL)\d+\b", r"\b[CBM][1-3]\b", r"RFC~?\d+", r"HTTP/1\.1", r"HTTP/[12]\b", r"TLS~1\.3", r"caddy-l4",
           r"MQTT~(?:3\.1\.1|5\.0)", r"\bv[12]\b", r"C\+\+23", r"X25519", r"\bIPv[46]\b", r"SHA-256", r"\bh2c?\b",
           r"\bnghttp2\b", r"\bG1\b", r"\bz_0\b", r"UTF-8",
           r"Bradistilov 11", r"\\newcommand\{\\orcidauthorA\}\{[^}]*\}",
           r"\\texttt\{0x[0-9A-Fa-f]+\}", r"\\texttt\{[1-5]\d\d\}",
           r"\\texttt\{[^}]*(/|\\_|\.py|\.sh|\.md|\.tex|\.json)[^}]*\}"]
STRIP = [r"\\vspace\{[^}]*\}", r"\\multicolumn\{\d+\}\{[lcrX|]+\}",r"\\begin\{adjustwidth\}\{[^}]*\}\{[^}]*\}",
         r"\\(cite|ref|label|input|tabinput|includegraphics|bibliography|bibliographystyle|url|href|setlength|"
         r"usepackage|documentclass)(\[[^\]]*\])?\{[^}]*\}(\{[^}]*\})?",
         r"\\begin\{tabularx\}\{[^}]*\}\{[^}]*\}", r"\\begin\{tabular\}\{[^}]*\}",
         r"\\(begin|end)\{[a-z*]+\}(\[[^\]]*\])?", r"\\[A-Za-z]+\*?", r"\[[0-9a-z=,.!]+\]"]
NOTES = ("TODO", "ForAlex", "Pending")
FORMS = ("authorcontributions", "conflictsofinterest", "acknowledgments", "dataavailability", "funding")
MAX_WORDS = 30
PASSIVE = re.compile(r"\b(is|are|was|were|be|been|being)\s+(\w+ly\s+)?(\w+ed|built|made|run|shown|given|found|"
                     r"kept|taken|done|seen|known|written|drawn|held|set|read|put|chosen|left)\b")


def uncomment(line: str) -> str:
    return re.split(r"(?<!\\)%", line, maxsplit=1)[0]


def check_dashes(path: Path) -> list[str]:
    """Every dash character; in a TeX or BibTeX file also a double hyphen, which LaTeX sets as a
    dash. A Python file may hold a double hyphen as code (a string it searches for)."""
    double = path.suffix != ".py"
    bad = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if any(c in line for c in DASHES) or (double and "--" in line):
            bad.append(f"{path.name}:{n}: dash: {line.strip()}")
    return bad


def argument(text: str, start: int) -> tuple[str, int]:
    """The brace group that opens at text[start] ('{'), and the index after it."""
    depth, i = 0, start
    while i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], len(text)


def drop_command(text: str, name: str, keep_newlines: bool = True) -> str:
    """Removes \\name{...} with its brace group; the group's newlines stay, so line numbers hold."""
    out, i = [], 0
    while True:
        j = text.find("\\" + name + "{", i)
        if j < 0:
            return "".join(out) + text[i:]
        arg, k = argument(text, j + len(name) + 1)
        out.append(text[i:j] + " " + ("\n" * arg.count("\n") if keep_newlines else ""))
        i = k


def body(path: Path) -> str:
    """The text to check: in main.tex from \\Title on (the preamble defines names), elsewhere all;
    comments and notes removed, line breaks kept."""
    lines = [uncomment(l) for l in path.read_text(encoding="utf-8").splitlines()]
    if path.name == "main.tex":
        start = next((i for i, l in enumerate(lines) if l.startswith("\\Title{")), 0)
        lines = [""] * start + lines[start:]
    text = "\n".join(lines)
    for name in NOTES:
        text = drop_command(text, name)
    return text


def check_digits(path: Path) -> list[str]:
    bad = []
    for n, line in enumerate(body(path).splitlines(), 1):
        text = line
        for pat in ALLOWED:
            text = re.sub(pat, " ", text)
        for pat in STRIP:
            text = re.sub(pat, " ", text)
        if re.search(r"\d", text):
            bad.append(f"{path.name}:{n}: digit: {line.strip()}")
    return bad


def prose(path: Path) -> str:
    text = body(path)
    if path.name == "main.tex":
        text = text[text.find("\\abstract{"):text.find("\\begin{adjustwidth}")]
    captions = []
    for env in ("table", "figure"):
        pat = r"\\begin\{" + env + r"\}.*?\\end\{" + env + r"\}"
        for m in re.finditer(pat, text, flags=re.S):
            j = m.group(0).find("\\caption{")
            if j >= 0:
                captions.append(argument(m.group(0), j + len("\\caption"))[0])
        text = re.sub(pat, " ", text, flags=re.S)
    text = text + "\n\n" + "\n\n".join(captions)
    for name in FORMS + ("keyword", "Title", "address", "corres", "Author", "AuthorNames"):
        text = drop_command(text, name, keep_newlines=False)
    text = re.sub(r"\\(cite|ref|label|input|bibliography|bibliographystyle|url)(\[[^\]]*\])?\{[^}]*\}", "", text)
    text = re.sub(r"\$[^$]*\$", " M ", text)
    text = re.sub(r"\\(texttt|emph|textbf|name|flag|hex)\{", "{", text)
    text = re.sub(r"\\(item|paragraph|runin|subsubsection|subsection|section)\*?", "\n\n", text)
    text = re.sub(r"\\(begin|end)\{[a-z*]+\}(\[[^\]]*\])?", "\n\n", text)
    text = re.sub(r"\\[A-Za-z]+\*?", " X ", text)
    return text.replace("~", " ").replace("{", " ").replace("}", " ").replace("\\ ", " ")


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.?!])\s+(?=[A-Z(]|X\b|``|[a-z][\w-]*\b)|\n\s*\n", text)
    return [" ".join(p.split()) for p in parts if len(p.split()) > 1]


def check_sentences(path: Path) -> tuple[list[str], list[str]]:
    long, passive = [], []
    for s in sentences(prose(path)):
        n = len(s.split())
        if n > MAX_WORDS:
            long.append(f"{path.name}: {n} words: {s[:200]}")
        if len(PASSIVE.findall(s)) >= 2:
            passive.append(f"{path.name}: passive: {s[:160]}")
    return long, passive


def main() -> int:
    tex = sorted(HERE.glob("*.tex"))
    dash_files = tex + [HERE / "references.bib"] + sorted(HERE.glob("*.py")) + [RESULTS / "design-macros.tex"]
    dash_files += [p for p in sorted(RESULTS.glob("*macros.tex")) if p.name != "design-macros.tex"]
    dash_files += sorted((RESULTS / "tables").glob("*.tex"))
    bad, notes = [], []
    for p in dash_files:
        bad += check_dashes(p)
    for p in tex:
        bad += check_digits(p)
        long, passive = check_sentences(p)
        bad += long
        notes += passive
    for b in bad:
        print(b)
    for n in notes:
        print("note", n)
    print(f"check_text: {len(tex)} files, {len(bad)} problems, {len(notes)} notes")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
