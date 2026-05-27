
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import mysql.connector
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

st.set_page_config(
    page_title="MSI Gaming Dashboard",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================
# LOAD DATA
# =====================================

@st.cache_data(ttl=300)  # cache 5 menit
def load_data():
    conn = mysql.connector.connect(**MYSQL_CONFIG)

    # Fact + dimensions join
    df_main = pd.read_sql("""
        SELECT
            f.fact_id,
            f.price,
            f.price_raw,
            f.rating,
            f.page,
            f.scraped_at,
            p.name          AS product_name,
            p.link          AS product_link,
            p.item_id,
            s.shop_ref_id   AS shop_id,
            s.shop_location AS lokasi,
            d.full_date     AS tanggal,
            d.year,
            d.month,
            d.day,
            c.keyword
        FROM fact_sales f
        JOIN dim_product  p ON f.product_id  = p.product_id
        JOIN dim_shop     s ON f.shop_id     = s.shop_id
        JOIN dim_date     d ON f.date_id     = d.date_id
        JOIN dim_category c ON f.category_id = c.category_id
        WHERE f.price > 0
    """, conn)

    # Summary stats
    df_stats = pd.read_sql("""
        SELECT
            COUNT(DISTINCT f.shop_id)    AS total_seller,
            COUNT(DISTINCT f.product_id) AS total_produk,
            COUNT(DISTINCT s.shop_location) AS total_kota,
            MIN(f.price)   AS harga_min,
            MAX(f.price)   AS harga_max,
            AVG(f.price)   AS harga_avg,
            COUNT(*)       AS total_data
        FROM fact_sales f
        JOIN dim_shop s ON f.shop_id = s.shop_id
        WHERE f.price > 0
    """, conn)

    conn.close()
    return df_main, df_stats


# =====================================
# MAIN APP
# =====================================

# Header
st.title("🎮 MSI Gaming — Shopee Dashboard")
st.caption(f"Data dari Shopee | Terakhir diperbarui: {datetime.now().strftime('%d %B %Y %H:%M')}")
st.divider()

# Load data
with st.spinner("Memuat data dari MySQL..."):
    try:
        df, df_stats = load_data()
        stats = df_stats.iloc[0]
    except Exception as e:
        st.error(f"Gagal konek ke MySQL: {e}")
        st.info("Pastikan Docker sudah jalan dan MySQL container aktif.")
        st.stop()

# =====================================
# SIDEBAR FILTER
# =====================================

st.sidebar.header("🔧 Filter")

# Filter lokasi
all_lokasi = ["Semua"] + sorted(df["lokasi"].dropna().unique().tolist())
selected_lokasi = st.sidebar.selectbox("Kota/Lokasi", all_lokasi)

# Filter harga
min_price = int(df["price"].min())
max_price = int(df["price"].max())
price_range = st.sidebar.slider(
    "Range Harga (Rp)",
    min_value=min_price,
    max_value=max_price,
    value=(min_price, max_price),
    format="Rp %d"
)

# Filter rating
show_rated = st.sidebar.checkbox("Hanya yang punya rating", value=False)

# Apply filters
df_filtered = df.copy()
if selected_lokasi != "Semua":
    df_filtered = df_filtered[df_filtered["lokasi"] == selected_lokasi]
df_filtered = df_filtered[
    (df_filtered["price"] >= price_range[0]) &
    (df_filtered["price"] <= price_range[1])
]
if show_rated:
    df_filtered = df_filtered[df_filtered["rating"].notna()]

st.sidebar.divider()
st.sidebar.metric("Data setelah filter", f"{len(df_filtered):,} produk")

# =====================================
# SUMMARY CARDS
# =====================================

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Total Seller", f"{int(stats['total_seller']):,}")
with col2:
    st.metric("Total Produk", f"{int(stats['total_produk']):,}")
with col3:
    st.metric("Kota", f"{int(stats['total_kota']):,}")
with col4:
    st.metric(
        "Harga Termurah",
        f"Rp {int(stats['harga_min']):,}"
    )
with col5:
    st.metric(
        "Rata-rata Harga",
        f"Rp {int(stats['harga_avg']):,}"
    )

st.divider()

# =====================================
# ROW 1: Distribusi harga & Top kota
# =====================================

col_left, col_right = st.columns([3, 2])

with col_left:
    st.subheader("📊 Distribusi Harga")
    fig_hist = px.histogram(
        df_filtered,
        x="price",
        nbins=30,
        labels={"price": "Harga (Rp)", "count": "Jumlah Produk"},
        color_discrete_sequence=["#1D9E75"],
    )
    fig_hist.update_layout(
        bargap=0.1,
        xaxis_tickformat=",.0f",
        showlegend=False,
        margin=dict(t=20, b=20),
        height=300,
    )
    fig_hist.add_vline(
        x=df_filtered["price"].median(),
        line_dash="dash",
        line_color="#D85A30",
        annotation_text=f"Median: Rp {int(df_filtered['price'].median()):,}",
        annotation_position="top right",
    )
    st.plotly_chart(fig_hist, use_container_width=True)

with col_right:
    st.subheader("🗺️ Top 10 Kota")
    top_kota = (
        df_filtered[df_filtered["lokasi"].notna()]
        .groupby("lokasi")
        .size()
        .reset_index(name="jumlah")
        .sort_values("jumlah", ascending=True)
        .tail(10)
    )
    fig_kota = px.bar(
        top_kota,
        x="jumlah",
        y="lokasi",
        orientation="h",
        labels={"jumlah": "Jumlah Produk", "lokasi": ""},
        color="jumlah",
        color_continuous_scale="Teal",
    )
    fig_kota.update_layout(
        showlegend=False,
        coloraxis_showscale=False,
        margin=dict(t=20, b=20),
        height=300,
    )
    st.plotly_chart(fig_kota, use_container_width=True)

# =====================================
# ROW 2: Box plot harga per kota & Scatter
# =====================================

col_left2, col_right2 = st.columns([2, 3])

with col_left2:
    st.subheader("📦 Sebaran Harga per Kota")
    top5_kota = (
        df_filtered[df_filtered["lokasi"].notna()]
        .groupby("lokasi")
        .size()
        .nlargest(8)
        .index.tolist()
    )
    df_box = df_filtered[df_filtered["lokasi"].isin(top5_kota)]
    fig_box = px.box(
        df_box,
        x="lokasi",
        y="price",
        labels={"price": "Harga (Rp)", "lokasi": ""},
        color="lokasi",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_box.update_layout(
        showlegend=False,
        yaxis_tickformat=",.0f",
        margin=dict(t=20, b=40),
        height=350,
        xaxis_tickangle=-20,
    )
    st.plotly_chart(fig_box, use_container_width=True)

with col_right2:
    st.subheader("⭐ Harga vs Rating")
    df_scatter = df_filtered[df_filtered["rating"].notna()].copy()
    df_scatter["rating_num"] = pd.to_numeric(df_scatter["rating"], errors="coerce")
    df_scatter = df_scatter[df_scatter["rating_num"].notna()]

    if not df_scatter.empty:
        fig_scatter = px.scatter(
            df_scatter,
            x="rating_num",
            y="price",
            color="lokasi",
            hover_data=["product_name", "lokasi"],
            labels={
                "rating_num": "Rating",
                "price": "Harga (Rp)",
                "lokasi": "Kota",
            },
            opacity=0.7,
        )
        fig_scatter.update_layout(
            yaxis_tickformat=",.0f",
            margin=dict(t=20, b=20),
            height=350,
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
    else:
        st.info("Tidak ada data dengan rating untuk filter yang dipilih.")

# =====================================
# ROW 3: Treemap & Price range donut
# =====================================

col_left3, col_right3 = st.columns([3, 2])

with col_left3:
    st.subheader("🌳 Treemap Produk per Kota")
    df_tree = (
        df_filtered[df_filtered["lokasi"].notna()]
        .groupby("lokasi")
        .agg(
            jumlah=("fact_id", "count"),
            avg_price=("price", "mean")
        )
        .reset_index()
    )
    fig_tree = px.treemap(
        df_tree,
        path=["lokasi"],
        values="jumlah",
        color="avg_price",
        color_continuous_scale="RdYlGn_r",
        labels={"avg_price": "Rata-rata Harga"},
        hover_data={"avg_price": ":,.0f"},
    )
    fig_tree.update_layout(margin=dict(t=20, b=20), height=320)
    st.plotly_chart(fig_tree, use_container_width=True)

with col_right3:
    st.subheader("💰 Segmen Harga")
    bins   = [0, 1e6, 5e6, 10e6, 20e6, 50e6, float("inf")]
    labels = ["<1 jt", "1-5 jt", "5-10 jt", "10-20 jt", "20-50 jt", ">50 jt"]
    df_filtered["segmen"] = pd.cut(
        df_filtered["price"], bins=bins, labels=labels
    )
    seg_count = df_filtered["segmen"].value_counts().reset_index()
    seg_count.columns = ["segmen", "jumlah"]

    fig_donut = px.pie(
        seg_count,
        names="segmen",
        values="jumlah",
        hole=0.5,
        color_discrete_sequence=px.colors.sequential.Teal,
    )
    fig_donut.update_layout(
        margin=dict(t=20, b=20),
        height=320,
        legend=dict(orientation="v", x=1, y=0.5),
    )
    st.plotly_chart(fig_donut, use_container_width=True)

# =====================================
# ROW 4: Top & Bottom produk
# =====================================

st.divider()

col_t, col_b = st.columns(2)

with col_t:
    st.subheader("💎 Top 10 Produk Termahal")
    df_top = (
        df_filtered
        .nlargest(10, "price")[["product_name", "lokasi", "price", "rating"]]
        .reset_index(drop=True)
    )
    df_top.index += 1
    df_top["price"] = df_top["price"].apply(lambda x: f"Rp {int(x):,}")
    df_top.columns = ["Nama Produk", "Kota", "Harga", "Rating"]
    df_top["Nama Produk"] = df_top["Nama Produk"].str[:60]
    st.dataframe(df_top, use_container_width=True, height=320)

with col_b:
    st.subheader("💚 Top 10 Produk Termurah")
    df_bot = (
        df_filtered
        .nsmallest(10, "price")[["product_name", "lokasi", "price", "rating"]]
        .reset_index(drop=True)
    )
    df_bot.index += 1
    df_bot["price"] = df_bot["price"].apply(lambda x: f"Rp {int(x):,}")
    df_bot.columns = ["Nama Produk", "Kota", "Harga", "Rating"]
    df_bot["Nama Produk"] = df_bot["Nama Produk"].str[:60]
    st.dataframe(df_bot, use_container_width=True, height=320)

# =====================================
# ROW 5: Raw data table
# =====================================

st.divider()
st.subheader("📋 Data Lengkap")

with st.expander("Klik untuk lihat tabel data"):
    df_show = df_filtered[[
        "product_name", "lokasi", "price", "rating", "tanggal"
    ]].copy()
    df_show["price"] = df_show["price"].apply(lambda x: f"Rp {int(x):,}")
    df_show.columns = ["Nama Produk", "Kota", "Harga", "Rating", "Tanggal"]
    df_show["Nama Produk"] = df_show["Nama Produk"].str[:70]
    st.dataframe(df_show, use_container_width=True, height=400)

    # Download button
    csv = df_filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download CSV",
        data=csv,
        file_name=f"msi_gaming_data_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

st.caption("Data Warehouse: shopee_dw | Pipeline: Shopee → MongoDB → MySQL")