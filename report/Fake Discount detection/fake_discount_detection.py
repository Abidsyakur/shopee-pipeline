"""
fake_discount_detection.py
Deteksi potensi fake discount pada produk MSI Gaming di Shopee.

Metode deteksi:
  1. Outlier harga — seller yang harganya jauh di atas median pasar
  2. Price gap antar seller — produk sama tapi harga beda drastis
  3. Suspicious markup — harga sebelum diskon vs sesudah tidak masuk akal

Output:
  - fake_discount_report.html
  - fake_discount_report.xlsx

Jalankan: python fake_discount_detection.py
"""

import mysql.connector
import pandas as pd
import numpy as np
from datetime import datetime

# =====================================
# CONFIG
# =====================================

MYSQL_CONFIG = {
    "host":     "localhost",
    "port":     3306,
    "user":     "dwuser",
    "password": "dwpassword",
    "database": "shopee_dw",
}

# Threshold deteksi
OUTLIER_MULTIPLIER  = 2.0   # harga > 2x median = mencurigakan
MIN_PRICE_GAP_PCT   = 30.0  # selisih harga antar seller > 30% = mencurigakan
MIN_SELLERS         = 2     # minimal 2 seller jual produk yang sama

OUTPUT_HTML  = "fake_discount_report.html"
OUTPUT_EXCEL = "fake_discount_report.xlsx"


# =====================================
# KONEKSI
# =====================================

def get_conn():
    return mysql.connector.connect(**MYSQL_CONFIG)


def query_to_df(conn, sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, conn)


# =====================================
# DETEKSI
# =====================================

def detect_price_outliers(conn) -> pd.DataFrame:
    """
    Deteksi seller yang harganya jauh di atas median pasar.
    Indikasi: harga di-markup tinggi sebelum diskon.
    """
    df = query_to_df(conn, """
        SELECT
            p.name          AS nama_produk,
            s.shop_ref_id   AS shop_id,
            s.shop_location AS lokasi,
            f.price         AS harga,
            f.rating        AS rating,
            p.link          AS link
        FROM fact_sales f
        JOIN dim_product p ON f.product_id = p.product_id
        JOIN dim_shop    s ON f.shop_id    = s.shop_id
        WHERE f.price > 0
    """)

    if df.empty:
        return pd.DataFrame()

    # Hitung median dan IQR
    median_price = df["harga"].median()
    Q1 = df["harga"].quantile(0.25)
    Q3 = df["harga"].quantile(0.75)
    IQR = Q3 - Q1
    upper_fence = Q3 + 1.5 * IQR  # batas atas outlier statistik

    # Tambah kolom analisis
    df["median_pasar"]  = median_price
    df["batas_normal"]  = upper_fence
    df["rasio_vs_median"] = (df["harga"] / median_price).round(2)
    df["is_outlier"]    = df["harga"] > upper_fence

    outliers = df[df["is_outlier"]].copy()
    outliers = outliers.sort_values("rasio_vs_median", ascending=False)
    outliers["keterangan"] = outliers["rasio_vs_median"].apply(
        lambda x: f"⚠️ Harga {x:.1f}x lipat dari median pasar"
    )

    return outliers[[
        "nama_produk", "shop_id", "lokasi", "harga",
        "median_pasar", "rasio_vs_median", "keterangan", "link"
    ]]


def detect_price_gap(conn) -> pd.DataFrame:
    """
    Deteksi produk yang sama dijual dengan harga sangat berbeda
    antar seller. Selisih besar = kemungkinan ada yang markup.
    """
    df = query_to_df(conn, """
        SELECT
            p.name                                          AS nama_produk,
            COUNT(DISTINCT f.shop_id)                       AS jumlah_seller,
            ROUND(MIN(f.price), 0)                          AS harga_min,
            ROUND(MAX(f.price), 0)                          AS harga_max,
            ROUND(AVG(f.price), 0)                          AS harga_avg,
            ROUND(MAX(f.price) - MIN(f.price), 0)           AS selisih_harga,
            ROUND(
                (MAX(f.price) - MIN(f.price))
                / NULLIF(MIN(f.price), 0) * 100, 1
            )                                               AS selisih_pct,
            GROUP_CONCAT(DISTINCT s.shop_location
                ORDER BY f.price ASC SEPARATOR ' | ')       AS lokasi_seller
        FROM fact_sales f
        JOIN dim_product p ON f.product_id = p.product_id
        JOIN dim_shop    s ON f.shop_id    = s.shop_id
        WHERE f.price > 0
        GROUP BY p.product_id, p.name
        HAVING jumlah_seller >= {min_sellers}
            AND selisih_pct  >= {min_gap}
        ORDER BY selisih_pct DESC
        LIMIT 20
    """.format(min_sellers=MIN_SELLERS, min_gap=MIN_PRICE_GAP_PCT))

    if df.empty:
        return pd.DataFrame()

    df["keterangan"] = df["selisih_pct"].apply(
        lambda x: (
            "🚨 Sangat mencurigakan" if x >= 100
            else "⚠️ Mencurigakan" if x >= 50
            else "📌 Perlu diperhatikan"
        )
    )

    return df


