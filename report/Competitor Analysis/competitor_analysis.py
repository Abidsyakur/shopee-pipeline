"""
competitor_analysis.py
Analisis kompetitor seller MSI Gaming di Shopee
dari data warehouse MySQL.

Output:
  - competitor_analysis.html  (laporan visual interaktif)
  - competitor_analysis.xlsx  (data mentah untuk Excel)

Jalankan: python competitor_analysis.py
"""

import mysql.connector
import pandas as pd
import json
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

OUTPUT_HTML  = "competitor_analysis.html"
OUTPUT_EXCEL = "competitor_analysis.xlsx"


# =====================================
# KONEKSI & QUERY
# =====================================

def get_conn():
    return mysql.connector.connect(**MYSQL_CONFIG)


def query_to_df(conn, sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, conn)


# =====================================
# ANALISIS
# =====================================

def analyze(conn) -> dict:
    results = {}

    # ── 1. Top 10 toko paling banyak produk ─────────────
    results["top_sellers"] = query_to_df(conn, """
        SELECT
            s.shop_ref_id                       AS shop_id,
            s.shop_location                     AS lokasi,
            COUNT(*)                            AS jumlah_produk,
            ROUND(MIN(f.price), 0)              AS harga_min,
            ROUND(MAX(f.price), 0)              AS harga_max,
            ROUND(AVG(f.price), 0)              AS harga_avg
        FROM fact_sales f
        JOIN dim_shop s ON f.shop_id = s.shop_id
        WHERE f.price > 0
        GROUP BY s.shop_ref_id, s.shop_location
        ORDER BY jumlah_produk DESC
        LIMIT 10
    """)

    # ── 2. Distribusi harga per kota ────────────────────
    results["price_by_city"] = query_to_df(conn, """
        SELECT
            COALESCE(NULLIF(s.shop_location, ''), 'Tidak Diketahui') AS kota,
            COUNT(*)                  AS jumlah_produk,
            ROUND(MIN(f.price), 0)    AS harga_min,
            ROUND(MAX(f.price), 0)    AS harga_max,
            ROUND(AVG(f.price), 0)    AS harga_avg
        FROM fact_sales f
        JOIN dim_shop s ON f.shop_id = s.shop_id
        WHERE f.price > 0
        GROUP BY kota
        ORDER BY jumlah_produk DESC
        LIMIT 15
    """)

    # ── 3. Produk sama dijual oleh banyak seller ─────────
    results["multi_seller_products"] = query_to_df(conn, """
        SELECT
            p.name                          AS nama_produk,
            COUNT(DISTINCT f.shop_id)       AS jumlah_seller,
            ROUND(MIN(f.price), 0)          AS harga_terendah,
            ROUND(MAX(f.price), 0)          AS harga_tertinggi,
            ROUND(MAX(f.price) - MIN(f.price), 0) AS selisih_harga,
            ROUND(
                (MAX(f.price) - MIN(f.price))
                / NULLIF(MIN(f.price), 0) * 100, 1
            )                               AS selisih_pct
        FROM fact_sales f
        JOIN dim_product p ON f.product_id = p.product_id
        WHERE f.price > 0
        GROUP BY p.product_id, p.name
        HAVING jumlah_seller > 1
        ORDER BY selisih_pct DESC
        LIMIT 15
    """)

    # ── 4. Rangkuman keseluruhan ─────────────────────────
    results["summary"] = query_to_df(conn, """
        SELECT
            COUNT(DISTINCT f.shop_id)       AS total_seller,
            COUNT(DISTINCT f.product_id)    AS total_produk,
            COUNT(DISTINCT s.shop_location) AS total_kota,
            ROUND(MIN(f.price), 0)          AS harga_termurah,
            ROUND(MAX(f.price), 0)          AS harga_termahal,
            ROUND(AVG(f.price), 0)          AS harga_rata_rata,
            ROUND(
                SUM(CASE WHEN f.rating IS NOT NULL THEN 1 ELSE 0 END)
                * 100.0 / COUNT(*), 1
            )                               AS pct_punya_rating
        FROM fact_sales f
        JOIN dim_shop s ON f.shop_id = s.shop_id
        WHERE f.price > 0
    """)

    # ── 5. Top 10 produk termurah ────────────────────────
    results["cheapest"] = query_to_df(conn, """
        SELECT
            p.name                      AS nama_produk,
            s.shop_location             AS lokasi,
            ROUND(f.price, 0)           AS harga,
            f.rating                    AS rating,
            p.link                      AS link
        FROM fact_sales f
        JOIN dim_product p ON f.product_id = p.product_id
        JOIN dim_shop    s ON f.shop_id    = s.shop_id
        WHERE f.price > 0
        ORDER BY f.price ASC
        LIMIT 10
    """)

    # ── 6. Top 10 produk termahal ────────────────────────
    results["expensive"] = query_to_df(conn, """
        SELECT
            p.name                      AS nama_produk,
            s.shop_location             AS lokasi,
            ROUND(f.price, 0)           AS harga,
            f.rating                    AS rating,
            p.link                      AS link
        FROM fact_sales f
        JOIN dim_product p ON f.product_id = p.product_id
        JOIN dim_shop    s ON f.shop_id    = s.shop_id
        WHERE f.price > 0
        ORDER BY f.price DESC
        LIMIT 10
    """)

    return results


