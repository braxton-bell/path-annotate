#!/usr/bin/env python3
"""
repo_to_markdown.py

Refactored to Class-Based Architecture with reusable "Winx" UI patterns.
"""

from __future__ import annotations

import argparse
import curses
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from codetools.shared.repo.repo_service import RepoService
from codetools.shared.repo.tree_node import TreeNode
from codetools.shared.ui.winx_gui_app import WinxGuiApp
from codetools.shared.ui.winx_tui_app import WinxTuiApp

# ==============================================================================
# SECTION 3: Application Implementations (CLI, GUI, TUI)
# ==============================================================================


class RepoCli:
    """Headless Command Line Interface."""

    def __init__(
        self,
        *,
        service: RepoService,
        root: Path,
        output: str,
        force_all: bool = False,
    ) -> None:
        self._service = service
        self._root = root
        self._output = output
        self._force_all = force_all

    def run(self) -> None:
        # 1. Scan for all valid files
        all_files = self._service.scan_directory(self._root)

        # 2. Determine selection logic
        final_files = []
        loaded_state = None

        if not self._force_all:
            loaded_state = self._service.load_selection_state(self._root)

        if loaded_state is not None:
            print("Using previous file selection (use --force-all to ignore)...")
            # Filter all_files against loaded_state
            for f in all_files:
                try:
                    rel = f.relative_to(self._root).as_posix()
                    if rel in loaded_state:
                        final_files.append(f)
                except ValueError:
                    continue
        else:
            if not self._force_all:
                print("No previous selection found. Defaulting to all files.")
            final_files = all_files

        # 3. Generate
        md = self._service.generate_markdown(final_files, self._root)
        Path(self._output).write_text(md, encoding="utf-8")
        print(f"Generated {self._output} ({len(final_files)} files)")


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

        # Load persistence state if available
        selected_paths = self._service.load_selection_state(path)

        # Use Factory to build tree via service rules
        self._root_node = TreeNode.build_tree(
            path, self._service, project_root=path, selected_paths=selected_paths
        )
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
                # Save State First
                self._service.save_selection_state(self._root_node.path, files)

                # Generate
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

        # Load state
        selected_paths = self._service.load_selection_state(root_path)

        self._root_node = TreeNode.build_tree(
            root_path, service, project_root=root_path, selected_paths=selected_paths
        )

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
            # Save State First
            self._service.save_selection_state(self._root_path, files)

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
    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Ignore previous selections and include all files (CLI only)",
    )

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
        app = RepoCli(
            service=service,
            root=root_path,
            output=out_file,
            force_all=args.force_all,
        )
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
