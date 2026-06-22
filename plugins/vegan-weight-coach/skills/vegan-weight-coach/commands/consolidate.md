---
description: Run the memory consolidation ("dreaming") pass over the store.
---
Consolidate the memory store (`${CLAUDE_PROJECT_DIR}/.claude/vegan-weight-coach/memory/`) using your file tools (read/edit/bash):

- **Weekly (light):** for each topic with new ledger entries, (re)generate `trajectory/<topic>.md` as a
  short "how it changed" narrative from recent ledger lines; refresh `CURRENT.md`; recompute the
  freshness list in `INDEX.md` (flag any state field whose `last_confirmed` is >~30 days or sits
  downstream of a life event).
- **Monthly (deep):** move ledger lines older than the current period into `archive/YYYY-MM/`; rebuild
  full trajectories; merge duplicate state lines; reconcile contradictions; prune only clearly-dead
  beliefs (enough contrary evidence). Re-read `anchor.md` and check for drift.

Keep trajectories compact. Never delete ledger history — archive it.
