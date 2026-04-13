# Plugin Critic — Design

## Problem

When a single agent reads an existing implementation and then tries to critique it, it
anchors to the loaded context. This produces incremental polish instead of genuine design
evaluation. The fix is architectural: structured multi-dimensional evaluation with
expectation construction before artifact reading, combined with criterion isolation
across independent evaluator agents and per-evaluator context routing that prevents
shared orientation from correlating evaluator analyses.

## Architecture

```
User: /review-plugin (on a PR branch)

ORCHESTRATOR (skill — main session, never reads plugin files)
|
+-- Phase 1: Setup
|   +-- create workspace at /tmp/claude/plugin-critic-{timestamp}/
|   +-- create git worktree for main -> workspace/base-worktree/
|   +-- detect new plugin (if base has no plugin files, redirect Phase A to PR branch)
|   +-- fetch best practices -> workspace/best-practices.md (hard fail if unavailable)
|
+-- Phase 2: Agent Pipeline (6 agents, file-based coordination)
|   |
|   |  [Phase A — summarize base, 1 agent]
|   |  BASE SUMMARIZER (worktree: main, or PR branch for new plugins)
|   |    -> workspace/system-overview.md
|   |    -> workspace/ground-coverage-economy.md
|   |    -> workspace/ground-soundness-resilience.md
|   |    -> workspace/ground-implementability.md
|   |
|   |  [Phase B — summarize PR, 1 agent, depends on Phase A]
|   |  PR SUMMARIZER (cwd: PR branch)
|   |    reads: system-overview + 3 ground files
|   |    -> workspace/context-coverage-economy.md
|   |    -> workspace/context-soundness-resilience.md
|   |    -> workspace/context-implementability.md
|   |
|   |  [Phase C — evaluate, 3 agents in parallel, depends on Phase B]
|   |  EVALUATOR 1 reads: ground-cov-econ + context-cov-econ + rubric-cov-econ
|   |    -> workspace/expectations-coverage-economy.md   (written before plugin read)
|   |    -> workspace/eval-coverage-economy.md
|   |  EVALUATOR 2 reads: ground-snd-res + context-snd-res + rubric-snd-res
|   |    -> workspace/expectations-soundness-resilience.md
|   |    -> workspace/eval-soundness-resilience.md
|   |  EVALUATOR 3 reads: ground-impl + context-impl + rubric-impl
|   |    -> workspace/expectations-implementability.md
|   |    -> workspace/eval-implementability.md
|   |
|   |  [Phase D — synthesize, 1 agent, depends on Phase C]
|   |  SYNTHESIZER reads: 3 eval files + 3 expectations files + plugin files + best-practices
|   |    -> workspace/review.md
|
+-- Phase 3: Present — read review.md, relay to user
```

## Information Isolation

| Data | Orch. | Base Sum. | PR Sum. | Eval 1 | Eval 2 | Eval 3 | Synth. |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Best practices | No | Yes | Yes | Yes | Yes | Yes | Yes |
| system-overview.md | No | -- | Yes | No | No | No | No |
| ground-coverage-economy.md | No | -- | Yes | Yes | No | No | No |
| ground-soundness-resilience.md | No | -- | Yes | No | Yes | No | No |
| ground-implementability.md | No | -- | Yes | No | No | Yes | No |
| context-coverage-economy.md | No | No | -- | Yes | No | No | No |
| context-soundness-resilience.md | No | No | -- | No | Yes | No | No |
| context-implementability.md | No | No | -- | No | No | Yes | No |
| Pre-change plugin files | No | Yes | Yes | No | No | No | No |
| PR branch plugin files | No | No | Yes | Yes | Yes | Yes | Yes |
| rubric-coverage-economy.md | No | No | No | Yes | No | No | No |
| rubric-soundness-resilience.md | No | No | No | No | Yes | No | No |
| rubric-implementability.md | No | No | No | No | No | Yes | No |
| eval-coverage-economy.md | No | No | No | -- | No | No | Yes |
| eval-soundness-resilience.md | No | No | No | No | -- | No | Yes |
| eval-implementability.md | No | No | No | No | No | -- | Yes |
| review.md | Yes | No | No | No | No | No | -- |

