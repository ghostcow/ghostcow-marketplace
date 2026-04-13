---
name: review-plugin
description: Reviews Claude Code plugin changes on a PR branch using rubric-driven evaluation with expectation-grounded assessment. Use when the user asks to review plugin prompt changes, critique a plugin PR, or improve plugin prompts.
---

# Plugin Critic — Review

You orchestrate a multi-agent review of Claude Code plugin changes on the current PR
branch. Six agents work in sequential phases to produce an evidence-based design
evaluation grounded in quality rubrics and prompting best practices.

## Prerequisites

You must be on a PR branch with plugin changes (prompt files, agent definitions, skills,
config). If not on a branch with changes, ask the user which branch to review.

Determine the **plugin path** by inspecting the branch's changed files. If multiple
plugins are changed, ask the user which to review.

If the user volunteers notes about the plugin or the changes (goals, context, concerns),
keep them for passing to the summarizer agents. These notes are optional — the system
works without them, and you should never ask the user for them.

## Phase 1: Setup

Prepare the workspace and resources.

### 1.1 Create workspace

Create a temporary workspace directory at `/tmp/claude/plugin-critic-{timestamp}/`.

### 1.2 Create base branch worktree

Create a git worktree for the base branch so agents can read pre-change files:

```bash
git worktree add {workspace}/base-worktree main
```

If this fails (e.g., main is already checked out), use the detached HEAD form:

```bash
git worktree add --detach {workspace}/base-worktree main
```

If the branch ref doesn't resolve at all, inform the user and ask which branch
represents the pre-change baseline.

Store the path `{workspace}/base-worktree` as `{base_worktree}`.

### 1.3 Detect new plugin

Check whether the plugin path exists on the base worktree:

```bash
test -d {base_worktree}/{plugin_path}
```

If the directory does not exist, this PR introduces a new plugin. Store
`{is_new_plugin} = true`. The pipeline adapts: Phase A summarizes the PR branch
version instead of a base version, and Phase B sees an empty base and describes
everything as additions. Phases C and D proceed unchanged.

If the directory exists, this is a modification to an existing plugin. Store
`{is_new_plugin} = false` and proceed with the standard pipeline.

### 1.4 Fetch best practices

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/fetch-best-practices.sh "{workspace}/best-practices.md"
```

If the script fails, stop the review and inform the user. The best-practices file is
essential — it is the external quality standard that grounds every evaluator's
expectations. The review cannot proceed without it.

## Phase 2: Run Review Pipeline

Launch agents in four sequential phases using the Agent tool. Each agent reads its
inputs from files in the workspace and writes its output to designated files. Wait for
each phase to complete before starting the next.

All agents use their corresponding definition from `${CLAUDE_PLUGIN_ROOT}/agents/`.
Pass file paths in agent prompts, not file content.

### Phase A: Summarize Base

Launch one agent. When `{is_new_plugin}` is true, pass the PR branch plugin path
instead of the base worktree path — the base-summarizer describes whatever plugin is at
the given path, so for a new plugin it summarizes the version introduced by the PR.

**base-summarizer** (agent: `base-summarizer.md`)
```
Summarize the plugin at: {base_worktree}/{plugin_path}    [or {plugin_path} when {is_new_plugin}]
Plugin system reference file: ${CLAUDE_PLUGIN_ROOT}/defaults/plugin-system-reference.md
Best practices file: {workspace}/best-practices.md
System overview output file: {workspace}/system-overview.md
Ground file output paths:
  ground-coverage-economy: {workspace}/ground-coverage-economy.md
  ground-soundness-resilience: {workspace}/ground-soundness-resilience.md
  ground-implementability: {workspace}/ground-implementability.md
```

If the user provided notes, append:
```
Optional user notes: {notes}
```

Wait for completion before proceeding. If the agent fails, follow the failure procedure
in Guidelines.

### Phase B: Summarize PR

Launch one agent:

**pr-summarizer** (agent: `pr-summarizer.md`)
```
System overview file: {workspace}/system-overview.md
Ground files:
  ground-coverage-economy: {workspace}/ground-coverage-economy.md
  ground-soundness-resilience: {workspace}/ground-soundness-resilience.md
  ground-implementability: {workspace}/ground-implementability.md
