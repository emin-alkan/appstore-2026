#!/usr/bin/env python3
"""Anlamsal App Store haritası — aşamalı ve kaldığı yerden devam eder.

  .venv/bin/python map_pipeline.py prep               # metinler + meta
  .venv/bin/python map_pipeline.py embed --pilot 5000 # hız ölçümü (map/pilot/)
  .venv/bin/python map_pipeline.py embed              # tam embedding (map/emb/chunk_*.npy)
  .venv/bin/python map_pipeline.py reduce             # PCA50 → UMAP 2B → KMeans
  .venv/bin/python map_pipeline.py analyze            # TF-IDF etiketler, yoğunluk boşlukları, çıktılar
  .venv/bin/python map_pipeline.py all                # prep hariç hepsi, sırayla
"""
import argparse
import glob
import json
import os
import re
import sys
import time

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # proje kökü
SRC = os.path.join(BASE, "apps_2026.jsonl")
MAP = os.path.join(BASE, "map")
TEXTS = os.path.join(MAP, "texts.txt")
META = os.path.join(MAP, "meta.parquet")
EMB_DIR = os.path.join(MAP, "emb")
COORDS = os.path.join(MAP, "coords.npy")
LABELS = os.path.join(MAP, "kmeans_labels.npy")

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK = 50_000
SEED = 42
AI_RX = re.compile(r"\bai\b|gpt|\bchat ?bots?\b|artificial intelligence|\bllms?\b")


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ prep
def cmd_prep(args):
    import pandas as pd
    os.makedirs(MAP, exist_ok=True)
    cols = {k: [] for k in ["trackId", "trackName", "primaryGenreName", "userRatingCount",
                            "averageUserRating", "price", "ai"]}
    kept = dropped = 0
    t0 = time.time()
    with open(SRC, encoding="utf-8") as f, open(TEXTS + ".tmp", "w", encoding="utf-8") as out:
        for line in f:
            a = json.loads(line)
            desc = (a.get("description") or "").strip()
            if len(desc) < 20:
                dropped += 1
                continue
            name = (a.get("trackName") or "").strip()
            text = " ".join(f"{name}. {desc[:800]}".split())  # tek satır
            out.write(text + "\n")
            cols["trackId"].append(a.get("trackId"))
            cols["trackName"].append(name)
            cols["primaryGenreName"].append(a.get("primaryGenreName"))
            cols["userRatingCount"].append(a.get("userRatingCount") or 0)
            cols["averageUserRating"].append(a.get("averageUserRating") or 0.0)
            cols["price"].append(a.get("price") or 0.0)
            cols["ai"].append(bool(AI_RX.search(desc.lower())))
            kept += 1
    os.replace(TEXTS + ".tmp", TEXTS)
    df = pd.DataFrame(cols)
    df["primaryGenreName"] = df["primaryGenreName"].astype("category")
    df.to_parquet(META, index=False)
    log(f"prep: {kept} tutuldu, {dropped} elendi (açıklama <20 karakter), {time.time()-t0:.0f} sn")


# ------------------------------------------------------------------ embed
def load_model():
    import torch
    from sentence_transformers import SentenceTransformer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    m = SentenceTransformer(MODEL, device=dev)
    if dev == "cuda":
        m.half()
    log(f"model {MODEL} | cihaz {dev}"
        f"{' (' + torch.cuda.get_device_name(0) + ')' if dev == 'cuda' else ''} | max_seq_length {m.max_seq_length}")
    return m, dev


