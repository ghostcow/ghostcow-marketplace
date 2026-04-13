# Rubric: Coverage + Economy

Two quality dimensions for the Coverage + Economy evaluator. Both examine "is the
right stuff here?" from complementary angles. Coverage asks what's missing; Economy
asks what's superfluous. Keeping these two criteria together preserves their shared
analytical context while staying at or below the 2-criteria isolation threshold.

---

## 1. Requirement Coverage

**Definition:** The degree to which the design addresses all stated requirements
completely and correctly, without introducing solutions for unstated problems.

**Evaluation questions:**
- Does the design leverage the appropriate plugin system features for its goals, or does
  it build custom solutions for problems the platform already solves? (Consult the plugin
  system reference for the full inventory of available features.)
- Does every stated goal map to a specific agent, skill, or orchestration decision?
- Are there goals that the design acknowledges but delegates to the base model's
  reasoning rather than addressing with plugin components (agents, skills, hooks, or
  tool configuration)?
- Does the design address boundary conditions mentioned in the problem context?
- Does the design introduce components, agents, or interaction patterns that serve no
  stated requirement?

**Scale:**
- Strong: All requirements addressed with specific, traceable design elements; no
  solutions for unstated problems
- Partial: Most requirements addressed, but some goals are delegated without
  justification or boundary conditions are overlooked
- Weak: Significant requirements unaddressed, misinterpreted, or obscured by solutions
  to unstated problems

---

## 2. Design Economy

**Definition:** The degree to which the design achieves its goals with the minimum
necessary complexity, where every agent, interaction, and information channel serves a
clear, non-redundant purpose.

**Evaluation questions:**
- Could any two agents be merged without losing a genuinely distinct capability?
- Does the orchestration pattern introduce coordination overhead that simpler
  information flow would avoid?
- Is each piece of context/information passed between agents necessary for the
  receiving agent's task?
- Are simpler alternatives considered in the Key Decisions section? Where complexity is
  added, is it explicitly justified?
- Does the design avoid accidental complexity -- complexity arising from the solution
  approach rather than required by the problem?

**Scale:**
- Strong: Every agent and interaction traces to a requirement; no redundancy; complexity
  is essential and explicitly justified
- Partial: Some unjustified agents, interactions, or coordination overhead, but the
  design is mostly lean
- Weak: Significant accidental complexity; agents that could be merged; information
  channels without clear purpose
