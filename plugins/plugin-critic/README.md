# plugin-critic

A Claude Code plugin that reviews other plugins' prompt architecture using rubric-driven evaluation with expectation-grounded assessment.

## Usage

On a PR branch with plugin changes:

```
/review-plugin
```

The skill detects which plugin changed on the branch, sets up a workspace, and runs the full review pipeline. The final output is a design review with file-level citations and actionable recommendations.

If multiple plugins changed, the skill asks which to review. Optional notes about the changes (goals, context, concerns) can be provided but are never requested.

## How It Works

The review runs in four sequential phases across six agents:

| Phase | Agent(s) | What it does |
|-------|----------|--------------|
| A | base-summarizer | Reads the plugin on the base branch and produces a system overview plus three per-evaluator ground files |
| B | pr-summarizer | Compares both branches and produces three per-evaluator context files describing what the PR changes |
| C | evaluator (x3) | Three parallel evaluators each assess the plugin on their assigned quality criteria |
| D | synthesizer | Selects findings across all evaluations, verifies evidence, and produces the final review |

### Quality Criteria

Five dimensions organized into three independent evaluator groups:

| Group | Criteria | Assesses |
|-------|----------|----------|
| Coverage + Economy | Requirement Coverage, Design Economy | Are all requirements addressed? Is complexity justified? |
| Soundness + Resilience | Architectural Soundness, Prompt-Architecture Resilience | Are boundaries well-drawn? Are LLM failure modes handled? |
| Implementability | Implementability | Can the design be faithfully translated into working code? |

### Key Design Decisions

**Expectation-grounded evaluation.** Evaluators construct expectations for what a strong implementation looks like *before* reading the plugin files. This prevents anchoring bias — evaluators assess against their rubric-driven expectations, not against whatever the implementation happens to do.

**Per-evaluator context routing.** Each evaluator receives only the system facts and change analysis relevant to its criteria. No shared summary context. This prevents correlation between evaluators' analyses and keeps each focused on its quality dimensions.

**File-based coordination.** Agents communicate through workspace files, not through the orchestrator's context. The orchestrator passes file paths in agent prompts, keeping its own context free of plugin content to preserve impartiality when presenting findings.

## File Structure

```
plugin-critic/
  .claude-plugin/
    plugin.json
  skills/
    review-plugin/
      SKILL.md               # Orchestrator — manages phases and agent coordination
  agents/
    base-summarizer.md        # Phase A: system overview + ground files from base branch
    pr-summarizer.md          # Phase B: per-evaluator change context from PR diff
    evaluator.md              # Phase C: expectation-grounded assessment (runs 3x)
    synthesizer.md            # Phase D: cross-dimensional synthesis into final review
  defaults/
    rubric-coverage-economy.md
    rubric-soundness-resilience.md
    rubric-implementability.md
    plugin-system-reference.md  # Plugin system knowledge base for grounding evaluations
  scripts/
    fetch-best-practices.sh   # Fetches Claude prompting best practices at review time
```

## Dependencies

Requires network access to fetch `claude-prompting-best-practices.md` from `platform.claude.com` at review time. The fetch script runs at the start of each review and stores the result in the workspace.

## Limitations

- **Single-plugin scope**: Reviews one plugin per invocation. Cross-plugin interactions are not assessed.
- **Prompt architecture only**: Evaluates design and prompt quality, not runtime behavior. Cannot detect issues that only surface during execution.
- **Base branch comparison**: Requires a base branch (defaults to `main`) for comparison. On the initial PR introducing a new plugin, all files are treated as additions with no prior behavior to compare against.
