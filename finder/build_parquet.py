"""apps_2026.jsonl → apps.parquet (tek seferlik). app.py ilk açılışta otomatik çağırır."""
import os
import time

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "apps_2026.jsonl")
DST = os.path.join(HERE, "apps.parquet")

COLUMNS = {
    "trackName": "VARCHAR", "description": "VARCHAR", "primaryGenreName": "VARCHAR",
    "averageUserRating": "DOUBLE", "userRatingCount": "BIGINT", "price": "DOUBLE",
    "currentVersionReleaseDate": "VARCHAR", "trackViewUrl": "VARCHAR",
    "sellerName": "VARCHAR", "languageCodesISO2A": "VARCHAR[]",
}


def build(src=SRC, dst=DST):
    t0 = time.time()
    con = duckdb.connect()
    con.execute("SET memory_limit='3GB'")          # makinede 7 GB RAM var
    con.execute(f"SET temp_directory='{os.path.join(HERE, '.duckdb_tmp')}'")
    cols = "{" + ", ".join(f"'{k}': '{v}'" for k, v in COLUMNS.items()) + "}"
    tmp = dst + ".tmp"
    con.execute(f"""
        COPY (
          SELECT
            trackName,
            primaryGenreName,
            coalesce(averageUserRating, 0)             AS averageUserRating,
            coalesce(userRatingCount, 0)               AS userRatingCount,
            coalesce(price, 0)                         AS price,
            TRY_CAST(substr(currentVersionReleaseDate, 1, 4) AS INTEGER) AS updateYear,
            currentVersionReleaseDate,
            trackViewUrl,
            sellerName,
            coalesce(array_to_string(languageCodesISO2A, ','), '') AS languages,
            lower(coalesce(trackName, '') || ' ' || coalesce(description, '')) AS search_text
          FROM read_json_auto(?, format='newline_delimited', columns={cols})
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)
    """, [src])
    os.replace(tmp, dst)
    n = con.execute(f"SELECT count(*) FROM '{dst}'").fetchone()[0]
    return n, time.time() - t0


if __name__ == "__main__":
    n, el = build()
    print(f"{n} satır → {DST} ({os.path.getsize(DST)/1e9:.2f} GB) {el:.1f} sn")
