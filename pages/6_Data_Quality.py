import altair as alt
import streamlit as st

from app_core import get_connection, get_dataset_bounds


st.set_page_config(page_title="Data Quality", layout="wide")
st.title("Data Quality Checks")
st.caption(
    "These checks catch broken relationships and values that can silently distort "
    "sales, customer, and inventory metrics."
)

conn = get_connection()
bounds = get_dataset_bounds(conn)

quality_sql = """
    WITH order_line_totals AS (
        SELECT orderid, SUM(amount * price::numeric) AS line_total
        FROM webshop.order_positions
        GROUP BY orderid
    ),
    checks AS (
        SELECT
            1 AS test_order,
            'Order total differs from line revenue' AS check_name,
            'Revenue' AS area,
            COUNT(*) AS failures,
            'order.total must equal SUM(amount × price)' AS expectation
        FROM webshop."order" AS o
        LEFT JOIN order_line_totals AS olt ON olt.orderid = o.id
        WHERE ABS(o.total::numeric - COALESCE(olt.line_total, 0)) > 0.01

        UNION ALL
        SELECT 2, 'Orders without positions', 'Revenue', COUNT(*),
            'Every order must contain at least one position'
        FROM webshop."order" AS o
        LEFT JOIN webshop.order_positions AS op ON op.orderid = o.id
        WHERE op.id IS NULL

        UNION ALL
        SELECT 3, 'Non-positive position quantity', 'Revenue', COUNT(*),
            'Position amount must be greater than zero'
        FROM webshop.order_positions
        WHERE amount IS NULL OR amount <= 0

        UNION ALL
        SELECT 4, 'Non-positive position price', 'Revenue', COUNT(*),
            'Paid unit price must be greater than zero'
        FROM webshop.order_positions
        WHERE price IS NULL OR price::numeric <= 0

        UNION ALL
        SELECT 5, 'Orders with missing customer', 'Relationships', COUNT(*),
            'order.customer must reference an existing customer'
        FROM webshop."order" AS o
        LEFT JOIN webshop.customer AS c ON c.id = o.customer
        WHERE c.id IS NULL

        UNION ALL
        SELECT 6, 'Articles with missing product', 'Relationships', COUNT(*),
            'articles.productid must reference an existing product'
        FROM webshop.articles AS a
        LEFT JOIN webshop.products AS p ON p.id = a.productid
        WHERE p.id IS NULL

        UNION ALL
        SELECT 7, 'Products with missing label', 'Relationships', COUNT(*),
            'products.labelid must reference an existing label'
        FROM webshop.products AS p
        LEFT JOIN webshop.labels AS l ON l.id = p.labelid
        WHERE l.id IS NULL

        UNION ALL
        SELECT 8, 'Articles with missing size or color', 'Relationships', COUNT(*),
            'Every article variant must have a valid size and color'
        FROM webshop.articles AS a
        LEFT JOIN webshop.sizes AS si ON si.id = a.size
        LEFT JOIN webshop.colors AS col ON col.id = a.colorid
        WHERE si.id IS NULL OR col.id IS NULL

        UNION ALL
        SELECT 9, 'Duplicate customer emails', 'Customers', COUNT(*),
            'A normalized non-empty email should belong to one customer'
        FROM (
            SELECT LOWER(TRIM(email)) AS normalized_email
            FROM webshop.customer
            WHERE NULLIF(TRIM(email), '') IS NOT NULL
            GROUP BY LOWER(TRIM(email))
            HAVING COUNT(*) > 1
        ) AS duplicate_emails

        UNION ALL
        SELECT 10, 'Invalid current customer address', 'Customers', COUNT(*),
            'currentaddressid must point to an address owned by that customer'
        FROM webshop.customer AS c
        LEFT JOIN webshop.address AS a
            ON a.id = c.currentaddressid AND a.customerid = c.id
        WHERE c.currentaddressid IS NOT NULL AND a.id IS NULL

        UNION ALL
        SELECT 11, 'Negative stock quantity', 'Inventory', COUNT(*),
            'Stock count must not be negative'
        FROM webshop.stock
        WHERE count < 0

        UNION ALL
        SELECT 12, 'Duplicate stock records per article', 'Inventory', COUNT(*),
            'Each article should have at most one current stock row'
        FROM (
            SELECT articleid
            FROM webshop.stock
            GROUP BY articleid
            HAVING COUNT(*) > 1
        ) AS duplicate_stock
    )
    SELECT *
    FROM checks
    ORDER BY test_order
"""

df_quality = conn.query(quality_sql, ttl=0)
df_quality["status"] = df_quality["failures"].apply(
    lambda failures: "Pass" if failures == 0 else "Review"
)

failed_checks = int((df_quality["failures"] > 0).sum())
detected_records = int(df_quality["failures"].sum())

kpi_tests, kpi_failed, kpi_records, kpi_period = st.columns(4)
kpi_tests.metric("Checks run", f"{len(df_quality)}")
kpi_failed.metric("Checks to review", f"{failed_checks}")
kpi_records.metric("Detected records/groups", f"{detected_records:,}")
kpi_period.metric("Orders through", str(bounds["max_date"]))

if failed_checks == 0:
    st.success("All configured checks passed.")
else:
    st.warning(
        f"{failed_checks} checks found data to review. A failure is a diagnostic "
        "signal; confirm the business rule before changing source data."
    )

status_view = df_quality[
    ["status", "area", "check_name", "failures", "expectation"]
]
st.dataframe(status_view, hide_index=True, use_container_width=True)

failed_rows = df_quality[df_quality["failures"] > 0]
if not failed_rows.empty:
    failure_chart = (
        alt.Chart(failed_rows)
        .mark_bar()
        .encode(
            x=alt.X("failures:Q", title="Detected records or duplicate groups"),
            y=alt.Y("check_name:N", title=None, sort="-x"),
            color=alt.Color("area:N", title="Area"),
            tooltip=[
                alt.Tooltip("check_name:N", title="Check"),
                alt.Tooltip("area:N", title="Area"),
                alt.Tooltip("failures:Q", title="Detected", format=","),
                alt.Tooltip("expectation:N", title="Expectation"),
            ],
        )
        .properties(height=max(220, len(failed_rows) * 45), title="Checks requiring review")
    )
    st.altair_chart(failure_chart, use_container_width=True)

st.info(
    "The order-total check intentionally compares total with merchandise lines "
    "only: in this dataset shippingcost is stored separately and is not included "
    "in order.total."
)

with st.expander("See SQL"):
    st.code(quality_sql, language="sql")
