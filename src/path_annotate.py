"""
path-annotate: A tool to add/update a first-line path comment in source files.

This tool recursively walks a directory, identifies files based on
configurable "signatures," and ensures the first non-blank line is a
comment containing the file's POSIX-style relative path.

It is idempotent, safe (with --dry-run), and configurable via JSONC.

Required third-party libraries:
- commentjson: For loading JSONC configuration files (with comments).
- pathspec: For robust .gitignore-style glob matching (exclusions).
- colorama: For colored console output.

Install dependencies:
    pip install commentjson pathspec colorama
"""

import argparse
import os
import sys
import re
import logging
from pathlib import Path
from typing import (
    List, Optional, Tuple, Literal, NamedTuple, Dict, ClassVar, Set
)
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import fnmatch

# Attempt to import dependencies
try:
    import commentjson
    import pathspec
    from colorama import init, Fore, Style
except ImportError as e:
    print(
        f"Error: Missing required dependency. {e}\n"
        "Please install requirements: "
        "pip install commentjson pathspec colorama",
        file=sys.stderr
    )
    sys.exit(1)

# --- Type Definitions & Result Models ---

ActionType = Literal[
    "inserted", "updated", "skipped_correct", "skipped_no_match", 
    "skipped_excluded", "error"
]

HeaderAction = Literal["insert", "update", "skip"]

@dataclass(slots=True)
class FileOutcome:
    """Result of processing a single file."""
    path: str
    action: ActionType
    signature_name: Optional[str] = None
    reason: Optional[str] = None

@dataclass
class RunReport:
    """Summary of a full annotation run."""
    files_scanned: int = 0
    files_inserted: int = 0
    files_updated: int = 0
    files_skipped_correct: int = 0
    files_skipped_no_match: int = 0
    files_skipped_excluded: int = 0
    files_with_errors: int = 0
    outcomes: List[FileOutcome] = field(default_factory=list)

    def tally(self, outcome: FileOutcome):
        """Add a FileOutcome to the report and update totals."""
        self.files_scanned += 1
        if outcome.action == "inserted":
            self.files_inserted += 1
        elif outcome.action == "updated":
            self.files_updated += 1
        elif outcome.action == "skipped_correct":
            self.files_skipped_correct += 1
        elif outcome.action == "skipped_no_match":
            self.files_skipped_no_match += 1
        elif outcome.action == "skipped_excluded":
            self.files_skipped_excluded += 1
        elif outcome.action == "error":
            self.files_with_errors += 1
        
        # Only store detailed outcomes if not quiet (to save memory)
        # We will filter this in the caller based on verbosity.
        self.outcomes.append(outcome)

    @property
    def total_changes(self) -> int:
        """Return total files changed (inserted + updated)."""
        return self.files_inserted + self.files_updated

    @property
    def total_matched(self) -> int:
        """Return total files that matched a signature."""
        return (
            self.files_inserted + self.files_updated + 
            self.files_skipped_correct + self.files_skipped_excluded
        )


class HeaderDecision(NamedTuple):
    """Internal decision model for file content modification."""
    action: HeaderAction
    text: str
    line_index: int
    existing_line_count: int


@dataclass(slots=True, frozen=True)
class Signature:
    """A normalized, compiled signature rule."""
    name: str
    comment_prefix: str
    required_suffix: str
    extensions: Optional[List[str]]
    globs: Optional[List[str]]
    exclude_spec: Optional[pathspec.PathSpec]
    detection_pattern: re.Pattern

    @classmethod
    def from_dict(cls, d: dict) -> "Signature":
        """Create a compiled Signature from a raw config dictionary."""
        name = d["name"]
        prefix = d["comment_prefix"]
        suffix = d["required_suffix"]
        
        escaped_prefix = re.escape(prefix)
        escaped_suffix = re.escape(suffix)
        pattern = re.compile(rf"^{escaped_prefix}\s+\S+{escaped_suffix}$")

        exclude_spec = None
        if d.get("exclude"):
            exclude_spec = pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, d["exclude"]
            )

        return cls(
            name=name,
            comment_prefix=prefix,
            required_suffix=suffix,
            extensions=d.get("extensions"),
            globs=d.get("globs"),
            exclude_spec=exclude_spec,
            detection_pattern=pattern
        )


