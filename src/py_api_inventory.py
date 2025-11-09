"""
py_api_inventory.py

Traverses a Python repository and outputs a YAML inventory of the repository's 
API surface (packages, modules, classes, methods, constants, etc.) using
static analysis via `ast`.

This tool is read-only and does not import or execute any of the target code.
"""

import argparse
import ast
import concurrent.futures
import dataclasses
import datetime
import enum
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import (
    Any, Dict, List, Literal, Optional, Set, Tuple, TypedDict, Union
)


# --- Dependency Imports ---
try:
    import colorama
    colorama.just_fix_windows_console()
    _HAS_COLORAMA = True
except ImportError:
    _HAS_COLORAMA = False

try:
    import commentjson
    _HAS_COMMENTJSON = True
except ImportError:
    print(
        "Error: 'commentjson' package not found. Please install it: "
        "pip install commentjson",
        file=sys.stderr
    )
    _HAS_COMMENTJSON = False

try:
    import pathspec
    _HAS_PATHSPEC = True
except ImportError:
    print(
        "Error: 'pathspec' package not found. Please install it: "
        "pip install pathspec",
        file=sys.stderr
    )
    _HAS_PATHSPEC = False

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    print(
        "Error: 'PyYAML' package not found. Please install it: "
        "pip install PyYAML",
        file=sys.stderr
    )
    _HAS_YAML = False

# Conditional TOML parser import
if sys.version_info >= (3, 11):
    import tomllib
    _HAS_TOML = True
else:
    try:
        import tomli
        tomllib = tomli
        _HAS_TOML = True
    except ImportError:
        _HAS_TOML = False
        # We only fail if the user *tries* to parse a pyproject.toml
        pass

# --- Fallback/Shared Utility Imports ---

# Attempt to import from path_annotate.py; provide fallbacks if unavailable.
try:
    # Assuming path_annotate.py is in PYTHONPATH
    from path_annotate import ConsoleManager, PathHeaderAnnotator
    _normalize_relpath = PathHeaderAnnotator.normalize_relpath
    _HAS_PATH_ANNOTATE = True
except ImportError:
    _HAS_PATH_ANNOTATE = False

    # class _FallbackConsoleManager:
    #     """Minimal ConsoleManager fallback."""
    #     INFO = 1
    #     WARN = 2
    #     ERROR = 3
        
    #     class LogLevel(int, enum.Enum):
    #         DEBUG = 0
    #         INFO = 1
    #         WARN = 2
    #         ERROR = 3
    #         QUIET = 99

    #     def __init__(self, level: int = LogLevel.INFO, no_color: bool = False):
    #         self.level = level
    #         self.no_color = no_color or not _HAS_COLORAMA or not sys.stderr.isatty()
    #         if not _HAS_COLORAMA and not no_color and sys.stderr.isatty():
    #             print(
    #                 "[py_api_inventory] 'colorama' not installed, color output disabled.",
    #                 file=sys.stderr
    #             )

    #     def set_level(self, level: int):
    #         self.level = level

    #     def _log(self, level: int, prefix: str, color, msg: str, **kwargs):
    #         if level < self.level:
    #             return
            
    #         if self.no_color:
    #             print(f"[{prefix}] {msg}", file=sys.stderr)
    #         else:
    #             print(
    #                 f"{color}[{prefix}]{colorama.Style.RESET_ALL} {msg}",
    #                 file=sys.stderr
    #             )

    #     def info(self, msg: str, **kwargs):
    #         self._log(
    #             self.LogLevel.INFO, "INFO", 
    #             colorama.Fore.CYAN if _HAS_COLORAMA else "", msg
    #         )
        
    #     def warn(self, msg: str, **kwargs):
    #         self._log(
    #             self.LogLevel.WARN, "WARN",
    #             colorama.Fore.YELLOW if _HAS_COLORAMA else "", msg
    #         )
        
    #     def error(self, msg: str, **kwargs):
    #         self._log(
    #             self.LogLevel.ERROR, "ERROR",
    #             colorama.Fore.RED if _HAS_COLORAMA else "", msg
    #         )

    #     def debug(self, msg: str, **kwargs):
    #         self._log(
    #             self.LogLevel.DEBUG, "DEBUG",
    #             colorama.Fore.MAGENTA if _HAS_COLORAMA else "", msg
    #         )

    #     def success(self, msg: str, **kwargs):
    #         self._log(
    #             self.LogLevel.INFO, "SUCCESS",
    #             colorama.Fore.GREEN if _HAS_COLORAMA else "", msg
    #         )

    # ConsoleManager = _FallbackConsoleManager

    def _fallback_normalize_relpath(root: Path, file_path: Path) -> str:
        """Minimal path normalization fallback."""
        try:
            rel_path = file_path.resolve().relative_to(root.resolve())
            return rel_path.as_posix()
        except ValueError:
            # Fallback if not relative (e.g., symlinks)
            return file_path.as_posix()
    
    _normalize_relpath = _fallback_normalize_relpath


# --- Type Definitions & Data Models ---

# Using TypedDict for YAML serialization simplicity (vs. @dataclass)
# These must match the YAML Schema documentation.

class Param(TypedDict):
    name: str
    kind: Literal[
        "positional_only",
        "positional_or_keyword",
        "var_positional",
        "keyword_only",
        "var_keyword"
    ]
    annotation: Optional[str]
    default: Optional[str]

class FunctionSignature(TypedDict):
    params: List[Param]
    returns: Optional[str]

class ConstantRecord(TypedDict):
    name: str
    visibility: Literal["public", "private", "dunder"]
    scope: Literal["module", "class"]
    value: Optional[Any]  # JSON-safe simple literal
    value_repr: str       # Always present

class EnumMemberRecord(TypedDict):
    name: str
    value_repr: str

class EnumRecord(TypedDict):
    name: str
    qname: str
    docstring: Optional[str]
    members: List[EnumMemberRecord]

class MethodRecord(TypedDict):
    name: str
    qname: str
    visibility: Literal["public", "private", "dunder"]
    kind: Literal["instance", "class", "static"]
    decorators: List[str]
    signature: FunctionSignature
    docstring: Optional[str]

class FunctionRecord(TypedDict):
    """For module-level functions."""
    name: str
    qname: str
    visibility: Literal["public", "private", "dunder"]
    decorators: List[str]
    signature: FunctionSignature
    docstring: Optional[str]

