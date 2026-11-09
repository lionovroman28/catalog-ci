#!/usr/bin/env python3
"""Verify the release ZIP before it is uploaded as an Actions artifact."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import zipfile


ALLOWED_FILES = {
    "COMMIT.txt",
    "app.py",
    "import catalog.py",
    "requirements.txt",
    "templates/catalog.html",
    "templates/about.html",
    "templates/error.html",
    "static/style.css",
}
MAX_TOTAL_SIZE = 5_000_000


def main() -> int:
    sha = os.environ.get("COMMIT_SHA", "").strip()
    if not sha:
        print("ERROR: COMMIT_SHA is empty", file=sys.stderr)
        return 1

    archive = Path("release") / f"catalog-{sha}.zip"
    if not archive.is_file():
        print(f"ERROR: archive not found: {archive}", file=sys.stderr)
        return 1

    problems: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        names = {info.filename for info in infos}

        if names != ALLOWED_FILES:
            for name in sorted(names - ALLOWED_FILES):
                problems.append(f"unexpected file: {name}")
            for name in sorted(ALLOWED_FILES - names):
                problems.append(f"missing file: {name}")

        total_size = sum(info.file_size for info in infos)
        if total_size > MAX_TOTAL_SIZE:
            problems.append(f"archive is too large: {total_size} bytes")

        for info in infos:
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                problems.append(f"unsafe path: {name}")

        try:
            commit = zf.read("COMMIT.txt").decode("ascii").strip()
        except (KeyError, UnicodeDecodeError):
            commit = ""
        if commit != sha:
            problems.append("COMMIT.txt does not match COMMIT_SHA")

    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1

    print(f"Archive composition OK: {archive}")
    for name in sorted(ALLOWED_FILES):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