def read_chunk(start, n):
    out = []
    with open(TEXTS, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < start:
                continue
            if len(out) >= n:
                break
            out.append(line.rstrip("\n"))
    return out


def cmd_embed(args):
    m, dev = load_model()
    total = sum(1 for _ in open(TEXTS, encoding="utf-8"))

    if args.pilot:
        texts = read_chunk(0, args.pilot)
        m.encode(texts[:512], batch_size=args.batch)  # ısınma
        t0 = time.time()
        e = m.encode(texts, batch_size=args.batch, convert_to_numpy=True, normalize_embeddings=True)
        el = time.time() - t0
        rate = len(texts) / el
        os.makedirs(os.path.join(MAP, "pilot"), exist_ok=True)
        np.save(os.path.join(MAP, "pilot", "emb_pilot.npy"), e.astype(np.float16))
        log(f"PİLOT: {len(texts)} metin {el:.1f} sn → {rate:.0f} metin/sn | boyut {e.shape} | "
            f"NaN {int(np.isnan(e).sum())} | tam veri ({total}) tahmini {total/rate/60:.1f} dk")
        return

    if dev != "cuda" and not args.force:
        sys.exit("GPU yok: tam veri yerine 250.000 örnek gerekir (henüz uygulanmadı) — --force ile CPU'da devam.")
    os.makedirs(EMB_DIR, exist_ok=True)
    starts = list(range(0, total, CHUNK))
    t0, done_now = time.time(), 0
    with open(TEXTS, encoding="utf-8") as f:
        for ci, s in enumerate(starts):
            n = min(CHUNK, total - s)
            texts = [f.readline().rstrip("\n") for _ in range(n)]  # dosyada sırayla ilerle
            path = os.path.join(EMB_DIR, f"chunk_{ci:05d}.npy")
            if os.path.exists(path):
                continue
            e = m.encode(texts, batch_size=args.batch, convert_to_numpy=True, normalize_embeddings=True)
            np.save(path + ".tmp.npy", e.astype(np.float16))
            os.replace(path + ".tmp.npy", path)
            done_now += n
            el = time.time() - t0
            rate = done_now / el
            left = total - (s + n)
            log(f"[embed] parça {ci+1}/{len(starts)}  {s+n}/{total}  {rate:.0f} metin/sn  kalan ~{left/rate/60:.1f} dk")
    log("embed BİTTİ")


def load_embeddings():
    files = sorted(glob.glob(os.path.join(EMB_DIR, "chunk_*.npy")))
    return files, [np.load(p, mmap_mode="r") for p in files]


# ------------------------------------------------------------------ reduce
def cmd_reduce(args):
    import umap
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    files, parts = load_embeddings()
    total = sum(p.shape[0] for p in parts)
    rng = np.random.default_rng(SEED)

    # örneklem (PCA + UMAP eğitimi)
    sample_idx = np.sort(rng.choice(total, size=min(args.fit, total), replace=False))
    offsets = np.cumsum([0] + [p.shape[0] for p in parts])
    def rows(idx):
        out = np.empty((len(idx), parts[0].shape[1]), dtype=np.float32)
        for k, p in enumerate(parts):
            sel = (idx >= offsets[k]) & (idx < offsets[k + 1])
            out[sel] = p[idx[sel] - offsets[k]]
        return out
    X_fit = rows(sample_idx)
    log(f"reduce: {total} nokta, UMAP eğitim örneği {len(sample_idx)}")

    pca = PCA(n_components=50, random_state=SEED).fit(X_fit)
    log(f"PCA50 açıklanan varyans {pca.explained_variance_ratio_.sum():.3f}")
    Z_fit = pca.transform(X_fit).astype(np.float32)
    del X_fit

    t0 = time.time()
    reducer = umap.UMAP(n_components=2, n_neighbors=15, min_dist=0.05, metric="cosine",
                        random_state=SEED, low_memory=True, verbose=False)
    reducer.fit(Z_fit)
    log(f"UMAP fit {time.time()-t0:.0f} sn")

    coords = np.lib.format.open_memmap(COORDS + ".tmp.npy", mode="w+", dtype=np.float32, shape=(total, 2))
    t0 = time.time()
    for k, p in enumerate(parts):
        Zk = pca.transform(np.asarray(p, dtype=np.float32)).astype(np.float32)
        for j in range(0, len(Zk), 25_000):
            coords[offsets[k] + j: offsets[k] + j + len(Zk[j:j + 25_000])] = reducer.transform(Zk[j:j + 25_000])
        el = time.time() - t0
        log(f"[umap transform] parça {k+1}/{len(parts)}  kalan ~{el/(k+1)*(len(parts)-k-1)/60:.1f} dk")
    coords.flush()
    del coords
    os.replace(COORDS + ".tmp.npy", COORDS)

    C = np.load(COORDS)
    km = KMeans(n_clusters=args.k, n_init=4, random_state=SEED).fit(C)
    np.save(LABELS, km.labels_.astype(np.int16))
    log(f"KMeans k={args.k} bitti; reduce BİTTİ")


# ------------------------------------------------------------------ analyze
def cmd_analyze(args):
    import pandas as pd
    from scipy import ndimage
    from sklearn.feature_extraction.text import TfidfVectorizer

    meta = pd.read_parquet(META)
    C = np.load(COORDS)
    lab = np.load(LABELS)
    assert len(meta) == len(C) == len(lab), (len(meta), len(C), len(lab))
    meta["x"], meta["y"], meta["cluster"] = C[:, 0], C[:, 1], lab
    K = int(lab.max()) + 1
    rng = np.random.default_rng(SEED)

    # --- TF-IDF (c-TF-IDF tarzı): her kümeden ≤3000 metin, küme başına bir belge
    per = {c: rng.permutation(np.flatnonzero(lab == c))[:3000] for c in range(K)}
    want = np.zeros(len(meta), dtype=bool)
    for idx in per.values():
        want[idx] = True
    docs, doc_lab = [], []
    with open(TEXTS, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if want[i]:
                docs.append(line.split(". ", 1)[-1])  # ad değil açıklama
                doc_lab.append(lab[i])
    doc_lab = np.array(doc_lab)
    # Uygulama başına TF-IDF; nadir kelimeler (min_df) elenir. Skor = küme ortalaması − genel ortalama
    vec = TfidfVectorizer(stop_words="english", max_features=60_000, min_df=30, max_df=0.15,
                          token_pattern=r"(?u)\b[^\W\d_]{3,}\b", sublinear_tf=True)
    M = vec.fit_transform(docs)
    vocab = np.array(vec.get_feature_names_out())
    gmean = np.asarray(M.mean(axis=0)).ravel()
    terms = {}
    for c in range(K):
        cm = np.asarray(M[doc_lab == c].mean(axis=0)).ravel()
        terms[c] = vocab[np.argsort(-(cm - gmean))[:5]].tolist()

    clusters = []
    for c in range(K):
        g = meta[meta.cluster == c]
        rated = g.loc[g.userRatingCount > 0, "averageUserRating"]
        top_genres = g.primaryGenreName.value_counts(normalize=True).head(3)
        clusters.append({
            "cluster": c, "size": int(len(g)), "terms": terms[c],
            "centroid": [round(float(g.x.mean()), 3), round(float(g.y.mean()), 3)],
            "median_rating": round(float(rated.median()), 3) if len(rated) else None,
            "graveyard_pct": round(100 * float((g.userRatingCount == 0).mean()), 2),
            "traction_pct": round(100 * float((g.userRatingCount >= 100).mean()), 2),
            "ai_pct": round(100 * float(g.ai.mean()), 2),
            "paid_pct": round(100 * float((g.price > 0).mean()), 2),
            "top_genres": {str(k): round(100 * float(v), 1) for k, v in top_genres.items()},
            "top_apps": g.nlargest(5, "userRatingCount").trackName.tolist(),
        })
    with open(os.path.join(MAP, "clusters.json"), "w", encoding="utf-8") as f:
        json.dump({"k": K, "points": int(len(meta)), "clusters": clusters}, f, ensure_ascii=False, indent=1)

    # --- yoğunluk ızgarası: kendisi seyrek, halkası dolu hücreler
    G = args.grid
    lo = np.percentile(C, 0.5, axis=0)
    hi = np.percentile(C, 99.5, axis=0)
    H, xe, ye = np.histogram2d(C[:, 0], C[:, 1], bins=G, range=[[lo[0], hi[0]], [lo[1], hi[1]]])
    local = ndimage.gaussian_filter(H, 1.0)
    ring_k = np.zeros((2 * args.ring + 1,) * 2)
    yy, xx = np.mgrid[-args.ring:args.ring + 1, -args.ring:args.ring + 1]
    r = np.hypot(yy, xx)
    ring_k[(r <= args.ring) & (r > args.ring / 2)] = 1
    ring_k /= ring_k.sum()
    ring = ndimage.convolve(H, ring_k, mode="constant")
    occ = local[H > 0]                          # yalnızca gerçekten nokta içeren hücreler
    dense = (local >= np.percentile(occ, 50)).astype(float)
    enclosure = ndimage.convolve(dense, ring_k, mode="constant")  # halkanın ne kadarı yoğun
    dip = local / np.maximum(ring, 1e-9)                          # hücre / halka yoğunluk oranı
    hole = (enclosure >= args.enclosure) & (dip < args.dip)
    sparse_thr, dense_thr = float(args.dip), float(np.percentile(occ, 50))
    comp, ncomp = ndimage.label(hole)
    cell = np.array([(xe[1] - xe[0]), (ye[1] - ye[0])])
    cents = np.array([c["centroid"] for c in clusters])

    regions = []
    for rid in range(1, ncomp + 1):
        cells = np.argwhere(comp == rid)
        if len(cells) < args.min_cells:
            continue
        cx = xe[0] + (cells[:, 0].mean() + 0.5) * cell[0]
        cy = ye[0] + (cells[:, 1].mean() + 0.5) * cell[1]
        inside = H[comp == rid].sum()
        ring_mean = ring[comp == rid].mean()
        d = np.hypot(cents[:, 0] - cx, cents[:, 1] - cy)
        near = np.argsort(d)[:4]
        # bölgeye en yakın gerçek uygulamalar (kenarındakiler)
        dd = np.hypot(meta.x.values - cx, meta.y.values - cy)
        nn = np.argsort(dd)[:8]
        regions.append({
            "center": [round(float(cx), 3), round(float(cy), 3)],
            "cells": int(len(cells)),
            "area": round(float(len(cells) * cell[0] * cell[1]), 4),
            "apps_inside": int(inside),
            "inside_density": round(float(inside / len(cells)), 2),
            "ring_density": round(float(ring_mean), 2),
            "contrast": round(float(ring_mean / (inside / len(cells) + 1)), 2),
            "dip_ratio": round(float(dip[comp == rid].mean()), 3),
            "enclosure": round(float(enclosure[comp == rid].mean()), 3),
            "nearest_clusters": [{"cluster": int(c), "terms": clusters[c]["terms"],
                                  "distance": round(float(d[c]), 3)} for c in near],
            "edge_apps": [{"trackName": meta.trackName.iat[i], "genre": str(meta.primaryGenreName.iat[i]),
                           "userRatingCount": int(meta.userRatingCount.iat[i])} for i in nn],
        })
    regions.sort(key=lambda r: -r["contrast"] * r["cells"])
    with open(os.path.join(MAP, "empty_regions.json"), "w", encoding="utf-8") as f:
        json.dump({"grid": G, "ring_radius_cells": args.ring,
                   "criteria": f"halkanın ≥%{int(args.enclosure*100)}'i yoğun (≥ dolu hücre medyanı {dense_thr:.1f}) "
                               f"ve hücre yoğunluğu < halka × {args.dip}",
                   "caveat": "UMAP yoğunluğu korumaz; bölgeler aday hipotezdir, edge_apps ile elle doğrulanmalı",
                   "regions": regions}, f, ensure_ascii=False, indent=1)

    # --- harita noktaları
    pts = meta.sample(n=min(40_000, len(meta)), random_state=SEED)[
        ["x", "y", "cluster", "primaryGenreName", "trackName", "userRatingCount", "price"]]
    pts.to_parquet(os.path.join(MAP, "map_points.parquet"), index=False)
    log(f"analyze BİTTİ: {K} küme, {len(regions)} seyrek bölge, {len(pts)} harita noktası")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("prep")
    e = sp.add_parser("embed")
    e.add_argument("--pilot", type=int)
    e.add_argument("--batch", type=int, default=256)
    e.add_argument("--force", action="store_true")
    for name in ("reduce", "all"):
        r = sp.add_parser(name)
        r.add_argument("--fit", type=int, default=200_000)
        r.add_argument("--k", type=int, default=50)
        r.add_argument("--batch", type=int, default=256)
        r.add_argument("--force", action="store_true")
        r.add_argument("--pilot", type=int)
        r.add_argument("--grid", type=int, default=200)
        r.add_argument("--ring", type=int, default=6)
        r.add_argument("--enclosure", type=float, default=0.75)
        r.add_argument("--dip", type=float, default=0.5)
        r.add_argument("--min-cells", type=int, default=3)
    a = sp.add_parser("analyze")
    a.add_argument("--grid", type=int, default=200)
    a.add_argument("--ring", type=int, default=6)
    a.add_argument("--enclosure", type=float, default=0.75)
    a.add_argument("--dip", type=float, default=0.5)
    a.add_argument("--min-cells", type=int, default=3)
    args = ap.parse_args()
    if args.cmd == "all":
        cmd_embed(args); cmd_reduce(args); cmd_analyze(args)
    else:
        {"prep": cmd_prep, "embed": cmd_embed, "reduce": cmd_reduce, "analyze": cmd_analyze}[args.cmd](args)


if __name__ == "__main__":
    main()
