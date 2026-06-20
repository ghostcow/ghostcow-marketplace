# vegan-dietician

A Claude Code / Claude.ai plugin that acts as a personal **vegan nutrition coach**. It builds and refines a weekly menu around an exchange-portion system, answers calorie and food questions from authoritative databases, and saves and reuses your recipes — all fully plant-based.

## What it does

- **Builds your profile** — gathers stats, activity, goal, eating window, allergies, preferences, and supplements, then sets a daily calorie target (Mifflin-St Jeor).
- **Builds menus** from interchangeable units (protein / legume / grain / vegetable / fat) fitted to your lifestyle and eating window.
- **Refines collaboratively** — walks the menu part by part until you've approved every part.
- **Swaps** any item and rebalances the day to your target.
- **Answers calorie & food questions** by querying USDA FoodData Central and Open Food Facts rather than estimating, so numbers stay consistent.
- **Suggests, saves, and reuses recipes** that fit your menu and tastes.

It keeps your profile, current menu, and recipes in the project's memory, so it remembers you across sessions.

## Structure

```
vegan-dietician/
├── .claude-plugin/plugin.json
└── skills/vegan-dietician/
    ├── SKILL.md
    └── references/
        ├── calorie-sources.md     # USDA + Open Food Facts query playbook
        ├── menu-building.md       # the menu method (units, building, swapping)
        └── microwave-cookbook.md  # quick vegan recipes
```

## Calorie lookups

The skill queries two free sources: **USDA FoodData Central** (a free API key is required for generic foods) and **Open Food Facts** (no key, best for branded/Israeli products by name or barcode). See `skills/vegan-dietician/references/calorie-sources.md`.

## Note

This plugin is a wellness aid, not a substitute for a licensed dietitian or medical advice.
