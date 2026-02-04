#!/usr/bin/env python3
"""
repo_to_markdown.py

Create a single Markdown document that includes the contents of every .py and .json
file under a repository root, each preceded by a level-3 header containing the
file's relative path.

Example:
  python repo_to_markdown.py /path/to/repo -o repo_dump.md
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

INCLUDE_EXTS = {".py", ".json"}

# Directories to skip entirely (common repo noise / generated content)
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "site-packages",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
    ".cache",
    "node_modules",
}

# File names to skip (optional; add as needed)
SKIP_FILES = {
    ".DS_Store",
}

MAX_FILE_BYTES_DEFAULT = 2_000_000  # 2MB per file guardrail


def should_skip_dir(dirname: str) -> bool:
    if dirname in SKIP_DIRS:
        return True
    # handle glob-ish egg-info entry
    if dirname.endswith(".egg-info"):
        return True
    return False


def iter_files(root: Path) -> Iterable[Path]:
    """
    Yield matching files under root, skipping SKIP_DIRS directories.
    """
    # Use rglob but prune by manually walking to skip dirs efficiently.
    stack = [root]

    while stack:
        current = stack.pop()
        try:
            for p in current.iterdir():
                if p.is_dir():
                    if should_skip_dir(p.name):
                        continue
                    stack.append(p)
                elif p.is_file():
                    if p.name in SKIP_FILES:
                        continue
                    if p.suffix.lower() in INCLUDE_EXTS:
                        yield p
        except PermissionError:
            # Skip unreadable dirs/files
            continue


def fence_lang(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".py":
        return "python"
    if ext == ".json":
        return "json"
    return ""


def read_text_safely(path: Path, max_bytes: int) -> str:
    """
    Read text with UTF-8, fallback to latin-1 if needed. Skip if too large.
    """
    size = path.stat().st_size
    if size > max_bytes:
        return f"<<SKIPPED: file too large ({size} bytes) exceeds limit ({max_bytes} bytes)>>"

    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Last-resort decode; preserves bytes 0-255
        return data.decode("latin-1")


def normalize_code_fences(text: str) -> str:
    """
    If a file itself contains ``` fences, we keep them as-is.
    That can prematurely close our outer fence.

    Easiest robust approach: use a longer fence for our blocks when needed.
    But since you explicitly want triple-backticks, we’ll instead escape
    internal triple backticks by inserting a zero-width space.

    This keeps it human-readable and prevents accidental fence termination.
    """
    return text.replace("```", "``\u200b`")


def build_markdown(root: Path, max_bytes: int) -> str:
    files = sorted(iter_files(root), key=lambda p: str(p.relative_to(root)).lower())

    lines: list[str] = []
    lines.append(f"# Repository dump: {root.name}")
    lines.append("")
    lines.append(f"- Root: `{root.resolve()}`")
    lines.append(f"- Included extensions: {', '.join(sorted(INCLUDE_EXTS))}")
    lines.append(f"- Skipped directories: {', '.join(sorted(SKIP_DIRS))}")
    lines.append(f"- Max file size: {max_bytes} bytes")
    lines.append("")
    lines.append("---")
    lines.append("")

    for path in files:
        rel = path.relative_to(root).as_posix()
        lang = fence_lang(path)

        content = read_text_safely(path, max_bytes=max_bytes)
        content = normalize_code_fences(content)

        lines.append(f"### {rel}")
        lines.append("")
        lines.append(f"```{lang}".rstrip())
        lines.append(content.rstrip("\n"))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dump a repo's .py and .json files into a single Markdown file."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Repository root directory (default: current directory).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="repo_dump.md",
        help="Output Markdown file (default: repo_dump.md).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=MAX_FILE_BYTES_DEFAULT,
        help=f"Max bytes per file to include (default: {MAX_FILE_BYTES_DEFAULT}).",
    )

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Root path is not a directory: {root}")

    md = build_markdown(root, max_bytes=args.max_bytes)

    out_path = Path(args.output).resolve()
    out_path.write_text(md, encoding="utf-8", newline="\n")

    print(f"Wrote {out_path} ({len(md.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
