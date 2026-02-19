#!/usr/bin/env python3
"""
repo_to_markdown.py

Refactored to Class-Based Architecture with reusable "Winx" UI patterns.
"""

from __future__ import annotations

import argparse
import curses
import os
import sys
import tkinter as tk
from abc import ABC, abstractmethod
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

# ==============================================================================
# SECTION 1: Winx UI Library (Reusable Patterns)
# ==============================================================================


class WinxTuiApp(ABC):
    """
    Abstract Base Class for Terminal User Interfaces using Curses.
    Provides the standard wrapper and exception handling loop.
    """

    def __init__(self) -> None:
        self._running = True

    def run(self) -> None:
        """Entry point for the TUI."""
        try:
            # curses.wrapper handles init/teardown of colors, keypad, echo, etc.
            curses.wrapper(self._main_loop)
        except curses.error as e:
            # Fallback for Windows users missing windows-curses
            if sys.platform == "win32":
                print(f"WinxTui Error: {e}")
                print("On Windows, please run: pip install windows-curses")
            else:
                print(f"Curses Error: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            sys.exit(0)

    def _main_loop(self, stdscr: Any) -> None:
        """The main event loop. Override setup/draw/input methods, not this."""
        # Standard setup
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(False)  # Blocking input by default
        stdscr.keypad(True)
        curses.start_color()
        self.setup_colors()

        while self._running:
            h, w = stdscr.getmaxyx()
            stdscr.erase()

            self.draw(stdscr, h, w)
            stdscr.refresh()

            key = stdscr.getch()
            self.handle_input(stdscr, key)

    def setup_colors(self) -> None:
        """Override to define color pairs."""
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)

    @abstractmethod
    def draw(self, stdscr: Any, h: int, w: int) -> None:
        """Render the UI."""
        pass

    @abstractmethod
    def handle_input(self, stdscr: Any, key: int) -> None:
        """Handle key presses."""
        pass


class WinxGuiApp(ABC):
    """
    Abstract Base Class for Graphical User Interfaces using Tkinter.
    """

    def __init__(self, title: str = "Winx App", size: str = "600x600") -> None:
        self._root = tk.Tk()
        self._root.title(title)
        self._root.geometry(size)
        self._setup_core_widgets()

    def _setup_core_widgets(self) -> None:
        """Initial widget setup."""
        self.setup_ui(self._root)

    @abstractmethod
    def setup_ui(self, root: tk.Tk) -> None:
        """Build your widgets here."""
        pass

    def run(self) -> None:
        """Start the Tkinter main loop."""
        try:
            self._root.mainloop()
        except Exception as e:
            print(f"WinxGui Error: {e}")


# ==============================================================================
# SECTION 2: Domain Logic & Data Structures
# ==============================================================================


