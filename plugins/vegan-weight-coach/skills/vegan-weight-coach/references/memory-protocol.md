# Memory protocol — which files to read/edit, and when

The per-user **store** (`${CLAUDE_PROJECT_DIR}/.claude/vegan-weight-coach/memory/`, created on first run by
copying the plugin seed — see SKILL.md) is the only source of truth about this user. Edit it with your
native file tools (read/write/edit/bash); all paths below are relative to the store. Three kinds of
files, kept separate so change-over-time is never lost:

- **Current state** (`CURRENT.md`, `state/*.md`) — the single "now." Edit in place, but **supersede**:
  before changing a value, append the old one to the matching ledger, then write the new value with
  `last_confirmed` + source. Never silently overwrite an authoritative/safety fact — surface a
  discrepancy instead.
- **Point-in-time** (`ledger/*.jsonl`) — append-only dated events, one JSON line each; never edit or
  delete. Schemas in the store's `ledger/README.md`.
- **Trajectory** (`trajectory/*.md`) — "how it changed"; regenerated during consolidation, not per turn.

Read-only to you (the user owns them): `profile/constraints.md`, `reference/*`. Read them, never edit.

**Read — at session start:** `INDEX.md` + `CURRENT.md` + `anchor.md` (always). Then only what the
moment needs: a `state/*` file if INDEX's freshness list flags it or the topic comes up; a
`trajectory/*` for "how am I doing"; a `ledger/*` for a specific past detail; `profile/`/`reference/`
for constraints/meds. Don't load everything.

**Write — per turn (only on a real change):** append the event to the right ledger; update a `state/*`
field with the supersede rule. If nothing changed, write nothing. Mark inferred values as `inferred`
and confirm high-stakes ones before treating them as fact.

**Write — at session end:** append one short entry to `ledger/sessions.jsonl` (stage, what was agreed,
what landed, next checkpoint); refresh `CURRENT.md`; bump `last_confirmed` in INDEX's freshness list
for anything re-confirmed.

**Consolidate — on cadence** (`commands/consolidate.md`): weekly light, monthly deep. Regenerate
trajectories, merge/prune, roll old ledger lines to `archive/`. History is archived, never deleted.

Formats — state field: `field: value · last_confirmed: YYYY-MM-DD · source: … · conf: high|med|low ·
stated|inferred`. Ledger line: `{"ts":"YYYY-MM-DD","type":"…", …}`.
