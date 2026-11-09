# App Store Atlas — a fresh map of 1.6M iOS apps

A complete, **November 2026** snapshot of the public Apple App Store — **1,613,165 apps with full descriptions** — plus a semantic map and a **browser-based opportunity finder** that lets anyone hunt for under-served niches, with no server.

The most-used open App Store dataset (gauthamp10, 2021) is four years old and predates the entire AI-app wave. This one is newer, comes with the analysis, and ships a live tool on top of it.

**[→ Open the live app (map + finder)](https://emin-alkan.github.io/appstore-2026/)** · Dataset: *(Kaggle / HuggingFace link — coming)*

---

## What's inside

| | |
|---|---|
| **Apps** | 1,613,165 (US storefront, publicly listed) |
| **Collected** | 9 November 2026 |
| **Fields** | name, full description, category, rating, rating count, price, release / update dates, developer, size, languages, store URL |
| **Format** | JSONL (raw) · per-category Parquet (the finder) |
| **Coverage** | ~1.85M app IDs discovered via Apple's sitemap; 87% returned by the US lookup |

## The live app

Two tabs, both 100% client-side (no backend):

- **Map** — every app embedded and placed in 2D; 50 clusters coloured by how *alive* each region is (how many apps actually get used). Hover for app names; yellow pins flag sparse candidate regions.
- **Finder** — pick a category, then filter by keyword, reviews, rating, price and language to surface sub-niches with **demand but weak competition**. It runs DuckDB **in your browser** (DuckDB-WASM) over small per-category Parquet files, so it works on mobile and loads only the category you open. English UI with a Turkish toggle.

## Key findings

- **Half the store is a graveyard.** 53.6% of all apps have *zero* ratings. Only **7.2%** ever cross 100 ratings — the real "someone uses this" line.
- **There is no empty niche.** Embed all 1.6M descriptions and reduce to 2D, and there's almost no region that is surrounded yet truly empty. "Find the gap" works on 146k Steam games; at 1.6M apps every corner is filled.
- **The store grew and got younger.** 80.8% of apps were updated in 2024 or later, and Sensor Tower reported ~560k new apps in H1 2026 alone. Against the 2021 snapshot the growth skews to *tools over games* — Health & Fitness, Utilities, Productivity and Finance all grew sharply while Games barely moved. (Exact deltas mix two independently-scraped datasets, so read them as directional.)
- **The AI wave is concentrated.** Share of apps whose description mentions AI: Notes/Books cluster **40%**, Voice/Speech **38%**, Recipes **31%**, Photo/Image **29%** — but Food & Drink and Shopping barely **3%**.
- **The deadest clusters are white-label single-business apps** — one-restaurant ordering (71% dead), event/conference apps (70%), staff-management apps (73%). A whole mode to avoid.
- **Healthiest by real usage:** game clusters (18–21% traction) and banking (20%) — but banking is owned by actual banks.

## How it was built (reproducible)

```
scraper/scraper.py      sitemap crawl → ~1.85M app IDs, then iTunes Lookup (200/req, polite backoff)
pipeline/map_pipeline.py  multilingual MiniLM embeddings → PCA-50 → UMAP-2D → KMeans-50
pipeline/analyze.py       density grid → sparse-region detection
finder/                   Streamlit (desktop) + the per-category Parquet builder for the web finder
```

Full scrape runs in ~10 h from a single machine; embedding + mapping ~22 min on an RTX 3060.

## Data in this repo

- `data/` — the small analysis outputs: category stats, 50-cluster summary, sparse regions, a 40k-point sample.
- `docs/data/cat/` — 26 per-category Parquet files (~85 MB total) that power the web finder.
- The full raw dataset (~2.9 GB) is **not** in the repo; it's hosted on **[Kaggle / HuggingFace]** *(link coming)* under CC BY 4.0.

## Scope & limitations

- **Public, US-storefront apps only.** Unlisted, enterprise and non-US-only apps aren't included — by design, they're not in Apple's sitemap.
- Prices are up-front only; subscriptions and in-app purchases aren't in this field.
- `0 ratings` means *no ratings yet*, not a bad app — excluded from median-rating stats.
- The finder's keyword search covers the app name + first 100 characters of the description.
- UMAP doesn't preserve density exactly, so "sparse" regions are hypotheses, not proofs.
- Collected from Apple's public endpoints for research. Respect Apple's terms; don't use it to clone apps.

## License

Code: MIT. Dataset: CC BY 4.0. Not affiliated with Apple.

---

Built by **[Emin Alkan](https://github.com/emin-alkan)** · If this is useful, a ⭐ helps.
