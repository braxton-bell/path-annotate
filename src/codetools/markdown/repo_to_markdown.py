#!/usr/bin/env python3
"""
repo_to_markdown.py

A tool to dump code files into a single Markdown document.
Includes a GUI to visualize the directory tree and select specific files/folders.
Now includes an automatic "Project Structure" tree diagram in the output.

Usage:
  GUI Mode: python repo_to_markdown.py
  TUI Mode: python repo_to_markdown.py --tui
  CLI Mode: python repo_to_markdown.py /path/to/repo -o out.md
"""

from __future__ import annotations

import argparse
import curses
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List

# --- Configuration ---

INCLUDE_EXTS = {
    ".py",
    ".json",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".md",
    ".txt",
    ".sh",
    ".yaml",
    ".yml",
    ".c",
    ".cpp",
    ".h",
    ".rs",
    ".go",
    ".java",
    ".cs",
}

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
    "target",
    "bin",
    "obj",
}

SKIP_FILES = {
    ".DS_Store",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "Cargo.lock",
}

MAX_FILE_BYTES = 2_000_000

# --- Core Logic ---


class RepoProcessor:
    """Handles file scanning, reading, tree generation, and markdown assembly."""

    @staticmethod
    def should_skip_dir(dirname: str) -> bool:
        return (dirname in SKIP_DIRS) or (dirname.endswith(".egg-info"))

    @staticmethod
    def should_include_file(path: Path) -> bool:
        return (path.name not in SKIP_FILES) and (path.suffix.lower() in INCLUDE_EXTS)

    @staticmethod
    def scan_directory(root: Path) -> List[Path]:
        """Returns a list of all valid files under root, recursively."""
        valid_files = []
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                # Filter directories in-place
                dirnames[:] = [
                    d for d in dirnames if not RepoProcessor.should_skip_dir(d)
                ]

                for f in filenames:
                    p = Path(dirpath) / f
                    if RepoProcessor.should_include_file(p):
                        valid_files.append(p)
        except PermissionError:
            pass
        return sorted(valid_files, key=lambda p: str(p.relative_to(root)).lower())

    @staticmethod
    def read_text_safely(path: Path) -> str:
        """Reads file content and normalizes line endings."""
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                return f"<<SKIPPED: file too large ({size} bytes)>>"

            data = path.read_bytes()
            text = ""
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                # Fallback for non-UTF-8 files
                text = data.decode("latin-1")

            # --- CRITICAL FIX FOR WINDOWS ---
            # Replace Windows (\r\n) and classic Mac (\r) line endings with standard (\n).
            # If we don't do this, writing the file later on Windows will double the Carriage Returns.
            return text.replace("\r\n", "\n").replace("\r", "\n")

        except Exception as e:
            return f"<<ERROR: {e}>>"

    @staticmethod
    def normalize_fences(text: str) -> str:
        return text.replace("```", "``\u200b`")

    @staticmethod
    def get_lang(path: Path) -> str:
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

    # --- Tree Generation Logic ---

    @staticmethod
    def _build_tree_structure(paths: List[Path], root: Path) -> Dict:
        """Converts a list of paths into a nested dictionary structure."""
        tree = {}
        for path in paths:
            parts = path.relative_to(root).parts
            current = tree
            for part in parts:
                current = current.setdefault(part, {})
        return tree

    @staticmethod
    def _render_tree(tree: Dict, prefix: str = "") -> List[str]:
        """Recursively renders the dictionary tree into lines of text."""
        lines = []
        keys = sorted(tree.keys())  # Sort for consistent order
        for i, key in enumerate(keys):
            is_last = i == len(keys) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{key}")

            # Prepare prefix for children
            extension = "    " if is_last else "│   "

            # If the dict is not empty, it means this key is a directory with children
            if tree[key]:
                lines.extend(RepoProcessor._render_tree(tree[key], prefix + extension))
        return lines

    @staticmethod
    def generate_tree_diagram(files: List[Path], root: Path) -> str:
        """Generates a string representation of the file tree."""
        if not files:
            return ""
        tree_structure = RepoProcessor._build_tree_structure(files, root)
        rendered_lines = ["."] + RepoProcessor._render_tree(tree_structure)
        return "\n".join(rendered_lines)

    # --- Markdown Generation ---

    @staticmethod
    def generate_markdown(files: List[Path], root: Path) -> str:
        # Sort by path string for readability
        files.sort(key=lambda p: str(p))

        # 1. Header
        lines = [
            f"# Repository Dump: {root.name}",
            f"- Root: `{root.resolve()}`",
            f"- Files included: {len(files)}",
            "",
        ]

        # 2. Project Structure (Tree Diagram)
        lines.append("## Project Structure")
        lines.append("```text")
        lines.append(RepoProcessor.generate_tree_diagram(files, root))
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 3. File Contents
        lines.append("## File Contents")
        lines.append("")

        for path in files:
            rel = path.relative_to(root).as_posix()
            lang = RepoProcessor.get_lang(path)
            content = RepoProcessor.read_text_safely(path)
            content = RepoProcessor.normalize_fences(content)

            lines.append(f"### {rel}")
            lines.append("")
            lines.append(f"```{lang}")
            lines.append(content)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