def detect_suspicious_markup(conn) -> pd.DataFrame:
    """
    Deteksi produk dengan harga jauh di atas rata-rata
    kategori harga yang sama — kemungkinan sengaja di-markup
    untuk kemudian didiskon.
    """
    df = query_to_df(conn, """
        SELECT
            p.name          AS nama_produk,
            s.shop_location AS lokasi,
            f.price         AS harga,
            f.rating        AS rating,
            p.link          AS link,
            -- Hitung z-score sederhana dari semua produk
            (f.price - AVG(f.price) OVER()) /
            NULLIF(STDDEV(f.price) OVER(), 0) AS z_score
        FROM fact_sales f
        JOIN dim_product p ON f.product_id = p.product_id
        JOIN dim_shop    s ON f.shop_id    = s.shop_id
        WHERE f.price > 0
        ORDER BY z_score DESC
        LIMIT 20
    """)

    if df.empty:
        return pd.DataFrame()

    # Filter yang z-score tinggi (jauh dari rata-rata)
    df = df[df["z_score"] > 1.5].copy()
    df["z_score"] = df["z_score"].round(2)
    df["keterangan"] = df["z_score"].apply(
        lambda z: (
            "🚨 Ekstrem — kemungkinan markup" if z > 3
            else "⚠️ Tinggi — perlu dicek" if z > 2
            else "📌 Di atas rata-rata"
        )
    )

    return df[[
        "nama_produk", "lokasi", "harga", "z_score", "keterangan", "link"
    ]]


def get_price_distribution(conn) -> pd.DataFrame:
    """Distribusi harga dalam range untuk visualisasi."""
    return query_to_df(conn, """
        SELECT
            CASE
                WHEN price < 1000000    THEN 'Di bawah 1 juta'
                WHEN price < 5000000    THEN '1 - 5 juta'
                WHEN price < 10000000   THEN '5 - 10 juta'
                WHEN price < 20000000   THEN '10 - 20 juta'
                WHEN price < 50000000   THEN '20 - 50 juta'
                ELSE 'Di atas 50 juta'
            END AS range_harga,
            COUNT(*) AS jumlah_produk,
            ROUND(AVG(price), 0) AS avg_harga
        FROM fact_sales
        WHERE price > 0
        GROUP BY range_harga
        ORDER BY MIN(price)
    """)


# =====================================
# SUMMARY STATISTIK
# =====================================

def get_summary_stats(conn) -> dict:
    df = query_to_df(conn, """
        SELECT price FROM fact_sales WHERE price > 0
    """)
    prices = df["price"]
    return {
        "total":    len(prices),
        "mean":     prices.mean(),
        "median":   prices.median(),
        "std":      prices.std(),
        "min":      prices.min(),
        "max":      prices.max(),
        "Q1":       prices.quantile(0.25),
        "Q3":       prices.quantile(0.75),
        "IQR":      prices.quantile(0.75) - prices.quantile(0.25),
    }


# =====================================
# EXPORT EXCEL
# =====================================

def export_excel(results: dict):
    with pd.ExcelWriter(OUTPUT_EXCEL, engine="openpyxl") as writer:
        for sheet_name, df in results.items():
            if not df.empty:
                df_export = df.drop(columns=["link"], errors="ignore")
                df_export.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    print(f"💾 Excel: {OUTPUT_EXCEL}")


# =====================================
# EXPORT HTML
# =====================================

def df_to_table(df: pd.DataFrame, max_rows=20) -> str:
    if df.empty:
        return "<p style='color:#888;'>Tidak ada data mencurigakan ditemukan ✅</p>"
    df = df.head(max_rows).copy()
    # Format harga
    for col in ["harga", "harga_min", "harga_max", "harga_avg",
                "selisih_harga", "median_pasar", "batas_normal"]:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: f"Rp {int(x):,}" if pd.notna(x) and x > 0 else "-"
            )
    headers = "".join(f"<th>{c}</th>" for c in df.columns if c != "link")
    rows = ""
    for _, row in df.iterrows():
        cells = ""
        for col in df.columns:
            if col == "link":
                continue
            val = row[col]
            cells += f"<td>{val}</td>"
        rows += f"<tr>{cells}</tr>"
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"


