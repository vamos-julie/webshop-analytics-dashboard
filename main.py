import altair as alt
import streamlit as st

from app_core import (
    filter_params,
    get_connection,
    render_sidebar_filters,
    sales_filter_sql,
)


st.set_page_config(
    page_title="Webshop Analytics",
    page_icon="🛍️",
    layout="wide",
)

st.title("Webshop Analytics")
st.caption(
    "An interactive commercial analytics project built with PostgreSQL, SQL, "
    "Python, and Streamlit. Use the sidebar to filter this overview or open a "
    "specialized analysis page."
)

conn = get_connection()
filters = render_sidebar_filters(conn, "overview")
params = filter_params(filters)

overview_sql = f"""
    WITH filtered_lines AS (
        SELECT
            o.id AS order_id,
            o.customer AS customer_id,
            o.ordertimestamp::date AS order_date,
            p.id AS product_id,
            p.name AS product_name,
            p.category::text AS category,
            op.amount AS units,
            op.amount * op.price::numeric AS revenue
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
    ),
    order_metrics AS (
        SELECT
            order_id,
            customer_id,
            SUM(units) AS units,
            SUM(revenue) AS revenue
        FROM filtered_lines
        GROUP BY order_id, customer_id
    )
    SELECT
        COUNT(*) AS orders,
        COUNT(DISTINCT customer_id) AS purchasing_customers,
        COALESCE(SUM(units), 0) AS units_sold,
        ROUND(COALESCE(SUM(revenue), 0), 2) AS revenue,
        ROUND(COALESCE(AVG(revenue), 0), 2) AS revenue_per_order
    FROM order_metrics
"""

monthly_sql = f"""
    WITH filtered_lines AS (
        SELECT
            o.id AS order_id,
            DATE_TRUNC('month', o.ordertimestamp)::date AS order_month,
            op.amount AS units,
            op.amount * op.price::numeric AS revenue
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
    )
    SELECT
        order_month,
        COUNT(DISTINCT order_id) AS orders,
        SUM(units) AS units_sold,
        ROUND(SUM(revenue), 2) AS revenue
    FROM filtered_lines
    GROUP BY order_month
    ORDER BY order_month
"""

category_sql = f"""
    SELECT
        p.category::text AS category,
        COUNT(DISTINCT o.id) AS orders,
        SUM(op.amount) AS units_sold,
        ROUND(SUM(op.amount * op.price::numeric), 2) AS revenue
    FROM webshop."order" AS o
    JOIN webshop.order_positions AS op ON op.orderid = o.id
    JOIN webshop.articles AS a ON a.id = op.articleid
    JOIN webshop.products AS p ON p.id = a.productid
    JOIN webshop.labels AS l ON l.id = p.labelid
    WHERE {sales_filter_sql()}
    GROUP BY p.category
    ORDER BY revenue DESC, p.category
"""

top_products_sql = f"""
    SELECT
        p.id AS product_id,
        p.name AS product_name,
        p.category::text AS category,
        COUNT(DISTINCT o.id) AS orders,
        SUM(op.amount) AS units_sold,
        ROUND(SUM(op.amount * op.price::numeric), 2) AS revenue
    FROM webshop."order" AS o
    JOIN webshop.order_positions AS op ON op.orderid = o.id
    JOIN webshop.articles AS a ON a.id = op.articleid
    JOIN webshop.products AS p ON p.id = a.productid
    JOIN webshop.labels AS l ON l.id = p.labelid
    WHERE {sales_filter_sql()}
    GROUP BY p.id, p.name, p.category
    ORDER BY revenue DESC, p.id
    LIMIT 10
"""

customer_mix_sql = f"""
    WITH filtered_orders AS (
        SELECT DISTINCT o.id AS order_id, o.customer AS customer_id
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
    ),
    customer_orders AS (
        SELECT customer_id, COUNT(*) AS orders
        FROM filtered_orders
        GROUP BY customer_id
    )
    SELECT
        CASE
            WHEN orders = 1 THEN 'One-time in selected slice'
            ELSE 'Repeat in selected slice'
        END AS customer_type,
        COUNT(*) AS customers
    FROM customer_orders
    GROUP BY customer_type
    ORDER BY customer_type
"""

