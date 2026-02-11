import argparse
import sys
from unittest.mock import patch

# -----------------------------------------------------------------------------
# Execution Logic
# -----------------------------------------------------------------------------


def run_python_tool(tool_module, args):
    """
    Runs a Python tool's main function.
    We patch sys.argv so the tool's internal argparse handles the flags.
    """
    # 1. Construct a simulated argv: [script_name, ...args]
    #    e.g. ['to_markdown', '-h'] or ['path_annotate', 'src/', '--verbose']
    simulated_argv = [tool_module.__name__] + args

    # 2. Patch sys.argv and run the tool
    with patch.object(sys, "argv", simulated_argv):
        try:
            tool_module.main()
        except SystemExit as e:
            # Propagate exit codes cleanly (0 for success, non-zero for error)
            if e.code is not None and e.code != 0:
                sys.exit(e.code)
        except Exception as e:
            # Catch unhandled exceptions to prevent raw stack traces if desired
            print(f"Error executing {tool_module.__name__}: {e}", file=sys.stderr)
            sys.exit(1)


# -----------------------------------------------------------------------------
# Main Commander
# -----------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Codetools Commander", prog="codetools"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- 'run' Sub-command ---
    run_parser = subparsers.add_parser("run", help="Run a specific codetool")
    tool_subparsers = run_parser.add_subparsers(dest="tool", required=True)

    # -------------------------------------------------------------------------
    # Tool Definitions
    # -------------------------------------------------------------------------
    # Note: We use add_help=False so 'codetools run markdown -h'
    # doesn't trigger *this* parser's help, but passes it to the tool.

    tool_subparsers.add_parser(
        "annotate", help="Run Path Annotate utility", add_help=False
    )

    tool_subparsers.add_parser(
        "inventory", help="Run Python API Inventory utility", add_help=False
    )

    tool_subparsers.add_parser(
        "markdown", help="Run Markdown Generator utility", add_help=False
    )

    # -------------------------------------------------------------------------
    # Dispatch Logic
    # -------------------------------------------------------------------------

    # parse_known_args returns (known_args, list_of_unknown_strings)
    # 'extra_args' will contain flags like '-h', '--input', etc.
    args, extra_args = parser.parse_known_args()

    if args.command == "run":

        if args.tool == "annotate":
            from codetools.annotate import path_annotate

            run_python_tool(path_annotate, extra_args)

        elif args.tool == "inventory":
            from codetools.inventory import py_api_inventory

            run_python_tool(py_api_inventory, extra_args)

        elif args.tool == "markdown":
            from codetools.markdown import to_markdown

            run_python_tool(to_markdown, extra_args)


if __name__ == "__main__":
    main()