# --- Data Structure for UI ---


class TreeNode:
    def __init__(self, path: Path, is_dir: bool, parent=None):
        self.path = path
        self.name = path.name
        self.is_dir = is_dir
        self.parent = parent
        self.children: List[TreeNode] = []
        self.checked = True
        self.expanded = True  # For TUI initial state

    def toggle(self, state: bool = None):
        """Toggle check state, optionally forcing a state."""
        new_state = not self.checked if state is None else state
        self.checked = new_state
        # Propagate down
        for child in self.children:
            child.toggle(new_state)

    def get_selected_files(self) -> List[Path]:
        selected = []
        if not self.is_dir and self.checked:
            selected.append(self.path)
        for child in self.children:
            selected.extend(child.get_selected_files())
        return selected

    @classmethod
    def build_tree(cls, root_path: Path) -> TreeNode:
        node = cls(root_path, True)
        try:
            # Sort directories first, then files
            items = sorted(
                root_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())
            )
            for item in items:
                if item.is_dir():
                    if RepoProcessor.should_skip_dir(item.name):
                        continue
                    child_node = cls.build_tree(item)
                    child_node.parent = node
                    # Only add dir if it has content (cleanup empty dirs from view)
                    if child_node.children:
                        node.children.append(child_node)
                else:
                    if RepoProcessor.should_include_file(item):
                        child_node = cls(item, False, parent=node)
                        node.children.append(child_node)
        except PermissionError:
            pass
        return node


# --- Mode 1: Graphical User Interface (Tkinter) ---


class GuiApp:
    def __init__(self, root_tk, start_path: Path):
        self.root = root_tk
        self.root.title("Repo to Markdown")
        self.root.geometry("600x600")

        self.tree_map: Dict[str, TreeNode] = {}
        self.start_path = start_path

        self._setup_ui()
        self._load_tree(self.start_path)

    def _setup_ui(self):
        # Controls
        frame_top = ttk.Frame(self.root, padding=5)
        frame_top.pack(fill="x")

        ttk.Button(frame_top, text="Browse", command=self._browse).pack(side="left")
        ttk.Button(frame_top, text="Generate", command=self._generate).pack(
            side="right"
        )

        # TreeView
        frame_tree = ttk.Frame(self.root, padding=5)
        frame_tree.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(frame_tree, selectmode="browse")
        ysb = ttk.Scrollbar(frame_tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)

        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

        self.tree.bind("<ButtonRelease-1>", self._on_click)

    def _load_tree(self, path: Path):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.tree_map.clear()

        self.root_node = TreeNode.build_tree(path)
        self._insert_node("", self.root_node)

    def _insert_node(self, parent_id, node: TreeNode):
        icon = "☒" if node.checked else "☐"
        text = f"{icon} {node.name}"
        # Start expanded?
        oid = self.tree.insert(parent_id, "end", text=text, open=node.expanded)
        self.tree_map[oid] = node

        for child in node.children:
            self._insert_node(oid, child)

    def _refresh_node_visuals(self, oid):
        node = self.tree_map[oid]
        icon = "☒" if node.checked else "☐"
        self.tree.item(oid, text=f"{icon} {node.name}")

        for child_oid in self.tree.get_children(oid):
            self._refresh_node_visuals(child_oid)

    def _on_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region == "tree":
            oid = self.tree.identify_row(event.y)
            if oid:
                node = self.tree_map[oid]
                node.toggle()
                self._refresh_node_visuals(oid)

    def _browse(self):
        d = filedialog.askdirectory()
        if d:
            self._load_tree(Path(d))

    def _generate(self):
        files = self.root_node.get_selected_files()
        if not files:
            messagebox.showwarning("Empty", "No files selected.")
            return

        out = filedialog.asksaveasfilename(
            defaultextension=".md", initialfile="repo_dump.md"
        )
        if out:
            try:
                md = RepoProcessor.generate_markdown(files, self.root_node.path)
                Path(out).write_text(md, encoding="utf-8")
                messagebox.showinfo("Done", f"Saved to {out}")
            except Exception as e:
                messagebox.showerror("Error", str(e))


# --- Mode 2: Terminal User Interface (Curses) ---


