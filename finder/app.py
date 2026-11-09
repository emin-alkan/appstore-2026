"""App Store Fırsat Avcısı — streamlit run app.py"""
import os
import re
import time
from collections import Counter

import duckdb
import pandas as pd
import streamlit as st

from build_parquet import DST as PARQUET, build

st.set_page_config(page_title="App Store Fırsat Avcısı", page_icon="🔎", layout="wide")

TRACTION = 100  # "gerçek kullanım" eşiği (ABD mağazası yorum sayısı)
REVIEW_STEPS = [0, 1, 5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000,
                50_000, 100_000, 1_000_000, 100_000_000]
STOP = set("""
a an and the of for to in on with by at from your you my our is are be it its this that as or not
app apps free pro lite plus premium hd new best official mobile online easy simple smart my
ve ile için bir bu da de en çok mi mı
la le les el los las de del des du di da et y e o il un une der die das und für mit von
""".split())


@st.cache_resource
def db():
    if not os.path.exists(PARQUET):
        with st.spinner("İlk çalıştırma: apps_2026.jsonl → apps.parquet dönüştürülüyor (~10 sn)…"):
            n, el = build()
        st.toast(f"Parquet hazır: {n:,} satır, {el:.1f} sn")
    con = duckdb.connect()
    con.execute("SET memory_limit='3GB'")
    con.execute("SET threads=6")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"CREATE VIEW apps AS SELECT * FROM '{PARQUET}'")
    return con


def q(sql, params=()):
    con = db().cursor()
    return con.execute(sql, list(params)).df()


@st.cache_data
def genres():
    return q("SELECT primaryGenreName g, count(*) n FROM apps WHERE g IS NOT NULL GROUP BY g ORDER BY n DESC")


def where_clause(f):
    w, p = ["TRUE"], []
    for kw in f["keywords"]:
        # contains() hızlı ön filtre; regexp kelime başına bağlar ("habit" ≠ "inhabitant")
        w.append("contains(search_text, ?) AND regexp_matches(search_text, ?)")
        p += [kw, r"\b" + re.escape(kw)]
    if f["genres"]:
        w.append(f"primaryGenreName IN ({','.join('?' * len(f['genres']))})")
        p += f["genres"]
    w.append("userRatingCount BETWEEN ? AND ?")
    p += [f["rmin"], f["rmax"]]
    if f["min_rating"] > 0:
        w.append("averageUserRating >= ?")
        p.append(f["min_rating"])
    if f["price"] == "Ücretsiz":
        w.append("price = 0")
    elif f["price"] == "Ücretli":
        w.append("price > 0")
    if f["min_year"]:
        w.append("updateYear >= ?")
        p.append(f["min_year"])
    if f["lang"]:
        w.append("(',' || languages || ',') LIKE ?")
        p.append(f"%,{f['lang']},%")
    return " AND ".join(w), p


@st.cache_data(show_spinner=False)
def run(f):
    f = dict(f)
    w, p = where_clause(f)
    t0 = time.time()
    summary = q(f"""
        SELECT count(*) n,
               count(*) FILTER (userRatingCount >= {TRACTION}) traction,
               median(userRatingCount) med_reviews,
               avg((price > 0)::INT) paid_rate,
               avg(((',' || languages || ',') LIKE '%,TR,%')::INT) tr_rate,
               max(userRatingCount) leader,
               sum(userRatingCount) total_reviews
        FROM apps WHERE {w}""", p).iloc[0].to_dict()
    top = q(f"""SELECT trackName, userRatingCount, averageUserRating, price, sellerName, trackViewUrl
                FROM apps WHERE {w} ORDER BY userRatingCount DESC LIMIT 15""", p)
    names = q(f"SELECT trackName FROM apps WHERE {w} LIMIT 100000", p)
    summary["top3_share"] = (top.userRatingCount.head(3).sum() / summary["total_reviews"]
                             if summary["total_reviews"] else 0)
    summary["seconds"] = time.time() - t0
    return summary, top, names


@st.cache_data(show_spinner=False)
def table(f, order, limit):
    w, p = where_clause(dict(f))
    return q(f"""SELECT trackName, primaryGenreName, userRatingCount, averageUserRating, price,
                        updateYear, sellerName, languages, trackViewUrl
                 FROM apps WHERE {w} ORDER BY userRatingCount {order}, trackName LIMIT {int(limit)}""", p)


