# Python API Signature Extractor

`py_api_inventory.py` is a read-only, deterministic utility that traverses a Python repository and generates a YAML inventory of its API surface. It uses `ast` (Abstract Syntax Trees) for static analysis and **does not import or execute** any of the target project's code.

It is designed to capture:
* Packages (based on configurable strategy)
* Modules (`.py` files)
* Classes
* Methods (instance, class, static) with full signatures
* Module-level and Class-level Constants (optional)
* Enums (optional)
* Docstrings (optional)
* Module-level functions (optional)

---

## Installation

The tool requires a few third-party Python packages.

1.  Clone or download the script (`py_api_inventory.py`) and `requirements.txt`.
2.  Install dependencies:
    ```sh
    pip install -r requirements.txt
    ```

If you are using the associated `path_annotate.py` utility, ensure it is available in your `PYTHONPATH` so this script can use its `ConsoleManager` for a consistent logging UX. If not found, the script will use an internal fallback.

---

## Usage

### 🚀 CLI Examples

**Example 1: Basic inventory**

Scan the current directory, use the example config, find `pyproject.toml`, and write to `api_signatures.yaml` with a summary.

```sh
./py_api_inventory.py \
  --root . \
  --config ./py_api_inventory.jsonc \
  --output ./api_signatures.yaml \
  --pyproject ./pyproject.toml \
  --print-summary
```

**Example 2: Strict packages with docstrings**

Scan the `./src` directory, require `__init__.py` for packages, include docstrings, and only list `ALL_CAPS` constants.

```
./py_api_inventory.py \
  --root ./src \
  --package-mode require_init_py \
  --include-docstrings \
  --include-constants \
  --constant-visibility uppercase \
  --output ./api_signatures.yaml
```

**Example 3: Include all methods and functions, stream to stdout**

Scan the current directory, include private (`_`) and dunder (`__`) methods, include module-level functions, and pipe the YAML to `stdout`.

```
./py_api_inventory.py \
  --root . \
  --all-methods \
  --include-functions \
  --stdout
```

### 🖥️ Programmatic API

The tool is implemented as a class and can be imported and used from other Python scripts.

```
import sys
from py_api_inventory import PythonApiSignatureExtractor, ConsoleManager

# 1. Initialize a logger (real or fallback)
logger = ConsoleManager()

try:
    # 2. Configure the extractor using the classmethod factory
    extractor = PythonApiSignatureExtractor.from_config(
        root="/path/to/your/repo",
        logger=logger,
        # Pass CLI overrides directly
        config_path="/path/to/py_api_inventory.jsonc",
        pyproject_path="/path/to/your/repo/pyproject.toml",
        include_docstrings=True,
        public_only=False
    )
    
    # 3. Run the analysis
    # This is the CPU-intensive step
    report = extractor.run()
    
    # 4. Write the results
    extractor.write_yaml(report, output_path="inventory.yaml")

    print("API inventory complete.")

except (FileNotFoundError, ValueError) as e:
    logger.error(f"Configuration error: {e}")
    sys.exit(1)
except Exception as e:
    logger.error(f"Failed to run inventory: {e}")
    sys.exit(2)
```

* * *

Configuration (`py_api_inventory.jsonc`)
----------------------------------------

The tool is configured via a JSON/JSONC file and/or CLI arguments. CLI arguments always override file values.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `public_only` | boolean | `true` | If `true`, ignores items starting with `_` (except `__init__`). |
| `include_constants` | boolean | `false` | If `true`, inventories module/class constants. |
| `include_docstrings` | boolean | `false` | If `true`, captures docstrings for all items. |
| `include_enums` | boolean | `true` | If `true`, identifies `Enum` subclasses. |
| `include_functions` | boolean | `false` | If `true`, inventories module-level functions. |
| `strip_docstrings` | boolean | `false` | If `true`, applies `.strip()` to captured docstrings. |
| `package_mode` | string | `any_dir_with_py` | Strategy for package detection. See options below. |
| `constant_visibility` | string | `no_underscore` | Strategy for constant detection. See options below. |
| `leading_slash_in_paths` | boolean | `true` | If `true`, prepends a `/` to all `path` fields. |
| `exclude` | array\[string\] | `[...]` | List of git-style glob patterns to exclude. |

### `package_mode`

*   `"any_dir_with_py"`: (Default) Any directory that contains a `.py` file is treated as a package.
*   `"require_init_py"`: Only directories containing an `__init__.py` file are treated as packages.

