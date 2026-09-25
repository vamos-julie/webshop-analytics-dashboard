import altair as alt
import streamlit as st

from app_core import (
    filter_params,
    get_connection,
    render_sidebar_filters,
    sales_filter_sql,
)


st.set_page_config(page_title="Size and Color", layout="wide")
st.title("Size and Color Demand")
st.caption(
    "Sales are analyzed at article-variant level. This keeps size and color "
    "attached to the exact item that was purchased."
)

conn = get_connection()
filters = render_sidebar_filters(conn, "variant")

variant_sql = f"""
    SELECT
        p.category::text AS category,
        si.size,
        col.name AS color,
        SUM(op.amount) AS units_sold,
        COUNT(DISTINCT o.id) AS orders,
        ROUND(SUM(op.amount * op.price::numeric), 2) AS revenue
    FROM webshop."order" AS o
    JOIN webshop.order_positions AS op ON op.orderid = o.id
    JOIN webshop.articles AS a ON a.id = op.articleid
    JOIN webshop.products AS p ON p.id = a.productid
    JOIN webshop.labels AS l ON l.id = p.labelid
    JOIN webshop.sizes AS si ON si.id = a.size
    JOIN webshop.colors AS col ON col.id = a.colorid
    WHERE {sales_filter_sql()}
    GROUP BY p.category, si.size, col.name
    ORDER BY units_sold DESC, p.category, si.size, col.name
"""

df_variants = conn.query(
    variant_sql,
    params=filter_params(filters),
    ttl=0,
)

if df_variants.empty:
    st.warning("No purchases match the selected filters.")
    st.stop()

size_summary = (
    df_variants.groupby(["category", "size"], as_index=False)
    .agg(units_sold=("units_sold", "sum"), revenue=("revenue", "sum"))
)
color_summary = (
    df_variants.groupby(["category", "color"], as_index=False)
    .agg(units_sold=("units_sold", "sum"), revenue=("revenue", "sum"))
    .sort_values("units_sold", ascending=False)
)

top_size = size_summary.sort_values("units_sold", ascending=False).iloc[0]
top_color = color_summary.sort_values("units_sold", ascending=False).iloc[0]

kpi_units, kpi_size, kpi_color = st.columns(3)
kpi_units.metric("Units analyzed", f"{int(df_variants['units_sold'].sum()):,}")
kpi_size.metric(
    "Largest category-size combination",
    f"{top_size['category']} / {top_size['size']}",
    delta=f"{int(top_size['units_sold']):,} units",
    delta_color="off",
)
kpi_color.metric(
    "Largest category-color combination",
    f"{top_color['category']} / {top_color['color']}",
    delta=f"{int(top_color['units_sold']):,} units",
    delta_color="off",
)

size_tab, color_tab = st.tabs(["Sizes", "Colors"])

with size_tab:
    size_heatmap = (
        alt.Chart(size_summary)
        .mark_rect()
        .encode(
            x=alt.X("size:N", title="Size", sort="ascending"),
            y=alt.Y("category:N", title="Category", sort="ascending"),
            color=alt.Color("units_sold:Q", title="Units sold", scale=alt.Scale(scheme="blues")),
            tooltip=[
                alt.Tooltip("category:N", title="Category"),
                alt.Tooltip("size:N", title="Size"),
                alt.Tooltip("units_sold:Q", title="Units sold", format=","),
                alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
            ],
        )
        .properties(height=520, title="Units sold by category and size")
    )
    st.altair_chart(size_heatmap, use_container_width=True)
    st.dataframe(
        size_summary.sort_values("units_sold", ascending=False),
        hide_index=True,
        use_container_width=True,
    )

with color_tab:
    top_color_combinations = color_summary.head(30).copy()
    top_color_combinations["category_color"] = (
        top_color_combinations["category"] + " / " + top_color_combinations["color"]
    )
    color_chart = (
        alt.Chart(top_color_combinations)
        .mark_bar()
        .encode(
            x=alt.X("units_sold:Q", title="Units sold"),
            y=alt.Y("category_color:N", title=None, sort="-x"),
            color=alt.Color("category:N", title="Category"),
            tooltip=[
                alt.Tooltip("category:N", title="Category"),
                alt.Tooltip("color:N", title="Color"),
                alt.Tooltip("units_sold:Q", title="Units sold", format=","),
                alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
            ],
        )
        .properties(height=720, title="Top 30 category-color combinations")
    )
    st.altair_chart(color_chart, use_container_width=True)
    st.dataframe(color_summary, hide_index=True, use_container_width=True)

st.info(
    "These are observed sales, not pure customer demand: a size or color may have "
    "low sales because it was unavailable. Combine this page with the inventory "
    "page before making assortment decisions."
)

with st.expander("See SQL"):
    st.code(variant_sql, language="sql")
