# Ruff Hooks Plugin

Automatic Python linting and formatting with [Ruff](https://github.com/astral-sh/ruff) on file edits.

## Requirements

Install Ruff:

```bash
pip install ruff
# or
uv pip install ruff
```

## What It Does

This plugin adds a PostToolUse hook that runs automatically after `Write`, `Edit`, or `MultiEdit` operations on Python files:

### 1. Ruff Check (with auto-fix)

Runs comprehensive linting with auto-fix enabled. Blocks Claude if unfixable violations are found.

**Enabled rules:**
- **Core**: Pyflakes (F), critical pycodestyle (E4, E7, E9), isort (I)
- **Code Quality**: bugbear (B), pyupgrade (UP), comprehensions (C4), simplify (SIM), pie (PIE), Ruff-specific (RUF)
- **Data Science**: pandas-vet (PD), numpy (NPY)
- **Reliability**: Pylint (PLC, PLE, PLW), return (RET), raise (RSE), implicit-str-concat (ISC), unused-arguments (ARG), async (ASYNC), perflint (PERF)
- **Testing**: pytest-style (PT)

**Ignored rules:**
- Formatting rules (handled by format hook)
- F401 (unused imports) - too noisy during development
- Some pandas/unicode rules that cause false positives

### 2. Ruff Format Check (warn-only)

After linting, runs `ruff format --check` with a 120-character line length. This never rewrites the file — it only warns Claude if the file isn't formatted, leaving the actual reformatting to you or to `ruff format`.

## Installation

```
/plugin install ruff-hooks@airis-marketplace
```

## Project Config Integration

The plugin's rules are **additive** with your project's ruff configuration (`pyproject.toml`, `ruff.toml`, or `.ruff.toml`):

- **Check**: Uses `--extend-select` and `--extend-ignore`, so your project's rules are merged with the plugin defaults (not replaced)
- **Format check**: If a ruff config exists in your project, the plugin defers to it entirely (e.g., your `line-length` setting wins). The `--line-length 120` default only applies when no project config is found.

To disable a rule the plugin adds, add it to your project's `ignore` list (since `extend-select` is additive-only, you can't un-select rules — but `ignore` takes precedence):

```toml
[tool.ruff.lint]
ignore = ["PT"]  # Suppresses pytest rules added by the plugin
```

## Behavior

- **Python files only**: The hook skips non-Python files silently
- **Auto-fix**: Linting violations are fixed automatically where possible
- **Blocking**: Unfixable linting errors block Claude until resolved
- **Non-blocking**: An unformatted file, format-check errors, and a missing Ruff installation only warn — none of them rewrite the file