### `constant_visibility`

*   `"no_underscore"`: (Default) Any module/class-level variable assignment not starting with `_` is a constant.
*   `"uppercase"`: Only module/class-level variables with `ALL_CAPS` names are constants.

* * *

YAML Output Schema
------------------

The output is a single YAML document conforming to the following structure. Optional keys (like `docstring` or `constants`) will be omitted entirely if disabled via config or if no items are found.

```
# Schema version for this output format
schema_version: "1.0"
meta:
  # ISO-8601 UTC timestamp of when the report was generated
  generated_at: "YYYY-MM-DDTHH:MM:SSZ"
  package:
    # Populated from pyproject.toml (PEP 621 or Poetry)
    name: "mypackage"
    version: "1.2.3"
  # The absolute, resolved path to the scanned root
  root: "/path/to/repo"
  # A snapshot of the configuration used for this run
  config_effective:
    public_only: true
    include_constants: true
    include_docstrings: true
    include_enums: true
    include_functions: false
    package_mode: "any_dir_with_py"
    leading_slash_in_paths: true
    constant_visibility: "no_underscore"
    strip_docstrings: false
    exclude: ["**/.venv/**"]
    concurrency: 8

# Statistics from the run
stats:
  files_scanned: 0
  files_excluded: 0
  files_parsed_ok: 0
  files_parse_errors: 0
  packages: 0
  modules: 0
  classes: 0
  methods: 0
  constants: 0
  enums: 0
  functions: 0

# List of all packages found
packages:
  # A package directory
  - path: "/src/pkg/subpkg"                # POSIX relpath from root (with/without leading /)
    qname: "src.pkg.subpkg"                # Dotted path from root
    is_package: true
    # List of modules within this package
    modules:
      - path: "/src/pkg/subpkg/module.py"
        qname: "src.pkg.subpkg.module"
        docstring: "Module-level docstring."  # Omitted if empty or include_docstrings=false
        
        # Module-level constants (if include_constants=true)
        constants:
          - name: "MAX_SIZE"
            visibility: "public"           # "public" | "private" | "dunder"
            scope: "module"
            value: 100                     # JSON-safe literal, if simple
            value_repr: "100"              # String representation of the value
            
        # Module-level enums (if include_enums=true)
        enums:
          - name: "Color"
            qname: "src.pkg.subpkg.module.Color"
            docstring: "An enumeration of colors."
            members:
              - name: "RED"
                value_repr: "1"
              - name: "GREEN"
                value_repr: "auto()"

        # Module-level functions (if include_functions=true)
        functions:
          - name: "module_helper"
            qname: "src.pkg.subpkg.module.module_helper"
            visibility: "public"
            decorators: ["@functools.lru_cache"]
            signature:
              params:
                - { name: "arg1", kind: "positional_or_keyword", annotation: "str", default: null }
              returns: "bool"
            docstring: "Helper function docstring."

        # List of classes within this module
        classes:
          - name: "MyClass"
            qname: "src.pkg.subpkg.module.MyClass"
            docstring: "Class-level docstring."
            
            # Class-level constants (if include_constants=true)
            constants:
              - name: "DEFAULT_TIMEOUT"
                visibility: "public"
                scope: "class"
                value: 30
                value_repr: "30"
                
            # List of methods in this class
            methods:
              - name: "__init__"
                qname: "src.pkg.subpkg.module.MyClass.__init__"
                visibility: "dunder"
                kind: "instance"           # "instance" | "class" | "static"
                decorators: []             # List of decorator names as strings
                signature:
                  params:
                    - { name: "self", kind: "positional_or_keyword", annotation: null, default: null }
                    - { name: "timeout", kind: "positional_or_keyword", annotation: "int", default: "30" }
                  returns: null
                docstring: "Constructor docstring."
                
              - name: "ping"
                qname: "src.pkg.subpkg.module.MyClass.ping"
                visibility: "public"
                kind: "instance"
                decorators: []
                signature:
                  params:
                    - { name: "self", kind: "positional_or_keyword", annotation: null, default: null }
                    - { name: "host", kind: "positional_or_keyword", annotation: "str", default: null }
                    - { name: "timeout", kind: "keyword_only", annotation: "float", default: "1.0" }
                    - { name: "args", kind: "var_positional", annotation: null, default: null }
                    - { name: "kwargs", kind: "var_keyword", annotation: null, default: null }
                  returns: "bool"
                docstring: "Pings a host."
```

* * *
