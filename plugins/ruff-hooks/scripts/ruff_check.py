#!/usr/bin/env python3
"""
PostToolUse hook for checking Python files after editing.
This hook runs after Edit, Write, or MultiEdit operations and applies ruff checking.
NOTE: Excludes import checks (F401) which are handled by the Stop hook.
"""

import json
import subprocess
import sys

# Exit code constants
HOOK_SUCCESS = 0  # Continue normally
HOOK_WARN = 1  # Show output but don't block
HOOK_BLOCK = 2  # Block Claude and show error

# Ruff exit codes
RUFF_SUCCESS = 0
RUFF_VIOLATIONS = 1
RUFF_ERROR = 2


def print_output(stdout, stderr, stdout_to_stderr=False):
    """Print command output to appropriate streams."""
    if stdout:
        target = sys.stderr if stdout_to_stderr else sys.stdout
        print(stdout, file=target, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")


def main():
    """Main function to run ruff check hook."""
    try:
        # Read hook input data
        hook_data = json.load(sys.stdin)
        tool_input = hook_data.get("tool_input", {})

        # Get the file path from tool input
        file_path = tool_input.get("file_path", "")

        # Only process Python files and only for file editing tools
        if not file_path or not file_path.endswith((".py", ".pyi")):
            # Not a Python file, exit successfully
            print("Ruff check: Not a python file, skipping.", file=sys.stderr)
            sys.exit(HOOK_SUCCESS)

        # Run ruff check with comprehensive linting for production code
        try:
            check_result = subprocess.run(
                [
                    "ruff",
                    "check",
                    "--fix",
                    "--extend-select",
                    # Combine all selected rules into a single comma-separated string
                    ",".join(
                        [
                            # === CORE ERRORS (Must Have) ===
                            "F",  # Pyflakes: undefined names, unused imports, syntax errors (F401 ignored below)
                            "E4",
                            "E7",
                            "E9",  # Critical pycodestyle errors (E4: import, E7: statement, E9: syntax)
                            "I",  # isort: import organization and grouping logic
                            # === CODE QUALITY & BUGS ===
                            "B",  # bugbear: likely bugs and design problems (mutable defaults, etc.)
                            "UP",  # pyupgrade: modernize syntax for target Python version
                            "C4",  # comprehensions: unnecessary list/dict comprehensions
                            "SIM",  # simplify: code simplification opportunities
                            "PIE",  # pie: miscellaneous improvements
                            "RUF",  # Ruff-specific: quality improvements (unused noqa, etc.)
                            # === TYPE SAFETY ===
                            # ANN removed - too strict for practical use
                            # TCH removed - type-checking imports optimization not needed
                            # FA removed - future annotations too pedantic
                            # === DATA SCIENCE SPECIFIC ===
                            "PD",  # pandas-vet: pandas best practices and anti-patterns
                            "NPY",  # numpy: numpy deprecations and best practices
                            # === RELIABILITY & CORRECTNESS ===
                            "PLC",  # Pylint Convention: general conventions
                            "PLE",  # Pylint Error: likely errors
                            "PLW",  # Pylint Warning: suspicious code patterns
                            "RET",  # return: return statement consistency
                            "RSE",  # raise: exception raising patterns
                            "ISC",  # implicit-str-concat: catch accidental string concatenation
                            "ARG",  # unused-arguments: catch unused function arguments
                            # PTH removed - pathlib enforcement too strict
                            "ASYNC",  # async: async/await best practices
                            "PERF",  # perflint: performance anti-patterns
                            # === TESTING ===
                            "PT",  # pytest-style: pytest best practices
                        ]
                    ),
                    "--extend-ignore",
                    # Combine all ignored rules into a single comma-separated string
                    ",".join(
                        [
                            # === FORMATTING (handled by format hook) ===
                            "E1",
                            "E2",
                            "E3",
                            "E5",  # pycodestyle formatting
                            "W",  # pycodestyle warnings (whitespace)
                            "E501",  # Line too long
                            "E722",  # Bare except - sometimes needed
                            # === IMPORT EXCEPTIONS ===
                            "F401",  # UNUSED IMPORTS - Will be checked in Stop hook on whole directory
                            "PLC0415",  # import-outside-toplevel - sometimes needed for lazy loading
                            # === PANDAS EXCEPTIONS ===
                            "PD901",  # df is a perfectly fine variable name in context
                            # === UNICODE EXCEPTIONS ===
                            "RUF001",  # Ambiguous unicode in string - false positives on non-English text
                            "RUF002",  # Ambiguous unicode in docstring - false positives on non-English text
                            "RUF003",  # Ambiguous unicode in comment - false positives on non-English text
                        ]
                    ),
                    file_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            print("Ruff not found. Please install ruff.", file=sys.stderr)
            sys.exit(HOOK_WARN)

        # Handle ruff exit codes
        if check_result.returncode == RUFF_SUCCESS:
            # Success - no violations found
            print_output(check_result.stdout, check_result.stderr)
            sys.exit(HOOK_SUCCESS)
        elif check_result.returncode == RUFF_VIOLATIONS:
            # Violations found - block Claude and show errors
            print_output(check_result.stdout, check_result.stderr, stdout_to_stderr=True)
            sys.exit(HOOK_BLOCK)
        elif check_result.returncode == RUFF_ERROR:
            # Config/internal error - warn but don't block
            print(f"Ruff error (exit code {check_result.returncode})", file=sys.stderr)
            print_output(check_result.stdout, check_result.stderr)
            sys.exit(HOOK_WARN)

    except Exception as e:
        print(f"Hook error: {e}", file=sys.stderr)
        sys.exit(HOOK_WARN)  # Don't block on hook errors


if __name__ == "__main__":
    main()
