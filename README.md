# App Store 2026 — a fresh map of 1.6M iOS apps

A complete, **November 2026** snapshot of the public Apple App Store — **1,613,165 apps with full descriptions** — plus a semantic map that places every app next to its neighbours and asks a simple question: **where are the empty niches?**

The most-used open App Store dataset (gauthamp10, 2021) is four years old and predates the entire AI-app wave. This one is newer, larger on descriptions, and comes with the analysis, not just the rows.

**[→ Open the live interactive map](https://emin-alkan.github.io/appstore-2026/)** · Dataset: *(Kaggle / HuggingFace link — see below)*

![map preview](docs/map-preview.png)

---

## What's inside

| | |
|---|---|
| **Apps** | 1,613,165 (US storefront, publicly listed) |
| **Collected** | 9 November 2026 |
| **Fields** | name, full description, category, rating, rating count, price, release / update dates, developer, size, languages, store URL |
| **Format** | JSONL (raw) + Parquet (analysis) |
| **Coverage** | ~1.85M app IDs discovered via Apple's sitemap; 87% returned by the US lookup |

## Key findings

- **Half the store is a graveyard.** 53.6% of all apps have *zero* ratings. Only **7.2%** ever cross 100 ratings — the real "someone uses this" line.
- **There is no empty niche.** Embedding all 1.6M descriptions and reducing to 2D, there's almost no region that is surrounded yet truly empty. At 1.6M apps, every semantic corner is filled. "Find the gap" works on 146k Steam games; it mostly doesn't here.
- **The growth is in tools, not games.** vs the 2021 dataset: Health & Fitness **+97%**, Utilities **+54%**, Productivity **+56%**, Finance **+50%** — while **Games stayed flat (−2%)**, despite being the largest category.
- **The AI wave is concentrated.** Share of apps whose description mentions AI: Notes/Books cluster **40%**, Voice/Speech **38%**, Recipes **31%**, Photo/Image **29%** — but Food & Drink and Shopping barely **3%**.
- **The deadest clusters are white-label single-business apps** — one-restaurant ordering (71% dead), event/conference apps (70%), staff-management apps (73%). A whole mode to avoid.
- **Healthiest by real usage:** game clusters (18–21% traction) and banking (20%) — but banking is owned by actual banks.

## The interactive map

Every point is an app; nearby points are semantically similar. Colour = how alive the region is (red = graveyard, green = actually used). Yellow pins mark sparse edge regions worth a closer look. **[Open it →](https://emin-alkan.github.io/appstore-2026/)**

## How it was built (reproducible)

```
1. Discover IDs   sitemap crawl  →  1.85M unique app IDs      (scraper/ids.py)
2. Fetch details  iTunes Lookup API, 200/req, polite backoff  (scraper/fetch.py)
3. Embed          multilingual MiniLM sentence embeddings     (pipeline/embed.py)
4. Reduce + cluster  PCA-50 → UMAP-2D → KMeans-50             (pipeline/map.py)
5. Analyse        density grid → sparse-region detection      (pipeline/analyze.py)
```

Full scrape runs in ~10h from a single machine; embedding + mapping ~22 min on an RTX 3060. See [`REPRODUCE.md`](REPRODUCE.md).

## Dataset download

The raw dataset (~2.9 GB) is hosted on **[Kaggle / HuggingFace]** *(link coming)* under CC BY 4.0 — attribution to this repo. The small analysis outputs (`stats_2026.json`, `clusters.json`, `empty_regions.json`, a 40k-point sample) live in [`data/`](data/).

## Scope & limitations

- **Public, US-storefront apps only.** Unlisted, enterprise, and non-US-only apps are not included — by design, they're not in Apple's sitemap.
- Prices are up-front only; subscriptions and in-app purchases aren't in this field.
- `0 ratings` means *no ratings yet*, not a bad app — excluded from median-rating stats.
- UMAP does not preserve density exactly, so "sparse" regions are hypotheses, not proofs.
- This data is collected from Apple's public endpoints for research. Respect Apple's terms; don't use it to clone apps.

## License

Code: MIT. Dataset: CC BY 4.0. Not affiliated with Apple.

---

Built by **[Emin Alkan](https://github.com/emin-alkan)** · [X / Twitter](https://x.com/) · If this is useful, a ⭐ helps.
