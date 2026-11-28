"""File hygiene checks that mirror the pre-commit-hooks used in CI.

Checks every tracked text file for: a final newline, no trailing whitespace, no CRLF or mixed
line endings stored in git, and valid JSON/TOML/YAML syntax. These are the checks that failed
on master before (a missing final newline in a JSON fixture); the real hooks run in CI, but they
cannot run reliably on every developer machine, so this catches the same problems beforehand.

Run from the repository root: python scripts/check_hygiene.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import tomllib

SKIP_SUFFIXES = {".svg"}
SKIP_NAMES = {"package-lock.json"}


def tracked_files() -> list[tuple[str, str]]:
    """Return (index_eol_info, path) for every tracked file, e.g. ("i/lf", "README.md")."""
    out = subprocess.run(
        ["git", "ls-files", "--eol"], capture_output=True, text=True, check=True
    ).stdout
    files = []
    for line in out.splitlines():
        info, _, path = line.partition("\t")
        files.append((info.split()[0], path))
    return files


def check_file(index_eol: str, path: str) -> list[str]:
    problems = []
    if index_eol in ("i/crlf", "i/mixed"):
        problems.append(f"{path}: stored with {index_eol[2:]} line endings (use LF)")
    file_path = Path(path)
    if file_path.suffix in SKIP_SUFFIXES or file_path.name in SKIP_NAMES:
        return problems
    if index_eol == "i/-text":
        return problems  # binary
    data = file_path.read_bytes()
    if not data:
        return problems
    text = data.decode("utf-8", errors="replace")
    if not text.endswith("\n"):
        problems.append(f"{path}: missing final newline")
    elif text.endswith("\n\n"):
        problems.append(f"{path}: extra blank lines at the end of the file")
    for number, line in enumerate(text.splitlines(), start=1):
        if line != line.rstrip(" \t"):
            problems.append(f"{path}:{number}: trailing whitespace")
            break
    suffix = file_path.suffix
    try:
        if suffix == ".json":
            json.loads(text)
        elif suffix == ".toml":
            tomllib.loads(text)
        elif suffix in (".yml", ".yaml"):
            try:
                import yaml
            except ImportError:
                return problems
            list(yaml.safe_load_all(text))
    except Exception as exc:
        problems.append(f"{path}: invalid {suffix[1:].upper()} ({exc})")
    return problems


def main() -> int:
    problems = []
    for index_eol, path in tracked_files():
        if Path(path).is_file():
            problems.extend(check_file(index_eol, path))
    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} hygiene problem(s)")
        return 1
    print("file hygiene ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