Zero shared summary context across evaluators. Each evaluator receives exactly one
ground file, one context file, one rubric file, best practices, and the plugin files.
The orchestrator's context contains only the final review.

## Quality Evaluation

Evaluators use expectation-grounded assessment, a methodology adapted from PlanJudge
(Huang et al., 2026). Each evaluator constructs expectations for what a strong
implementation should look like — using only its ground file, context file, and best
practices — before reading the plugin files. This sequence is the core debiasing
mechanism: expectations formed before reading prevent anchoring to whatever the
implementation happens to do.

Three evaluator agents run in parallel, each handling one or two criteria from a group
of five quality dimensions:

- **Coverage + Economy** — both examine "is the right stuff here?" from complementary
  angles. Coverage asks what's missing; Economy asks what's superfluous.
- **Soundness + Resilience** — both examine "is this design robust?" Soundness is static
  structure quality; Resilience is dynamic failure behavior under LLM-specific conditions.
- **Implementability** — traces end-to-end flow and measures the design-to-implementation
  gap. A different analytical mode that does not pair naturally with the other criteria.

Keeping each evaluator at 2 or fewer criteria preserves genuine independence while
reducing the agent count from five to three (see Research Foundations).

The five quality dimensions are defined across three rubric files in `defaults/`:

1. **Requirement Coverage** — does the design address all stated requirements?
2. **Design Economy** — does the design achieve its goals with minimum complexity?
3. **Architectural Soundness** — are responsibilities, flows, and interfaces well-defined?
4. **Prompt-Architecture Resilience** — does the design contain LLM-specific failure modes?
5. **Implementability** — can the design be faithfully translated into working prompts?

A synthesizer produces an evidence-based review with file-level citations. It receives
the three evaluations, best practices, and the PR plugin files. The evaluator findings —
including their expectations and where the implementation met or fell short — guide the
synthesizer's attention toward what matters.

## Summary Formats

Two summarizer agents produce per-evaluator output files:

- **Base summarizer** produces four files: a system overview (functional description of
  the plugin for the PR summarizer) and three ground files (one per evaluator group).
  Each ground file contains hard constraints (binary, self-contained facts), design
  properties (directional qualities), and evaluable questions (assumptions and tensions
  framed for assessment). The ground files give each evaluator only the system facts
  relevant to its criteria.

- **PR summarizer** produces three context files (one per evaluator group). Each context
  file describes the PR's changes relevant to that evaluator's criteria: change intent,
  design-level changes with rationale and blast radius, and preserved behavior. The PR
  summarizer receives the system overview and all three ground files for orientation.

This per-evaluator routing ensures zero shared summary context across evaluators.

## Coordination Model

The orchestrator launches agents in four sequential phases using the Agent tool. Phases
A and B each run one agent sequentially (the PR summarizer depends on the base summary).
Phase C runs three evaluators in parallel. Phase D runs the synthesizer. Each agent reads
inputs from file paths specified in its prompt and writes its output to designated file
paths.

This file-based coordination means:
- Agent outputs go to workspace files, not through the orchestrator's context
- Agent prompts contain paths, not content
- Agents can produce large outputs without bloating the orchestrator's context window

## New Plugin Path

When a PR introduces a new plugin (the plugin path does not exist on the base branch),
the pipeline adapts rather than skipping phases:

- The orchestrator points the base-summarizer at the PR branch plugin path instead of
  the base worktree. The base-summarizer is agnostic about which version it reads — it
  produces a system overview and ground files for whatever plugin is at the given path.
- The PR summarizer runs normally but receives a note that the base worktree is empty.
  It describes all PR branch files as additions rather than modifications.
- Phases C and D proceed unchanged. Evaluators receive ground + context files as normal.
  The ground files describe the system as introduced; the context files describe
  everything as new.

