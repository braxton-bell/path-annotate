#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from codetools.shared.repo.repo_service import RepoService


class TreeNode:
    """Recursive data structure for the file tree."""

    def __init__(
        self, path: Path, is_dir: bool, parent: "TreeNode" | None = None
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
    def build_tree(  # noqa : ignore
        root_path: Path,
        service: RepoService,
        project_root: Path | None = None,
        selected_paths: set[str] | None = None,
    ) -> TreeNode:
        """
        Factory method to build the tree using service rules.

        :param root_path: The current directory being processed.
        :param service: The repo service logic.
        :param project_root: The top-level root of the project (used for relative path matching).
        :param selected_paths: A set of relative path strings to check. If None, check all.
        """
        # On first call, project_root is typically the root_path
        if project_root is None:
            project_root = root_path

        node = TreeNode(root_path, True)

        # If we are in "restore state" mode (selected_paths is not None),
        # default directory checked state to False. Visual expansion is left default.
        if selected_paths is not None:
            node.checked = False

        try:
            items = sorted(
                root_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())
            )
            for item in items:
                if item.is_dir():
                    if service.should_skip_dir(item.name):
                        continue
                    child_node = TreeNode.build_tree(
                        item, service, project_root, selected_paths
                    )
                    child_node.parent = node
                    # Only add dir if it has content
                    if child_node.children:
                        node.children.append(child_node)
                else:
                    if service.should_include_file(item):
                        child_node = TreeNode(item, False, parent=node)

                        # Apply selection state logic
                        if selected_paths is not None:
                            try:
                                rel_path = item.relative_to(project_root).as_posix()
                                child_node.checked = rel_path in selected_paths
                            except ValueError:
                                child_node.checked = False
                        else:
                            # Default behavior: All checked
                            child_node.checked = True

                        node.children.append(child_node)
        except PermissionError:
            pass
        return node
