# Setup (one-time, per user)

1. **Memory store — auto-created.** On first run the coach copies the bundled seed
   (`${CLAUDE_PLUGIN_ROOT}/skills/vegan-weight-coach/seed/memory/`) into the live store at
   `${CLAUDE_PROJECT_DIR}/.claude/vegan-weight-coach/memory/`. No manual copy needed. Each person uses their own
   project/account, so their store is isolated; keep `.claude/vegan-weight-coach/` local/untracked.
2. **Fill the user-owned authoritative files** (in the live store, once created):
   - `profile/identity.md` — name, weight-talk consent + preferred words, dieter subtype.
   - `profile/constraints.md` — their strict-vegan rules + allergies.
   - `reference/meds_supplements.md` — medications/supplements + any diet-interaction notes.
   These are READ-ONLY to the coach; the user edits them.
3. **Set the local crisis resource** in `references/scripts.md` (e.g. 988 in the US).
4. *(Optional)* put a USDA FoodData Central API key in the environment for calorie grounding.

The agent maintains everything else. The user can edit any memory file directly, anytime.
