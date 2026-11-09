#!/usr/bin/env python3
"""App Store scraper — resumable.

  python3 scraper.py sitemaps            # ADIM 1: ids.txt üret
  python3 scraper.py lookup --limit 1000 # PİLOT: ilk 1000 ID
  python3 scraper.py lookup              # ADIM 2: tam çekim

Tüm durum dosyaları bu script'in klasöründe tutulur.
"""
import argparse
import gzip
import json
import os
import queue
import re
import sys
import threading
import time

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # proje kökü
P = lambda name: os.path.join(BASE, name)

INDEX_URL = "https://apps.apple.com/sitemaps_apps_index_app_1.xml"
LOOKUP_URL = "https://itunes.apple.com/lookup"
IDS = P("ids.txt")
DONE_SITEMAPS = P("done_sitemaps.txt")
SITEMAP_LIST = P("sitemap_list.txt")
OUT = P("apps_2026.jsonl")
PROGRESS = P("progress.txt")
STATS = P("lookup_stats.json")

FIELDS = [
    "trackId", "trackName", "bundleId", "description", "primaryGenreName",
    "genres", "averageUserRating", "userRatingCount", "price", "currency",
    "releaseDate", "currentVersionReleaseDate", "version", "sellerName",
    "artistId", "contentAdvisoryRating", "fileSizeBytes", "minimumOsVersion",
    "languageCodesISO2A", "trackViewUrl",
]
GROUP = 200
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
ID_RE = re.compile(r"/id(\d+)")

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) appstore-2026-research"


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [l.strip() for l in f if l.strip()]


def append_lines(path, lines):
    with open(path, "a") as f:
        for l in lines:
            f.write(f"{l}\n")
        f.flush()
        os.fsync(f.fileno())


def fetch(url, tries=6, **kw):
    delay = 5
    for i in range(tries):
        try:
            r = session.get(url, timeout=60, **kw)
            if r.status_code == 200:
                return r
            log(f"HTTP {r.status_code} {url} (deneme {i+1})")
        except requests.RequestException as e:
            log(f"Hata {type(e).__name__}: {e} (deneme {i+1})")
        time.sleep(delay)
        delay = min(delay * 2, 300)
    raise RuntimeError(f"İndirilemedi: {url}")


# ---------------------------------------------------------------- ADIM 1
def cmd_sitemaps(args):
    r = fetch(INDEX_URL)
    subs = list(dict.fromkeys(LOC_RE.findall(r.text)))
    with open(SITEMAP_LIST, "w") as f:
        f.write("\n".join(subs) + "\n")
    done = set(read_lines(DONE_SITEMAPS))
    seen = set(read_lines(IDS))
    todo = [s for s in subs if s not in done]
    log(f"Index: {len(subs)} alt sitemap, {len(done)} bitmiş, {len(todo)} kaldı, mevcut ID: {len(seen)}")

    t0 = time.time()
    for n, url in enumerate(todo, 1):
        raw = fetch(url).content
        try:
            text = gzip.decompress(raw).decode("utf-8", "replace")
        except OSError:  # sunucu zaten açmış olabilir
            text = raw.decode("utf-8", "replace")
        new = []
        for loc in LOC_RE.findall(text):
            m = ID_RE.search(loc)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                new.append(m.group(1))
        append_lines(IDS, new)          # önce ID'ler,
        append_lines(DONE_SITEMAPS, [url])  # sonra "bitti" işareti
        if n % 50 == 0 or n == len(todo):
            el = time.time() - t0
            log(f"[sitemap] {len(done)+n}/{len(subs)}  ID: {len(seen)}  "
                f"kalan ~{(len(todo)-n)*el/n/60:.1f} dk")
        time.sleep(args.delay)

    total_done = len(set(read_lines(DONE_SITEMAPS)) & set(subs))
    log(f"BİTTİ. Toplam sitemap: {len(subs)} (tamamlanan {total_done}), tekil ID: {len(seen)}")


# ---------------------------------------------------------------- ADIM 2
class SharedLimiter:
    """Tüm worker'ların ortak kapısı.

    - İstek başlangıçları arasında en az `interval` sn (60/rpm) bırakır → toplam ≤ rpm.
    - Herhangi bir worker 403/429/5xx alırsa interval TÜM worker'lar için katlanır ve
      herkes `interval` kadar duraklar (ortak backoff).
    - 50 ardışık temiz yanıttan sonra interval yavaşça tabana (60/rpm) iner.
    """

    def __init__(self, rpm, ceil=600):
        self.floor = 60.0 / rpm
        self.interval = self.floor
        self.ceil = ceil
        self.next_slot = time.monotonic()
        self.clean = 0
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.monotonic()
            slot = max(now, self.next_slot)
            self.next_slot = slot + self.interval
        if slot > now:
            time.sleep(slot - now)

    def ok(self):
        with self.lock:
            self.clean += 1
            if self.clean >= 50 and self.interval > self.floor:
                self.interval = max(self.floor, self.interval * 0.85)
                self.clean = 0
                log(f"[limiter] 50 temiz yanıt → aralık {self.interval:.2f} sn")

    def fail(self, why):
        with self.lock:
            self.clean = 0
            self.interval = min(self.ceil, self.interval * 2)
            # herkesi duraklat: bir sonraki slot en erken şimdi + interval
            self.next_slot = max(self.next_slot, time.monotonic() + self.interval)
            log(f"[limiter] {why} → tüm worker'lar için aralık {self.interval:.1f} sn")


