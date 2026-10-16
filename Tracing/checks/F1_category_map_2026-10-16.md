# F1: category map loaded, daily check after loading (16 Oct 2026)

Kala's feedback F1 (ENG-03, ENG-29, X-20). Settings config_version 5: 78 category-map entries from the app's LEGACY_LABEL_MAP (null entries left out), its category tree's interest tags (scripts/seed-catalog.js), and the app team's answers of 16 Oct (Q6). Dev platform database, read-only.

| | Before (14 Oct) | After (16 Oct) |
|---|---|---|
| Unmapped labels (daily check) | 42 | **7** |
| Products in one of the 23 | 0 of 2,011 | 4 of 2,011 (every product not in the catimp test stores or without a category) |
| Posts with a category in the 23 | 8 of 8 | 8 of 8 |
| Users with declared interests in the 23 | | 13 of 16 |

The daily category check (`python -m reco.jobs category_check`), 16 Oct:

```
"job": "category_check", "unmapped": 7, "labels": ["Menswear catimp1790216912437", "Menswear catimp1790217539835", "Nature", "Fishing", "(no category id)", "Shopping", "Fishing & Marine"]
```

Still unmapped, and why:

| Label | Items | Why |
|---|---|---|
| Menswear catimp1790216912437 / …7539835 | 1,005 / 1,000 products | Test data from the app's catalogue-import test (app team, Q6): not mapped; to be deleted on dev |
| (no category id) | 2 products | No category at all |
| Nature, Fishing, Shopping | 3, 2, 1 user interests | The app's own map gives no interest (LEGACY_LABEL_MAP null); mock-seed labels |
| Fishing & Marine | 1 business | No rule in the app; for Kala |

Also outside the 23 in the app's admin list (left unmapped): Watches, Appliances, Tools & Home Improvement.