def signal(s):
    """Basit, şeffaf kurallar. Sonuç bir hipotezdir, karar değil."""
    n, tr, leader, tr_rate = int(s["n"]), int(s["traction"]), int(s["leader"] or 0), s["tr_rate"] or 0
    notes = []
    if n < 5:
        return "⚪ Veri yetersiz", "Eşleşen uygulama çok az; anahtar kelimeleri genişletin.", notes
    if tr == 0:
        label, why = "⚫ Ölü", f"Hiçbir uygulama {TRACTION}+ yoruma ulaşmamış — talep kanıtı yok."
    elif tr <= 2:
        label, why = "🟠 Zayıf talep", f"Yalnızca {tr} uygulama {TRACTION}+ yorumda; talep ince ya da tek oyuncuya bağlı."
    elif tr >= 50 or leader >= 100_000 or n >= 3_000:
        label, why = "🔴 Kalabalık", (f"{tr} uygulama {TRACTION}+ yorumda, lider {leader:,} yorum, "
                                     f"toplam {n:,} rakip — girmek için net bir farklılaşma gerekir.")
    else:
        label, why = "🟢 Umut verici", (f"Talep var ({tr} uygulama {TRACTION}+ yorumda) ama lider {leader:,} yorumla "
                                       f"ezici değil ve rakip sayısı ({n:,}) yönetilebilir.")
    if s["top3_share"] >= 0.8 and tr > 0:
        notes.append(f"İlk 3 uygulama yorumların %{100*s['top3_share']:.0f}'ini topluyor — pazar birkaç oyuncuda yoğunlaşmış.")
    if tr > 0 and tr_rate < 0.10:
        notes.append(f"Yerel boşluk: eşleşenlerin yalnızca %{100*tr_rate:.1f}'i Türkçe destekliyor.")
    elif tr_rate >= 0.25:
        notes.append(f"Türkçe destek yaygın (%{100*tr_rate:.0f}) — yerel avantaj sınırlı.")
    return label, why, notes


# ------------------------------------------------------------------ arayüz
st.title("🔎 App Store Fırsat Avcısı")
st.caption("1,6M uygulama · ABD mağazası verisi (yorum sayıları ve fiyatlar ABD'ye ait) · Kasım 2026 çekimi")

with st.sidebar:
    st.header("Filtreler")
    kw_raw = st.text_input("Anahtar kelime(ler)", placeholder="ör. habit tracker",
                           help="Ad + açıklamada aranır, küçük harf. Birden çok kelime = VE. Kelime başına eşleşir.")
    g = genres()
    sel_genres = st.multiselect("Kategori", g.g.tolist(), format_func=lambda x: f"{x} ({int(g.set_index('g').n[x]):,})")
    rmin, rmax = st.select_slider("Yorum sayısı aralığı", options=REVIEW_STEPS, value=(0, REVIEW_STEPS[-1]),
                                  format_func=lambda v: "∞" if v == REVIEW_STEPS[-1] else f"{v:,}",
                                  help="Az hizmet verilen alanları görmek için üst sınırı düşük tutun.")
    min_rating = st.slider("Min ortalama puan", 0.0, 5.0, 0.0, 0.1,
                           help="0 = filtre yok. >0 seçilirse hiç oy almamış uygulamalar elenir.")
    price = st.radio("Fiyat", ["Hepsi", "Ücretsiz", "Ücretli"], horizontal=True)
    min_year = st.number_input("Son güncelleme yılı (min)", min_value=0, max_value=2026, value=0, step=1,
                               help="0 = filtre yok")
    lang = st.text_input("Dil içerir (ISO-2)", placeholder="ör. TR").strip().upper()
    st.divider()
    st.caption(f"Talep eşiği: ≥{TRACTION} yorum")

keywords = [k for k in kw_raw.lower().split() if k]
filters = dict(keywords=tuple(keywords), genres=tuple(sel_genres), rmin=rmin, rmax=rmax,
               min_rating=min_rating, price=price, min_year=int(min_year), lang=lang)
fkey = tuple(sorted(filters.items()))

if not keywords and not sel_genres:
    st.info("Başlamak için soldan bir anahtar kelime ya da kategori seçin. (Tüm 1,6M uygulamayı da tarayabilir, ama özet anlamsız olur.)")
    st.stop()

