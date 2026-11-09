"""apps_2026.jsonl → apps_lite.parquet (tarayıcı / DuckDB-WASM için küçük dosya)."""
import os
import time

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "apps_2026.jsonl")
DST = os.path.join(HERE, "apps_lite.parquet")

COLUMNS = {
    "trackId": "BIGINT", "trackName": "VARCHAR", "description": "VARCHAR",
    "primaryGenreName": "VARCHAR", "userRatingCount": "BIGINT", "averageUserRating": "DOUBLE",
    "price": "DOUBLE", "currentVersionReleaseDate": "VARCHAR", "languageCodesISO2A": "VARCHAR[]",
}

t0 = time.time()
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
con.execute("SET threads=6")
con.execute(f"SET temp_directory='{os.path.join(HERE, '.duckdb_tmp')}'")
cols = "{" + ", ".join(f"'{k}': '{v}'" for k, v in COLUMNS.items()) + "}"
con.execute(f"""
    COPY (
      SELECT
        trackId                                                        AS id,
        trackName                                                      AS name,
        primaryGenreName                                               AS genre,
        coalesce(userRatingCount, 0)::INTEGER                          AS reviews,
        coalesce(averageUserRating, 0)::FLOAT                          AS rating,
        coalesce(price, 0)::FLOAT                                      AS price,
        TRY_CAST(substr(currentVersionReleaseDate, 1, 4) AS SMALLINT)  AS year,
        (list_contains(coalesce(languageCodesISO2A, []), 'TR'))::TINYINT AS tr,
        lower(coalesce(trackName, '') || ' ' ||
              coalesce(left(regexp_replace(description, '\\s+', ' ', 'g'), 140), '')) AS s
      FROM read_json_auto(?, format='newline_delimited', columns={cols})
      ORDER BY genre, reviews DESC          -- kategori filtresinde row-group atlamayı mümkün kılar
    ) TO '{DST}.tmp' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 19, ROW_GROUP_SIZE 122880)
""", [SRC])
os.replace(DST + ".tmp", DST)
el = time.time() - t0

print(f"süre {el:.1f} sn")
print(con.execute(f"DESCRIBE SELECT * FROM '{DST}'").df()[["column_name", "column_type"]].to_string(index=False))
n, = con.execute(f"SELECT count(*) FROM '{DST}'").fetchone()
print(f"\nsatır: {n:,}   boyut: {os.path.getsize(DST)/1e6:.1f} MB ({os.path.getsize(DST)/2**20:.1f} MiB)")
print(con.execute(f"""
    SELECT path_in_schema AS kolon, round(sum(total_compressed_size)/1e6, 1) AS MB,
           count(*) AS row_groups
    FROM parquet_metadata('{DST}') GROUP BY 1 ORDER BY 2 DESC""").df().to_string(index=False))
print(con.execute(f"SELECT * FROM '{DST}' WHERE reviews > 0 USING SAMPLE 3 ROWS").df().to_string())
