import altair as alt
import streamlit as st

from app_core import (
    filter_params,
    get_connection,
    render_sidebar_filters,
    sales_filter_sql,
)


st.set_page_config(page_title="Basket Analysis", layout="wide")
st.title("Market Basket Analysis")
st.caption(
    "The analysis finds category pairs bought in the same order. Categories are "
    "deduplicated inside each order before pairs are created."
)

conn = get_connection()
filters = render_sidebar_filters(conn, "basket")
params = filter_params(filters)

pair_sql = f"""
    WITH filtered_order_categories AS (
        SELECT DISTINCT
            o.id AS order_id,
            p.category::text AS category
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
    ),
    order_count AS (
        SELECT COUNT(DISTINCT order_id) AS total_orders
        FROM filtered_order_categories
    ),
    category_orders AS (
        SELECT category, COUNT(DISTINCT order_id) AS category_order_count
        FROM filtered_order_categories
        GROUP BY category
    ),
    pair_orders AS (
        SELECT
            left_category.category AS category_a,
            right_category.category AS category_b,
            COUNT(*) AS pair_order_count
        FROM filtered_order_categories AS left_category
        JOIN filtered_order_categories AS right_category
            ON left_category.order_id = right_category.order_id
            AND left_category.category < right_category.category
        GROUP BY left_category.category, right_category.category
    )
    SELECT
        po.category_a,
        po.category_b,
        po.pair_order_count,
        ROUND(100.0 * po.pair_order_count / NULLIF(oc.total_orders, 0), 2)
            AS support_pct,
        ROUND(100.0 * po.pair_order_count / NULLIF(ca.category_order_count, 0), 2)
            AS confidence_a_to_b_pct,
        ROUND(100.0 * po.pair_order_count / NULLIF(cb.category_order_count, 0), 2)
            AS confidence_b_to_a_pct,
        ROUND(
            po.pair_order_count::numeric * oc.total_orders
            / NULLIF(ca.category_order_count * cb.category_order_count, 0),
            3
        ) AS lift
    FROM pair_orders AS po
    JOIN category_orders AS ca ON ca.category = po.category_a
    JOIN category_orders AS cb ON cb.category = po.category_b
    CROSS JOIN order_count AS oc
    ORDER BY po.pair_order_count DESC, po.category_a, po.category_b
"""

basket_size_sql = f"""
    WITH filtered_order_categories AS (
        SELECT DISTINCT
            o.id AS order_id,
            p.category::text AS category
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
    ),
    basket_sizes AS (
        SELECT order_id, COUNT(*) AS distinct_categories
        FROM filtered_order_categories
        GROUP BY order_id
    )
    SELECT
        distinct_categories,
        COUNT(*) AS orders,
        distinct_categories * (distinct_categories - 1) / 2 AS pairs_per_order
    FROM basket_sizes
    GROUP BY distinct_categories
    ORDER BY distinct_categories
"""

df_pairs = conn.query(pair_sql, params=params, ttl=0)
df_basket_sizes = conn.query(basket_size_sql, params=params, ttl=0)

if df_basket_sizes.empty:
    st.warning("No purchases match the selected filters.")
    st.stop()

total_orders = int(df_basket_sizes["orders"].sum())
multi_category_orders = int(
    df_basket_sizes.loc[df_basket_sizes["distinct_categories"] >= 2, "orders"].sum()
)
max_categories = int(df_basket_sizes["distinct_categories"].max())

kpi_orders, kpi_multi, kpi_max = st.columns(3)
kpi_orders.metric("Orders analyzed", f"{total_orders:,}")
kpi_multi.metric("Orders with 2+ categories", f"{multi_category_orders:,}")
kpi_max.metric("Maximum categories in one order", f"{max_categories}")

st.info(
    "An order with 4 distinct categories produces 4 × 3 ÷ 2 = 6 unique pairs. "
    "This lets every category participate in the analysis without creating a "
    "variable-width row. Triplets can be analyzed separately if needed."
)

if df_pairs.empty:
    st.warning("There are no orders containing at least two selected categories.")
    st.stop()

max_pair_orders = int(df_pairs["pair_order_count"].max())
minimum_pair_orders = st.slider(
    "Minimum orders containing the pair",
    min_value=1,
    max_value=max_pair_orders,
    value=min(5, max_pair_orders),
    help="Increase this threshold to hide pairs based on very few orders.",
)

visible_pairs = df_pairs[
    df_pairs["pair_order_count"] >= minimum_pair_orders
].copy()

metric_options = {
    "Pair orders": ("pair_order_count", "Orders"),
    "Support": ("support_pct", "Support (%)"),
    "Lift": ("lift", "Lift"),
}
selected_metric = st.radio(
    "Heatmap metric",
    list(metric_options),
    horizontal=True,
)
metric_field, metric_title = metric_options[selected_metric]

heatmap = (
    alt.Chart(visible_pairs)
    .mark_rect()
    .encode(
        x=alt.X("category_a:N", title="Category A", sort="ascending"),
        y=alt.Y("category_b:N", title="Category B", sort="ascending"),
        color=alt.Color(f"{metric_field}:Q", title=metric_title, scale=alt.Scale(scheme="blues")),
        tooltip=[
            alt.Tooltip("category_a:N", title="Category A"),
            alt.Tooltip("category_b:N", title="Category B"),
            alt.Tooltip("pair_order_count:Q", title="Pair orders", format=","),
            alt.Tooltip("support_pct:Q", title="Support", format=".2f"),
            alt.Tooltip("confidence_a_to_b_pct:Q", title="A → B confidence", format=".2f"),
            alt.Tooltip("confidence_b_to_a_pct:Q", title="B → A confidence", format=".2f"),
            alt.Tooltip("lift:Q", title="Lift", format=".3f"),
        ],
    )
    .properties(height=520, title=f"Category pairs by {selected_metric.lower()}")
)
st.altair_chart(heatmap, use_container_width=True)

st.caption(
    "Support is the share of all orders containing both categories. Confidence "
    "A → B is the share of A orders that also contain B. Lift above 1 means the "
    "pair occurs more often than expected if the categories were independent."
)

left_table, right_table = st.columns([1.5, 1])
with left_table:
    st.subheader("Category pairs")
    st.dataframe(visible_pairs, hide_index=True, use_container_width=True)
with right_table:
    st.subheader("Basket size distribution")
    st.dataframe(df_basket_sizes, hide_index=True, use_container_width=True)

with st.expander("See pair SQL"):
    st.code(pair_sql, language="sql")

with st.expander("See basket-size SQL"):
    st.code(basket_size_sql, language="sql")
