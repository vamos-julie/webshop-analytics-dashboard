import altair as alt
import streamlit as st

from app_core import (
    filter_params,
    get_connection,
    render_sidebar_filters,
    sales_filter_sql,
)


st.set_page_config(page_title="ABC and Inventory", layout="wide")
st.title("ABC Product Analysis and Inventory Priority")
st.caption(
    "Products are ranked by revenue in the selected period. Class A contributes "
    "the first 80% of revenue, B the next 15%, and C the remaining 5%."
)

conn = get_connection()
filters = render_sidebar_filters(conn, "abc")

abc_sql = f"""
    WITH filtered_lines AS (
        SELECT
            p.id AS product_id,
            p.name AS product_name,
            p.category::text AS category,
            o.ordertimestamp::date AS order_date,
            op.amount AS units,
            op.amount * op.price::numeric AS revenue
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
    ),
    analysis_date AS (
        SELECT MAX(order_date) AS last_order_date
        FROM filtered_lines
    ),
    product_sales AS (
        SELECT
            fl.product_id,
            fl.product_name,
            fl.category,
            SUM(fl.units) AS units_sold,
            ROUND(SUM(fl.revenue), 2) AS revenue,
            SUM(fl.units) FILTER (
                WHERE fl.order_date >= ad.last_order_date - 89
            ) AS units_sold_last_90_days
        FROM filtered_lines AS fl
        CROSS JOIN analysis_date AS ad
        GROUP BY fl.product_id, fl.product_name, fl.category
    ),
    current_stock AS (
        SELECT
            a.productid AS product_id,
            SUM(st.count) AS units_in_stock
        FROM webshop.articles AS a
        LEFT JOIN webshop.stock AS st ON st.articleid = a.id
        GROUP BY a.productid
    ),
    revenue_rank AS (
        SELECT
            ps.*,
            SUM(ps.revenue) OVER (
                ORDER BY ps.revenue DESC, ps.product_id
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) / NULLIF(SUM(ps.revenue) OVER (), 0) AS cumulative_revenue_share
        FROM product_sales AS ps
    )
    SELECT
        rr.product_id,
        rr.product_name,
        rr.category,
        rr.units_sold,
        rr.revenue,
        ROUND(100.0 * rr.revenue / NULLIF(SUM(rr.revenue) OVER (), 0), 2)
            AS revenue_share_pct,
        ROUND(100.0 * rr.cumulative_revenue_share, 2)
            AS cumulative_revenue_pct,
        CASE
            WHEN rr.cumulative_revenue_share <= 0.80 THEN 'A'
            WHEN rr.cumulative_revenue_share <= 0.95 THEN 'B'
            ELSE 'C'
        END AS abc_class,
        COALESCE(cs.units_in_stock, 0) AS units_in_stock,
        COALESCE(rr.units_sold_last_90_days, 0) AS units_sold_last_90_days,
        ROUND(
            90.0 * COALESCE(cs.units_in_stock, 0)
            / NULLIF(rr.units_sold_last_90_days, 0),
            1
        ) AS estimated_days_of_stock,
        CASE
            WHEN COALESCE(cs.units_in_stock, 0) <= 0 THEN 'Critical: out of stock'
            WHEN COALESCE(rr.units_sold_last_90_days, 0) = 0 THEN 'No recent sales'
            WHEN 90.0 * COALESCE(cs.units_in_stock, 0)
                / rr.units_sold_last_90_days < 30 THEN 'High: under 30 days'
            WHEN 90.0 * COALESCE(cs.units_in_stock, 0)
                / rr.units_sold_last_90_days < 60 THEN 'Medium: under 60 days'
            ELSE 'Healthy: 60+ days'
        END AS stock_status
    FROM revenue_rank AS rr
    LEFT JOIN current_stock AS cs USING (product_id)
    ORDER BY rr.revenue DESC, rr.product_id
"""

df_abc = conn.query(
    abc_sql,
    params=filter_params(filters),
    ttl=0,
)

variant_stock_sql = f"""
    WITH filtered_lines AS (
        SELECT
            a.id AS article_id,
            a.productid AS product_id,
            o.ordertimestamp::date AS order_date,
            op.amount AS units
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
    ),
    analysis_date AS (
        SELECT MAX(order_date) AS last_order_date
        FROM filtered_lines
    ),
    recent_variant_sales AS (
        SELECT
            fl.article_id,
            fl.product_id,
            SUM(fl.units) AS units_sold_last_90_days
        FROM filtered_lines AS fl
        CROSS JOIN analysis_date AS ad
        WHERE fl.order_date >= ad.last_order_date - 89
        GROUP BY fl.article_id, fl.product_id
    ),
    current_stock AS (
        SELECT articleid AS article_id, SUM(count) AS units_in_stock
        FROM webshop.stock
        GROUP BY articleid
    )
    SELECT
        rvs.article_id,
        rvs.product_id,
        p.name AS product_name,
        p.category::text AS category,
        col.name AS color,
        si.size,
        COALESCE(cs.units_in_stock, 0) AS units_in_stock,
        rvs.units_sold_last_90_days,
        ROUND(
            90.0 * COALESCE(cs.units_in_stock, 0)
            / NULLIF(rvs.units_sold_last_90_days, 0),
            1
        ) AS estimated_days_of_stock,
        CASE
            WHEN COALESCE(cs.units_in_stock, 0) <= 0 THEN 'Critical: out of stock'
            WHEN 90.0 * COALESCE(cs.units_in_stock, 0)
                / rvs.units_sold_last_90_days < 30 THEN 'High: under 30 days'
            WHEN 90.0 * COALESCE(cs.units_in_stock, 0)
                / rvs.units_sold_last_90_days < 60 THEN 'Medium: under 60 days'
            ELSE 'Healthy: 60+ days'
        END AS stock_status
    FROM recent_variant_sales AS rvs
    JOIN webshop.articles AS a ON a.id = rvs.article_id
    JOIN webshop.products AS p ON p.id = rvs.product_id
    JOIN webshop.colors AS col ON col.id = a.colorid
    JOIN webshop.sizes AS si ON si.id = a.size
    LEFT JOIN current_stock AS cs USING (article_id)
    ORDER BY rvs.units_sold_last_90_days DESC, rvs.article_id
"""