df_overview = conn.query(overview_sql, params=params, ttl=0).iloc[0]
df_monthly = conn.query(monthly_sql, params=params, ttl=0)
df_categories = conn.query(category_sql, params=params, ttl=0)
df_top_products = conn.query(top_products_sql, params=params, ttl=0)
df_customer_mix = conn.query(customer_mix_sql, params=params, ttl=0)

if int(df_overview["orders"]) == 0:
    st.warning("No purchases match the selected filters.")
    st.stop()

revenue = float(df_overview["revenue"])
orders = int(df_overview["orders"])
units_sold = int(df_overview["units_sold"])
customers = int(df_overview["purchasing_customers"])
revenue_per_order = float(df_overview["revenue_per_order"])

kpi_revenue, kpi_orders, kpi_aov, kpi_customers, kpi_units = st.columns(5)
kpi_revenue.metric("Revenue", f"${revenue:,.2f}")
kpi_orders.metric("Orders", f"{orders:,}")
kpi_aov.metric(
    "Revenue per order",
    f"${revenue_per_order:,.2f}",
    help="Revenue from selected products divided by distinct orders in the slice.",
)
kpi_customers.metric("Purchasing customers", f"{customers:,}")
kpi_units.metric("Units sold", f"{units_sold:,}")

st.subheader("Sales over time")
monthly_base = alt.Chart(df_monthly).encode(
    x=alt.X("yearmonth(order_month):T", title="Month")
)
revenue_area = monthly_base.mark_area(
    color="#4C78A8",
    opacity=0.25,
    line={"color": "#4C78A8"},
).encode(
    y=alt.Y("revenue:Q", title="Revenue"),
    tooltip=[
        alt.Tooltip("yearmonth(order_month):T", title="Month"),
        alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
        alt.Tooltip("orders:Q", title="Orders", format=","),
        alt.Tooltip("units_sold:Q", title="Units", format=","),
    ],
)
st.altair_chart(
    revenue_area.properties(height=360, title="Monthly revenue"),
    use_container_width=True,
)

category_chart = (
    alt.Chart(df_categories)
    .mark_bar()
    .encode(
        x=alt.X("revenue:Q", title="Revenue"),
        y=alt.Y("category:N", title=None, sort="-x"),
        color=alt.Color("category:N", legend=None),
        tooltip=[
            alt.Tooltip("category:N", title="Category"),
            alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
            alt.Tooltip("orders:Q", title="Orders", format=","),
            alt.Tooltip("units_sold:Q", title="Units", format=","),
        ],
    )
    .properties(height=380, title="Revenue by category")
)

customer_chart = (
    alt.Chart(df_customer_mix)
    .mark_arc(innerRadius=55)
    .encode(
        theta=alt.Theta("customers:Q"),
        color=alt.Color("customer_type:N", title=None),
        tooltip=[
            alt.Tooltip("customer_type:N", title="Customer type"),
            alt.Tooltip("customers:Q", title="Customers", format=","),
        ],
    )
    .properties(height=380, title="Customer purchase frequency")
)

left_chart, right_chart = st.columns([1.6, 1])
with left_chart:
    st.altair_chart(category_chart, use_container_width=True)
with right_chart:
    st.altair_chart(customer_chart, use_container_width=True)

st.subheader("Top products by revenue")
st.dataframe(
    df_top_products,
    hide_index=True,
    use_container_width=True,
)

st.info(
    "Continue with the pages in the sidebar for cohort retention, RFM customer "
    "segments, basket affinities, ABC inventory priorities, size/color demand, "
    "and automated data-quality checks."
)

with st.expander("See overview SQL"):
    st.code(overview_sql, language="sql")
    st.code(monthly_sql, language="sql")
    st.code(category_sql, language="sql")
    st.code(top_products_sql, language="sql")
    st.code(customer_mix_sql, language="sql")
