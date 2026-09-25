import altair as alt
import streamlit as st

from app_core import (
    filter_params,
    get_connection,
    render_sidebar_filters,
    sales_filter_sql,
)


st.set_page_config(page_title="RFM Analysis", layout="wide")
st.title("RFM Customer Segmentation")
st.caption(
    "RFM summarizes customer value using Recency (days since the last order), "
    "Frequency (number of orders), and Monetary value (revenue). Higher scores "
    "are better for all three dimensions."
)

conn = get_connection()
filters = render_sidebar_filters(conn, "rfm")

rfm_sql = f"""
    WITH filtered_order_lines AS (
        SELECT
            o.id AS order_id,
            o.customer AS customer_id,
            o.ordertimestamp::date AS order_date,
            op.amount * op.price::numeric AS line_revenue
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
    ),
    customer_metrics AS (
        SELECT
            customer_id,
            MAX(order_date) AS last_order_date,
            COUNT(DISTINCT order_id) AS frequency,
            ROUND(SUM(line_revenue), 2) AS monetary
        FROM filtered_order_lines
        GROUP BY customer_id
    ),
    analysis_date AS (
        SELECT MAX(order_date) + 1 AS date
        FROM filtered_order_lines
    ),
    rfm_values AS (
        SELECT
            cm.*,
            ad.date - cm.last_order_date AS recency_days
        FROM customer_metrics AS cm
        CROSS JOIN analysis_date AS ad
    ),
    rfm_scores AS (
        SELECT
            *,
            NTILE(4) OVER (
                ORDER BY recency_days DESC, customer_id
            ) AS recency_score,
            NTILE(4) OVER (
                ORDER BY frequency, customer_id
            ) AS frequency_score,
            NTILE(4) OVER (
                ORDER BY monetary, customer_id
            ) AS monetary_score
        FROM rfm_values
    )
    SELECT
        customer_id,
        last_order_date,
        recency_days,
        frequency,
        monetary,
        recency_score,
        frequency_score,
        monetary_score,
        CONCAT(recency_score, frequency_score, monetary_score) AS rfm_code,
        CASE
            WHEN recency_score = 4
                AND frequency_score >= 3
                AND monetary_score >= 3
                THEN 'Champions'
            WHEN frequency_score = 4 AND recency_score >= 2
                THEN 'Loyal customers'
            WHEN recency_score >= 3 AND frequency_score IN (2, 3)
                THEN 'Potential loyalists'
            WHEN recency_score = 4 AND frequency_score = 1
                THEN 'New customers'
            WHEN recency_score <= 2 AND frequency_score >= 3
                THEN 'At risk'
            WHEN recency_score <= 2 AND frequency_score <= 2
                THEN 'Hibernating'
            ELSE 'Needs attention'
        END AS segment
    FROM rfm_scores
    ORDER BY monetary DESC, customer_id
"""

df_rfm = conn.query(
    rfm_sql,
    params=filter_params(filters),
    ttl=0,
)

if df_rfm.empty:
    st.warning("No purchases match the selected filters.")
    st.stop()

segment_summary = (
    df_rfm.groupby("segment", as_index=False)
    .agg(
        customers=("customer_id", "nunique"),
        revenue=("monetary", "sum"),
        average_orders=("frequency", "mean"),
        average_recency=("recency_days", "mean"),
    )
    .sort_values("revenue", ascending=False)
)

customer_count = int(df_rfm["customer_id"].nunique())
champion_count = int((df_rfm["segment"] == "Champions").sum())
at_risk_count = int((df_rfm["segment"] == "At risk").sum())

kpi_customers, kpi_champions, kpi_at_risk = st.columns(3)
kpi_customers.metric("Customers analyzed", f"{customer_count:,}")
kpi_champions.metric("Champions", f"{champion_count:,}")
kpi_at_risk.metric("At-risk customers", f"{at_risk_count:,}")

segment_chart = (
    alt.Chart(segment_summary)
    .mark_bar()
    .encode(
        x=alt.X("customers:Q", title="Customers"),
        y=alt.Y("segment:N", title=None, sort="-x"),
        color=alt.Color("segment:N", title="Segment", legend=None),
        tooltip=[
            alt.Tooltip("segment:N", title="Segment"),
            alt.Tooltip("customers:Q", title="Customers", format=","),
            alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
            alt.Tooltip("average_orders:Q", title="Average orders", format=".2f"),
            alt.Tooltip("average_recency:Q", title="Average recency", format=".1f"),
        ],
    )
    .properties(height=320, title="Customer segments")
)

rfm_scatter = (
    alt.Chart(df_rfm)
    .mark_circle(opacity=0.65)
    .encode(
        x=alt.X("recency_days:Q", title="Recency (days)"),
        y=alt.Y("frequency:Q", title="Orders"),
        size=alt.Size("monetary:Q", title="Revenue", scale=alt.Scale(range=[20, 700])),
        color=alt.Color("segment:N", title="Segment"),
        tooltip=[
            alt.Tooltip("customer_id:Q", title="Customer"),
            alt.Tooltip("recency_days:Q", title="Recency"),
            alt.Tooltip("frequency:Q", title="Orders"),
            alt.Tooltip("monetary:Q", title="Revenue", format=",.2f"),
            alt.Tooltip("rfm_code:N", title="RFM code"),
            alt.Tooltip("segment:N", title="Segment"),
        ],
    )
    .properties(height=420, title="Recency, frequency, and monetary value")
)

left_chart, right_chart = st.columns([1, 1.4])
with left_chart:
    st.altair_chart(segment_chart, use_container_width=True)
with right_chart:
    st.altair_chart(rfm_scatter, use_container_width=True)

st.info(
    "Scores are quartiles within the selected data slice, so segment boundaries "
    "change when filters change. This is useful for prioritization, not a causal "
    "prediction of future purchases."
)

with st.expander("Segment summary", expanded=True):
    st.dataframe(segment_summary, hide_index=True, use_container_width=True)

with st.expander("Customer-level RFM data"):
    st.dataframe(df_rfm, hide_index=True, use_container_width=True)

with st.expander("See SQL"):
    st.code(rfm_sql, language="sql")