class TuiApp:
    def __init__(self, root_path: Path):
        self.root_path = root_path
        self.root_node = TreeNode.build_tree(root_path)
        self.visible_nodes: List[tuple[TreeNode, int]] = []
        self.selected_idx = 0
        self.offset = 0

    def run(self):
        try:
            curses.wrapper(self._main_loop)
        except Exception as e:
            # Fallback for Windows users who forgot to install windows-curses
            print(f"TUI Error: {e}")
            print("If you are on Windows, run: pip install windows-curses")
            sys.exit(1)

    def _rebuild_visible_list(self):
        self.visible_nodes = []

        def recurse(node, depth):
            self.visible_nodes.append((node, depth))
            if node.is_dir and node.expanded:
                for child in node.children:
                    recurse(child, depth + 1)

        recurse(self.root_node, 0)

    def _main_loop(self, stdscr):  # noqa : ignore
        curses.curs_set(0)
        stdscr.nodelay(False)
        stdscr.keypad(True)

        curses.start_color()
        # Pair 1: Highlight (Black text on White bg)
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)

        while True:
            self._rebuild_visible_list()
            h, w = stdscr.getmaxyx()
            stdscr.erase()

            # Header
            header = f"Repo TUI: {self.root_path.name} | [Space]:Check [Enter]:Expand [g]:Generate [q]:Quit"
            stdscr.addstr(0, 0, header[: w - 1], curses.A_REVERSE)

            # List
            max_display = h - 2

            # Scroll handling
            if self.selected_idx < self.offset:
                self.offset = self.selected_idx
            elif self.selected_idx >= self.offset + max_display:
                self.offset = self.selected_idx - max_display + 1

            # Ensure safe bounds if list shrinks
            if self.selected_idx >= len(self.visible_nodes):
                self.selected_idx = len(self.visible_nodes) - 1

            for i in range(max_display):
                list_idx = self.offset + i
                if list_idx >= len(self.visible_nodes):
                    break

                node, depth = self.visible_nodes[list_idx]
                row = i + 1

                check_mark = "[x]" if node.checked else "[ ]"
                icon = ""
                if node.is_dir:
                    icon = "▼ " if node.expanded else "▶ "
                else:
                    icon = "  "

                line_str = f"{'  '*depth}{icon}{check_mark} {node.name}"
                style = (
                    curses.color_pair(1)
                    if list_idx == self.selected_idx
                    else curses.A_NORMAL
                )
                stdscr.addstr(row, 0, line_str[: w - 1], style)

            stdscr.refresh()

            # Input
            key = stdscr.getch()

            if key == curses.KEY_UP:
                self.selected_idx = max(0, self.selected_idx - 1)
            elif key == curses.KEY_DOWN:
                self.selected_idx = min(
                    len(self.visible_nodes) - 1, self.selected_idx + 1
                )
            elif key == ord(" "):
                node, _ = self.visible_nodes[self.selected_idx]
                node.toggle()
            elif key == 10 or key == 13:  # Enter
                node, _ = self.visible_nodes[self.selected_idx]
                if node.is_dir:
                    node.expanded = not node.expanded
            elif key == ord("g"):
                self._action_generate(stdscr)
                break
            elif key == ord("q"):
                sys.exit(0)

    def _action_generate(self, stdscr):
        files = self.root_node.get_selected_files()

        # Simple prompt overlay
        h, w = stdscr.getmaxyx()
        prompt_win = curses.newwin(3, w - 4, h // 2 - 1, 2)
        prompt_win.box()
        prompt_win.addstr(1, 2, "Output filename: ")
        prompt_win.refresh()

        curses.echo()
        curses.curs_set(1)

        # Read input
        out_bytes = prompt_win.getstr(1, 19)
        out_name = out_bytes.decode("utf-8").strip()

        if not out_name:
            out_name = "repo_dump.md"

        try:
            md = RepoProcessor.generate_markdown(files, self.root_path)
            Path(out_name).write_text(md, encoding="utf-8")
        except Exception as e:
            # Errors in TUI are hard to show without a proper dialog manager,
            # so we just crash gracefully printing error
            curses.endwin()
            print(f"Error generating file: {e}")
            sys.exit(1)


# --- Main Entry Point ---


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".", help="Root directory")
    parser.add_argument("-o", "--output", help="Output file (CLI mode only)")
    parser.add_argument("--tui", action="store_true", help="Use Terminal UI")
    parser.add_argument("--cli", action="store_true", help="Run headlessly")

    args = parser.parse_args()
    root_path = Path(args.root).resolve()

    if not root_path.is_dir():
        print(f"Error: {root_path} is not a directory")
        sys.exit(1)

    # 1. Headless / Simple CLI
    if args.cli or (args.output and not args.tui):
        files = RepoProcessor.scan_directory(root_path)
        out = args.output or "repo_dump.md"
        md = RepoProcessor.generate_markdown(files, root_path)
        Path(out).write_text(md, encoding="utf-8")
        print(f"Generated {out} ({len(files)} files)")
        return

    # 2. TUI Mode
    if args.tui:
        app = TuiApp(root_path)
        app.run()
        return

    # 3. GUI Mode (Default)
    try:
        root_tk = tk.Tk()
        app = GuiApp(root_tk, root_path)
        root_tk.mainloop()
    except Exception as e:
        print(f"GUI Error: {e}")
        print("Try running with --tui or --cli")


if __name__ == "__main__":
    main()