class ClassRecord(TypedDict):
    name: str
    qname: str
    docstring: Optional[str]
    constants: List[ConstantRecord]  # Optional presence
    methods: List[MethodRecord]
    
class ModuleRecord(TypedDict):
    path: str
    qname: str
    docstring: Optional[str]
    constants: List[ConstantRecord]  # Optional presence
    enums: List[EnumRecord]          # Optional presence
    functions: List[FunctionRecord]  # Optional presence
    classes: List[ClassRecord]

class PackageRecord(TypedDict):
    path: str
    qname: str
    is_package: Literal[True]
    modules: List[ModuleRecord]

class InventoryStats(TypedDict):
    files_scanned: int
    files_excluded: int
    files_parsed_ok: int
    files_parse_errors: int
    packages: int
    modules: int
    classes: int
    methods: int
    constants: int
    enums: int
    functions: int

class Metadata(TypedDict):
    schema_version: str
    generated_at: str
    package: Dict[str, Optional[str]]
    root: str
    config_effective: Dict[str, Any]

class InventoryReport(TypedDict):
    meta: Metadata
    stats: InventoryStats
    packages: List[PackageRecord]


# --- Configuration Defaults ---

DEFAULT_CONFIG = {
    "public_only": True,
    "include_constants": False,
    "include_docstrings": False,
    "include_enums": True,
    "include_functions": False,
    "package_mode": "any_dir_with_py",
    "leading_slash_in_paths": True,
    "constant_visibility": "no_underscore",
    "strip_docstrings": False,
    "exclude": [
        "**/.venv/**",
        "**/__pycache__/**",
        "**/build/**",
        "**/dist/**",
        "**/node_modules/**",
        "**/*.egg-info/**",
        "**/.*",  # Exclude .git, .vscode, etc.
    ],
    # Internal/CLI only, not from JSON
    "concurrency": os.cpu_count() or 1,
}

# --- Main Implementation Class ---

