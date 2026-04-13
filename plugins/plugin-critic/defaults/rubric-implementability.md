# Rubric: Implementability

One quality dimension for the Implementability evaluator. This criterion traces
end-to-end flow and measures the design-to-implementation gap. It uses a different
analytical mode than the other criteria -- tracing execution paths rather than
assessing structural properties -- and does not pair naturally with them.

---

## 5. Implementability

**Definition:** The degree to which the design can be correctly understood and
faithfully translated into working prompts, orchestration code, and agent
configurations by the intended implementer.

**Evaluation questions:**
- Are all plugin system features used by the design correctly specified — frontmatter
  fields, environment variables, event types, capability constraints? (Consult the plugin
  system reference to verify.)
- Can you trace a user request through the system from input to final output,
  identifying which agent handles each stage?
- Are there implicit dependencies or emergent behaviors that arise from agent
  interaction but aren't described in any individual agent's spec?
- Does the design use consistent, unambiguous terminology throughout? Could prompts
  derived from this spec be unambiguous to an LLM?
- How large is the gap between reading the design and knowing how to write the actual
  prompts and orchestration code?

**Scale:**
- Strong: Control flow is traceable end-to-end; no hidden behaviors; terminology is
  consistent; the gap from design to implementation is small; plugin system features
  are correctly specified; assumptions about model behavior are explicit
- Partial: Mostly clear with some ambiguity, implicit assumptions, or inconsistent
  terminology
- Weak: Hard to trace; emergent behaviors; inconsistent terminology; large
  implementation gap; plugin system features misspecified or missing; unstated
  assumptions about model behavior
