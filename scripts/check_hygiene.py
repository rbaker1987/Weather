"""File hygiene checks that mirror the pre-commit-hooks used in CI.

Checks the content git stores for every tracked text file (not the working copy, so Windows
autocrlf checkouts give the same answer as CI): a final newline and no extra blank lines at the
end, no trailing whitespace, no carriage returns of any kind (CRLF, mixed, or a stray CR inside a
line), and valid JSON/TOML/YAML syntax. These are problems that reached master before; the real
hooks run in CI, but they cannot run reliably on every developer machine.

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
CR = bytes([13])
LF = bytes([10])


def tracked_files() -> list[str]:
    """Paths of every tracked file."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [path for path in out.decode("utf-8").split(chr(0)) if path]


def index_contents(paths: list[str]) -> dict[str, bytes]:
    """Read the staged content of each path in one `git cat-file --batch` call."""
    request = "".join(f":{path}\n" for path in paths).encode()
    out = subprocess.run(
        ["git", "cat-file", "--batch"], input=request, capture_output=True, check=True
    ).stdout
    contents: dict[str, bytes] = {}
    position = 0
    for path in paths:
        header_end = out.index(LF, position)
        header = out[position:header_end].split()
        position = header_end + 1
        if len(header) < 3 or header[-1] == b"missing":
            continue
        size = int(header[2])
        contents[path] = out[position : position + size]
        position += size + 1  # content is followed by a newline
    return contents


def check_file(path: str, data: bytes) -> list[str]:
    problems = []
    file_path = Path(path)
    if file_path.suffix in SKIP_SUFFIXES or file_path.name in SKIP_NAMES:
        return problems
    # Detect binary content by NUL bytes. Git's own i/-text label is not enough: git also labels
    # a file with a lone carriage return as non-text, which is exactly what this should catch.
    if not data or bytes([0]) in data:
        return problems  # empty or binary
    if CR + LF in data:
        problems.append(f"{path}: stored with CRLF line endings (use LF)")
    elif CR in data:
        problems.append(f"{path}: contains a stray carriage return character")
    text = data.decode("utf-8", errors="replace")
    if not text.endswith("\n"):
        problems.append(f"{path}: missing final newline")
    elif text.endswith("\n\n"):
        problems.append(f"{path}: extra blank lines at the end of the file")
    for number, line in enumerate(text.split("\n"), start=1):
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
    paths = tracked_files()
    contents = index_contents(paths)
    problems = []
    for path in paths:
        if path in contents:
            problems.extend(check_file(path, contents[path]))
    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} hygiene problem(s)")
        return 1
    print("file hygiene ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