@dataclass(slots=True, frozen=True)
class ResolvedConfig:
    """Holds all compiled signatures."""
    signatures: List[Signature]


# --- Logger Wrapper for Color/Quiet/Verbose ---

classLogger = logging.getLogger("PathHeaderAnnotator")

class ConsoleManager:
    """Manages console output, respecting quiet/verbose/color flags."""
    def __init__(self, level: int, no_color: bool):
        self.level = level
        self.no_color = no_color
        if not no_color:
            init(autoreset=True)

    def _log(self, msg: str, log_level: int, color: str = ""):
        if log_level < self.level:
            return
        
        if not self.no_color and color:
            msg = f"{color}{msg}{Style.RESET_ALL}"
        
        if log_level >= logging.ERROR:
            logging.error(msg)
        elif log_level >= logging.WARNING:
            logging.warning(msg)
        elif log_level >= logging.INFO:
            logging.info(msg)
        else:
            logging.debug(msg)

    def debug(self, msg: str):
        self._log(msg, logging.DEBUG, Style.DIM)

    def info(self, msg: str):
        self._log(msg, logging.INFO)

    def warning(self, msg: str):
        self._log(msg, logging.WARNING, Fore.YELLOW)

    def error(self, msg: str):
        self._log(msg, logging.ERROR, Fore.RED)
    
    def critical(self, msg: str):
        self._log(msg, logging.CRITICAL, Fore.RED + Style.BRIGHT)

    def report_outcome(self, outcome: FileOutcome, dry_run: bool):
        """Log a single file outcome if verbosity allows."""
        if self.level > logging.DEBUG:
            return # Only show per-file in verbose

        dry_prefix = "[DRY RUN] " if dry_run else ""
        path_str = str(outcome.path)
        
        if outcome.action == "inserted":
            self.debug(f"{dry_prefix}INSERT:  {path_str} (as {outcome.signature_name})")
        elif outcome.action == "updated":
            self.debug(f"{dry_prefix}UPDATE:  {path_str} (as {outcome.signature_name})")
        elif outcome.action == "skipped_correct":
            self.debug(f"SKIP:    {path_str} (already correct)")
        elif outcome.action == "skipped_excluded":
            self.debug(f"EXCLUDE: {path_str} ({outcome.reason})")
        elif outcome.action == "skipped_no_match":
            self.debug(f"NO_MATCH: {path_str}")
        elif outcome.action == "error":
            self.warning(f"ERROR:   {path_str} ({outcome.reason})")

    def print_summary(self, report: RunReport):
        """Print the final summary table."""
        if self.level > logging.INFO: # Only suppress if quiet
            return

        print("\n--- Path Annotation Summary ---")
        
        total_matched = report.total_matched
        
        # Helper for coloring non-zero values
        def color_val(val, color_if_nonzero):
            if val > 0 and not self.no_color:
                return f"{color_if_nonzero}{val}{Style.RESET_ALL}"
            return str(val)

        summary_data = [
            ("Files Scanned", report.files_scanned, ""),
            ("Files Matched Signature", total_matched, ""),
            ("  - Headers Inserted", report.files_inserted, Fore.GREEN),
            ("  - Headers Updated", report.files_updated, Fore.YELLOW),
            ("  - Skipped (Correct)", report.files_skipped_correct, Style.DIM),
            ("  - Skipped (Excluded)", report.files_skipped_excluded, Style.DIM),
            ("Files Not Matched", report.files_skipped_no_match, Style.DIM),
            ("File Errors", report.files_with_errors, Fore.RED + Style.BRIGHT),
        ]

        max_label = max(len(label) for label, _, _ in summary_data)

        for label, value, color in summary_data:
            val_str = color_val(value, color)
            print(f"{label:<{max_label}} : {val_str}")
        
        print("-------------------------------")
        if report.total_changes > 0:
            self.info(f"Run complete. {report.total_changes} file(s) changed.")
        else:
            self.info("Run complete. No changes made.")


