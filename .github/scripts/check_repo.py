#!/usr/bin/env python3
"""Limited repository policy check.

This script fails when a tracked path is outside the explicit allowlist or when a
small set of obvious secret patterns is found. It never prints file contents.
A clean result is not a guarantee that the repository contains no secrets.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]

ALLOWED_EXACT = {
    ".gitignore",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "app.py",
    "import catalog.py",
    ".github/workflows/ci.yml",
    ".github/scripts/check_repo.py",
    ".github/scripts/check_archive.py",
}
ALLOWED_GLOBS = (
    "templates/*.html",
    "static/*.css",
    "tests/*.py",
)
REQUIRED = {
    ".gitignore",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "app.py",
    "import catalog.py",
    "templates/catalog.html",
    "templates/about.html",
    "templates/error.html",
    "static/style.css",
    "tests/test_app.py",
    ".github/workflows/ci.yml",
    ".github/scripts/check_repo.py",
    ".github/scripts/check_archive.py",
}
FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    "data",
    "dist",
    "build",
    "node_modules",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".xlsx",
    ".xls",
    ".key",
    ".pem",
    ".zip",
    ".7z",
    ".rar",
    ".log",
}
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "assigned-secret",
        re.compile(
            r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)"
            r"\s*[:=]\s*['\"][^'\"]{8,}['\"]"
        ),
    ),
)
SKIP_SECRET_SCAN = {".github/scripts/check_repo.py"}
MAX_SCAN_BYTES = 1_000_000


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [os.fsdecode(item) for item in result.stdout.split(b"\0") if item]


def is_allowed(path: str) -> bool:
    if path in ALLOWED_EXACT:
        return True
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in ALLOWED_GLOBS)


def forbidden_reason(path: str) -> str | None:
    parts = Path(path).parts
    for part in parts:
        if part in FORBIDDEN_PARTS:
            return f"forbidden directory: {part}"
    name = Path(path).name
    if name == ".env" or name.startswith(".env."):
        return "environment file"
    suffix = Path(path).suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        return f"forbidden suffix: {suffix}"
    return None


def scan_secrets(paths: list[str]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if path in SKIP_SECRET_SCAN:
            continue
        full_path = ROOT / path
        try:
            if full_path.stat().st_size > MAX_SCAN_BYTES:
                continue
            data = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(data.splitlines(), start=1):
            for rule, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{path}:{number}: {rule}")
    return findings


def main() -> int:
    files = tracked_files()
    problems: list[str] = []

    for path in files:
        if not is_allowed(path):
            problems.append(f"tracked path outside allowlist: {path}")
        reason = forbidden_reason(path)
        if reason:
            problems.append(f"forbidden tracked path: {path} ({reason})")

    missing = sorted(REQUIRED - set(files))
    for path in missing:
        problems.append(f"required file is not tracked: {path}")

    findings = scan_secrets(files)
    problems.extend(f"possible secret: {item}" for item in findings)

    print(f"Tracked files: {len(files)}")
    print(f"Allowlist: {'OK' if not any('allowlist' in item or 'forbidden tracked' in item for item in problems) else 'FAILED'}")
    print(f"Required files: {'OK' if not missing else 'MISSING'}")
    print(f"Limited secret scan: {len(findings)} finding(s)")
    print("Note: this is a limited pattern check, not a guarantee that no secrets exist.")

    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
