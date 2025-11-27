# Path Comment Annotator (`path-annotate`)

A Python utility that recursively scans a directory and adds or updates a single, idempotent path comment at the top of matching files.

This tool ensures that source files contain a canonical reference to their own location within the project, which is invaluable for debugging, navigating large codebases, and maintaining consistency.

It is idempotent (safe to run repeatedly), highly configurable via JSONC, and built to be CI-friendly.

-----

### Before & After

**`path-annotate`** turns this:

```python
# File: src/app/utils.py

# A file that was moved, but the header is stale
# old/wrong/location.py

from os import path

def do_stuff():
    ...
```

...into this:

```python
# File: src/app/utils.py

# src/app/utils.py
from os import path

def do_stuff():
    ...
```

It **inserts** the header if missing, **updates** it if incorrect, and **leaves it** if correct.

-----

## Features

  * **Idempotent:** Never duplicates headers. Running it 100 times has the same result as running it once.
  * **Recursive & Fast:** Traverses the entire directory tree, using parallel processing for I/O.
  * **Configurable Signatures:** Define *which* files to touch and *how* to comment using a simple `jsonc` file (JSON with comments).
  * **Path Normalization:** Always uses POSIX-style forward slashes (`/`) in paths, regardless of the operating system (e.g., Windows).
  * **CI/CD Ready:** Includes a `--fail-on-change` flag that exits with a non-zero code if any files would be modified, perfect for pre-commit hooks or CI checks.
  * **Safe Dry-Run:** Use `--dry-run` to see what changes *would* be made without modifying any files.
  * **Smart Exclusions:** Supports global exclusions (`--exclude`) and per-signature exclusions, all using robust `.gitignore`-style glob patterns.
  * **Preserves Formatting:** Maintains the original file encoding (UTF-8 fallback) and newline style (`\n` vs. `\r\n`).

-----

## Requirements

  * Python 3.8+
  * Third-party libraries: `commentjson`, `pathspec`, `colorama`

## Installation

1.  **Install Dependencies:**

    ```bash
    pip install commentjson pathspec colorama
    ```

2.  **Get the Script:**
    Download or copy the `path_annotate.py` script into your project, (e.g., in a `scripts/` directory).

    Make it executable (optional, but convenient):

    ```bash
    chmod +x path_annotate.py
    ```

-----

## Usage

The tool is driven by a configuration file that defines the "signatures" for files you want to manage.

### 1\. Create a Configuration File

Create a file named `path-annotate.jsonc` (or any name you prefer). This file defines the rules for each file type.

**`path-annotate.jsonc`**

```jsonc
{
  // -----------------------------------------------------------------
  // Path Comment Annotator Signatures
  // -----------------------------------------------------------------
  // Signatures are processed in order. The first one that matches
  // a file is used.
  // -----------------------------------------------------------------

  "signatures": [
    {
      "name": "python",
      "enabled": true,
      "comment_prefix": "#",
      "required_suffix": ".py",
      "globs": ["**/*.py"],
      // Per-signature ignores
      "exclude": [
        "**/.venv/**",
        "**/__pycache__/**"
      ]
    },
    {
      "name": "sql",
      "enabled": true,
      "comment_prefix": "--",
      "required_suffix": ".sql",
      "globs": ["**/*.sql"],
      "exclude": [
        "**/logs/**",
        "**/target/**" // Exclude compiled build artifacts
      ]
    },
    {
      "name": "javascript",
      "enabled": true,
      "comment_prefix": "//",
      "required_suffix": ".js",
      "globs": ["**/*.js", "**/*.jsx"],
      "exclude": [
        "**/node_modules/**",
        "**/dist/**",
        "**/*.min.js" // Don't touch minified files
      ]
    },
    {
      "name": "typescript",
      "enabled": true,
      "comment_prefix": "//",
      "required_suffix": ".ts",
      "extensions": [".ts", ".tsx"], // You can also use extensions
      "exclude": [
        "**/node_modules/**",
        "**/dist/**"
      ]
    },
    {
      "name": "shell-disabled",
      "enabled": false, // This signature is currently disabled
      "comment_prefix": "#",
      "required_suffix": ".sh",
      "extensions": [".sh", ".bash"]
    }
  ]
}
```

