# codetools

**codetools** is a toolkit for generating and managing code documentation and maintenance. It provides a suite of utilities designed to be CI/CD friendly, idempotent, and highly configurable.

## 🧰 The Toolkit

| Tool | CLI Command | Description |
| :--- | :--- | :--- |
| **Path Annotator** | `annotate` | **Recursive File Header Manager.**<br>Automatically inserts or updates canonical file path comments (e.g., `# src/utils.py`) at the top of source files. |
| **API Inventory** | `inventory` | **Static API Surface Extractor.**<br>Uses AST analysis to traverse a Python repository and generate a structured YAML inventory of all packages, modules, classes, and methods. |

-----

## 📦 Installation

This project requires **Python 3.12+**.

Since the project is configured as a package, you can install it directly from the source. This will install dependencies and register the `annotate` and `inventory` commands on your path.

**User Installation**

```bash
pip install .
```

**Developer Installation (Editable mode with dev tools)**

```bash
pip install -e ".[dev]"
```

-----

## 🚀 Quick Start

Once installed, you can run the tools directly from your terminal.

### 1\. Annotate (`path-annotate`)

Ensure every file in your project knows where it lives.

```bash
# Preview changes (Dry Run)
annotate --root . --config path-annotate.jsonc --dry-run

# Apply changes (Add headers to Python, JS, SQL, etc.)
annotate --root . --config path-annotate.jsonc
```

### 2\. Inventory (`py-api-inventory`)

Generate a snapshot of your project's public API.

```bash
# Generate a YAML report of the public API surface
inventory --root ./src --output api_dump.yaml --public-only

# Check statistics of the codebase (Summary only)
inventory --root ./src --print-summary --dry-run
```

-----

## 🤝 Contributing

This project uses `pre-commit` and `pytest` for quality assurance.

```bash
# Install pre-commit hooks
pre-commit install

# Run the test suite
pytest
```

For detailed configuration options regarding specific tools, please refer to the sub-readmes in `src/codetools/annotate` and `src/codetools/inventory`.