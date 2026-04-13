# Rubric: Soundness + Resilience

Two quality dimensions for the Soundness + Resilience evaluator. Both examine "is the
design robust?" Soundness is static structure quality; Resilience is dynamic failure
behavior under LLM-specific conditions. Keeping these two criteria together preserves
their shared analytical context while staying at the 2-criteria isolation threshold.

---

## 3. Architectural Soundness

**Definition:** The degree to which component responsibilities are clearly defined,
information flows are justified and complete, and interfaces between components are
well-specified.

**Evaluation questions:**
- Do component boundaries and information flows use the plugin system's built-in
  mechanisms — tool access control, model selection, isolation, activation scoping —
  correctly and completely? (Consult the plugin system reference for how these mechanisms
  work.)
- Does each agent have a single, well-defined responsibility that can be described
  without referencing other agents?
- Does each agent receive the information it needs and nothing extraneous? Is context
  managed intentionally?
- Are the contracts between agents (what they receive, what they produce, in what
  format) explicit enough that one agent's prompt could be rewritten without
  renegotiating others' expectations?
- Are there points where information is lost, transformed ambiguously, or duplicated
  across agent boundaries?
- Are boundaries drawn at natural seams where information hiding is genuinely useful, or
  are they arbitrary decompositions?
- Does the design account for information degradation across LLM boundaries
  (summarization loss, format drift)?

**Scale:**
- Strong: Each agent's responsibility is clear in one sentence; information flows are
  justified and complete; interfaces are explicit; boundaries are at natural seams
- Partial: Mostly clear boundaries and information flows with some ambiguity, overlap,
  or implicit contracts
- Weak: Unclear responsibilities; information is lost or duplicated across boundaries;
  contracts are implicit; boundaries are arbitrary

---

## 4. Prompt-Architecture Resilience

**Definition:** The degree to which the design anticipates, contains, and recovers from
the specific failure modes of LLM-based multi-agent systems: non-deterministic output,
off-spec formatting, quality variance, and cascading errors through agent pipelines.

**Evaluation questions:**
- What happens when an agent produces output that doesn't match the expected format or
  content? Are there validation or correction points between agent stages?
- Does the design account for variance in LLM output quality across runs?
- If one agent in a parallel pipeline produces a low-quality result, does the downstream
  consumer have enough signal from other sources to compensate?
- Are failure modes identified in the Tradeoffs and Risks section? Does the design
  propose containment mechanisms?
- Does partial failure of the system produce partial results, or does any single agent
  failure cascade to total failure?
- What assumptions about LLM behavior does the design depend on, and what would need to
  change if those assumptions are violated?
- Does the design express instructions in positive, actionable terms rather than
  prohibitions? Negative framing ("do not do X") is a known LLM reliability risk --
  models follow positive instructions ("do Y instead") more consistently.

**Scale:**
- Strong: Failure modes are identified and specific to LLM-based systems; containment
  prevents cascading failures; partial failure produces partial results; LLM behavior
  assumptions are explicit
- Partial: Some failure awareness but incomplete containment; LLM-specific failure modes
  partially addressed
- Weak: Single points of failure; cascading failures likely; no containment for off-spec
  output; LLM behavior assumptions are implicit
