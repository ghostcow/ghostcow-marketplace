# Calorie and food sources

Look up real values from these databases instead of estimating from memory — that is what keeps answers accurate and consistent across sessions and across people. Query in English or Hebrew; the relevant item usually ranks first, so take the top sensible hit and ignore unrelated ones. Skip entries that have no energy value. Present the result with a one-line basis (which food, which source).

## Which source to use

- **Generic food or ingredient** (banana, tofu, lentils, tahini, cooked rice) → **USDA FoodData Central**.
- **A specific or Israeli packaged product** (a particular soy milk, a branded snack) → **Open Food Facts**.

## USDA FoodData Central

Base: `https://api.nal.usda.gov/fdc/v1` — append `&api_key=…` to every call. Read the user's USDA key from their profile/memory; if none is set, use `DEMO_KEY` (works with no setup, but rate-limited to ~30/hour).

- Ingredient: `/foods/search?query=<food>&dataType=Foundation,SR Legacy`
- Prepared or mixed dish: `/foods/search?query=<dish>&dataType=Survey (FNDDS)`
- Full detail by id: `/food/{fdcId}`
- Nutrient numbers: 208 energy (kcal), 203 protein, 204 fat, 205 carbohydrate.

## Open Food Facts (search-a-licious)

Base: `https://search.openfoodfacts.org`

- Search: `/search?q=<query>&langs=he,en&fields=product_name,brands,nutriments&page_size=5`
- The `q` field is Lucene — mix free text with filters:
  - `countries_tags:"en:israel"` — Israeli products
  - `labels_tags:"en:vegan"` — vegan-labelled products
  - `nutriments.energy-kcal_100g:[* TO 150]` — a calorie ceiling; sort with `sort_by=nutriments.energy-kcal_100g`
- Exact product by barcode: `https://world.openfoodfacts.org/api/v2/product/{barcode}?fields=product_name,brands,nutriments`
