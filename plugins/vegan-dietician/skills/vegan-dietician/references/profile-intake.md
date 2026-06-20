# Profile intake (first run)

Run this once — when there is no profile yet, or when the user asks to redo it. Gather the full set of details before building any menus. It is a finite list, so ask for all of it, and take the space it needs:

- **Body stats** — weight, height, age, and sex (these set the calorie estimate).
- **Activity level** — from sedentary to very active.
- **Goal** — their target weight or the rate of loss they want, which sets the daily deficit.
- **Eating pattern** — eating window or fasting, how many meals, and the rough daily schedule.
- **Allergies.**
- **Likes, dislikes, and constraints** — including anything like soy-free.
- **Supplements** they take.
- **USDA API key** *(optional)* — for calorie lookups. If they have one, save it; if not, lookups fall back to a shared demo key.

Then compute the daily calorie target (see `menu-building.md`), show the assembled profile and target back to the user, and adjust to their input. Save it to memory, pinning the calorie target and allergies so they hold across sessions.
