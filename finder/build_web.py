"""apps_2026.jsonl → web/data/cat/<genre>.parquet + web/index.json (DuckDB-WASM / GitHub Pages)."""
import json
import os
import re
import time

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "apps_2026.jsonl")
WEB = os.path.join(HERE, "web")
CAT = os.path.join(WEB, "data", "cat")

COLUMNS = {
    "trackId": "BIGINT", "trackName": "VARCHAR", "description": "VARCHAR",
    "primaryGenreName": "VARCHAR", "userRatingCount": "BIGINT", "averageUserRating": "DOUBLE",
    "price": "DOUBLE", "currentVersionReleaseDate": "VARCHAR", "languageCodesISO2A": "VARCHAR[]",
}


def slug(genre):
    return re.sub(r"[^A-Za-z0-9]+", "_", genre).strip("_") or "Unknown"


t0 = time.time()
os.makedirs(CAT, exist_ok=True)
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
con.execute("SET threads=6")
con.execute(f"SET temp_directory='{os.path.join(HERE, '.duckdb_tmp')}'")
cols = "{" + ", ".join(f"'{k}': '{v}'" for k, v in COLUMNS.items()) + "}"
con.execute(f"""
    CREATE TEMP TABLE a AS
    SELECT
      coalesce(primaryGenreName, 'Unknown')                          AS genre,
      trackId                                                        AS id,
      trackName                                                      AS name,
      coalesce(userRatingCount, 0)::INTEGER                          AS reviews,
      coalesce(averageUserRating, 0)::FLOAT                          AS rating,
      coalesce(price, 0)::FLOAT                                      AS price,
      TRY_CAST(substr(currentVersionReleaseDate, 1, 4) AS SMALLINT)  AS year,
      (list_contains(coalesce(languageCodesISO2A, []), 'TR'))::TINYINT AS tr,
      lower(coalesce(trackName, '') || ' ' ||
            coalesce(left(regexp_replace(description, '\\s+', ' ', 'g'), 100), '')) AS s
    FROM read_json_auto(?, format='newline_delimited', columns={cols})
""", [SRC])
log_load = time.time() - t0

genres = [g for (g,) in con.execute("SELECT DISTINCT genre FROM a ORDER BY genre").fetchall()]
slugs = {g: slug(g) for g in genres}
assert len(set(slugs.values())) == len(slugs), f"dosya adı çakışması: {slugs}"

stats = con.execute("""
    SELECT genre,
           count(*)                                                  AS count,
           round(100 * avg((reviews >= 100)::INT), 2)                AS traction,
           round(100 * avg((reviews = 0)::INT), 2)                   AS graveyard,
           round(100 * avg(tr), 2)                                   AS tr_pct,
           round(median(rating) FILTER (WHERE reviews > 0), 3)       AS median_rating
    FROM a GROUP BY genre ORDER BY count DESC
""").df()

categories = []
for r in stats.itertuples(index=False):
    fname = f"{slugs[r.genre]}.parquet"
    path = os.path.join(CAT, fname)
    con.execute(f"""
        COPY (SELECT id, name, reviews, rating, price, year, tr, s
              FROM a WHERE genre = ? ORDER BY reviews DESC, id)
        TO '{path}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 19, ROW_GROUP_SIZE 122880)
    """, [r.genre])
    categories.append({
        "genre": r.genre, "file": f"data/cat/{fname}", "count": int(r.count),
        "traction": float(r.traction), "graveyard": float(r.graveyard), "tr_pct": float(r.tr_pct),
        "median_rating": None if r.median_rating != r.median_rating else round(float(r.median_rating), 3),
        "bytes": os.path.getsize(path),
    })

total = int(stats["count"].sum())
index = {"total": total, "category_count": len(categories),
         "generated_at": time.strftime("%Y-%m-%d"), "source": "App Store (US) lookup, Kasım 2026",
         "categories": categories}
with open(os.path.join(WEB, "index.json"), "w", encoding="utf-8") as f:
    json.dump(index, f, ensure_ascii=False, indent=1)

# doğrulama: dosyalardaki satır toplamı = toplam, sıralama azalan
n_files = con.execute(f"SELECT count(*) FROM '{CAT}/*.parquet'").fetchone()[0]
assert n_files == total, (n_files, total)
for c in categories:
    bad = con.execute(f"""SELECT count(*) FROM (SELECT reviews, lag(reviews) OVER () p
                          FROM '{os.path.join(WEB, c['file'])}') WHERE reviews > p""").fetchone()[0]
    assert bad == 0, c["file"]

print(f"yükleme {log_load:.1f} sn, toplam {time.time()-t0:.1f} sn | {len(categories)} kategori, {total:,} uygulama "
      f"(dosyalardaki satır toplamı {n_files:,})")
size = sum(c["bytes"] for c in categories)
print(f"data/cat toplam: {size/1e6:.1f} MB ({size/2**20:.1f} MiB)\n")
for c in sorted(categories, key=lambda c: -c["bytes"]):
    print(f"{c['file']:<42}{c['count']:>9,}  {c['bytes']/1e6:6.2f} MB  traction %{c['traction']:5.2f}  "
          f"mezarlık %{c['graveyard']:5.2f}  TR %{c['tr_pct']:5.2f}  ★{c['median_rating']}")