def load_stats():
    if os.path.exists(STATS):
        with open(STATS) as f:
            return json.load(f)
    return {"requests": 0, "ok": 0, "http_errors": {}, "net_errors": 0,
            "ids_requested": 0, "apps_returned": 0}


def save_stats(s):
    tmp = STATS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATS)


def cmd_lookup(args):
    ids = read_lines(IDS)
    subs = read_lines(SITEMAP_LIST)
    if args.limit is None and not args.force:
        if not subs or len(set(read_lines(DONE_SITEMAPS)) & set(subs)) < len(subs):
            sys.exit("ADIM 1 bitmemiş (done_sitemaps eksik). Önce `sitemaps` çalıştırın ya da --force.")
    if args.limit:
        ids = ids[: args.limit]

    groups = [(i, ids[i:i + GROUP]) for i in range(0, len(ids), GROUP)]
    done = set(int(x) for x in read_lines(PROGRESS))
    todo = [(off, g) for off, g in groups if off not in done]

    have = set()  # tekrar eden trackId yazılmasın
    if os.path.exists(OUT):
        with open(OUT) as f:
            for line in f:
                try:
                    have.add(json.loads(line)["trackId"])
                except (ValueError, KeyError):
                    pass

    stats = load_stats()
    limiter = SharedLimiter(args.rpm)
    write_lock = threading.Lock()
    total = len(ids)
    state = {"done_ids": sum(len(g) for off, g in groups if off in done),
             "run_ids": 0, "run_groups": 0}
    log(f"Lookup: {total} ID, {len(groups)} grup, {len(done)} bitmiş, {len(todo)} kaldı, "
        f"jsonl'de {len(have)} kayıt, {args.workers} worker, ≤{args.rpm} istek/dk")

    q = queue.Queue()
    for item in todo:
        q.put(item)
    out = open(OUT, "a")
    t0 = time.time()

    def bump(key, sub=None):
        with write_lock:
            if sub is None:
                stats[key] += 1
            else:
                stats[key][sub] = stats[key].get(sub, 0) + 1

    def fetch_group(sess, g):
        while True:
            limiter.acquire()
            bump("requests")
            try:
                r = sess.get(LOOKUP_URL, timeout=60, params={
                    "id": ",".join(g), "country": "us", "entity": "software"})
                code = r.status_code
            except requests.RequestException as e:
                bump("net_errors")
                limiter.fail(f"ağ hatası {type(e).__name__}")
                continue
            if code == 200:
                try:
                    return r.json().get("results", [])
                except ValueError:
                    code = "bad_json"
            bump("http_errors", str(code))
            limiter.fail(f"HTTP {code}")

    def worker():
        sess = requests.Session()
        sess.headers.update(session.headers)
        while True:
            try:
                off, g = q.get_nowait()
            except queue.Empty:
                return
            results = fetch_group(sess, g)
            limiter.ok()
            with write_lock:
                rows = []
                for app in results:
                    if app.get("wrapperType") != "software" and app.get("kind") not in ("software", "mac-software"):
                        continue
                    tid = app.get("trackId")
                    if tid in have:
                        continue
                    have.add(tid)
                    rows.append(json.dumps({k: app.get(k) for k in FIELDS}, ensure_ascii=False))
                if rows:
                    out.write("\n".join(rows) + "\n")
                out.flush()
                os.fsync(out.fileno())
                if len(g) == GROUP:  # eksik son grup işaretlenmez; ids.txt büyürse tekrar denenir
                    append_lines(PROGRESS, [off])
                stats["ok"] += 1
                stats["ids_requested"] += len(g)
                stats["apps_returned"] += len(rows)
                save_stats(stats)
                state["done_ids"] += len(g)
                state["run_ids"] += len(g)
                state["run_groups"] += 1
                n = state["run_groups"]
                if n % 50 == 0 or n == len(todo):
                    el = time.time() - t0
                    rate = state["run_ids"] / el * 60 if el else 0
                    eta = (total - state["done_ids"]) / rate if rate else 0
                    log(f"[lookup] {state['done_ids']}/{total} ID  {rate:.0f} ID/dk  "
                        f"{n / el * 60:.1f} istek/dk  kalan ~{eta/60:.1f} sa  "
                        f"aralık {limiter.interval:.2f} sn  dönen uygulama {stats['apps_returned']}  "
                        f"hatalar {stats['http_errors']} ağ {stats['net_errors']}")

    threads = [threading.Thread(target=worker, name=f"w{i}") for i in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out.close()
    log("BİTTİ.", json.dumps(stats, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s1 = sp.add_parser("sitemaps")
    s1.add_argument("--delay", type=float, default=0.5)
    s2 = sp.add_parser("lookup")
    s2.add_argument("--limit", type=int)
    s2.add_argument("--workers", type=int, default=3)
    s2.add_argument("--rpm", type=float, default=18,
                    help="tüm worker'lar toplamı için dakikadaki azami istek")
    s2.add_argument("--force", action="store_true")
    a = ap.parse_args()
    {"sitemaps": cmd_sitemaps, "lookup": cmd_lookup}[a.cmd](a)


if __name__ == "__main__":
    main()