class PythonApiSignatureExtractor:
    """
    Recursively analyzes a Python repository and emits a YAML inventory
    of packages, modules, classes, methods, constants, and enums per config.
    
    Uses AST static analysis; does not import or execute target code.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        root: Path,
        logger: ConsoleManager,
        path_matcher: Optional["pathspec.PathSpec"] = None,
    ):
        self.config = config
        self.root = root
        self.logger = logger
        self.path_matcher = path_matcher
        
        # Validate config
        self._validate_config()
        
        # Set CPU-bound work concurrency
        self.concurrency = max(1, self.config.get("concurrency", os.cpu_count() or 1))

    def _validate_config(self):
        """Ensure critical config values are valid."""
        pkg_mode = self.config.get("package_mode")
        if pkg_mode not in ("any_dir_with_py", "require_init_py"):
            raise ValueError(
                f"Invalid 'package_mode': {pkg_mode}. Must be "
                "'any_dir_with_py' or 'require_init_py'."
            )
        
        const_vis = self.config.get("constant_visibility")
        if const_vis not in ("no_underscore", "uppercase"):
            raise ValueError(
                f"Invalid 'constant_visibility': {const_vis}. Must be "
                "'no_underscore' or 'uppercase'."
            )

    @classmethod
    def from_config(
        cls,
        root: str,
        logger: "ConsoleManager",
        *,
        config_path: Optional[str] = None,
        excludes: Optional[List[str]] = None,
        pyproject_path: Optional[str] = None,
        public_only: Optional[bool] = None,
        include_constants: Optional[bool] = None,
        include_docstrings: Optional[bool] = None,
        include_enums: Optional[bool] = None,
        include_functions: Optional[bool] = None,
        package_mode: Optional[str] = None,
        leading_slash_in_paths: Optional[bool] = None,
        constant_visibility: Optional[str] = None,
        strip_docstrings: Optional[bool] = None,
        concurrency: Optional[int] = None,
    ) -> "PythonApiSignatureExtractor":
        """Load JSON/JSONC config, apply CLI overrides, validate, and construct."""
        
        if not _HAS_COMMENTJSON:
             raise ImportError(
                 "Configuration file requires 'commentjson' to be installed."
             )

        # 1. Start with defaults
        config = DEFAULT_CONFIG.copy()

        # 2. Load from config file
        if config_path:
            config_p = Path(config_path)
            if not config_p.is_file():
                raise FileNotFoundError(f"Config file not found: {config_path}")
            try:
                with open(config_p, 'r', encoding='utf-8') as f:
                    config_from_file = commentjson.load(f)
                config.update(config_from_file)
            except Exception as e:
                raise IOError(f"Failed to parse config file {config_path}: {e}")

        # 3. Apply CLI overrides
        cli_overrides = {
            "public_only": public_only,
            "include_constants": include_constants,
            "include_docstrings": include_docstrings,
            "include_enums": include_enums,
            "include_functions": include_functions,
            "package_mode": package_mode,
            "leading_slash_in_paths": leading_slash_in_paths,
            "constant_visibility": constant_visibility,
            "strip_docstrings": strip_docstrings,
            "concurrency": concurrency,
        }
        config.update({k: v for k, v in cli_overrides.items() if v is not None})
        
        # Handle repeatable 'exclude'
        if excludes:
            # Add CLI excludes to config excludes
            config["exclude"] = list(set(config.get("exclude", []) + excludes))
            
        # Store pyproject path
        config["_pyproject_path"] = pyproject_path

        # 4. Resolve root path
        try:
            resolved_root = Path(root).resolve(strict=True)
            if not resolved_root.is_dir():
                raise NotADirectoryError(f"Root path is not a directory: {root}")
        except FileNotFoundError:
            raise FileNotFoundError(f"Root path not found: {root}")

        # 5. Build pathspec matcher
        path_matcher = None
        if _HAS_PATHSPEC:
            exclude_patterns = config.get("exclude", [])
            if exclude_patterns:
                try:
                    path_matcher = pathspec.PathSpec.from_lines(
                        'gitwildmatch', exclude_patterns
                    )
                except Exception as e:
                    raise ValueError(f"Invalid exclude pattern: {e}")
        else:
            logger.warn(
                "'pathspec' not installed. Exclude patterns will be ignored."
            )

        return cls(config, resolved_root, logger, path_matcher)

    def run(self) -> "InventoryReport":
        """Traverse, parse, and return the structured inventory model."""
        self.logger.info(f"Starting inventory of '{self.root}'...")
        self.logger.info(f"Using up to {self.concurrency} parallel processes.")

        start_time = datetime.datetime.now(datetime.timezone.utc)
        
        # 1. Read pyproject.toml
        pkg_name, pkg_version = self._read_pyproject(
            self.config.get("_pyproject_path")
        )
        
        # 2. Collect files
        self.logger.debug("Collecting candidate files...")
        all_files, excluded_count = self._collect_candidate_files()
        
        # 3. Build package/module skeletons
        self.logger.debug("Building package and module tree...")
        packages = self._build_package_tree(all_files)
        
        all_module_skeletons: List[ModuleRecord] = []
        for pkg in packages:
            # all_module_skeletons.extend(pkg.modules)
            all_module_skeletons.extend(pkg['modules'])
        
        stats = InventoryStats(
            files_scanned=len(all_files),
            files_excluded=excluded_count,
            files_parsed_ok=0,
            files_parse_errors=0,
            packages=len(packages),
            modules=len(all_module_skeletons),
            classes=0,
            methods=0,
            constants=0,
            enums=0,
            functions=0
        )
        
        if not all_module_skeletons:
            self.logger.warn("No Python modules found to parse.")
            return self._build_report(start_time, stats, packages, pkg_name, pkg_version)

        # 4. Parse modules in parallel
        self.logger.info(f"Parsing {len(all_module_skeletons)} modules...")
        
        # Map qname -> result
        parsed_modules: Dict[str, Union[ModuleRecord, str]] = {}
        
        # Use ProcessPoolExecutor for CPU-bound AST parsing
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=self.concurrency
        ) as executor:
            
            futures_map = {
                executor.submit(
                    self._parse_module_content,
                    self.root / mod_skeleton["path"].lstrip('/'),
                    self.config,
                    self.root
                ): mod_skeleton["qname"]
                for mod_skeleton in all_module_skeletons
            }

            for future in concurrent.futures.as_completed(futures_map):
                qname = futures_map[future]
                try:
                    # Result is (qname, ModuleRecord | ErrorString)
                    _qname, result = future.result()
                    parsed_modules[_qname] = result
                except Exception as e:
                    err_msg = f"Unhandled parsing process error: {e}"
                    self.logger.error(f"Failed to parse {qname}: {err_msg}")
                    parsed_modules[qname] = err_msg

        # 5. Integrate parsed data back into package tree
        self.logger.debug("Integrating parse results...")
        total_modules_processed = 0
        for pkg in packages:
            processed_modules: List[ModuleRecord] = []
            for mod_skeleton in pkg["modules"]:
                qname = mod_skeleton["qname"]
                result = parsed_modules.get(qname)
                total_modules_processed += 1
                
                if isinstance(result, dict): # i.e., is a ModuleRecord TypedDict
                    # Update stats
                    stats["files_parsed_ok"] += 1
                    stats["constants"] += len(result.get("constants", []))
                    stats["enums"] += len(result.get("enums", []))
                    stats["functions"] += len(result.get("functions", []))
                    stats["classes"] += len(result["classes"])
                    for cls in result["classes"]:
                        stats["constants"] += len(cls.get("constants", []))
                        stats["methods"] += len(cls["methods"])
                    processed_modules.append(result)
                
                elif isinstance(result, str):
                    # Parse error
                    stats["files_parse_errors"] += 1
                    self.logger.warn(
                        f"Failed to parse {mod_skeleton['path']}: {result}"
                    )
                else:
                    # Should not happen
                    stats["files_parse_errors"] += 1
                    self.logger.error(
                        f"Missing parse result for {mod_skeleton['path']}"
                    )
            
            # Replace skeleton list with sorted, populated list
            pkg["modules"] = sorted(
                processed_modules, key=lambda m: m["qname"]
            )
            
        self.logger.debug(f"Total modules processed: {total_modules_processed}")

        # 6. Build final report
        return self._build_report(start_time, stats, packages, pkg_name, pkg_version)

    def _build_report(
        self,
        start_time: datetime.datetime,
        stats: InventoryStats,
        packages: List[PackageRecord],
        pkg_name: Optional[str],
        pkg_version: Optional[str]
    ) -> InventoryReport:
        """Helper to assemble the final report dictionary."""
        
        # Create effective config, remove internal keys
        effective_config = self.config.copy()
        effective_config.pop("_pyproject_path", None)
        
        meta = Metadata(
            schema_version="1.0",
            generated_at=start_time.isoformat().replace('+00:00', 'Z'),
            package={"name": pkg_name, "version": pkg_version},
            root=str(self.root),
            config_effective=effective_config
        )
        
        return InventoryReport(
            meta=meta,
            stats=stats,
            packages=sorted(packages, key=lambda p: p["qname"])
        )

    def _collect_candidate_files(self) -> Tuple[List[Path], int]:
        """Find all .py files, respecting exclusions."""
        all_py_files: List[Path] = []
        excluded_count = 0
        
        try:
            for file_path in self.root.rglob("*.py"):
                if not file_path.is_file() or file_path.is_symlink():
                    continue
                
                # Get path relative to root for matching
                try:
                    rel_path_str = file_path.relative_to(self.root).as_posix()
                except ValueError:
                    continue # Should not happen if rglob starts from root

                if self.path_matcher and self.path_matcher.match_file(rel_path_str):
                    excluded_count += 1
                    self.logger.debug(f"Excluding (glob): {rel_path_str}")
                    continue
                    
                all_py_files.append(file_path)
        
        except PermissionError as e:
            self.logger.error(f"Permission denied during file traversal: {e}")
        
        return sorted(all_py_files), excluded_count

    def _build_package_tree(
        self, 
        files: List[Path]
    ) -> List[PackageRecord]:
        """Create package and module skeletons based on file list and package_mode."""
        
        package_dirs: Set[Path] = set()
        package_mode = self.config.get("package_mode")
        
        if package_mode == "require_init_py":
            package_dirs = {
                p.parent for p in files if p.name == "__init__.py"
            }
        else: # "any_dir_with_py"
            package_dirs = {p.parent for p in files}
            
        packages_map: Dict[str, PackageRecord] = {}
        
        # Create all package records
        for pkg_path in sorted(list(package_dirs)):
            rel_path = self._get_rel_path_str(pkg_path)
            qname = self._path_to_qname(rel_path)
            
            packages_map[rel_path] = PackageRecord(
                path=rel_path,
                qname=qname,
                is_package=True,
                modules=[]
            )

        # Assign modules to their direct parent package
        for file_path in files:
            parent_dir_path = file_path.parent
            parent_rel_path = self._get_rel_path_str(parent_dir_path)
            
            if parent_rel_path in packages_map:
                module_rel_path = self._get_rel_path_str(file_path)
                module_qname = self._path_to_qname(module_rel_path)
                
                # Create skeleton module
                module_skeleton = ModuleRecord(
                    path=module_rel_path,
                    qname=module_qname,
                    docstring=None,
                    constants=[],
                    enums=[],
                    functions=[],
                    classes=[]
                )
                packages_map[parent_rel_path]["modules"].append(module_skeleton)

        return list(packages_map.values())

    def _get_rel_path_str(self, path: Path) -> str:
        """Get the normalized relative path string based on config."""
        rel_path = _normalize_relpath(self.root, path)
        if self.config.get("leading_slash_in_paths"):
            return f"/{rel_path}"
        return rel_path

    @staticmethod
    def _path_to_qname(path_str: str) -> str:
        """Convert a POSIX relative path to a qualified name."""
        return path_str.lstrip('/') \
                       .replace('.py', '') \
                       .replace('/__init__', '') \
                       .replace('/', '.')

    def _read_pyproject(
        self, 
        pyproject_path_str: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Parse pyproject.toml for package name and version."""
        
        if not pyproject_path_str:
            return None, None
            
        if not _HAS_TOML:
            self.logger.warn(
                f"Cannot parse '{pyproject_path_str}': 'tomli' (for Python < 3.11) "
                "or 'tomllib' is not available."
            )
            return None, None

        pyproject_path = Path(pyproject_path_str)
        if not pyproject_path.is_file():
            self.logger.warn(
                f"Pyproject file not found at: {pyproject_path}"
            )
            return None, None

        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            
            # PEP 621
            if "project" in data:
                name = data["project"].get("name")
                version = data["project"].get("version")
                if name or version:
                    return name, version
            
            # Poetry fallback
            if "tool" in data and "poetry" in data["tool"]:
                name = data["tool"]["poetry"].get("name")
                version = data["tool"]["poetry"].get("version")
                if name or version:
                    return name, version

            return None, None
        
        except Exception as e:
            self.logger.error(f"Failed to read/parse {pyproject_path}: {e}")
            return None, None

    def write_yaml(
        self, 
        report: "InventoryReport", 
        output_path: Optional[str], 
        to_stdout: bool = False
    ) -> None:
        """Serialize `report` to YAML file or stdout."""
        
        if not _HAS_YAML:
            raise ImportError(
                "YAML output requires 'PyYAML' to be installed."
            )

        # Custom dumper to format multiline docstrings nicely
        class MultilineDocstringDumper(yaml.SafeDumper):
            def represent_scalar(self, tag, value, style=None):
                if isinstance(value, str) and '\n' in value:
                    style = '|'
                return super().represent_scalar(tag, value, style)

        def no_alias_dumper(data, stream=None, Dumper=MultilineDocstringDumper, **kwds):
            """Disable YAML anchors/aliases for cleaner output."""
            class NoAliasDumper(Dumper):
                def ignore_aliases(self, data):
                    return True
            return yaml.dump(data, stream, Dumper=NoAliasDumper, **kwds)
        
        # Convert dataclasses/TypedDicts to plain dicts for dumping
        # (TypedDicts are already dicts)
        report_dict = dict(report)

        dump_kwargs = {
            "sort_keys": False,
            "default_flow_style": False,
            "allow_unicode": True,
            "encoding": "utf-8"
        }

        if to_stdout:
            self.logger.info("Writing YAML to stdout...")
            try:
                # Use default dumper for stdout, simpler
                yaml.safe_dump(report_dict, sys.stdout, **dump_kwargs)
            except (IOError,BrokenPipeError):
                # Handle piping to `head` etc.
                pass
            except Exception as e:
                self.logger.error(f"Error writing to stdout: {e}")
        
        elif output_path:
            out_p = Path(output_path)
            self.logger.info(f"Writing YAML to {out_p}...")
            try:
                out_p.parent.mkdir(parents=True, exist_ok=True)
                with open(out_p, 'wb') as f: # Write bytes for explicit encoding
                    # Use custom dumper for file output
                    no_alias_dumper(report_dict, f, **dump_kwargs)
                self.logger.success(f"Successfully wrote {out_p}")
            except Exception as e:
                self.logger.error(f"Failed to write output file {out_p}: {e}")
        
        else:
            self.logger.error("No output destination specified (internal error).")

    # --- Static Parsing Helpers (for Process Pool) ---

    @staticmethod
    def _parse_module_content(
        file_path: Path,
        config: Dict[str, Any],
        root: Path
    ) -> Tuple[str, Union["ModuleRecord", str]]:
        """
        AST-parses a single file. Designed to be run in a separate process.
        Returns (qname, ModuleRecord | ErrorString).
        """
        
        # Must re-calculate paths, cannot pass Path objects easily
        try:
            rel_path_str = _normalize_relpath(root, file_path)
            if config.get("leading_slash_in_paths"):
                rel_path_str = f"/{rel_path_str}"
            
            qname = PythonApiSignatureExtractor._path_to_qname(rel_path_str)
        except Exception as e:
            return (
                str(file_path), 
                f"Error calculating relative path: {e}"
            )

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content, filename=str(file_path))
            
            module_docstring = (
                PythonApiSignatureExtractor._get_docstring(
                    tree, config.get("strip_docstrings", False)
                )
                if config.get("include_docstrings")
                else None
            )

            # Extract top-level nodes
            constants, enums, functions, classes = (
                PythonApiSignatureExtractor._extract_nodes(
                    tree.body, config, qname, "module"
                )
            )

            # Build final record
            module_record = ModuleRecord(
                path=rel_path_str,
                qname=qname,
                docstring=module_docstring,
                constants=constants,
                enums=enums,
                functions=functions,
                classes=classes
            )
            
            # Omit empty optional fields
            if not module_docstring:
                module_record.pop("docstring", None)
            if not config.get("include_constants"):
                module_record.pop("constants", None)
            if not config.get("include_enums"):
                module_record.pop("enums", None)
            if not config.get("include_functions"):
                module_record.pop("functions", None)

            return qname, module_record

        except SyntaxError as e:
            return qname, f"SyntaxError: {e.msg} (line {e.lineno})"
        except (IOError, OSError, UnicodeDecodeError) as e:
            return qname, f"File I/O Error: {e}"
        except Exception as e:
            return qname, f"Unexpected Parsing Error: {e}"

    @staticmethod
    def _extract_nodes(
        tree_body: List[ast.stmt],
        config: Dict[str, Any],
        parent_qname: str,
        scope: Literal["module", "class"]
    ) -> Tuple[
        List[ConstantRecord],
        List[EnumRecord],
        List[FunctionRecord],
        List[ClassRecord]
    ]:
        """Extracts all relevant API surface items from a list of AST statements."""
        
        constants: List[ConstantRecord] = []
        enums: List[EnumRecord] = []
        functions: List[FunctionRecord] = []
        classes: List[ClassRecord] = []

        for node in tree_body:
            # 1. Constants (Assign or AnnAssign)
            if config.get("include_constants") and \
               isinstance(node, (ast.Assign, ast.AnnAssign)) and \
               (target := getattr(node, 'target', None)) and \
               isinstance(target, ast.Name):
                
                const_rec = PythonApiSignatureExtractor._build_constant_record(
                    node, config, scope
                )
                if const_rec:
                    constants.append(const_rec)
            
            # 2. Functions (module-level)
            elif config.get("include_functions") and \
                 isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                 scope == "module":
                
                vis = PythonApiSignatureExtractor._visibility(node.name)
                if config.get("public_only") and vis != "public":
                    continue
                
                func_rec = PythonApiSignatureExtractor._build_function_record(
                    node, parent_qname, config
                )
                functions.append(func_rec)

            # 3. Classes (and Enums)
            elif isinstance(node, ast.ClassDef):
                vis = PythonApiSignatureExtractor._visibility(node.name)
                # Note: 'public_only' for classes is a bit ambiguous in the prompt.
                # Assuming it applies to classes as well.
                if config.get("public_only") and vis != "public":
                    continue
                
                class_qname = f"{parent_qname}.{node.name}"
                
                # Check for Enums
                if config.get("include_enums") and \
                   PythonApiSignatureExtractor._is_enum(node):
                    
                    enum_rec = PythonApiSignatureExtractor._build_enum_record(
                        node, class_qname, config
                    )
                    enums.append(enum_rec)
                
                # Regular Class
                else:
                    class_rec = PythonApiSignatureExtractor._build_class_record(
                        node, class_qname, config
                    )
                    classes.append(class_rec)

        return (
            sorted(constants, key=lambda x: x["name"]),
            sorted(enums, key=lambda x: x["qname"]),
            sorted(functions, key=lambda x: x["qname"]),
            sorted(classes, key=lambda x: x["qname"])
        )
    
    @staticmethod
    def _build_constant_record(
        node: Union[ast.Assign, ast.AnnAssign],
        config: Dict[str, Any],
        scope: Literal["module", "class"]
    ) -> Optional[ConstantRecord]:
        """Builds a ConstantRecord from an Assign/AnnAssign node."""
        
        # 'target' is ast.Name (checked in caller)
        target: ast.Name = node.target 
        name = target.id
        vis = PythonApiSignatureExtractor._visibility(name)
        
        # Apply visibility strategy
        strategy = config.get("constant_visibility", "no_underscore")
        if strategy == "uppercase":
            if not (name.isupper() and re.match(r"^[A-Z0-9_]+$", name) and vis == "public"):
                return None
        elif strategy == "no_underscore":
            if vis != "public":
                return None
        
        value_node = getattr(node, 'value', None)
        literal_val, value_repr = PythonApiSignatureExtractor._extract_literal_value(
            value_node
        )
        
        const_rec = ConstantRecord(
            name=name,
            visibility=vis,
            scope=scope,
            value=literal_val,
            value_repr=value_repr
        )
        
        if literal_val is None:
            const_rec.pop("value", None) # Omit if not a simple literal
            
        return const_rec

    @staticmethod
    def _build_enum_record(
        node: ast.ClassDef,
        qname: str,
        config: Dict[str, Any]
    ) -> EnumRecord:
        """Builds an EnumRecord from a ClassDef node."""
        
        docstring = (
            PythonApiSignatureExtractor._get_docstring(
                node, config.get("strip_docstrings", False)
            )
            if config.get("include_docstrings")
            else None
        )
        
        members: List[EnumMemberRecord] = []
        for item in node.body:
            # Enum members are simple assignments (or AnnAssign)
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                target = getattr(item, 'target', None)
                if isinstance(target, ast.Name):
                    name = target.id
                    if name.startswith('_'): # Skip private/dunder members
                        continue
                    
                    _val, value_repr = PythonApiSignatureExtractor._extract_literal_value(
                         getattr(item, 'value', None)
                    )
                    members.append(
                        EnumMemberRecord(name=name, value_repr=value_repr)
                    )

        enum_rec = EnumRecord(
            name=node.name,
            qname=qname,
            docstring=docstring,
            members=sorted(members, key=lambda m: m["name"])
        )
        
        if not docstring:
            enum_rec.pop("docstring", None)
            
        return enum_rec

    @staticmethod
    def _build_class_record(
        node: ast.ClassDef,
        qname: str,
        config: Dict[str, Any]
    ) -> ClassRecord:
        """Builds a ClassRecord from a ClassDef node."""
        
        docstring = (
            PythonApiSignatureExtractor._get_docstring(
                node, config.get("strip_docstrings", False)
            )
            if config.get("include_docstrings")
            else None
        )
        
        # Get class-level constants, functions (should be methods), and nested classes
        # Note: _extract_nodes doesn't support nested classes yet, but it's
        # not required by the schema.
        constants, _enums, _funcs, _classes = (
            PythonApiSignatureExtractor._extract_nodes(
                node.body, config, qname, "class"
            )
        )
        
        # Get methods
        methods: List[MethodRecord] = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                vis = PythonApiSignatureExtractor._visibility(item.name)
                
                # Apply public_only logic, but ALWAYS include __init__
                if item.name == "__init__":
                    pass # Always include
                elif config.get("public_only") and vis != "public":
                    continue
                
                method_rec = PythonApiSignatureExtractor._build_method_record(
                    item, qname, config
                )
                methods.append(method_rec)

        class_rec = ClassRecord(
            name=node.name,
            qname=qname,
            docstring=docstring,
            constants=constants,
            methods=sorted(methods, key=lambda m: m["name"])
        )
        
        if not docstring:
            class_rec.pop("docstring", None)
        if not config.get("include_constants"):
            class_rec.pop("constants", None)
            
        return class_rec
    
    @staticmethod
    def _build_method_record(
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        class_qname: str,
        config: Dict[str, Any]
    ) -> MethodRecord:
        """Builds a MethodRecord from a FunctionDef node."""
        
        name = node.name
        qname = f"{class_qname}.{name}"
        vis = PythonApiSignatureExtractor._visibility(name)
        kind, decorators = PythonApiSignatureExtractor._decorator_kind(
            node.decorator_list
        )
        
        # If __init__, kind is 'instance' regardless of decorators
        if name == "__init__":
            kind = "instance"
            
        sig = PythonApiSignatureExtractor._build_signature(
            node.args, node.returns
        )
        
        docstring = (
            PythonApiSignatureExtractor._get_docstring(
                node, config.get("strip_docstrings", False)
            )
            if config.get("include_docstrings")
            else None
        )
        
        method_rec = MethodRecord(
            name=name,
            qname=qname,
            visibility=vis,
            kind=kind,
            decorators=decorators,
            signature=sig,
            docstring=docstring
        )
        
        if not docstring:
            method_rec.pop("docstring", None)
            
        return method_rec

    @staticmethod
    def _build_function_record(
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        module_qname: str,
        config: Dict[str, Any]
    ) -> FunctionRecord:
        """Builds a FunctionRecord for a module-level function."""
        
        name = node.name
        qname = f"{module_qname}.{name}"
        vis = PythonApiSignatureExtractor._visibility(name)
        _kind, decorators = PythonApiSignatureExtractor._decorator_kind(
            node.decorator_list
        )
            
        sig = PythonApiSignatureExtractor._build_signature(
            node.args, node.returns
        )
        
        docstring = (
            PythonApiSignatureExtractor._get_docstring(
                node, config.get("strip_docstrings", False)
            )
            if config.get("include_docstrings")
            else None
        )
        
        func_rec = FunctionRecord(
            name=name,
            qname=qname,
            visibility=vis,
            decorators=decorators,
            signature=sig,
            docstring=docstring
        )
        
        if not docstring:
            func_rec.pop("docstring", None)
            
        return func_rec

    @staticmethod
    def _build_signature(
        args: ast.arguments,
        returns: Optional[ast.expr]
    ) -> FunctionSignature:
        """Builds the serializable FunctionSignature from ast.arguments."""
        
        params: List[Param] = []
        
        # 1. Positional-only args
        for arg in args.posonlyargs:
            params.append(Param(
                name=arg.arg,
                kind="positional_only",
                annotation=PythonApiSignatureExtractor._unparse_node(
                    arg.annotation
                ),
                default=None # Positional-only cannot have defaults in 'args'
            ))
        
        # 2. Positional-or-keyword args (with defaults)
        defaults_offset = len(args.args) - len(args.defaults)
        for i, arg in enumerate(args.args):
            default_val = None
            if i >= defaults_offset:
                default_val = PythonApiSignatureExtractor._unparse_node(
                    args.defaults[i - defaults_offset]
                )
                
            params.append(Param(
                name=arg.arg,
                kind="positional_or_keyword",
                annotation=PythonApiSignatureExtractor._unparse_node(
                    arg.annotation
                ),
                default=default_val
            ))

        # 3. Var-positional (*args)
        if args.vararg:
            params.append(Param(
                name=args.vararg.arg,
                kind="var_positional",
                annotation=PythonApiSignatureExtractor._unparse_node(
                    args.vararg.annotation
                ),
                default=None
            ))

        # 4. Keyword-only args
        for i, arg in enumerate(args.kwonlyargs):
            default_val = None
            if args.kw_defaults[i] is not None:
                default_val = PythonApiSignatureExtractor._unparse_node(
                    args.kw_defaults[i]
                )

            params.append(Param(
                name=arg.arg,
                kind="keyword_only",
                annotation=PythonApiSignatureExtractor._unparse_node(
                    arg.annotation
                ),
                default=default_val
            ))

        # 5. Var-keyword (**kwargs)
        if args.kwarg:
            params.append(Param(
                name=args.kwarg.arg,
                kind="var_keyword",
                annotation=PythonApiSignatureExtractor._unparse_node(
                    args.kwarg.annotation
                ),
                default=None
            ))

        return FunctionSignature(
            params=params,
            returns=PythonApiSignatureExtractor._unparse_node(returns)
        )

    @staticmethod
    def _extract_literal_value(
        node: Optional[ast.expr]
    ) -> Tuple[Optional[Any], str]:
        """
        Attempts to extract a JSON-safe literal value from an AST node.
        Always returns the string representation.
        """
        value_repr = PythonApiSignatureExtractor._unparse_node(node)
        if value_repr is None:
            value_repr = "None"
            
        if node is None:
            return None, value_repr

        # Python 3.8+
        if isinstance(node, ast.Constant):
            val = node.value
            if isinstance(val, (str, int, float, bool, type(None))):
                return val, value_repr
        
        # Python 3.7 and earlier (ast.Num, ast.Str, etc.)
        # elif sys.version_info < (3, 8):
        #     if isinstance(node, ast.Num):
        #         return node.n, value_repr
        #     if isinstance(node, ast.Str):
        #         return node.s, value_repr
        #     if isinstance(node, ast.NameConstant):
        #         return node.value, value_repr
        #     if isinstance(node, ast.Bytes):
        #         try:
        #             return node.s.decode('utf-8'), value_repr
        #         except UnicodeDecodeError:
        #             return f"<bytes: {len(node.s)} bytes>", value_repr
        
        # Simple containers (list, tuple, set, dict)
        try:
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                if all(isinstance(e, ast.Constant) for e in node.elts):
                    val = [e.value for e in node.elts]
                    if isinstance(node, ast.Tuple): return tuple(val), value_repr
                    if isinstance(node, ast.Set): return set(val), value_repr
                    return val, value_repr
            
            if isinstance(node, ast.Dict):
                if all(isinstance(k, ast.Constant) and 
                       isinstance(v, ast.Constant) 
                       for k, v in zip(node.keys, node.values)):
                    val = {k.value: v.value for k, v in zip(node.keys, node.values)}
                    return val, value_repr
        except Exception:
            pass # Failed to evaluate simple literal

        return None, value_repr # Not a simple literal

    @staticmethod
    def _is_enum(node: ast.ClassDef) -> bool:
        """Checks if a ClassDef node subclasses an Enum."""
        enum_names = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
        for base in node.bases:
            # Direct name: class MyEnum(Enum)
            if isinstance(base, ast.Name) and base.id in enum_names:
                return True
            # Attribute: class MyEnum(enum.Enum)
            if isinstance(base, ast.Attribute) and base.attr in enum_names:
                return True
        return False

    @staticmethod
    def _visibility(name: str) -> Literal["public", "private", "dunder"]:
        """Determine API visibility based on naming conventions."""
        if name.startswith("__") and name.endswith("__") and len(name) > 4:
            return "dunder"
        if name.startswith("_"):
            return "private"
        return "public"

    @staticmethod
    def _decorator_kind(
        decorators: List[ast.expr]
    ) -> Tuple[Literal["instance", "class", "static"], List[str]]:
        """
        Determine method kind (instance, static, class) from decorators.
        Returns (kind, list_of_decorator_names).
        """
        kind: Literal["instance", "class", "static"] = "instance"
        decorator_names: List[str] = []
        
        for deco in decorators:
            # Unroll calls like @my_decorator(arg)
            if isinstance(deco, ast.Call):
                deco_node = deco.func
            else:
                deco_node = deco
            
            name = PythonApiSignatureExtractor._unparse_node(deco_node)
            if name:
                decorator_names.append(name)
                # Check for simple name or attribute path
                if name.endswith("staticmethod"):
                    kind = "static"
                elif name.endswith("classmethod"):
                    kind = "class"
                    
        return kind, sorted(decorator_names)

    @staticmethod
    def _get_docstring(
        node: Union[ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef, ast.Module],
        strip: bool
    ) -> Optional[str]:
        """Safely extract docstring using ast.get_docstring."""
        try:
            doc = ast.get_docstring(node, clean=False)
            if doc and strip:
                return doc.strip()
            return doc if doc else None
        except Exception:
            return None

    @staticmethod
    def _unparse_node(node: Optional[ast.expr]) -> Optional[str]:
        """
        Stringify an AST expression node (annotation, default value).
        Uses ast.unparse if available (3.9+), otherwise a simple fallback.
        """
        if node is None:
            return None
        
        # Use built-in unparser if available
        if sys.version_info >= (3, 9):
            try:
                return ast.unparse(node)
            except Exception:
                # Fallback for complex nodes ast.unparse might fail on?
                pass # Try our fallback

        # --- Fallback for Python 3.8 ---
        
        # Handle 3.8 literal types
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.NameConstant): # True/False/None
            return repr(node.value)
        if isinstance(node, ast.Num): # 123, 1.23
            return repr(node.n)
        if isinstance(node, ast.Str): # "hello"
            return repr(node.s)
        if isinstance(node, ast.Bytes): # b"hello"
            return repr(node.s)

        # Handle common type annotations
        if isinstance(node, ast.Name):
            return node.id
        
        if isinstance(node, ast.Attribute):
            val = PythonApiSignatureExtractor._unparse_node(node.value)
            if val:
                return f"{val}.{node.attr}"
        
        if isinstance(node, ast.Subscript):
            val = PythonApiSignatureExtractor._unparse_node(node.value)
            
            # 3.8: slice is ast.Index
            slic_node = node.slice
            if isinstance(slic_node, ast.Index):
                slic = PythonApiSignatureExtractor._unparse_node(slic_node.value)
            # 3.9+: slice is the value itself
            else: 
                slic = PythonApiSignatureExtractor._unparse_node(slic_node)
                
            if val and slic:
                return f"{val}[{slic}]"
        
        if isinstance(node, ast.Tuple):
            elements = ", ".join(
                e_str for el in node.elts
                if (e_str := PythonApiSignatureExtractor._unparse_node(el))
            )
            return f"Tuple[{elements}]" # Common for Union
            
        if isinstance(node, ast.List):
            elements = ", ".join(
                e_str for el in node.elts
                if (e_str := PythonApiSignatureExtractor._unparse_node(el))
            )
            return f"List[{elements}]"

        # Fallback for anything else
        try:
            # Try to force it (might work for simple nodes)
            return str(ast.dump(node))
        except Exception:
            return f"<ast.{type(node).__name__}>"