class RepoConfig:
    """Configuration singleton for file filtering."""

    INCLUDE_EXTS: set[str] = {
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

    SKIP_DIRS: set[str] = {
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

    SKIP_FILES: set[str] = {
        ".DS_Store",
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
        "Cargo.lock",
    }

    MAX_FILE_BYTES: int = 2_000_000


class TreeNode:
    """Recursive data structure for the file tree."""

    def __init__(
        self, path: Path, is_dir: bool, parent: TreeNode | None = None
    ) -> None:
        self.path = path
        self.name = path.name
        self.is_dir = is_dir
        self.parent = parent
        self.children: list[TreeNode] = []
        self.checked = True
        self.expanded = True

    def toggle(self, state: bool | None = None) -> None:
        """Toggle check state, optionally forcing a state."""
        new_state = not self.checked if state is None else state
        self.checked = new_state
        for child in self.children:
            child.toggle(new_state)

    def get_selected_files(self) -> list[Path]:
        """Return list of selected file paths."""
        selected = []
        if not self.is_dir and self.checked:
            selected.append(self.path)
        for child in self.children:
            selected.extend(child.get_selected_files())
        return selected

    @staticmethod
    def build_tree(root_path: Path, service: RepoService) -> TreeNode:
        """Factory method to build the tree using service rules."""
        node = TreeNode(root_path, True)
        try:
            items = sorted(
                root_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())
            )
            for item in items:
                if item.is_dir():
                    if service.should_skip_dir(item.name):
                        continue
                    child_node = TreeNode.build_tree(item, service)
                    child_node.parent = node
                    # Only add dir if it has content
                    if child_node.children:
                        node.children.append(child_node)
                else:
                    if service.should_include_file(item):
                        child_node = TreeNode(item, False, parent=node)
                        node.children.append(child_node)
        except PermissionError:
            pass
        return node


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


# ==============================================================================
# SECTION 3: Application Implementations (CLI, GUI, TUI)
# ==============================================================================


class RepoCli:
    """Headless Command Line Interface."""

    def __init__(self, *, service: RepoService, root: Path, output: str) -> None:
        self._service = service
        self._root = root
        self._output = output

    def run(self) -> None:
        files = self._service.scan_directory(self._root)
        md = self._service.generate_markdown(files, self._root)
        Path(self._output).write_text(md, encoding="utf-8")
        print(f"Generated {self._output} ({len(files)} files)")


class RepoGui(WinxGuiApp):
    """Graphical Implementation using WinxGuiApp."""

    def __init__(self, *, service: RepoService, root_path: Path) -> None:
        self._service = service
        self._start_path = root_path
        self._tree_map: dict[str, TreeNode] = {}
        self._root_node: TreeNode | None = None
        super().__init__(title="Repo to Markdown", size="600x600")

    def setup_ui(self, root: tk.Tk) -> None:
        # Controls
        frame_top = ttk.Frame(root, padding=5)
        frame_top.pack(fill="x")
        ttk.Button(frame_top, text="Browse", command=self._browse).pack(side="left")
        ttk.Button(frame_top, text="Generate", command=self._generate).pack(
            side="right"
        )

        # TreeView
        frame_tree = ttk.Frame(root, padding=5)
        frame_tree.pack(fill="both", expand=True)

        self._tree = ttk.Treeview(frame_tree, selectmode="browse")
        ysb = ttk.Scrollbar(frame_tree, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=ysb.set)

        self._tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self._tree.bind("<ButtonRelease-1>", self._on_click)

        # Initial Load
        self._load_tree(self._start_path)

    def _load_tree(self, path: Path) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._tree_map.clear()

        # Use Factory to build tree via service rules
        self._root_node = TreeNode.build_tree(path, self._service)
        self._insert_node("", self._root_node)

    def _insert_node(self, parent_id: str, node: TreeNode) -> None:
        icon = "☒" if node.checked else "☐"
        text = f"{icon} {node.name}"
        oid = self._tree.insert(parent_id, "end", text=text, open=node.expanded)
        self._tree_map[oid] = node
        for child in node.children:
            self._insert_node(oid, child)

    def _refresh_node_visuals(self, oid: str) -> None:
        node = self._tree_map[oid]
        icon = "☒" if node.checked else "☐"
        self._tree.item(oid, text=f"{icon} {node.name}")
        for child_oid in self._tree.get_children(oid):
            self._refresh_node_visuals(child_oid)

    def _on_click(self, event: Any) -> None:
        region = self._tree.identify("region", event.x, event.y)
        if region == "tree":
            oid = self._tree.identify_row(event.y)
            if oid:
                node = self._tree_map[oid]
                node.toggle()
                self._refresh_node_visuals(oid)

    def _browse(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self._load_tree(Path(d))

    def _generate(self) -> None:
        if not self._root_node:
            return
        files = self._root_node.get_selected_files()
        if not files:
            messagebox.showwarning("Empty", "No files selected.")
            return

        out = filedialog.asksaveasfilename(
            defaultextension=".md", initialfile="repo_dump.md"
        )
        if out:
            try:
                md = self._service.generate_markdown(files, self._root_node.path)
                Path(out).write_text(md, encoding="utf-8")
                messagebox.showinfo("Done", f"Saved to {out}")
            except Exception as e:
                messagebox.showerror("Error", str(e))


class RepoTui(WinxTuiApp):
    """Terminal Implementation using WinxTuiApp."""

    def __init__(self, *, service: RepoService, root_path: Path) -> None:
        super().__init__()
        self._service = service
        self._root_path = root_path
        self._root_node = TreeNode.build_tree(root_path, service)

        # State
        self._visible_nodes: list[tuple[TreeNode, int]] = []
        self._selected_idx = 0
        self._offset = 0

    def _rebuild_visible_list(self) -> None:
        self._visible_nodes = []

        def recurse(node: TreeNode, depth: int) -> None:
            self._visible_nodes.append((node, depth))
            if node.is_dir and node.expanded:
                for child in node.children:
                    recurse(child, depth + 1)

        recurse(self._root_node, 0)

    def draw(self, stdscr: Any, h: int, w: int) -> None:
        self._rebuild_visible_list()

        # Header
        header = f"Repo TUI: {self._root_path.name} | [Space]:Check [Enter]:Expand [g]:Generate [q]:Quit"
        stdscr.addstr(0, 0, header[: w - 1], curses.A_REVERSE)

        max_display = h - 2

        # Scroll Logic
        if self._selected_idx < self._offset:
            self._offset = self._selected_idx
        elif self._selected_idx >= self._offset + max_display:
            self._offset = self._selected_idx - max_display + 1

        if self._selected_idx >= len(self._visible_nodes):
            self._selected_idx = len(self._visible_nodes) - 1

        for i in range(max_display):
            list_idx = self._offset + i
            if list_idx >= len(self._visible_nodes):
                break

            node, depth = self._visible_nodes[list_idx]
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
                if list_idx == self._selected_idx
                else curses.A_NORMAL
            )
            stdscr.addstr(row, 0, line_str[: w - 1], style)

    def handle_input(self, stdscr: Any, key: int) -> None:
        if key == curses.KEY_UP:
            self._selected_idx = max(0, self._selected_idx - 1)
        elif key == curses.KEY_DOWN:
            self._selected_idx = min(
                len(self._visible_nodes) - 1, self._selected_idx + 1
            )
        elif key == ord(" "):
            if self._visible_nodes:
                node, _ = self._visible_nodes[self._selected_idx]
                node.toggle()
        elif key in (10, 13):  # Enter
            if self._visible_nodes:
                node, _ = self._visible_nodes[self._selected_idx]
                if node.is_dir:
                    node.expanded = not node.expanded
        elif key == ord("q"):
            sys.exit(0)
        elif key == ord("g"):
            self._action_generate(stdscr)
            self._running = False

    def _action_generate(self, stdscr: Any) -> None:
        files = self._root_node.get_selected_files()

        h, w = stdscr.getmaxyx()
        prompt_win = curses.newwin(3, w - 4, h // 2 - 1, 2)
        prompt_win.box()
        prompt_win.addstr(1, 2, "Output filename: ")
        prompt_win.refresh()

        curses.echo()
        curses.curs_set(1)

        out_bytes = prompt_win.getstr(1, 19)
        out_name = out_bytes.decode("utf-8").strip() or "repo_dump.md"

        try:
            md = self._service.generate_markdown(files, self._root_path)
            Path(out_name).write_text(md, encoding="utf-8")
        except Exception as e:
            # We are exiting anyway, so printing to stderr works after endwin() is called by wrapper
            raise e


# ==============================================================================
# SECTION 4: Main Entry Point
# ==============================================================================


def main() -> None:
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

    # Initialize Core Service
    service = RepoService(app_config={})

    # Mode Selection
    if args.cli or (args.output and not args.tui):
        out_file = args.output or "repo_dump.md"
        app = RepoCli(service=service, root=root_path, output=out_file)
        app.run()
        return

    if args.tui:
        tui_app = RepoTui(service=service, root_path=root_path)
        tui_app.run()
        return

    # Default to GUI
    try:
        gui_app = RepoGui(service=service, root_path=root_path)
        gui_app.run()
    except Exception as e:
        print(f"GUI Error: {e}")
        print("Try running with --tui or --cli")


if __name__ == "__main__":
    main()