Plugin path: {plugin_path}
Base worktree path: {base_worktree}/{plugin_path}
Plugin system reference file: ${CLAUDE_PLUGIN_ROOT}/defaults/plugin-system-reference.md
Best practices file: {workspace}/best-practices.md
Context file output paths:
  context-coverage-economy: {workspace}/context-coverage-economy.md
  context-soundness-resilience: {workspace}/context-soundness-resilience.md
  context-implementability: {workspace}/context-implementability.md
```

When `{is_new_plugin}` is true, append:
```
This is a new plugin — the base worktree contains no plugin files at this path.
Describe all PR branch files as additions.
```

If the user provided notes, append:
```
Optional user notes: {notes}
```

Wait for completion before proceeding. If the agent fails, follow the failure procedure
in Guidelines.

### Phase C: Evaluate

Launch three evaluator agents in parallel, one per criterion group. Each uses agent
definition `evaluator.md`:

**evaluator-coverage-economy** (agent: `evaluator.md`)
```
Ground file: {workspace}/ground-coverage-economy.md
Context file: {workspace}/context-coverage-economy.md
Rubric file: ${CLAUDE_PLUGIN_ROOT}/defaults/rubric-coverage-economy.md
Plugin path: {plugin_path}
Plugin system reference file: ${CLAUDE_PLUGIN_ROOT}/defaults/plugin-system-reference.md
Best practices file: {workspace}/best-practices.md
Expectations output file: {workspace}/expectations-coverage-economy.md
Evaluation output file: {workspace}/eval-coverage-economy.md
```

**evaluator-soundness-resilience** (agent: `evaluator.md`)
```
Ground file: {workspace}/ground-soundness-resilience.md
Context file: {workspace}/context-soundness-resilience.md
Rubric file: ${CLAUDE_PLUGIN_ROOT}/defaults/rubric-soundness-resilience.md
Plugin path: {plugin_path}
Plugin system reference file: ${CLAUDE_PLUGIN_ROOT}/defaults/plugin-system-reference.md
Best practices file: {workspace}/best-practices.md
Expectations output file: {workspace}/expectations-soundness-resilience.md
Evaluation output file: {workspace}/eval-soundness-resilience.md
```

**evaluator-implementability** (agent: `evaluator.md`)
```
Ground file: {workspace}/ground-implementability.md
Context file: {workspace}/context-implementability.md
Rubric file: ${CLAUDE_PLUGIN_ROOT}/defaults/rubric-implementability.md
Plugin path: {plugin_path}
Plugin system reference file: ${CLAUDE_PLUGIN_ROOT}/defaults/plugin-system-reference.md
Best practices file: {workspace}/best-practices.md
Expectations output file: {workspace}/expectations-implementability.md
Evaluation output file: {workspace}/eval-implementability.md
```

Wait for all three to complete before proceeding. If any evaluator fails, follow the
failure procedure in Guidelines.

### Phase D: Synthesize

Launch one agent:

**synthesizer** (agent: `synthesizer.md`)
```
Evaluation files:
  - {workspace}/eval-coverage-economy.md
  - {workspace}/eval-soundness-resilience.md
  - {workspace}/eval-implementability.md
Plugin path: {plugin_path}
Plugin system reference file: ${CLAUDE_PLUGIN_ROOT}/defaults/plugin-system-reference.md
Best practices file: {workspace}/best-practices.md
Output file: {workspace}/review.md
```

Wait for completion. If the agent fails, follow the failure procedure in Guidelines.

## Phase 3: Present Findings

When the synthesizer completes, read `{workspace}/review.md` and relay it to the user.
Present the review as the synthesizer wrote it — do not rewrite, reformat, or editorialize.

After presenting, offer to show any individual evaluation file if the user wants to see
the evaluator's detailed expectations and findings.

## Guidelines

- Delegate all plugin file reading to the agents — keeping your context free of plugin
  content preserves impartiality when presenting findings.
- Pass agent outputs through file paths in task descriptions. Let the agents' words
  speak for themselves.
- The pipeline completes fully with all phases succeeding, or it does not produce a
  review. The synthesizer requires all three evaluations to produce a balanced
  cross-dimensional review, so partial results would be incomplete and misleading. If
  any agent fails, stop the pipeline and present two options to the user:
  (a) retry the failed agent(s) and continue the pipeline normally once they succeed, or
  (b) stop the review entirely.
- The orchestrator manages phase sequencing — wait for each phase to complete before
  launching the next. Agents within a phase run in parallel.
- The workspace is in `/tmp/claude` and will be cleaned up by the OS. Leave it intact so the
  user can read intermediate files if they choose.
