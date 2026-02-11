# Repo to Markdown (R2M)

A precision tool for AI-assisted development. R2M converts your source code into a single, well-structured Markdown document, optimized for pasting into LLMs (ChatGPT, Claude, Gemini, etc.).

Unlike raw copy-pasting, this tool preserves your project's **topology** by including a directory tree and clearly labeling file paths, giving the AI the context it needs to understand relationships between files.

## Features

-   **🎯 Precision Context:** Select exactly which files and folders to include using a GUI or Terminal UI.
-   **🌳 Project Topology:** Automatically generates a visual directory tree at the top of the output, grounding the AI in your project structure.
-   **🧠 LLM-Optimized Output:**
    -   Wraps code in correct language fences (e.g., \`python\`, \`json\`, \`rust\`).
    -   Normalizes whitespace (prevents Windows `\r\n` double-spacing issues).
    -   Escapes internal backticks to prevent Markdown breakage.
-   **🚀 Zero-Dependency:** Runs on standard Python libraries.
-   **💻 Three Modes:**
    1.  **GUI:** Desktop window with checkbox tree view (Default).
    2.  **TUI:** Terminal-based UI for SSH sessions or keyboard-centric workflows.
    3.  **CLI:** Headless mode for automation/scripts.

## Installation

No installation required. Just download the script.

**Prerequisites:**
-   Python 3.8+
-   *(Windows Users only)*: For TUI mode, install `windows-curses`:
    ```bash
    pip install windows-curses
    ```

## Usage

### 1. GUI Mode (Default)
Ideal for visual selection on a desktop.
```bash
python repo_to_markdown.py

```

* **Browse** to your target repository.
* **Check/Uncheck** files or entire folders to curate the context.
* Click **Generate** to save the `.md` file.

### 2. TUI Mode (Terminal UI)

Ideal for fast, keyboard-only usage or remote servers.

```bash
python repo_to_markdown.py --tui

```

**Controls:**

* `Arrow Keys`: Navigate
* `Space`: Toggle selection (checked/unchecked)
* `Enter`: Expand/Collapse directories
* `g`: Generate output file
* `q`: Quit

### 3. CLI Mode (Headless)

Ideal for automated dumps of an entire repo.

```bash
python repo_to_markdown.py /path/to/repo -o dump.md --cli

```

## Configuration

You can customize the script by editing the constants at the top of `repo_to_markdown.py`:

* `INCLUDE_EXTS`: Add extensions (e.g., `.cpp`, `.go`, `.java`) to include them in the scan.
* `SKIP_DIRS`: Add directories to ignore (e.g., `node_modules`, `venv`, `target`).
* `MAX_FILE_BYTES`: Adjust the file size limit (default 2MB) to prevent token overflow.

## Why use this?

**The Problem:**
When asking an AI to fix a bug involving multiple files, pasting them one by one loses the file path context. The AI doesn't know that `utils.py` is inside `src/core/`.

**The Solution:**
R2M produces a single artifact that looks like this:

```markdown
# Project Structure
.
├── src
│   ├── main.py
│   └── utils.py

## File Contents

### src/main.py
'''python
import utils
...
'''

### src/utils.py
'''python
def helper():
...
'''

```

> This allows the AI to "see" your project structure and dependencies instantly.