# --- CLI Entry Point ---

def main():
    """Command-line interface entry point."""
    
    # Check for core dependencies
    if not all([_HAS_COLORAMA, _HAS_COMMENTJSON, _HAS_PATHSPEC, _HAS_YAML, _HAS_TOML or sys.version_info >= (3, 11)]):
        print(
            "Error: Missing one or more required dependencies: "
            "'commentjson', 'pathspec', 'PyYAML', 'tomli' (if Python < 3.11).",
            file=sys.stderr
        )
        print("Please run: pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description=(
            "Python API Signature Extractor. Traverses a repository and "
            "generates a YAML inventory of its API surface using AST."
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # --- Core ---
    parser.add_argument(
        "--root", 
        required=True, 
        help="Top-level directory to traverse."
    )
    parser.add_argument(
        "--config",
        help="Path to a JSON/JSONC configuration file."
    )
    parser.add_argument(
        "-e", "--exclude",
        action="append",
        dest="excludes",
        help=(
            "Git-style glob pattern to exclude (relative to root). "
            "Can be used multiple times. Augments config 'exclude' list."
        )
    )
    parser.add_argument(
        "--pyproject",
        dest="pyproject_path",
        help=(
            "Path to pyproject.toml to extract package name/version. "
            "Safe if missing."
        )
    )

    # --- Output ---
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "-o", "--output",
        dest="output_path",
        help="Path to write the output YAML file (default: api_signatures.yaml)"
    )
    output_group.add_argument(
        "--stdout",
        action="store_true",
        help="Write YAML output to stdout instead of a file."
    )
    
    # --- Toggles (Visibility) ---
    vis_group = parser.add_mutually_exclusive_group()
    vis_group.add_argument(
        "--public-only",
        action="store_true",
        dest="public_only",
        default=None,
        help="Include only public methods/classes (default)."
    )
    vis_group.add_argument(
        "--all-methods",
        action="store_false",
        dest="public_only",
        help="Include private and dunder methods/classes."
    )
    
    # --- Toggles (Content) ---
    parser.add_argument(
        "--include-constants",
        action="store_true",
        dest="include_constants",
        default=None,
        help="Include module/class-level constants."
    )
    parser.add_argument(
        "--include-docstrings",
        action="store_true",
        dest="include_docstrings",
        default=None,
        help="Include docstrings for modules, classes, and methods/functions."
    )
    parser.add_argument(
        "--strip-docstrings",
        action="store_true",
        dest="strip_docstrings",
        default=None,
        help="Apply .strip() to docstrings (requires --include-docstrings)."
    )
    
    enum_group = parser.add_mutually_exclusive_group()
    enum_group.add_argument(
        "--include-enums",
        action="store_true",
        dest="include_enums",
        default=None,
        help="Include Enum definitions (default)."
    )
    enum_group.add_argument(
        "--no-enums",
        action="store_false",
        dest="include_enums",
        help="Exclude Enum definitions."
    )
    
    parser.add_argument(
        "--include-functions",
        action="store_true",
        dest="include_functions",
        default=None,
        help="Include module-level functions."
    )

    # --- Toggles (Parsing Strategy) ---
    parser.add_argument(
        "--package-mode",
        choices=["any_dir_with_py", "require_init_py"],
        default=None,
        help="Strategy for identifying package directories (default: any_dir_with_py)."
    )
    
    path_slash_group = parser.add_mutually_exclusive_group()
    path_slash_group.add_argument(
        "--leading-slash",
        action="store_true",
        dest="leading_slash_in_paths",
        default=None,
        help="Include a leading slash in YAML paths (e.g., /src/pkg) (default)."
    )
    path_slash_group.add_argument(
        "--no-leading-slash",
        action="store_false",
        dest="leading_slash_in_paths",
        help="Do not include a leading slash in YAML paths (e.g., src/pkg)."
    )
    
    parser.add_argument(
        "--constant-visibility",
        choices=["no_underscore", "uppercase"],
        default=None,
        help="Strategy for identifying constants (default: no_underscore)."
    )

    # --- Concurrency & Logging ---
    parser.add_argument(
        "-j", "--concurrency",
        type=int,
        default=None,
        help="Number of parallel processes for parsing (default: CPU count)."
    )
    
    log_level_group = parser.add_mutually_exclusive_group()
    log_level_group.add_argument(
        "-v", "--verbose",
        action="store_const",
        dest="log_level",
        const=logging.DEBUG,
        help="Enable verbose (DEBUG) logging."
    )
    log_level_group.add_argument(
        "-q", "--quiet",
        action="store_const",
        dest="log_level",
        const=logging.ERROR,
        help="Silence all logging except ERRORs."
    )
    
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colorized console output."
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print a summary of findings to stderr on completion."
    )

    args = parser.parse_args()

    # --- Setup Logger ---
    log_level = args.log_level or logging.INFO
    logger = ConsoleManager(level=log_level, no_color=args.no_color)

    if not _HAS_PATH_ANNOTATE:
        logger.debug(
            "Using internal fallback 'ConsoleManager' "
            "('path_annotate' not found)."
        )

    # --- Set Output Path ---
    output_path = None
    if not args.stdout:
        output_path = args.output_path or "api_signatures.yaml"

    # --- Run Extractor ---
    exit_code = 0
    report = None
    try:
        extractor = PythonApiSignatureExtractor.from_config(
            root=args.root,
            logger=logger,
            config_path=args.config,
            excludes=args.excludes,
            pyproject_path=args.pyproject_path,
            public_only=args.public_only,
            include_constants=args.include_constants,
            include_docstrings=args.include_docstrings,
            include_enums=args.include_enums,
            include_functions=args.include_functions,
            package_mode=args.package_mode,
            leading_slash_in_paths=args.leading_slash_in_paths,
            constant_visibility=args.constant_visibility,
            strip_docstrings=args.strip_docstrings,
            concurrency=args.concurrency,
        )
        
        report = extractor.run()
        
        if report:
            extractor.write_yaml(report, output_path, args.stdout)
            
            if report["stats"]["files_parse_errors"] > 0:
                logger.warn(
                    f"Completed with {report['stats']['files_parse_errors']} "
                    "parsing errors."
                )
                exit_code = 2
            else:
                logger.success("Inventory complete.")
                exit_code = 0
        else:
            logger.error("Failed to generate report (unknown error).")
            exit_code = 2

    except (
        ValueError, 
        FileNotFoundError, 
        NotADirectoryError, 
        IOError, 
        ImportError
    ) as e:
        logger.error(f"Configuration or Setup Error: {e}")
        exit_code = 1
    except Exception as e:
        logger.error(f"Unhandled runtime error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        exit_code = 2

    # --- Print Summary ---
    if args.print_summary and report:
        stats = report["stats"]
        print("\n--- API Inventory Summary ---", file=sys.stderr)
        print(f"  Files Scanned:  {stats['files_scanned']}", file=sys.stderr)
        print(f"  Files Excluded: {stats['files_excluded']}", file=sys.stderr)
        print(f"  Parsed OK:      {stats['files_parsed_ok']}", file=sys.stderr)
        print(f"  Parse Errors:   {stats['files_parse_errors']}", file=sys.stderr)
        print("---", file=sys.stderr)
        print(f"  Packages:       {stats['packages']}", file=sys.stderr)
        print(f"  Modules:        {stats['modules']}", file=sys.stderr)
        print(f"  Classes:        {stats['classes']}", file=sys.stderr)
        print(f"  Enums:          {stats['enums']}", file=sys.stderr)
        print(f"  Methods:        {stats['methods']}", file=sys.stderr)
        print(f"  Functions:      {stats['functions']}", file=sys.stderr)
        print(f"  Constants:      {stats['constants']}", file=sys.stderr)
        print("---------------------------\n", file=sys.stderr)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()