### 2\. Run from the Command Line

The tool provides a simple CLI for execution.

```bash
usage: path_annotate.py [-h] --root ROOT --config CONFIG
                        [--exclude EXCLUDES]
                        [--signature ENABLED_SIGNATURE_NAMES]
                        [--dry-run] [--fail-on-change]
                        [--print-summary] [-j CONCURRENCY]
                        [-v | -q] [--no-color]

Recursively add or update a first-line path comment in files.

options:
  -h, --help            show this help message and exit
  --root ROOT           Top-level directory to process.
  --config CONFIG       JSON or JSONC configuration file defining
                        signatures.
  --exclude EXCLUDES    Paths or globs to omit (relative to --root).
                        Repeatable.
  --signature ENABLED_SIGNATURE_NAMES
                        Limit processing to one or more signature
                        names. Repeatable.
  --dry-run             Report what would change; do not write to any
                        files.
  --fail-on-change      Exit non-zero if any modifications would be/were
                        made.
  --print-summary       Print a final counts table at the end of the
                        run.
  -j CONCURRENCY, --concurrency CONCURRENCY
                        Optional parallelism (default: system CPU
                        count).
  -v, --verbose         Emit per-file decisions and reasons (DEBUG
                        level).
  -q, --quiet           Suppress non-errors (ERROR level).
  --no-color            Disable ANSI color codes in output.
```

### 3\. Common Examples

#### Example 1: Check for Changes (Dry Run)

Safely scan the `src` directory and report what *would* change, with per-file details. **No files will be modified.**

```bash
./path_annotate.py \
  --root ./src \
  --config ./path-annotate.jsonc \
  --dry-run \
  --print-summary \
  --verbose
```

#### Example 2: Apply All Changes

Scan the entire project, applying all changes defined in the config. This is the standard "fix" command.

```bash
./path_annotate.py \
  --root . \
  --config ./path-annotate.jsonc \
  --print-summary \
  --exclude "**/node_modules/**" \
  --exclude "**/.venv/**"
```

#### Example 3: CI / Pre-Commit Check

Run in "check mode." This command will be silent on success but will **exit with code 3** if any files are missing or have incorrect headers.

```bash
./path_annotate.py \
  --root . \
  --config ./path-annotate.jsonc \
  --fail-on-change \
  --quiet
```

#### Example 4: Run Only Specific Signatures

Apply changes, but only for the `python` and `sql` signatures defined in the config file.

```bash
./path_annotate.py \
  --root . \
  --config ./path-annotate.jsonc \
  --signature python \
  --signature sql \
  --print-summary
```

-----

## Exit Codes

The script uses specific exit codes, especially important for CI/CD pipelines.

  * `0`: Success. No errors occurred. (Changes may or may not have been made).
  * `1`: Usage or Configuration Error. (e.g., config file not found, bad JSON).
  * `2`: File Processing Error. One or more files failed to read or write.
  * `3`: Changes Detected. Triggered only when `--fail-on-change` is set and files were (or would be) inserted or updated.

-----

## Programmatic API

The tool is encapsulated in a class and can be imported and used directly in other Python scripts.

```python
from path_annotate import PathHeaderAnnotator, ConsoleManager
import logging

# 1. Set up a logger
console = ConsoleManager(level=logging.INFO, no_color=False)

try:
    # 2. Configure the annotator
    annotator = PathHeaderAnnotator.from_config(
        root="./src",
        config_path="./path-annotate.jsonc",
        logger=console,
        excludes=["**/node_modules/**"],
        dry_run=True
    )
    
    # 3. Run the scan
    report = annotator.run()

    # 4. Use the results
    console.print_summary(report)
    if report.total_changes > 0:
        print("Changes were detected!")

except Exception as e:
    console.critical(f"Failed to run annotator: {e}")

```

-----