This preserves the full pipeline and gives evaluators better orientation than rubric and
best practices alone — the ground files still carry hard constraints, design properties,
and evaluable questions derived from the actual plugin.

## Known Constraints

**Context window limits.** Very large plugins may approach model context window limits
during evaluation, particularly for agents that read all plugin files (evaluators and
synthesizer). File-based coordination mitigates this at the orchestrator level — the
orchestrator's context contains only the final review, not plugin content. Individual
agents that read large plugin codebases may still face context pressure. This is an
inherent limit of the approach; for exceptionally large plugins, the evaluators' ability
to hold the complete implementation in context determines review quality.

## Key Decisions

- **Expectation-grounded evaluation.** Evaluators construct expectations before reading
  plugin files. This provides the counterfactual signal ("what should be here?") that
  prevents anchoring. *Alternative rejected: direct holistic scoring, where evaluators
  read the implementation and assess it directly. Without pre-formed expectations,
  criteria scores correlate above 0.93 — a phenomenon called factor collapse (Feuer et
  al., 2025). Contains: anchoring bias.*

- **Per-evaluator context routing.** Summarizers know about evaluator groups and produce
  targeted files. Each evaluator receives only the system facts and change analysis
  relevant to its criteria. This eliminates shared orientation prose that would correlate
  evaluator expectations. *Alternative rejected: full-context broadcast to all agents,
  which scales as O(n*S*|D|) triply-multiplicative overhead (Parakhin, 2026) and dilutes
  evaluator focus on irrelevant information (Liu et al., 2025 — RCR-Router). Contains:
  evaluator correlation (shared prose leading to convergent expectations).*

- **Three grouped evaluators (2+2+1).** Criterion grouping by affinity (Coverage +
  Economy, Soundness + Resilience, Implementability solo) keeps each evaluator at 2 or
  fewer criteria to preserve isolation while reducing coordination overhead. *Alternatives
  rejected: a single evaluator handling all criteria, which causes criteria collapse at
  3+ simultaneous dimensions (Feuer et al., 2025); and one evaluator per criterion, which
  adds coordination overhead and misses within-group coherence checks (Shen et al.,
  2026 — RRD). Contains: criteria collapse.*

- **Impartial review.** The system judges from the code. Optional user notes can flow to
  summarizers as orientation hints, but they are never demanded and never reach
  evaluators or the synthesizer. This prevents the user's natural bias toward their own
  solution from influencing the evaluation. *Alternative rejected: post-hoc bias
  correction, which requires training data or ground truth labels not available in
  zero-shot plugin review (Yang et al., 2025 — RBD; Hong et al., 2026 — RULERS).
  Contains: confirmation bias.*

- **Lean synthesizer inputs.** The synthesizer receives evaluation files, plugin files,
  and best practices — no summary files or user context. Evaluator output is structured
  with evidence and rationale so the synthesizer can select and assemble findings
  directly into the final review. *Alternative rejected: majority voting or mean
  aggregation, which cannot resolve evaluator contradictions and exhibit asymmetric
  failure — 96% true positive rate but less than 25% true negative rate (Jain et al.,
  2025; Roumeliotis et al., 2026). Contains: synthesizer anchoring (summary framing
  influencing how the synthesizer weights findings).*

- **PR summarizer depends on base summary.** The PR summary is more accurate when the
  summarizer understands what the system is before analyzing what changed. *Alternative
  rejected: no base orientation, which causes the PR summarizer to misattribute changes
  when it lacks the baseline picture. Contains: change misattribution.*

- **System overview goes to PR summarizer only.** The architectural description helps
  the PR summarizer understand what changed. Evaluators get criterion-specific ground
  files instead — no shared orientation prose. *Alternative rejected: sharing the system
  overview with all agents, which creates shared orientation prose that correlates
  evaluator expectations (same mechanism as per-evaluator context routing). Contains:
  evaluator correlation.*

