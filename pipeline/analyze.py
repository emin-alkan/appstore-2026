#!/usr/bin/env python3
"""apps_2026.jsonl → stats_2026.json (kategori bazlı özet). Dosyayı satır satır okur."""
import json
import os
import re
import statistics
import time
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # proje kökü
SRC = os.path.join(BASE, "apps_2026.jsonl")
DST = os.path.join(BASE, "stats_2026.json")

# Kelime sınırlı arama: düz "ai" alt dizesi "email", "said", "train" gibi kelimeleri de yakalar.
TERMS = {
    "ai": re.compile(r"\bai\b"),
    "gpt": re.compile(r"gpt"),              # chatgpt, gpt-4o vb. de sayılsın
    "chatbot": re.compile(r"\bchat ?bots?\b"),
    "artificial intelligence": re.compile(r"artificial intelligence"),
    "llm": re.compile(r"\bllms?\b"),
}


def new():
    return {"n": 0, "zero": 0, "used": 0, "paid": 0, "paid_sum": 0.0, "fresh": 0,
            "ai_any": 0, "ai_naive": 0, "terms": defaultdict(int), "ratings": []}


def pct(a, b):
    return round(100 * a / b, 2) if b else None


def finish(s):
    n = s["n"]
    return {
        "apps": n,
        "graveyard_pct": pct(s["zero"], n),
        "traction_pct": pct(s["used"], n),
        "paid_pct": pct(s["paid"], n),
        "avg_paid_price": round(s["paid_sum"] / s["paid"], 2) if s["paid"] else None,
        "median_rating": round(statistics.median(s["ratings"]), 3) if s["ratings"] else None,
        "rated_apps": len(s["ratings"]),
        "fresh_2024plus_pct": pct(s["fresh"], n),
        "ai_apps": s["ai_any"],
        "ai_pct": pct(s["ai_any"], n),
        "ai_terms": {t: s["terms"][t] for t in TERMS},
        "ai_naive_substring_apps": s["ai_naive"],
    }


def main():
    t0 = time.time()
    by = defaultdict(new)
    allg = new()
    bad = 0
    with open(SRC, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                a = json.loads(line)
            except ValueError:
                bad += 1
                continue
            for s in (by[a.get("primaryGenreName") or "(yok)"], allg):
                rc = a.get("userRatingCount") or 0
                price = a.get("price") or 0
                s["n"] += 1
                s["zero"] += rc == 0
                s["used"] += rc >= 100
                if price > 0:
                    s["paid"] += 1
                    s["paid_sum"] += price
                if rc > 0 and a.get("averageUserRating") is not None:
                    s["ratings"].append(a["averageUserRating"])
                d = a.get("currentVersionReleaseDate") or ""
                s["fresh"] += d[:4] >= "2024"
            desc = (a.get("description") or "").lower()
            hits = [t for t, rx in TERMS.items() if rx.search(desc)]
            naive = any(t in desc for t in TERMS)
            for s in (by[a.get("primaryGenreName") or "(yok)"], allg):
                for t in hits:
                    s["terms"][t] += 1
                s["ai_any"] += bool(hits)
                s["ai_naive"] += naive
            if i % 400000 == 0:
                print(f"{i} satır, {time.time()-t0:.0f} sn", flush=True)

    cats = {g: finish(s) for g, s in sorted(by.items(), key=lambda kv: -kv[1]["n"])}
    out = {
        "source": "apps_2026.jsonl",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "notes": {
            "graveyard_pct": "userRatingCount == 0 yüzdesi",
            "traction_pct": "userRatingCount >= 100 yüzdesi",
            "median_rating": "yalnızca userRatingCount > 0",
            "fresh_2024plus_pct": "currentVersionReleaseDate yılı >= 2024",
            "ai": "description küçük harf; ai/llm/chatbot kelime sınırlı, gpt ve 'artificial intelligence' alt dize. "
                  "ai_naive_substring_apps = düz alt dize araması (yanıltıcı, karşılaştırma için)",
            "price": "ABD mağazası uygulama fiyatı (USD); uygulama içi satın alma dahil değil",
        },
        "category_count": len(cats),
        "bad_lines": bad,
        "total": finish(allg),
        "categories": cats,
    }
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"\nBitti: {time.time()-t0:.0f} sn, {allg['n']} uygulama, {len(cats)} kategori, bozuk satır {bad}\n")
    hdr = f"{'Kategori':<20}{'Uygulama':>10}{'Mezarlık%':>10}{'≥100oy%':>9}{'Ücretli%':>9}{'Ort.$':>7}{'Medyan★':>8}{'2024+%':>8}{'AI%':>7}"
    print(hdr)
    print("-" * len(hdr))
    rows = list(cats.items())[:15] + [("TOPLAM", out["total"])]
    for g, c in rows:
        print(f"{g[:19]:<20}{c['apps']:>10,}{c['graveyard_pct']:>10.1f}{c['traction_pct']:>9.1f}"
              f"{c['paid_pct']:>9.1f}{(c['avg_paid_price'] or 0):>7.2f}{(c['median_rating'] or 0):>8.2f}"
              f"{c['fresh_2024plus_pct']:>8.1f}{c['ai_pct']:>7.1f}")
    t = out["total"]
    print(f"\nAI terimleri (toplam): {t['ai_terms']}  | herhangi biri: {t['ai_apps']:,}"
          f"  | düz alt dize ile olsaydı: {t['ai_naive_substring_apps']:,}")


if __name__ == "__main__":
    main()
