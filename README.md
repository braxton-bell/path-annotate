# codetools

**codetools** is a toolkit for generating and managing code documentation and maintenance. It provides a suite of utilities designed to be CI/CD friendly, idempotent, and highly configurable.

It ships as a single **commander-style CLI** (`codetools`) with sub-commands under:

- `codetools run <tool> [tool args...]`

This keeps your console entry points stable (one script) while still letting each tool keep its own argparse flags and help output.

## Project Structure

```text
.
├── .pre-commit-config.yaml
├── README.md
└── src
    └── codetools
        ├── cli.py                    # Commander entry point
        ├── annotate/                 # Tool: Path Annotator
        ├── inventory/                # Tool: API Inventory
        ├── markdown/                 # Tool: Repo to Markdown
        └── shared/                   # Shared Infrastructure
            ├── repo/                 # Domain Kernel (File scanning, Tree models)
            └── ui/                   # "Winx" UI Framework (TUI/GUI Base classes)

```

## 🧰 The Toolkit

| Tool | Commander Command | Description |
| :--- | :--- | :--- |
| **Path Annotator** | `codetools run annotate` | **Recursive File Header Manager.**<br>Automatically inserts or updates canonical file path comments (e.g., `# src/utils.py`) at the top of source files. |
| **API Inventory** | `codetools run inventory` | **Static API Surface Extractor.**<br>Uses AST analysis to traverse a Python repository and generate a structured YAML inventory of all packages, modules, classes, and methods. |
| **Repo → Markdown** | `codetools run markdown` | **LLM Context Packager.**<br>Converts a repository into a single, well-structured Markdown document (tree + file contents) optimized for pasting into LLMs. Supports GUI/TUI/CLI-style selection depending on the tool implementation. |

---

## 🏗️ Architecture & Shared Libraries

CodeTools is built on a modular kernel (`src/codetools/shared`) to ensure consistency across all utilities.

### 1. The Repository Kernel (`codetools.shared.repo`)

Centralizes the logic for how the toolkit "sees" a codebase.

* **`RepoService`**: Handles recursive directory scanning, enforcing `.gitignore` rules, and safe text reading.
* **`RepoConfig`**: Defines global constants for ignored directories (`.git`, `__pycache__`) and allowed extensions.
* **`TreeNode`**: A recursive data structure used to model the file system for UI rendering.

### 2. The Winx UI Framework (`codetools.shared.ui`)

A unified set of abstract base classes that allow tools to support multiple interface modes with minimal boilerplate.

* **`WinxTuiApp`**: Wraps `curses` handling, color initialization, and the main event loop for Terminal UIs.
* **`WinxGuiApp`**: Wraps `tkinter` setup and window management for Graphical UIs.

---

## 📦 Installation

This project requires **Python 3.12+**.

This project is configured as a package and uses **uv** for dependency management. Syncing will install dependencies and make the `codetools` command available in the environment.

**User Installation / Runtime deps**

```bash
uv sync

```

**Developer Installation (includes dev group)**

```bash
uv sync --all-groups

```

---

## 🚀 Quick Start

Once installed, run tools through the commander.

### 1. Annotate (Path Annotator)

Ensure every file in your project knows where it lives.

```bash
# Preview changes (Dry Run)
codetools run annotate --root . --config path-annotate.jsonc --dry-run

# Apply changes (Add headers to Python, JS, SQL, etc.)
codetools run annotate --root . --config path-annotate.jsonc

```

### 2. Inventory (API Inventory)

Generate a snapshot of your project's public API.

```bash
# Generate a YAML report of the public API surface
codetools run inventory --root ./src --output api_dump.yaml --public-only

# Check statistics of the codebase (Summary only)
codetools run inventory --root ./src --print-summary --dry-run

```

### 3. Markdown (Repo → Markdown)

Generate a single Markdown artifact containing a directory tree + selected file contents, intended for LLM prompts and reviews.

```bash
# Run the markdown tool (mode/flags are owned by the markdown tool itself)
codetools run markdown -h

```

#### `codetools run markdown ...` context

* `codetools run markdown` **passes all flags through** to the markdown tool’s own `argparse` (because the commander dispatch uses `parse_known_args()` and patches `sys.argv` for the downstream module).
* That means help/usage is always the tool’s help:

```bash
codetools run markdown -h

```

* And you run the tool the same way you would if it were standalone—just with the `codetools run markdown` prefix.

Examples (exact flags depend on your markdown tool implementation):

```bash
# Example: headless dump into a single artifact (if supported by the tool)
codetools run markdown /path/to/repo -o dump.md --cli

# Example: terminal UI mode (if supported by the tool)
codetools run markdown --tui

# Example: GUI mode default (if supported by the tool)
codetools run markdown

```

---

## 🤝 Contributing

This project uses `pre-commit` and `pytest` for quality assurance.

```bash
# Sync including dev tooling (pre-commit, pytest, linters, etc.)
uv sync --all-groups

# Install pre-commit hooks
pre-commit install

# Run the test suite
pytest

```

For detailed configuration options regarding specific tools, please refer to the sub-readmes in:

* `src/codetools/annotate`
* `src/codetools/inventory`
* `src/codetools/markdown`