with st.spinner("Sorgulanıyor…"):
    s, top, names = run(fkey)

# 1. Niş özeti + 5. fırsat sinyali
label, why, notes = signal(s)
st.subheader("Niş Özeti")
c = st.columns(6)
c[0].metric("Eşleşen uygulama", f"{int(s['n']):,}")
c[1].metric(f"≥{TRACTION} yorum (talep)", f"{int(s['traction']):,}",
            f"%{100*s['traction']/s['n']:.1f}" if s["n"] else None, delta_color="off")
c[2].metric("Medyan yorum", f"{(s['med_reviews'] or 0):,.0f}")
c[3].metric("Ücretli oranı", f"%{100*(s['paid_rate'] or 0):.1f}")
c[4].metric("Türkçe destekli", f"%{100*(s['tr_rate'] or 0):.1f}")
c[5].metric("Lider (yorum)", f"{int(s['leader'] or 0):,}")

with st.container(border=True):
    st.markdown(f"### Fırsat sinyali: {label}")
    st.write(why)
    for n_ in notes:
        st.write("• " + n_)
    st.caption("Kurallar: ≥100 yorumlu uygulama yok → ölü · 1–2 → zayıf talep · ≥50 ya da lider ≥100k yorum ya da "
               "≥3.000 rakip → kalabalık · aksi halde umut verici. Yorum sayısı ABD mağazasından; "
               "uygulama içi gelir ve diğer ülkeler dahil değil. Bu bir ön okumadır, doğrulama değil.")
st.caption(f"Sorgu süresi {s['seconds']:.2f} sn")

if not s["n"]:
    st.stop()

link = st.column_config.LinkColumn("App Store", display_text="Aç ↗")
fmt = {
    "trackName": "Ad", "primaryGenreName": "Kategori", "sellerName": "Geliştirici",
    "userRatingCount": st.column_config.NumberColumn("Yorum", format="%d"),
    "averageUserRating": st.column_config.NumberColumn("Puan", format="%.2f"),
    "price": st.column_config.NumberColumn("Fiyat $", format="%.2f"),
    "updateYear": st.column_config.NumberColumn("Güncelleme", format="%d"),
    "languages": "Diller", "trackViewUrl": link,
}

left, right = st.columns([3, 2])
# 2. Rakipler
with left:
    st.subheader("Rakipler — en çok yorumlu 15")
    st.dataframe(top, column_config=fmt, hide_index=True, width="stretch")
# 4. Alt-niş dağılımı
with right:
    st.subheader("Alt-niş dağılımı — adlardaki en sık 20 kelime")
    cnt = Counter()
    skip = STOP | set(keywords)
    for name in names.trackName.dropna():
        words = {w for w in re.findall(r"[^\W\d_]{3,}", name.lower()) if w not in skip}
        cnt.update(words)  # her uygulama bir kelimeyi bir kez sayar
    wf = pd.DataFrame(cnt.most_common(20), columns=["kelime", "uygulama"])
    if len(wf):
        st.bar_chart(wf.set_index("kelime"), horizontal=True, height=520)
    if len(names) == 100_000:
        st.caption("İlk 100.000 eşleşmenin adlarından hesaplandı.")

# 3. Sonuç tablosu
st.subheader("Sonuç tablosu")
o1, o2 = st.columns([2, 1])
order_lbl = o1.radio("Sıralama", ["Yoruma göre azalan (liderler)", "Yoruma göre artan (az hizmet verilen)"], key="order",
                     horizontal=True)
limit = o2.selectbox("Gösterilecek satır", [500, 2_000, 10_000], index=1)
res = table(fkey, "DESC" if order_lbl.startswith("Yoruma göre azalan") else "ASC", limit)
st.dataframe(res, column_config=fmt, hide_index=True, width="stretch", height=600)
shown = min(limit, int(s["n"]))
st.caption(f"{int(s['n']):,} eşleşmenin {shown:,} tanesi gösteriliyor. Sütun başlıklarına tıklayarak da sıralayabilirsiniz.")
st.download_button("Gösterilen satırları CSV indir", res.to_csv(index=False).encode("utf-8"),
                   file_name="firsat_avcisi.csv", mime="text/csv")
