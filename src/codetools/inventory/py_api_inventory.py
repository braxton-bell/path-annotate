"""
py_api_inventory.py

Traverses a Python repository and outputs a YAML inventory of the repository's 
API surface (packages, modules, classes, methods, constants, etc.) using
static analysis via `ast`.

This tool is read-only and does not import or execute any of the target code.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from .config import ConfigurationManager
from .core import InventoryService


class CliInterface:
    """
    Handles command-line arguments and application bootstrapping.
    """

    def __init__(self) -> None:
        self._parser = self._build_parser()

    def run(self) -> None:
        args = self._parser.parse_args()

        try:
            config = self._build_config(args)

            service = InventoryService(
                app_config=config,
                root_path=Path(args.root).resolve(strict=True),
            )

            report = service.run_inventory()

            # Determine output path (Default to 'api_signatures.yaml' if not provided)
            output_path = args.output_path or "api_signatures.yaml"
            service.write_yaml(report, output_path)

            if args.print_summary:
                s = report["stats"]
                print(
                    f"\nSummary: {s['files_scanned']} scanned, {s['files_parsed_ok']} ok, {s['files_parse_errors']} errors."
                )

            sys.exit(2 if report["stats"]["files_parse_errors"] > 0 else 0)

        except Exception as e:
            print(f"Fatal Error: {e}")
            sys.exit(1)

    def _build_config(self, args: argparse.Namespace) -> dict[str, Any]:
        overrides = {
            "public_only": args.public_only,
            "include_constants": args.include_constants,
            "include_docstrings": args.include_docstrings,
            "include_enums": args.include_enums,
            "include_functions": args.include_functions,
            "package_mode": args.package_mode,
            "leading_slash_in_paths": args.leading_slash_in_paths,
            "constant_visibility": args.constant_visibility,
            "strip_docstrings": args.strip_docstrings,
            "concurrency": args.concurrency,
            "exclude": args.excludes,
            "_pyproject_path": args.pyproject_path,
        }

        mgr = ConfigurationManager()
        return mgr.load_config(args.config, overrides)

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Python API Signature Extractor.",
            formatter_class=argparse.RawTextHelpFormatter,
        )

        # Core
        parser.add_argument("--root", required=True, help="Top-level directory.")
        parser.add_argument("--config", help="Path to JSON config.")
        parser.add_argument("-e", "--exclude", action="append", dest="excludes")
        parser.add_argument("--pyproject", dest="pyproject_path")

        # Output
        parser.add_argument(
            "-o",
            "--output",
            dest="output_path",
            help="Output YAML file path (default: api_signatures.yaml)",
        )

        # Toggles
        parser.add_argument("--public-only", action="store_true", default=None)
        parser.add_argument("--all-methods", action="store_false", dest="public_only")
        parser.add_argument("--include-constants", action="store_true", default=None)
        parser.add_argument("--include-docstrings", action="store_true", default=None)
        parser.add_argument("--strip-docstrings", action="store_true", default=None)
        parser.add_argument("--include-enums", action="store_true", default=None)
        parser.add_argument("--no-enums", action="store_false", dest="include_enums")
        parser.add_argument("--include-functions", action="store_true", default=None)

        parser.add_argument(
            "--package-mode", choices=["any_dir_with_py", "require_init_py"]
        )
        parser.add_argument(
            "--leading-slash",
            action="store_true",
            dest="leading_slash_in_paths",
            default=None,
        )
        parser.add_argument(
            "--no-leading-slash", action="store_false", dest="leading_slash_in_paths"
        )
        parser.add_argument(
            "--constant-visibility", choices=["no_underscore", "uppercase"]
        )
        parser.add_argument("-j", "--concurrency", type=int)

        # Misc
        parser.add_argument("--print-summary", action="store_true")

        return parser


def main() -> None:
    CliInterface().run()


if __name__ == "__main__":
    main()
