#!/usr/bin/env python3


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
