# The MDPI LaTeX template of this paper

## Source

- The same template as the previous paper (`papers/typed-routing/paper/TEMPLATE.md`), downloaded
  by Alex from mdpi.com on 2026-09-28.
- File: `C:\Users\alext\Downloads\MDPI_template_ACS.zip`, sha256
  `62744425fbcec9cd3e58147cbee65bdec2e2ff0440f29792c26edc97a11b6c70`, checked again on
  2026-10-04 before use.
- Class version: `mdpi.cls` declares `\mdpidate` 2026-09-11 and `\mdpiversion` v6.5a.
- `template.tex` and `template.pdf` are not copied here.

## Files copied into `paper/Definitions/`

Copied from `papers/typed-routing/paper/Definitions/` on 2026-10-04, and each compared with the
zip's file: every file is byte for byte as in the zip, `journalnames.tex` included (CRLF line
endings, as in the zip; this repository has no `.gitattributes` and `core.autocrlf` is false).

| file | sha256 |
|---|---|
| journalnames.tex | c8c035b1980b852336584428b44499fdd1dc069c7be8985f258f2ef282775233 |
| logo-mdpi.eps | f02d31469c6b2666c9de2da8d8731773bce3751d2fa99a27ff4bcf61a106cdcf |
| logo-orcid.pdf | 0558a0097dc4d1ffe3f4a1b3c9b4b98c6e568eac7d7439d447ca56ed1a8ec759 |
| logo-updates.eps | 71ad8b00bcca718b62f3286af02ea56678e8199b5843d7ed4fdc86bd969c2809 |
| mdpi.bst | 3b747eee144173c46a43562ead905c26322c7cb394e350a925d36dcf63884680 |
| mdpi.cls | 658dbb5b2db2f6560bf3de3ecff7efac310a5817721eebd7539c1990b5345f01 |
| mdpi_apacite.bst | c7fffe0231922e5521dc360889fafe941ee26d154c1ce4e167e4ec9f2d13498f |
| mdpi_apacite.sty | a77a994f978c1860ff14dbcae74631f3ed835b418adbdcf84de2f06d98c34599 |
| mdpi_chicago.bst | 4a73faf6e0cf1a225d1b9a41a6955d3cc29a55c5fdce662177d00eee3946ce36 |
| unicode.tex | 1a41f6c85db06401a4582008e6b8933c7212d17541497701797a55fe473d19e0 |

The paper uses `\documentclass[futureinternet,article,submit,oneauthor]`, and the class selects
the numbered style `mdpi.bst` itself for Future Internet; the Chicago and APA variants are not used.
The licence terms found in the files are those `papers/typed-routing/paper/TEMPLATE.md` lists; Alex
decides whether the template files stay in a public repository.

## Page ranges and citation ranges without a range dash

As in the previous paper: `mdpi.bst`'s `n.dashify` turns every `-` of a `pages` field into a range
dash, so `references.bib` writes a page range as `1\bibhyph{,}4`, and `main.tex` defines
`\newcommand{\bibhyph}[1]{-}`. `main.tex` also patches natbib so that a range of citations is
joined by a hyphen. `mdpi.bst` is not edited.
