# Calorie and food sources

Look up real values rather than estimating from memory — that is what keeps numbers consistent across sessions and people. There is no fixed query recipe that works for every food; what carries over is understanding what each source holds, so you can pick the right one and read the results critically. Present a result with a one-line basis (which food, which source).

## The two sources

**USDA FoodData Central** — `https://api.nal.usda.gov/fdc/v1`. Generic foods and ingredients. Append `&api_key=…`; read the user's key from their profile, or use `DEMO_KEY` when none is set (rate-limited ~30/hour). Search with `/foods/search?query=<food>`, optionally filtered by `dataType`.

**Open Food Facts** — `https://search.openfoodfacts.org`. Specific branded or Israeli packaged products, by name or barcode. Reach for it when the user names a product or has the package in hand.

## Knowing the USDA datasets (the part that matters)

`dataType` selects which collection you search, and each holds something different — choosing the right one is most of the skill:

- **Foundation** — lab-analyzed whole/single foods ("Oats, whole grain, rolled"). Cleanest names and best quality for a plain ingredient, but a small set. Energy here is often reported as Atwater factors rather than the classic field (see below).
- **SR Legacy** — the broad classic reference (~7,800 foods), covering generic foods both dry and cooked ("Cereals, oats … dry" vs "… cooked with water").
- **Survey (FNDDS)** — foods *as eaten* from diet surveys, including cooked and mixed dishes ("Oatmeal, NFS", "Beans and rice"). The right pick for a prepared or cooked item.
- **Branded** — manufacturer label data; overlaps with Open Food Facts.

So a plain ingredient leans Foundation or SR Legacy, a cooked or mixed dish leans FNDDS, and a specific product goes to Open Food Facts.

## Reading results well

- **Fix the form first — it dominates.** Dry versus cooked can differ about fivefold (oats ≈ 380 kcal/100g dry vs ≈ 75 cooked). Match the entry to the form and portion the user means; menu items are usually cooked.
- **Judge the hit, don't trust the rank.** Search ranks by text match, so derivatives ("oat oil", "oat bran", "oatmeal cookies") and branded items can sit above the food you want. Read the descriptions and take the one that *is* the food, in the right form.
- **Read energy from whichever field carries it.** It may be nutrient `1008` ("Energy", kcal) or, especially in Foundation, `957`/`958` ("Energy, Atwater General/Specific Factors") — Atwater *General* is the standard kcal figure. A missing `1008` does not mean the food has no calories.
- **Fetch detail when a search row is thin:** `GET /food/{fdcId}?format=full` returns the full nutrient set.
- **Name your fallback.** If nothing clean matches (e.g. seitan isn't in USDA's generic data), use the menu's ballpark unit and say so, rather than passing off a wrong hit as fact.

## Open Food Facts query shape

`GET /search?q=<terms> countries_tags:"en:israel"&langs=he,en&fields=product_name,brands,code,nutriments&page_size=5`. The `q` field is Lucene, so combine free text with filters like `labels_tags:"en:vegan"` or a kcal range `nutriments.energy-kcal_100g:[* TO 150]`. Exact product by barcode: `https://world.openfoodfacts.org/api/v2/product/{barcode}`.

## Worked example — "calories in oats"

1. **Form?** The menu says *cooked* oats, so you want an as-eaten figure.
2. **Source?** Cooked → FNDDS (`oatmeal`) gives ~75/100g, or SR Legacy "Cereals, oats … cooked with water" ~71/100g. (Dry would be Foundation/SR Legacy, ~380/100g.)
3. **Read the list,** skip oat oil / bran / cookies, take the oats entry, read its energy (`1008`, or Atwater `957`/`958`), and scale to the portion.
