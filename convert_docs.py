#!/usr/bin/env python3
"""Convert mirrored KLayout Qt5 docs (HTML) to offline markdown.

Input:  klayout-python/references/docs_html/{programming,code}/**/*.html
Output: klayout-python/references/docs_md/{programming,code}/**/*.md

Also emits:
- klayout-python/references/docs_md/INDEX.md (simple TOC)

This is intentionally pragmatic rather than perfect. Goal: offline searchable docs.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify as md

ROOT = Path(__file__).resolve().parent
IN_DIR = ROOT / "klayout-python" / "references" / "docs_html"
OUT_DIR = ROOT / "klayout-python" / "references" / "docs_md"

PROGRAMMING_PREFIX = "https://www.klayout.de/doc-qt5/programming/"
CODE_PREFIX = "https://www.klayout.de/doc-qt5/code/"


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    # remove nav/headers/footers where they exist
    for tag in soup.select("nav, header, footer"):  # best-effort
        tag.decompose()

    # remove scripts/styles
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Prefer main content if readable-style blocks exist
    main = soup.find("main")
    if main is None:
        # many pages are Doxygen-like; use body
        main = soup.body or soup

    # fix links: make them relative to docs_md root
    for a in main.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        # keep anchors
        if href.startswith("#"):
            continue

        # normalize absolute links
        if href.startswith(PROGRAMMING_PREFIX):
            rel = href[len(PROGRAMMING_PREFIX) :]
            a["href"] = f"../programming/{rel.replace('.html', '.md')}"
        elif href.startswith(CODE_PREFIX):
            rel = href[len(CODE_PREFIX) :]
            a["href"] = f"../code/{rel.replace('.html', '.md')}"
        elif href.startswith("../code/"):
            a["href"] = "../code/" + href[len("../code/") :].replace(".html", ".md")
        elif href.startswith("../programming/"):
            a["href"] = "../programming/" + href[len("../programming/") :].replace(".html", ".md")
        else:
            # leave other links as-is (may point outside scope)
            pass

    return str(main)


def html_to_md(html: str) -> str:
    # markdownify does a decent job if we feed it cleaned HTML
    text = md(html, heading_style="ATX")

    # collapse excessive blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # strip trailing spaces
    text = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"

    return text


def convert_tree(subdir: str) -> tuple[int, list[Path]]:
    src_root = IN_DIR / subdir
    dst_root = OUT_DIR / subdir
    html_files = sorted(src_root.rglob("*.html"))
    written = 0
    failures: list[Path] = []

    for i, f in enumerate(html_files, 1):
        try:
            rel = f.relative_to(src_root)
            out = (dst_root / rel).with_suffix(".md")
            out.parent.mkdir(parents=True, exist_ok=True)

            raw = f.read_text("utf-8", errors="ignore")
            cleaned = clean_html(raw)
            md_text = html_to_md(cleaned)

            # add a minimal provenance header
            if subdir == "programming":
                url = PROGRAMMING_PREFIX + str(rel).replace("\\", "/")
            else:
                url = CODE_PREFIX + str(rel).replace("\\", "/")
            url = url.replace(".md", ".html")

            md_text = (
                f"<!-- Source: {url} -->\n"
                f"<!-- Generated for offline use by OpenClaw klayout-python skill -->\n\n"
                + md_text
            )

            out.write_text(md_text, "utf-8")
            written += 1

            if i % 250 == 0:
                print(f"[{subdir}] converted {i}/{len(html_files)}")

        except Exception as e:
            failures.append(f)

    return written, failures


def build_index() -> None:
    idx = OUT_DIR / "INDEX.md"
    idx.parent.mkdir(parents=True, exist_ok=True)

    # include the programming index + code index
    lines = []
    lines.append("# KLayout Qt5 Docs (Offline Mirror)\n")
    lines.append("This folder is an offline mirror of KLayout documentation pages, converted from HTML to Markdown.\n")
    lines.append("## Programming\n")
    lines.append("- [Programming index](programming/index.md)\n")
    lines.append("- [Using Python](programming/python.md)\n")
    lines.append("- [Database API](programming/database_api.md)\n")
    lines.append("- [Geometry API](programming/geometry_api.md)\n")
    lines.append("- [Application API](programming/application_api.md)\n")
    lines.append("- [Events](programming/events.md)\n")
    lines.append("\n## Class Reference (Doxygen)\n")
    lines.append("- [Class index](code/index.md)\n")
    lines.append("\n## Notes\n")
    lines.append("- Some pages may be missing if the upstream site returned 404 during mirroring.\n")
    lines.append("- Prefer searching locally (ripgrep/grep) across `references/docs_md/`.\n")

    idx.write_text("".join(lines), "utf-8")


def main() -> int:
    if not IN_DIR.exists():
        print(f"Missing input dir: {IN_DIR}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    all_failures: list[Path] = []

    for sub in ("programming", "code"):
        n, failures = convert_tree(sub)
        total += n
        all_failures.extend(failures)

    build_index()

    print(f"Converted {total} pages to markdown into {OUT_DIR}")
    if all_failures:
        fail_path = OUT_DIR / "_conversion_failures.txt"
        fail_path.write_text("\n".join(str(p) for p in all_failures) + "\n", "utf-8")
        print(f"WARN: {len(all_failures)} failures. See {fail_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