# =====================================
# EXPORT EXCEL
# =====================================

def export_excel(results: dict):
    with pd.ExcelWriter(OUTPUT_EXCEL, engine="openpyxl") as writer:
        results["summary"].to_excel(writer, sheet_name="Rangkuman", index=False)
        results["top_sellers"].to_excel(writer, sheet_name="Top Seller", index=False)
        results["price_by_city"].to_excel(writer, sheet_name="Harga per Kota", index=False)
        results["multi_seller_products"].to_excel(writer, sheet_name="Produk Multi Seller", index=False)
        results["cheapest"].to_excel(writer, sheet_name="Termurah", index=False)
        results["expensive"].to_excel(writer, sheet_name="Termahal", index=False)
    print(f"💾 Excel tersimpan: {OUTPUT_EXCEL}")


# =====================================
# EXPORT HTML REPORT
# =====================================

def df_to_html_table(df: pd.DataFrame, max_rows=15) -> str:
    df = df.head(max_rows)
    rows = ""
    for _, row in df.iterrows():
        cells = ""
        for val in row:
            if isinstance(val, float):
                val = f"{val:,.0f}" if val > 100 else f"{val:.1f}"
            cells += f"<td>{val}</td>"
        rows += f"<tr>{cells}</tr>"
    headers = "".join(f"<th>{col}</th>" for col in df.columns)
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>"


