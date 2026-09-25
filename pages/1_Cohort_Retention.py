import altair as alt
import streamlit as st

from app_core import (
    filter_params,
    get_connection,
    render_sidebar_filters,
    sales_filter_sql,
)


st.set_page_config(page_title="Cohort Retention", layout="wide")
st.title("Cohort Retention")
st.caption(
    "Customers are grouped by the month of their first purchase within the "
    "selected slice. Month 0 is the acquisition month."
)

conn = get_connection()
filters = render_sidebar_filters(conn, "cohort")

cohort_sql = f"""
    WITH filtered_orders AS (
        SELECT
            o.id AS order_id,
            o.customer AS customer_id,
            DATE_TRUNC('month', o.ordertimestamp)::date AS order_month,
            SUM(op.amount * op.price::numeric) AS revenue
        FROM webshop."order" AS o
        JOIN webshop.order_positions AS op ON op.orderid = o.id
        JOIN webshop.articles AS a ON a.id = op.articleid
        JOIN webshop.products AS p ON p.id = a.productid
        JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE {sales_filter_sql()}
        GROUP BY o.id, o.customer, DATE_TRUNC('month', o.ordertimestamp)::date
    ),
    customer_months AS (
        SELECT
            customer_id,
            order_month,
            SUM(revenue) AS revenue
        FROM filtered_orders
        GROUP BY customer_id, order_month
    ),
    cohort_activity AS (
        SELECT
            *,
            MIN(order_month) OVER (
                PARTITION BY customer_id
            ) AS cohort_month
        FROM customer_months
    ),
    indexed_activity AS (
        SELECT
            *,
            (
                EXTRACT(YEAR FROM AGE(order_month, cohort_month)) * 12
                + EXTRACT(MONTH FROM AGE(order_month, cohort_month))
            )::int AS cohort_age_month
        FROM cohort_activity
    ),
    cohort_monthly AS (
        SELECT
            cohort_month,
            cohort_age_month,
            COUNT(DISTINCT customer_id) AS active_customers,
            SUM(revenue) AS revenue
        FROM indexed_activity
        GROUP BY cohort_month, cohort_age_month
    ),
    cohort_baseline AS (
        SELECT
            cohort_month,
            MAX(active_customers) FILTER (
                WHERE cohort_age_month = 0
            ) AS cohort_size,
            MAX(revenue) FILTER (
                WHERE cohort_age_month = 0
            ) AS month_zero_revenue
        FROM cohort_monthly
        GROUP BY cohort_month
    )
    SELECT
        cm.cohort_month,
        cm.cohort_age_month,
        cb.cohort_size,
        cm.active_customers,
        ROUND(
            100.0 * cm.active_customers / NULLIF(cb.cohort_size, 0), 2
        ) AS customer_retention,
        ROUND(cm.revenue, 2) AS revenue,
        ROUND(
            100.0 * cm.revenue / NULLIF(cb.month_zero_revenue, 0), 2
        ) AS revenue_retention
    FROM cohort_monthly AS cm
    JOIN cohort_baseline AS cb USING (cohort_month)
    ORDER BY cm.cohort_month, cm.cohort_age_month
"""

df_cohort = conn.query(
    cohort_sql,
    params=filter_params(filters),
    ttl=0,
)

if df_cohort.empty:
    st.warning("No purchases match the selected filters.")
    st.stop()

cohort_count = df_cohort["cohort_month"].nunique()
customer_count = int(
    df_cohort.loc[df_cohort["cohort_age_month"] == 0, "cohort_size"].sum()
)
revenue_retention_peak = float(df_cohort["revenue_retention"].max())

kpi_cohorts, kpi_customers, kpi_revenue_peak = st.columns(3)
kpi_cohorts.metric("Cohorts", f"{cohort_count}")
kpi_customers.metric("Customers", f"{customer_count:,}")
kpi_revenue_peak.metric(
    "Peak revenue retention",
    f"{revenue_retention_peak:,.1f}%",
    help="Revenue retention can exceed 100% when a cohort spends more than in month 0.",
)


def retention_heatmap(data, field, title, legend_title):
    return (
        alt.Chart(data)
        .mark_rect()
        .encode(
            x=alt.X(
                "cohort_age_month:O",
                title="Months since first purchase",
            ),
            y=alt.Y(
                "yearmonth(cohort_month):O",
                title="Acquisition cohort",
                sort="ascending",
            ),
            color=alt.Color(
                f"{field}:Q",
                title=legend_title,
                scale=alt.Scale(scheme="blues"),
            ),
            tooltip=[
                alt.Tooltip("yearmonth(cohort_month):O", title="Cohort"),
                alt.Tooltip("cohort_age_month:O", title="Cohort age"),
                alt.Tooltip("cohort_size:Q", title="Initial customers"),
                alt.Tooltip("active_customers:Q", title="Active customers"),
                alt.Tooltip("customer_retention:Q", title="Customer retention", format=".1f"),
                alt.Tooltip("revenue:Q", title="Revenue", format=",.2f"),
                alt.Tooltip("revenue_retention:Q", title="Revenue retention", format=".1f"),
            ],
        )
        .properties(height=max(350, cohort_count * 22), title=title)
    )


customer_tab, revenue_tab = st.tabs(
    ["Customer retention", "Revenue retention"]
)

with customer_tab:
    st.altair_chart(
        retention_heatmap(
            df_cohort,
            "customer_retention",
            "Customer retention by acquisition cohort",
            "Retention (%)",
        ),
        use_container_width=True,
    )
    st.caption(
        "Active unique customers in cohort month N divided by the original cohort size."
    )

with revenue_tab:
    st.altair_chart(
        retention_heatmap(
            df_cohort,
            "revenue_retention",
            "Revenue retention by acquisition cohort",
            "Revenue retention (%)",
        ),
        use_container_width=True,
    )
    st.caption(
        "Cohort revenue in month N divided by that cohort's revenue in month 0. "
        "Values above 100% mean the cohort spent more than during acquisition."
    )

with st.expander("Cohort data"):
    st.dataframe(df_cohort, hide_index=True, use_container_width=True)

with st.expander("See SQL"):
    st.code(cohort_sql, language="sql")