df_variant_stock = conn.query(
    variant_stock_sql,
    params=filter_params(filters),
    ttl=0,
)

if df_abc.empty:
    st.warning("No purchases match the selected filters.")
    st.stop()

abc_summary = (
    df_abc.groupby("abc_class", as_index=False)
    .agg(
        products=("product_id", "nunique"),
        revenue=("revenue", "sum"),
        units_sold=("units_sold", "sum"),
        units_in_stock=("units_in_stock", "sum"),
    )
    .sort_values("abc_class")
)

df_variant_stock = df_variant_stock.merge(
    df_abc[["product_id", "abc_class", "revenue"]],
    on="product_id",
    how="left",
)
priority_mask = df_variant_stock["stock_status"].isin(
    ["Critical: out of stock", "High: under 30 days"]
)
priority_variants = df_variant_stock[priority_mask].copy()
priority_a_variants = int(
    ((df_variant_stock["abc_class"] == "A") & priority_mask).sum()
)

kpi_products, kpi_a, kpi_priority, kpi_priority_a = st.columns(4)
kpi_products.metric("Products sold", f"{len(df_abc):,}")
kpi_a.metric("Class A products", f"{int((df_abc['abc_class'] == 'A').sum()):,}")
kpi_priority.metric("High-priority variants", f"{len(priority_variants):,}")
kpi_priority_a.metric("Priority variants in A", f"{priority_a_variants:,}")

product_chart = (
    alt.Chart(df_abc)
    .mark_circle(opacity=0.7)
    .encode(
        x=alt.X("cumulative_revenue_pct:Q", title="Cumulative revenue (%)"),
        y=alt.Y("revenue:Q", title="Product revenue"),
        color=alt.Color(
            "abc_class:N",
            title="ABC class",
            sort=["A", "B", "C"],
            scale=alt.Scale(domain=["A", "B", "C"], range=["#2ca02c", "#ffbf00", "#d62728"]),
        ),
        tooltip=[
            alt.Tooltip("product_name:N", title="Product"),
            alt.Tooltip("category:N", title="Category"),
            alt.Tooltip("abc_class:N", title="ABC class"),
            alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
            alt.Tooltip("cumulative_revenue_pct:Q", title="Cumulative revenue", format=".2f"),
            alt.Tooltip("units_in_stock:Q", title="Current stock", format=","),
            alt.Tooltip("estimated_days_of_stock:Q", title="Estimated stock days", format=".1f"),
        ],
    )
    .properties(height=420, title="Revenue concentration by product")
)

summary_chart = (
    alt.Chart(abc_summary)
    .mark_bar()
    .encode(
        x=alt.X("abc_class:N", title="ABC class", sort=["A", "B", "C"]),
        y=alt.Y("products:Q", title="Products"),
        color=alt.Color(
            "abc_class:N",
            title=None,
            legend=None,
            scale=alt.Scale(domain=["A", "B", "C"], range=["#2ca02c", "#ffbf00", "#d62728"]),
        ),
        tooltip=[
            alt.Tooltip("abc_class:N", title="Class"),
            alt.Tooltip("products:Q", title="Products", format=","),
            alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
            alt.Tooltip("units_sold:Q", title="Units sold", format=","),
            alt.Tooltip("units_in_stock:Q", title="Current stock", format=","),
        ],
    )
    .properties(height=420, title="Number of products by ABC class")
)

left_chart, right_chart = st.columns([1.5, 1])
with left_chart:
    st.altair_chart(product_chart, use_container_width=True)
with right_chart:
    st.altair_chart(summary_chart, use_container_width=True)

st.caption(
    "Estimated stock cover uses the last 90 days ending at the latest purchase in "
    "the selected slice. Current stock is a snapshot, so this is a prioritization "
    "signal rather than a historical inventory forecast."
)

st.subheader("Restocking priorities")
if priority_variants.empty:
    st.success("No recently sold variants are out of stock or below 30 estimated days of cover.")
else:
    st.dataframe(
        priority_variants.sort_values(
            ["abc_class", "units_in_stock", "revenue"],
            ascending=[True, True, False],
        ),
        hide_index=True,
        use_container_width=True,
    )

with st.expander("ABC summary"):
    st.dataframe(abc_summary, hide_index=True, use_container_width=True)

with st.expander("All product metrics"):
    st.dataframe(df_abc, hide_index=True, use_container_width=True)

with st.expander("All recently sold size/color variants"):
    st.dataframe(df_variant_stock, hide_index=True, use_container_width=True)

with st.expander("See SQL"):
    st.code(abc_sql, language="sql")
    st.code(variant_stock_sql, language="sql")
