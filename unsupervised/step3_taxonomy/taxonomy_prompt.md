# Role
You are a customer support operations analyst who designs call-driver taxonomies for Lenovo PC support (ThinkPad, ThinkCentre, IdeaPad, IdeaCentre, Legion, Yoga, Chromebook, monitors, docks and accessories; US warranty and technical support lines).

# Background
We extracted a free-text `category` (1–3 words) for every customer request in 1,000 support calls. The model wrote the categories freely, so the same area appears under different names (e.g. "screen" / "display", "fan" / "cooling" / "overheating"), some are too broad ("software"), and some are mistakes. Each category names what the call is about (the product or service area), not the root cause.

# Task
Recommend a call-driver category list for Lenovo PC service, and map every observed category onto it.

1. Propose top-level categories (aim for 12–20) that together cover all the observed categories. Use your own knowledge of Lenovo PC support and PC service operations to:
   - merge synonyms and near-duplicates into one category
   - split categories that are too broad to act on, if the examples show distinct areas inside them
   - name categories the way a support operations team would report on them
   - add a category that is standard in PC support but missing or rare in this sample only if it is likely to matter at scale; mark it `"observed": false`
2. Keep categories at the level of product/service area (e.g. "Display", "Power & Charging", "Warranty & Coverage"), not root cause and not specific symptoms.
3. Keep "what it is about" separate from "what the customer wants". We track the customer's ask separately (fix a problem, check warranty, buy warranty, case status, return/replace, setup/how-to, purchase, account admin), so do not create categories that only restate an ask unless no product area applies (e.g. a call purely about a repair case or order).
4. Give each category a one-sentence definition precise enough that two analysts would assign the same calls to it, and 2–5 subcategories for drill-down.
5. Map every observed category string to exactly one recommended category, using the counts and example requests to decide. Map mistakes and unclear strings to the best-fitting category, or to "Other / Unclear" if nothing fits.

# Input
Observed categories, one per line: `<category> | <request count> | <example requests separated by " ;; ">`

{table}

# Output
Valid JSON only, no commentary or markdown fences:
{
  "categories": [
    {
      "name": "<category name>",
      "definition": "<one sentence>",
      "subcategories": ["<subcategory>", "..."],
      "observed": true,
      "rationale": "<why this category exists or how it was merged/split, one sentence>"
    }
  ],
  "mapping": {"<observed category string exactly as given>": "<recommended category name>"},
  "notes": ["<short observations about the data or the taxonomy, e.g. categories that are too broad, ambiguous boundaries>"]
}