def export_html(results: dict, stats: dict, dist_df: pd.DataFrame):
    date_str = datetime.now().strftime("%d %B %Y %H:%M")

    # Buat bar chart distribusi harga sederhana
    dist_bars = ""
    if not dist_df.empty:
        max_count = dist_df["jumlah_produk"].max()
        for _, row in dist_df.iterrows():
            pct = int(row["jumlah_produk"] / max_count * 100)
            dist_bars += f"""
            <div class="bar-row">
              <span class="bar-label">{row['range_harga']}</span>
              <div class="bar-wrap">
                <div class="bar" style="width:{pct}%"></div>
                <span class="bar-val">{int(row['jumlah_produk'])} produk</span>
              </div>
            </div>"""

    outlier_count   = len(results.get("Price Outlier", pd.DataFrame()))
    price_gap_count = len(results.get("Price Gap", pd.DataFrame()))
    markup_count    = len(results.get("Suspicious Markup", pd.DataFrame()))

    html = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Fake Discount Detection — MSI Gaming Shopee</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Segoe UI',sans-serif; background:#f4f6f9; color:#333; }}
  header {{ background:#1a1a2e; color:white; padding:24px 32px; }}
  header h1 {{ font-size:22px; margin-bottom:4px; }}
  header p {{ font-size:13px; opacity:.8; }}
  .container {{ max-width:1100px; margin:24px auto; padding:0 24px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:16px; margin-bottom:28px; }}
  .card {{ background:white; border-radius:10px; padding:18px; text-align:center; box-shadow:0 2px 8px rgba(0,0,0,.08); }}
  .card .val {{ font-size:26px; font-weight:700; color:#e74c3c; margin-bottom:4px; }}
  .card .lbl {{ font-size:12px; color:#888; }}
  section {{ background:white; border-radius:10px; padding:24px; margin-bottom:24px; box-shadow:0 2px 8px rgba(0,0,0,.08); }}
  section h2 {{ font-size:15px; margin-bottom:6px; color:#1a1a2e; border-bottom:2px solid #f0f0f0; padding-bottom:10px; }}
  section p.desc {{ font-size:12px; color:#888; margin-bottom:14px; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th {{ background:#1a1a2e; color:white; padding:9px 10px; text-align:left; }}
  td {{ padding:8px 10px; border-bottom:1px solid #f0f0f0; vertical-align:top; }}
  tr:hover td {{ background:#fef9f9; }}
  .bar-row {{ display:flex; align-items:center; margin-bottom:10px; gap:12px; }}
  .bar-label {{ min-width:160px; font-size:12px; color:#555; }}
  .bar-wrap {{ flex:1; display:flex; align-items:center; gap:8px; }}
  .bar {{ height:20px; background:#e74c3c; border-radius:4px; min-width:4px; transition:width .3s; }}
  .bar-val {{ font-size:12px; color:#888; white-space:nowrap; }}
  .stat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }}
  .stat {{ background:#f8f9fa; border-radius:8px; padding:12px; text-align:center; }}
  .stat .sv {{ font-size:18px; font-weight:700; color:#1a1a2e; }}
  .stat .sl {{ font-size:11px; color:#888; margin-top:2px; }}
  footer {{ text-align:center; padding:24px; color:#aaa; font-size:12px; }}
</style>
</head>
<body>

<header>
  <h1>🔍 Fake Discount Detection — MSI Gaming di Shopee</h1>
  <p>Analisis kecurigaan harga | Dianalisis: {date_str}</p>
</header>

<div class="container">

  <!-- SUMMARY CARDS -->
  <div class="cards">
    <div class="card">
      <div class="val">{int(stats['total']):,}</div>
      <div class="lbl">Total Produk</div>
    </div>
    <div class="card">
      <div class="val" style="color:#e67e22;">{outlier_count}</div>
      <div class="lbl">Price Outlier</div>
    </div>
    <div class="card">
      <div class="val" style="color:#e74c3c;">{price_gap_count}</div>
      <div class="lbl">Price Gap Mencurigakan</div>
    </div>
    <div class="card">
      <div class="val" style="color:#8e44ad;">{markup_count}</div>
      <div class="lbl">Suspicious Markup</div>
    </div>
    <div class="card">
      <div class="val">Rp {int(stats['median']):,}</div>
      <div class="lbl">Median Harga Pasar</div>
    </div>
  </div>

  <!-- STATISTIK HARGA -->
  <section>
    <h2>📊 Statistik Harga Pasar</h2>
    <div class="stat-grid" style="margin-top:12px;">
      <div class="stat"><div class="sv">Rp {int(stats['min']):,}</div><div class="sl">Minimum</div></div>
      <div class="stat"><div class="sv">Rp {int(stats['Q1']):,}</div><div class="sl">Q1 (25%)</div></div>
      <div class="stat"><div class="sv">Rp {int(stats['median']):,}</div><div class="sl">Median</div></div>
      <div class="stat"><div class="sv">Rp {int(stats['mean']):,}</div><div class="sl">Rata-rata</div></div>
      <div class="stat"><div class="sv">Rp {int(stats['Q3']):,}</div><div class="sl">Q3 (75%)</div></div>
      <div class="stat"><div class="sv">Rp {int(stats['max']):,}</div><div class="sl">Maximum</div></div>
    </div>
  </section>

  <!-- DISTRIBUSI HARGA -->
  <section>
    <h2>📈 Distribusi Harga</h2>
    <p class="desc">Berapa banyak produk di masing-masing range harga.</p>
    <div style="margin-top:8px;">{dist_bars}</div>
  </section>

  <!-- PRICE OUTLIER -->
  <section>
    <h2>⚠️ Price Outlier — Harga Jauh di Atas Batas Normal</h2>
    <p class="desc">
      Produk dengan harga di atas batas statistik (Q3 + 1.5×IQR = Rp {int(stats['Q3'] + 1.5*stats['IQR']):,}).
      Seller ini kemungkinan sengaja pasang harga tinggi sebelum diskon.
    </p>
    {df_to_table(results.get("Price Outlier", pd.DataFrame()))}
  </section>

  <!-- PRICE GAP -->
  <section>
    <h2>⚔️ Price Gap — Produk Sama, Harga Beda Drastis</h2>
    <p class="desc">
      Produk identik yang dijual lebih dari 1 seller dengan selisih harga &gt; {MIN_PRICE_GAP_PCT:.0f}%.
      Seller dengan harga tertinggi patut dicurigai melakukan markup.
    </p>
    {df_to_table(results.get("Price Gap", pd.DataFrame()))}
  </section>

  <!-- SUSPICIOUS MARKUP -->
  <section>
    <h2>🚨 Suspicious Markup — Z-Score Tinggi</h2>
    <p class="desc">
      Produk dengan z-score &gt; 1.5 artinya harganya jauh dari rata-rata secara statistik.
      Z-score &gt; 3 = ekstrem, sangat mencurigakan.
    </p>
    {df_to_table(results.get("Suspicious Markup", pd.DataFrame()))}
  </section>

</div>

<footer>
  Analisis berbasis data warehouse shopee_dw | Metode: IQR Outlier + Price Gap + Z-Score
</footer>

</body>
</html>"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"🌐 HTML: {OUTPUT_HTML}")


# =====================================
# MAIN
# =====================================

if __name__ == "__main__":
    print("=" * 55)
    print("🔍 Fake Discount Detection — MSI Gaming Shopee")
    print("=" * 55)

    conn = get_conn()

    try:
        print("\n⚙️  Menjalankan deteksi...")

        stats    = get_summary_stats(conn)
        dist_df  = get_price_distribution(conn)
        outliers = detect_price_outliers(conn)
        gap_df   = detect_price_gap(conn)
        markup   = detect_suspicious_markup(conn)

        results = {
            "Price Outlier":     outliers,
            "Price Gap":         gap_df,
            "Suspicious Markup": markup,
        }

        # Print ke terminal
        print(f"\n{'=' * 55}")
        print(f"📌 HASIL DETEKSI")
        print(f"{'=' * 55}")
        print(f"   Median harga pasar : Rp {int(stats['median']):,}")
        print(f"   Batas normal (IQR) : Rp {int(stats['Q3'] + 1.5*stats['IQR']):,}")
        print(f"   Price outlier      : {len(outliers)} produk")
        print(f"   Price gap >30%     : {len(gap_df)} produk")
        print(f"   Suspicious markup  : {len(markup)} produk")

        if not gap_df.empty:
            print(f"\n⚔️  Top 3 Price Gap terbesar:")
            for _, row in gap_df.head(3).iterrows():
                print(
                    f"   {str(row['nama_produk'])[:50]:<50} | "
                    f"{int(row['jumlah_seller'])} seller | "
                    f"selisih {row['selisih_pct']}%"
                )

        if not outliers.empty:
            print(f"\n⚠️  Top 3 Price Outlier:")
            for _, row in outliers.head(3).iterrows():
                print(
                    f"   {str(row['nama_produk'])[:50]:<50} | "
                    f"Rp {int(row['harga']):,} | "
                    f"{row['rasio_vs_median']}x median"
                )

        # Export
        print()
        export_excel(results)
        export_html(results, stats, dist_df)

        print(f"\n✅ Selesai! Buka {OUTPUT_HTML} di browser.")

    finally:
        conn.close()