# --- Main Annotator Class ---

class PathHeaderAnnotator:
    """
    Recursively annotates files with a first-nonblank-line path comment
    based on configured signatures. Idempotent.
    """
    
    _config: ResolvedConfig
    _root: Path
    _global_exclude_spec: Optional[pathspec.PathSpec]
    _dry_run: bool
    _concurrency: int
    _logger: ConsoleManager

    # Use ClassVar for defaults that don't change per instance
    DEFAULT_ENCODING: ClassVar[str] = "utf-8"
    FALLBACK_ENCODING: ClassVar[str] = "latin-1"

    def __init__(
        self,
        root: Path,
        config: ResolvedConfig,
        logger: ConsoleManager,
        global_exclude_spec: Optional[pathspec.PathSpec] = None,
        dry_run: bool = False,
        concurrency: int = 4,
    ):
        """Private constructor. Use PathHeaderAnnotator.from_config()"""
        self._root = root.resolve()
        self._config = config
        self._logger = logger
        self._global_exclude_spec = global_exclude_spec
        self._dry_run = dry_run
        self._concurrency = max(1, concurrency)
        
        if not self._root.is_dir():
            raise FileNotFoundError(f"Root directory not found: {self._root}")

    @classmethod
    def from_config(
        cls,
        root: str,
        config_path: str,
        logger: ConsoleManager,
        *,
        excludes: Optional[List[str]] = None,
        enabled_signature_names: Optional[List[str]] = None,
        dry_run: bool = False,
        verbose: bool = False,  # Note: verbose/quiet handled in logger
        quiet: bool = False,    # Note: verbose/quiet handled in logger
        concurrency: Optional[int] = None,
    ) -> "PathHeaderAnnotator":
        """Factory that loads and validates the JSON/JSONC configuration."""
        
        root_path = Path(root)
        
        # 1. Load and normalize config
        config = cls.load_config(config_path)
        
        # 2. Filter signatures if names are provided
        if enabled_signature_names:
            enabled_set = set(enabled_signature_names)
            filtered_signatures = [
                s for s in config.signatures if s.name in enabled_set
            ]
            if len(filtered_signatures) != len(enabled_set):
                loaded_names = {s.name for s in config.signatures}
                missing = enabled_set - loaded_names
                if missing:
                    raise ValueError(
                        f"Specified signature(s) not found in config: {missing}"
                    )
            config = ResolvedConfig(signatures=filtered_signatures)
            
        # 3. Compile global excludes
        global_exclude_spec = None
        if excludes:
            global_exclude_spec = pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, excludes
            )
            
        # 4. Determine concurrency
        resolved_concurrency = concurrency if concurrency is not None else os.cpu_count() or 4

        return cls(
            root=root_path,
            config=config,
            logger=logger,
            global_exclude_spec=global_exclude_spec,
            dry_run=dry_run,
            concurrency=resolved_concurrency,
        )

    @staticmethod
    def load_config(config_path: str) -> ResolvedConfig:
        """Load & normalize JSON/JSONC config."""
        config_file = Path(config_path)
        if not config_file.is_file():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = commentjson.load(f)
        except Exception as e:
            raise ValueError(f"Failed to parse config file {config_path}: {e}")

        if "signatures" not in data or not isinstance(data["signatures"], list):
            raise ValueError(f"Config must have a top-level 'signatures' array.")

        signatures = []
        for i, sig_dict in enumerate(data["signatures"]):
            if not sig_dict.get("enabled", False):
                continue
            
            # Validate required keys
            for key in ("name", "comment_prefix", "required_suffix"):
                if key not in sig_dict:
                    raise ValueError(
                        f"Signature #{i} (name: {sig_dict.get('name', 'N/A')}) "
                        f"is missing required key: '{key}'"
                    )
            
            signatures.append(Signature.from_dict(sig_dict))
            
        return ResolvedConfig(signatures=signatures)

    def run(self) -> RunReport:
        """
        Execute full traversal/update.
        Returns a RunReport with counts and per-file outcomes.
        """
        self._logger.info(f"Starting scan from root: {self._root}")
        if self._dry_run:
            self._logger.warning("Running in [DRY RUN] mode. No files will be changed.")
            
        report = RunReport()
        files_to_process = []
        
        self._logger.debug("Collecting and sorting files...")
        for file_path in self._root.rglob("*"):
            if file_path.is_file() and not file_path.is_symlink():
                files_to_process.append(file_path)
                
        # Deterministic order
        files_to_process.sort()
        self._logger.debug(f"Found {len(files_to_process)} total files to scan.")

        with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
            futures = {
                executor.submit(self.process_file, path): path
                for path in files_to_process
            }
            
            for future in as_completed(futures):
                path = futures[future]
                try:
                    outcome = future.result()
                    report.tally(outcome)
                    self._logger.report_outcome(outcome, self._dry_run)
                except Exception as e:
                    relpath = self.normalize_relpath(self._root, path)
                    outcome = FileOutcome(
                        path=relpath,
                        action="error",
                        reason=f"Unhandled exception: {e}"
                    )
                    report.tally(outcome)
                    self._logger.report_outcome(outcome, self._dry_run)

        # Ensure deterministic reporting
        report.outcomes.sort(key=lambda o: o.path)
        return report

    def process_file(self, file_path: Path) -> FileOutcome:
        """
        Process a single file if it matches a signature.
        This is the core worker function for the thread pool.
        """
        relpath = self.normalize_relpath(self._root, file_path)
        
        try:
            # 1. Global Exclude Check
            if (self._global_exclude_spec and 
                self._global_exclude_spec.match_file(relpath)):
                return FileOutcome(
                    path=relpath, 
                    action="skipped_excluded", 
                    reason="Global exclude"
                )
                
            # 2. Find Matching Signature
            matched_sig = None
            for sig in self._config.signatures:
                if self._matches_signature(relpath, sig):
                    matched_sig = sig
                    break
            
            if not matched_sig:
                return FileOutcome(path=relpath, action="skipped_no_match")

            # 3. Per-Signature Exclude Check
            if (matched_sig.exclude_spec and 
                matched_sig.exclude_spec.match_file(relpath)):
                return FileOutcome(
                    path=relpath, 
                    action="skipped_excluded", 
                    reason=f"Signature '{matched_sig.name}' exclude",
                    signature_name=matched_sig.name
                )
            
            # 4. File Content Processing
            encoding, newline_char, lines = self._read_file_content(file_path)
            
            first_nonblank_line, first_nonblank_idx = self._find_first_nonblank(lines)
            
            # 5. Get Header Decision
            canonical_header = f"{matched_sig.comment_prefix} {relpath}"
            
            decision = self._decide_header_action(
                first_nonblank_line,
                first_nonblank_idx,
                matched_sig,
                canonical_header
            )
            
            # 6. Act on Decision
            if decision.action == "skip":
                return FileOutcome(
                    path=relpath, 
                    action="skipped_correct",
                    signature_name=matched_sig.name
                )

            # It's an "insert" or "update"
            outcome_action = (
                "inserted" if decision.action == "insert" else "updated"
            )
            
            if self._dry_run:
                return FileOutcome(
                    path=relpath, 
                    action=outcome_action, 
                    signature_name=matched_sig.name,
                    reason="Dry run"
                )
            
            # 7. Write Changes (Not a dry run)
            self._write_file_content(
                file_path, lines, decision, encoding, newline_char
            )
            
            return FileOutcome(
                path=relpath, 
                action=outcome_action, 
                signature_name=matched_sig.name
            )

        except Exception as e:
            return FileOutcome(
                path=relpath, 
                action="error", 
                reason=str(e),
                signature_name=getattr(matched_sig, 'name', None)
            )

    def _matches_signature(self, relpath: str, sig: Signature) -> bool:
        """Check if a relative path matches a signature's filters."""
        # 1. Must end with required_suffix
        if not relpath.endswith(sig.required_suffix):
            return False
        
        # 2. Check extensions (if provided)
        if sig.extensions:
            if not any(relpath.endswith(ext) for ext in sig.extensions):
                return False
        
        # 3. Check globs (if provided)
        if sig.globs:
            if not any(fnmatch.fnmatch(relpath, glob) for glob in sig.globs):
                return False
        
        return True

    def _detect_encoding(self, file_path: Path) -> str:
        """Best-effort encoding detection per spec."""
        try:
            # Try reading as UTF-8 first
            with open(file_path, "rb") as f:
                f.read().decode(self.DEFAULT_ENCODING)
            return self.DEFAULT_ENCODING
        except UnicodeDecodeError:
            self._logger.debug(
                f"File {file_path} not {self.DEFAULT_ENCODING}, "
                f"falling back to {self.FALLBACK_ENCODING}"
            )
            return self.FALLBACK_ENCODING
        except Exception:
            # File might be empty or unreadable, default to fallback
            return self.FALLBACK_ENCODING

    def _read_file_content(self, file_path: Path) -> Tuple[str, str, List[str]]:
        """
        Read file, detecting encoding and newlines.
        Returns (encoding, newline_char, list_of_lines).
        """
        encoding = self._detect_encoding(file_path)
        
        with open(file_path, "r", encoding=encoding, newline='') as f:
            content = f.read()
            
            # f.newlines is the detected newline.
            # It can be a tuple if mixed, or None if no newlines.
            newlines = f.newlines
            if isinstance(newlines, tuple):
                self._logger.warning(
                    f"Mixed newlines in {file_path}; "
                    f"preserving first detected: {newlines[0]!r}"
                )
                newline_char = newlines[0]
            elif newlines is None:
                # No newlines detected (e.g., empty file or single line no EOL)
                # Default to system lineterminator
                newline_char = os.linesep
            else:
                newline_char = newlines  # e.g., "\n" or "\r\n"
        
        # splitlines() correctly handles all newline types
        lines = content.splitlines() 
        return encoding, newline_char, lines

    def _write_file_content(
        self,
        file_path: Path,
        lines: List[str],
        decision: HeaderDecision,
        encoding: str,
        newline_char: str
    ):
        """Write the modified lines list back to the file."""
        if decision.action == "insert":
            lines.insert(decision.line_index, decision.text)
        elif decision.action == "update":
            lines[decision.line_index] = decision.text
        
        # Re-join with the *detected* newline
        content = newline_char.join(lines)
        
        # Add a trailing newline if the list is not empty
        # (splitlines() drops the final one)
        if lines:
            content += newline_char
            
        file_path.write_text(content, encoding=encoding, newline=newline_char)

    @staticmethod
    def _find_first_nonblank(lines: List[str]) -> Tuple[Optional[str], int]:
        """Find the first non-blank line and its index."""
        for i, line in enumerate(lines):
            if line.strip():
                return line, i
        return None, 0 # No non-blank lines, target index is 0

    @staticmethod
    def normalize_relpath(root: Path, file_path: Path) -> str:
        """Return POSIX-style relative path (forward slashes)."""
        relpath = file_path.relative_to(root)
        return relpath.as_posix()

    @staticmethod
    def _decide_header_action(
        first_nonblank_line: Optional[str],
        first_nonblank_idx: int,
        sig: Signature,
        canonical_header: str
    ) -> HeaderDecision:
        """
        Decide whether to INSERT or OVERWRITE and build the exact line text.
        """
        
        if first_nonblank_line is None:
            # File is empty or all whitespace
            return HeaderDecision(
                action="insert",
                text=canonical_header,
                line_index=0, # Insert at the very top
                existing_line_count=0
            )

        # Check if the line matches the *pattern*
        if sig.detection_pattern.match(first_nonblank_line):
            # It's a header. Is it the *correct* header?
            if first_nonblank_line == canonical_header:
                # Already perfect
                return HeaderDecision(
                    action="skip",
                    text=canonical_header,
                    line_index=first_nonblank_idx,
                    existing_line_count=1
                )
            else:
                # It's a header, but wrong path (e.g., file moved)
                return HeaderDecision(
                    action="update",
                    text=canonical_header,
                    line_index=first_nonblank_idx,
                    existing_line_count=1
                )
        else:
            # It's a non-blank line, but not our header (e.g., `import os`)
            return HeaderDecision(
                action="insert",
                text=canonical_header,
                line_index=first_nonblank_idx, # Insert *before* this line
                existing_line_count=0
            )


