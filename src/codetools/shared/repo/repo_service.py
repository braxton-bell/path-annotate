#!/usr/bin/env python3

import os
from pathlib import Path
from typing import Any

from codetools.shared.repo.repo_config import RepoConfig


class RepoService:
    """
    Core Logic Service.
    Handles file scanning, content reading, and Markdown generation.
    """

    def __init__(self, *, app_config: dict[str, Any] | None = None) -> None:
        self._config = app_config or {}
        # Dependencies initialized here
        self._ext_filter = RepoConfig.INCLUDE_EXTS
        self._dir_skip = RepoConfig.SKIP_DIRS
        self._file_skip = RepoConfig.SKIP_FILES
        self._max_bytes = RepoConfig.MAX_FILE_BYTES

    def should_skip_dir(self, dirname: str) -> bool:
        return (dirname in self._dir_skip) or (dirname.endswith(".egg-info"))

    def should_include_file(self, path: Path) -> bool:
        return (path.name not in self._file_skip) and (
            path.suffix.lower() in self._ext_filter
        )

    def scan_directory(self, root: Path) -> list[Path]:
        """Returns a list of all valid files under root, recursively."""
        valid_files: list[Path] = []
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                # Filter directories in-place
                dirnames[:] = [d for d in dirnames if not self.should_skip_dir(d)]
                for f in filenames:
                    p = Path(dirpath) / f
                    if self.should_include_file(p):
                        valid_files.append(p)
        except PermissionError:
            pass
        return sorted(valid_files, key=lambda p: str(p.relative_to(root)).lower())

    def read_text_safely(self, path: Path) -> str:
        """Reads file content and normalizes line endings."""
        try:
            size = path.stat().st_size
            if size > self._max_bytes:
                return f"<<SKIPPED: file too large ({size} bytes)>>"

            data = path.read_bytes()
            text = ""
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("latin-1")

            # Windows CR fix
            return text.replace("\r\n", "\n").replace("\r", "\n")

        except Exception as e:
            return f"<<ERROR: {e}>>"

    def normalize_fences(self, text: str) -> str:
        return text.replace("```", "``\u200b`")

    def get_lang(self, path: Path) -> str:
        ext = path.suffix.lower()
        mapping = {
            ".py": "python",
            ".json": "json",
            ".js": "javascript",
            ".ts": "typescript",
            ".html": "html",
            ".css": "css",
            ".md": "markdown",
            ".sh": "bash",
            ".rs": "rust",
            ".go": "go",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".cs": "csharp",
            ".java": "java",
            ".yaml": "yaml",
            ".yml": "yaml",
        }
        return mapping.get(ext, "")

    def _build_tree_structure(self, paths: list[Path], root: Path) -> dict:
        tree: dict = {}
        for path in paths:
            try:
                parts = path.relative_to(root).parts
                current = tree
                for part in parts:
                    current = current.setdefault(part, {})
            except ValueError:
                continue
        return tree

    def _render_tree(self, tree: dict, prefix: str = "") -> list[str]:
        lines: list[str] = []
        keys = sorted(tree.keys())
        for i, key in enumerate(keys):
            is_last = i == len(keys) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{key}")
            extension = "    " if is_last else "│   "
            if tree[key]:
                lines.extend(self._render_tree(tree[key], prefix + extension))
        return lines

    def generate_tree_diagram(self, files: list[Path], root: Path) -> str:
        if not files:
            return ""
        tree_structure = self._build_tree_structure(files, root)
        rendered_lines = ["."] + self._render_tree(tree_structure)
        return "\n".join(rendered_lines)

    def generate_markdown(self, files: list[Path], root: Path) -> str:
        files.sort(key=lambda p: str(p))
        lines = [
            f"# Repository Dump: {root.name}",
            f"- Root: `{root.resolve()}`",
            f"- Files included: {len(files)}",
            "",
            "## Project Structure",
            "```text",
            self.generate_tree_diagram(files, root),
            "```",
            "",
            "---",
            "",
            "## File Contents",
            "",
        ]

        for path in files:
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = str(path)

            lang = self.get_lang(path)
            content = self.read_text_safely(path)
            content = self.normalize_fences(content)

            lines.append(f"### {rel}")
            lines.append("")
            lines.append(f"```{lang}")
            lines.append(content)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)
