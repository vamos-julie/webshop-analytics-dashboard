# Validation Guide

Use this checklist after changing SQL, filters, joins, metrics, or deployment
configuration. The goal is to verify analytical meaning, not only that the app
runs without an error.

## 1. Baseline values

With all filters selected and the full dataset period (`2016-08-03` through
`2018-08-02`), the overview must show:

| Metric | Expected value |
|---|---:|
| Orders | 2,000 |
| Purchasing customers | 868 |
| Units sold | 5,985 |
| Revenue | $528,186.11 |

Run this independent query in PostgreSQL to reproduce the baseline:

```sql
SELECT
    COUNT(DISTINCT o.id) AS orders,
    COUNT(DISTINCT o.customer) AS purchasing_customers,
    SUM(op.amount) AS units_sold,
    ROUND(SUM(op.amount * op.price::numeric), 2) AS revenue
FROM webshop."order" AS o
JOIN webshop.order_positions AS op ON op.orderid = o.id;
```

If a presentation-only change alters one of these values, stop and inspect the
query grain and joins before continuing.

## 2. Join and grain checks

Before accepting a query, complete these sentences:

- One row in the starting dataset represents ...
- One row in every CTE represents ...
- One row in the final result represents ...
- The join relationship is one-to-one, one-to-many, or many-to-many ...

Check row counts before and after a new join:

```sql
SELECT COUNT(*) FROM webshop.order_positions;

SELECT COUNT(*)
FROM webshop.order_positions AS op
JOIN webshop.articles AS a ON a.id = op.articleid
JOIN webshop.products AS p ON p.id = a.productid;
```

For these many-to-one joins, the counts should match. If a join unexpectedly
increases the row count, identify the duplicate key before calculating totals.

## 3. Manual order check

Choose an order from the dashboard and replace `123` below with its ID:

```sql
SELECT
    o.id AS order_id,
    op.id AS order_position_id,
    op.articleid AS article_id,
    op.amount AS units,
    op.price::numeric AS unit_price,
    op.amount * op.price::numeric AS line_revenue
FROM webshop."order" AS o
JOIN webshop.order_positions AS op ON op.orderid = o.id
WHERE o.id = 123
ORDER BY op.id;
```

Manually add `units` and `line_revenue`. They must agree with any order-level
aggregation built from the same data.

## 4. Page checks

### Overview

- Baseline values match the table above.
- Monthly revenue sums to total revenue.
- Category revenue sums to total revenue.
- A category, label, audience, or date filter changes every relevant component.
- Clearing filters restores the baseline values.

### Cohort retention

- Every customer belongs to only one cohort in the selected slice.
- Customer retention in month 0 is 100%.
- Customer retention is between 0% and 100%.
- Revenue retention in month 0 is 100%.
- Revenue retention after month 0 may exceed 100% if the cohort spends more.
- A manually selected customer's cohort equals the month of that customer's
  first purchase inside the selected slice.

### RFM analysis

- One final row represents one customer.
- `frequency` is the distinct order count, not the order-position count.
- `monetary` equals the sum of line revenue for that customer.
- `recency_days` is measured from the analysis date to the last order date.
- All R, F, and M scores are integers from 1 through 4.
- Every customer belongs to exactly one segment.
- Overlapping segment conditions are resolved by the top-to-bottom `CASE` order.

### Market basket analysis

- Categories are deduplicated inside each order before pairs are generated.
- A basket with `n` categories creates `n × (n - 1) / 2` unique pairs.
- `support` and both confidence values are between 0% and 100%.
- `lift` is non-negative.
- For one selected pair, independently count orders containing A, B, and both.

For `100` total orders, `30` A orders, `20` B orders, and `10` joint orders:

```text
support = 10 / 100 = 10%
confidence A → B = 10 / 30 = 33.3%
confidence B → A = 10 / 20 = 50%
lift = (10 / 100) / ((30 / 100) × (20 / 100)) = 1.67
```

### ABC and inventory

- One ABC row represents one product.
- Product revenue sums to the selected overview revenue.
- Every product belongs to exactly one of A, B, or C.
- Cumulative revenue percentage never decreases and ends at 100%.
- Variant stock joins on `article_id`, not only `product_id`.
- Missing stock is deliberately interpreted as zero stock.
- Estimated stock cover uses the last 90 days in the selected slice.

### Size and color

- One SQL row represents a category-size-color combination.
- `units_sold` uses `SUM(amount)`, not `COUNT(*)`.
- Size and color remain attached to the purchased `article_id`.
- Low observed sales are not automatically interpreted as low demand because
  availability can constrain sales.

### Data quality

- Open the Data Quality page after every material SQL or data change.
- All 12 configured checks should show `Pass` for the supplied demo dataset.
- Investigate a failure before changing source data; the business rule may need
  clarification.

## 5. Filter and edge-case checks

Test at least these cases:

- the full date range;
- one month;
- one category;
- one label;
- one product audience;
- two or more filters together;
- a slice with very few purchases;
- a slice with no matching purchases.

An empty result must display a clear message instead of a Python traceback.
Queries that divide must protect the denominator with `NULLIF(..., 0)` where
zero is possible.

## 6. Deployment checks

After every push that changes application behavior:

1. Open the live app in a private/incognito browser window.
2. Confirm that it loads without a GitHub or Streamlit login.
3. Open every page in the sidebar.
4. Change and clear filters on at least two pages.
5. Check that long KPI values and labels are not truncated.
6. Confirm that no red Streamlit exception is displayed.
7. Open the Data Quality page and review its results.
8. Confirm that `.streamlit/secrets.toml`, passwords, and database URLs are not
   committed to GitHub.

## 7. Questions to ask before accepting AI-generated SQL

1. What does one row represent in every CTE?
2. Can any join multiply rows?
3. Why is the metric using `COUNT`, `COUNT(DISTINCT ...)`, or `SUM(...)`?
4. Can any value be `NULL`?
5. Can a denominator be zero?
6. What simpler, independent query can verify the result?
7. Which manually selected record should be checked?
8. Which edge cases can break the query?

Do not accept an answer only because it runs. Accept it when its grain is clear,
its totals reconcile, and several records have been independently checked.