# --- CLI Entrypoint ---

def main():
    """Command-line interface entrypoint."""
    parser = argparse.ArgumentParser(
        description="Recursively add or update a first-line path comment in files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  path-annotate \\
    --root ./src \\
    --config ./path-annotate.jsonc \\
    --exclude "**/node_modules/**" \\
    --exclude "**/.venv/**" \\
    --dry-run \\
    --print-summary
"""
    )
    
    # Required args
    parser.add_argument(
        "--root", 
        type=str, 
        required=True,
        help="Top-level directory to process."
    )
    parser.add_argument(
        "--config", 
        type=str, 
        required=True,
        help="JSON or JSONC configuration file defining signatures."
    )
    
    # Optional args
    parser.add_argument(
        "--exclude",
        action="append",
        dest="excludes",
        help="Paths or globs to omit (relative to --root). Repeatable."
    )
    parser.add_argument(
        "--signature",
        action="append",
        dest="enabled_signature_names",
        help="Limit processing to one or more signature names. Repeatable."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change; do not write to any files."
    )
    parser.add_argument(
        "--fail-on-change",
        action="store_true",
        help="Exit non-zero if any modifications would be/were made."
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print a final counts table at the end of the run."
    )
    parser.add_argument(
        "-j", "--concurrency",
        type=int,
        help="Optional parallelism (default: system CPU count)."
    )
    
    # Output control
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Emit per-file decisions and reasons (DEBUG level)."
    )
    output_group.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress non-errors (ERROR level)."
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color codes in output."
    )
    
    args = parser.parse_args()

    # 1. Set up logging level
    if args.quiet:
        log_level = logging.ERROR
    elif args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
        
    logging.basicConfig(
        level=log_level,
        format="%(message)s", # Handled by ConsoleManager
        handlers=[logging.StreamHandler(sys.stderr)] # Log to stderr
    )
    
    console = ConsoleManager(level=log_level, no_color=args.no_color)

    # 2. Run the annotator
    try:
        annotator = PathHeaderAnnotator.from_config(
            root=args.root,
            config_path=args.config,
            logger=console,
            excludes=args.excludes,
            enabled_signature_names=args.enabled_signature_names,
            dry_run=args.dry_run,
            concurrency=args.concurrency,
        )
        
        report = annotator.run()

        # 3. Print summary if requested
        if args.print_summary:
            console.print_summary(report)
        
        # 4. Determine exit code
        if report.files_with_errors > 0:
            console.error(
                f"Run finished with {report.files_with_errors} error(s)."
            )
            sys.exit(2)
            
        if args.fail_on_change and report.total_changes > 0:
            console.warning(
                f"Exiting with code 3: --fail-on-change was set and "
                f"{report.total_changes} change(s) were detected."
            )
            sys.exit(3)
            
        sys.exit(0) # Success

    except (FileNotFoundError, ValueError, TypeError) as e:
        console.critical(f"Configuration or Usage Error: {e}")
        sys.exit(1)
    except Exception as e:
        console.critical(f"An unexpected error occurred: {e}", exc_info=args.verbose)
        sys.exit(2)


if __name__ == "__main__":
    main()