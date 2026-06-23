# Setup

On first run the coach creates the memory store at
`${CLAUDE_PROJECT_DIR}/.claude/vegan-weight-coach/memory/` from the bundled seed, then gathers the
authoritative facts during onboarding by asking the user for:
- their name, and consent + preferred words for talking about weight;
- their strict-vegan rules and any allergies;
- current medications/supplements and any diet-relevant notes.

The coach writes these into the store and treats them as ground truth, changing them only when the user
says they have changed. To update anything in memory later, the user simply tells the coach what to
change.

Operator options:
- Set the local crisis line in `references/scripts.md` (e.g. 988 in the US).
- Optionally provide a USDA FoodData Central API key in the environment for calorie grounding.

Each person uses their own project/account, so their store stays isolated; keep
`.claude/vegan-weight-coach/` local and untracked.