- **Ground files carry evaluable questions.** Assumptions and tensions are framed as
  "evaluate whether X holds" — giving evaluators coverage without pre-diagnosing.
  Well-formed questions are discriminative: a real implementation could plausibly fail.
  *Alternative rejected: flat rubric without constraint/property distinction, which
  causes "Evaluation Illusion" where judges anchor on shared surface heuristics — rubric
  structure alone explains 62% of total agreement (Song et al., 2026; Liu et al., 2026 —
  CDRRM). Contains: evaluation gaps (evaluators failing to assess tensions visible from
  the base system but not obvious from the PR alone).*

- **File-based coordination over message passing.** Agent outputs can be large. Passing
  file paths rather than content keeps task descriptions lean and avoids context limits.
  *Alternative rejected: explicit message passing between agents, where inter-agent
  messages leak information at 68.8% versus 27.2% for output-only channels (He et al.,
  2025). Contains: orchestrator context bloat, inter-agent information leakage.*

- **Synthesizer uses evaluator findings as guide, not script.** The evaluator findings
  orient the synthesizer's attention, but the synthesizer brings its own critical
  judgment — it can see cross-dimensional patterns that no individual evaluator could.
  *Alternative rejected: statistical aggregation (e.g., CARE — Zhao et al., 2026), which
  cannot reason about why evaluators disagree, only smooth out the disagreement. Contains:
  blind aggregation (accepting weak findings without critical judgment).*

- **Expectations committed to a separate file before plugin read.** The evaluator writes
  its expectations to `expectations-{group}.md` before opening any plugin file, then
  writes findings to `eval-{group}.md` after. Splitting the artifacts makes the Step 2
  commitment structural (it produces a file, not just context) and gives the synthesizer
  and human auditors an addressable record of what was expected, independent of what was
  found. Findings cite expectations by rubric question (`Q1`, `Q2`, ...). *Alternative
  rejected: combining expectations and findings into one file written at end, which
  loses the distinction between pre-code reasoning and post-code findings. Contains:
  opaque evaluation.*

- **Orchestrator never reads plugin files.** Stays clean to present findings without
  bias. *Alternative rejected: orchestrator reads plugin files and delegates analysis,
  which creates anchoring in task framing — the orchestrator's understanding of the
  plugin would shape how it frames tasks for downstream agents. Contains: orchestrator
  bias.*

- **Workspace survives the review.** The workspace is in `/tmp/claude` and will be cleaned
  up by the OS. The user can read intermediate files (ground files, context files,
  individual evaluations) after the review. *Alternative rejected: automatic cleanup
  after review, which blocks audit and debugging when a review finding seems wrong.
  Contains: audit opacity.*

## Research Foundations

The evaluator's expectation-before-reading sequence — construct expectations from
orientation context, then read the implementation — adapts PlanJudge's structural
debiasing methodology (Huang et al., 2026), which improved BiasBench scores from 67.5
to 95.0 over prompt-based approaches.

Criteria are grouped into evaluator pairs (2+2+1) rather than isolated into five
separate agents. Section-level rubric evaluation outperforms multi-agent council
ensembles when criteria share analytical context (Thorne et al., 2026), and
multi-criteria evaluation collapses into a single latent factor at 3+ simultaneous
criteria, setting the upper bound at 2 per evaluator.

Summarizers produce per-evaluator output files rather than a single shared summary.
Tailoring context per agent role showed 8.3% higher F1 versus uniform context
(Vasumathi et al., 2026), and eliminating shared orientation prose across evaluators
prevents correlation of their expectations.

Ground files use a two-tier structure — binary hard constraints and directional design
properties — adapted from CDRRM's Hard Rules versus Principles distinction (Liu et al.,
2026). Hard constraint items are self-contained and evidence-anchored: each states what
the constraint is and what is currently true, following RULERS' requirement that
checklist items be "auditable from verbatim evidence" (Hong et al., 2026). Evaluable
questions target ~50% expected fail rate and are atomic, self-contained, and verifiable
without external lookup, drawing on RRD's rubric quality properties (Shen et al., 2026).
Context files structure each change with what changed, rationale, affected properties,
and file pointers, adapted from CDRRM's contrastive profiling format.
