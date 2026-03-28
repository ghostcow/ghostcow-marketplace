#!/usr/bin/env python3
"""
PostToolUse hook for formatting Python files after editing.
This hook runs after Edit, Write, or MultiEdit operations and applies ruff formatting.
"""

import json
import subprocess
import sys
from pathlib import Path

# Exit code constants
HOOK_SUCCESS = 0  # Continue normally
HOOK_WARN = 1  # Show output but don't block

# Ruff format exit codes
RUFF_SUCCESS = 0
RUFF_ERROR = 2  # Format doesn't use exit code 1


def has_ruff_config(file_path):
    """Check if a ruff config exists in the project by walking up from the file."""
    current = Path(file_path).resolve().parent
    for directory in [current, *current.parents]:
        if (directory / "ruff.toml").is_file() or (directory / ".ruff.toml").is_file():
            return True
        pyproject = directory / "pyproject.toml"
        if pyproject.is_file():
            try:
                content = pyproject.read_text()
                if "[tool.ruff]" in content:
                    return True
            except OSError:
                pass
    return False


def print_output(stdout, stderr, stdout_to_stderr=False):
    """Print command output to appropriate streams."""
    if stdout:
        target = sys.stderr if stdout_to_stderr else sys.stdout
        print(stdout, file=target, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")


def main():
    """Main function to run ruff format hook."""
    try:
        # Read hook input data
        hook_data = json.load(sys.stdin)
        tool_input = hook_data.get("tool_input", {})

        # Get the file path from tool input
        file_path = tool_input.get("file_path", "")

        # Only process Python files and only for file editing tools
        if not file_path or not file_path.endswith((".py", ".pyi")):
            # Not a Python file, exit successfully
            print("Ruff format: Not a python file, skipping.", file=sys.stderr)
            sys.exit(HOOK_SUCCESS)

        # Build command: use --line-length only as fallback when no project config exists
        cmd = ["ruff", "format"]
        if not has_ruff_config(file_path):
            cmd += ["--line-length", "120"]
        cmd.append(file_path)

        # Run ruff format
        try:
            format_result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            print("Ruff not found. Please install ruff.", file=sys.stderr)
            sys.exit(HOOK_WARN)

        # Handle ruff exit codes
        if format_result.returncode == RUFF_SUCCESS:
            # Success - files were formatted or already formatted
            print_output(format_result.stdout, format_result.stderr)
            sys.exit(HOOK_SUCCESS)
        elif format_result.returncode == RUFF_ERROR:
            # Abnormal termination - config or internal error
            print("Ruff format error", file=sys.stderr)
            print_output(format_result.stdout, format_result.stderr, stdout_to_stderr=True)
            sys.exit(HOOK_WARN)
    except Exception as e:
        print(f"Hook error: {e}", file=sys.stderr)
        sys.exit(HOOK_WARN)  # Don't block on hook errors


if __name__ == "__main__":
    main()
