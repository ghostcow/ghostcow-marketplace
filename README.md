# ghostcow-marketplace

A personal Claude Code plugin marketplace.

## Installation

```
/plugin marketplace add ghostcow/ghostcow-marketplace
```

Then install individual plugins:

```
/plugin install ruff-hooks@ghostcow-marketplace
/plugin install catline-status@ghostcow-marketplace
/plugin install research-assistant@ghostcow-marketplace
```

## Plugins

| Plugin | Description |
|--------|-------------|
| **ruff-hooks** | Runs ruff check (with auto-fix) and ruff format on Python files after every Write, Edit, or MultiEdit. Blocks Claude on unfixable linting violations. |
| **catline-status** | Claude Code statusline showing model, working directory, git branch, and remaining context — with rotating cat face animations. |
| **research-assistant** | Academic research assistant powered by Semantic Scholar. Search papers, explore citation networks, and synthesize findings. |
