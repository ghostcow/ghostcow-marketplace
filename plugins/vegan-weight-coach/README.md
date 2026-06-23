# vegan-weight-coach

A long-term coaching plugin for someone who already eats strictly plant-based, focused on sustainable,
non-judgmental weight-loss and eating-well support over weeks and months.

`skills/vegan-weight-coach/SKILL.md` runs the coaching relationship: a Self-Determination-Theory /
Motivational-Interviewing behavior-change arc with per-turn state reading, calibrated support, and a
Tier-1 safety layer. Each user's evolving picture lives in a file-based **memory store** that the coach
maintains as the conversation unfolds; built-in chat memory plays no role.

The store is created on first run from the bundled seed and lives at
`${CLAUDE_PROJECT_DIR}/.claude/vegan-weight-coach/memory/`; each person uses their own project/account,
so their data stays isolated. See `SETUP.md`. Seed layout: `skills/vegan-weight-coach/seed/memory/`.
