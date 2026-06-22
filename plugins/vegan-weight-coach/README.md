# vegan-weight-coach

A longitudinal personal vegan nutrition + weight-loss coaching plugin — one user, over months.

`skills/vegan-weight-coach/SKILL.md` runs an SDT/MI behavior-change relationship; per-user state lives in a
file-based **memory store** the agent reads/writes with native tools (read/write/edit/bash). No MCP,
and Claude.ai's built-in memory is not used. The model already knows the behavior-change canon, so the
skill *invokes* it rather than re-teaching it; the files hold only what's specific to this user, what's
2026-design, or what must stay exact.

See `SETUP.md`. Memory layout: `skills/vegan-weight-coach/seed/memory/`.