def export_html(results: dict):
    summary = results["summary"].iloc[0]
    scrape_date = datetime.now().strftime("%d %B %Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Competitor Analysis — MSI Gaming Shopee</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', sans-serif; background: #f4f6f9; color: #333; }}
  header {{ background: #c0392b; color: white; padding: 24px 32px; }}
  header h1 {{ font-size: 24px; margin-bottom: 4px; }}
  header p  {{ font-size: 13px; opacity: 0.85; }}
  .container {{ max-width: 1100px; margin: 24px auto; padding: 0 24px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .card {{ background: white; border-radius: 10px; padding: 20px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
  .card .val {{ font-size: 28px; font-weight: 700; color: #c0392b; margin-bottom: 4px; }}
  .card .lbl {{ font-size: 12px; color: #888; }}
  section {{ background: white; border-radius: 10px; padding: 24px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
  section h2 {{ font-size: 16px; margin-bottom: 16px; color: #c0392b; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #c0392b; color: white; padding: 10px 12px; text-align: left; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid #f0f0f0; }}
  tr:hover td {{ background: #fff5f5; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  tr:nth-child(even):hover td {{ background: #fff5f5; }}
  .badge {{ background: #c0392b; color: white; border-radius: 12px; padding: 2px 10px; font-size: 11px; }}
  footer {{ text-align: center; padding: 24px; color: #aaa; font-size: 12px; }}
</style>
</head>
<body>

<header>
  <h1>🎮 Competitor Analysis — MSI Gaming di Shopee</h1>
  <p>Data diambil dari MySQL Data Warehouse | Dianalisis: {scrape_date}</p>
</header>

<div class="container">

  <!-- SUMMARY CARDS -->
  <div class="cards">
    <div class="card">
      <div class="val">{int(summary['total_seller']):,}</div>
      <div class="lbl">Total Seller</div>
    </div>
    <div class="card">
      <div class="val">{int(summary['total_produk']):,}</div>
      <div class="lbl">Total Produk</div>
    </div>
    <div class="card">
      <div class="val">{int(summary['total_kota']):,}</div>
      <div class="lbl">Kota</div>
    </div>
    <div class="card">
      <div class="val">Rp {int(summary['harga_termurah']):,}</div>
      <div class="lbl">Harga Termurah</div>
    </div>
    <div class="card">
      <div class="val">Rp {int(summary['harga_rata_rata']):,}</div>
      <div class="lbl">Rata-rata Harga</div>
    </div>
    <div class="card">
      <div class="val">Rp {int(summary['harga_termahal']):,}</div>
      <div class="lbl">Harga Termahal</div>
    </div>
  </div>

  <!-- TOP SELLERS -->
  <section>
    <h2>🏆 Top 10 Seller Terbanyak Produk MSI Gaming</h2>
    {df_to_html_table(results["top_sellers"])}
  </section>

  <!-- HARGA PER KOTA -->
  <section>
    <h2>🗺️ Distribusi Harga per Kota</h2>
    {df_to_html_table(results["price_by_city"])}
  </section>

  <!-- MULTI SELLER -->
  <section>
    <h2>⚔️ Produk yang Dijual Banyak Seller (Selisih Harga Terbesar)</h2>
    <p style="font-size:12px;color:#888;margin-bottom:12px;">
      Produk yang sama dijual oleh lebih dari 1 seller — cocok untuk cek siapa yang paling kompetitif.
    </p>
    {df_to_html_table(results["multi_seller_products"])}
  </section>

  <!-- TERMURAH -->
  <section>
    <h2>💚 Top 10 Produk Termurah</h2>
    {df_to_html_table(results["cheapest"].drop(columns=["link"], errors="ignore"))}
  </section>

  <!-- TERMAHAL -->
  <section>
    <h2>💎 Top 10 Produk Termahal</h2>
    {df_to_html_table(results["expensive"].drop(columns=["link"], errors="ignore"))}
  </section>

</div>

<footer>
  Data Warehouse: shopee_dw | Tabel: fact_sales + dim_* | Pipeline: MongoDB → MySQL
</footer>

</body>
</html>"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"🌐 HTML Report tersimpan: {OUTPUT_HTML}")


# =====================================
# MAIN
# =====================================

if __name__ == "__main__":
    print("=" * 55)
    print("📊 Competitor Analysis — MSI Gaming Shopee")
    print("=" * 55)

    conn = get_conn()

    try:
        print("⚙️  Menjalankan query analisis...")
        results = analyze(conn)

        # Print ringkasan ke terminal
        s = results["summary"].iloc[0]
        print(f"\n{'=' * 55}")
        print(f"📌 RINGKASAN")
        print(f"{'=' * 55}")
        print(f"   Total Seller   : {int(s['total_seller']):>6}")
        print(f"   Total Produk   : {int(s['total_produk']):>6}")
        print(f"   Total Kota     : {int(s['total_kota']):>6}")
        print(f"   Harga Termurah : Rp {int(s['harga_termurah']):>12,}")
        print(f"   Harga Rata2    : Rp {int(s['harga_rata_rata']):>12,}")
        print(f"   Harga Termahal : Rp {int(s['harga_termahal']):>12,}")

        print(f"\n🏆 Top 5 Seller:")
        for _, row in results["top_sellers"].head(5).iterrows():
            print(f"   Shop {row['shop_id'][:10]:<12} | {str(row['lokasi']):<20} | {int(row['jumlah_produk'])} produk | avg Rp {int(row['harga_avg']):,}")

        print(f"\n⚔️  Top 5 Produk Multi-Seller (selisih terbesar):")
        for _, row in results["multi_seller_products"].head(5).iterrows():
            print(f"   {str(row['nama_produk'])[:50]:<50} | {int(row['jumlah_seller'])} seller | selisih {row['selisih_pct']}%")

        # Export
        print()
        export_excel(results)
        export_html(results)

        print(f"\n✅ Analisis selesai!")
        print(f"   Buka {OUTPUT_HTML} di browser untuk laporan visual.")

    finally:
        conn.close()