#!/usr/bin/env bash
# Tam çekim: ADIM 1 (bitmişse sadece index'i kontrol eder) + ADIM 2. Kaldığı yerden devam eder.
cd "$(dirname "$0")"
python3 -I scraper.py sitemaps >> ../sitemaps.log 2>&1 || exit 1
exec python3 -I scraper.py lookup >> ../scrape.log 2>&1
