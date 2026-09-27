# Webshop Analytics Dashboard

A multipage Streamlit portfolio project built on a PostgreSQL webshop dataset.
It demonstrates SQL aggregation at order, customer, product, and article-variant
grain, together with practical commercial analytics.

[Open the live Streamlit dashboard](https://webshop-analytics-dashboard.streamlit.app/)

## What is included

- Management dashboard: revenue, orders, units, categories, labels, discounts,
  customers, and low-stock articles.
- Cohort retention: monthly customer retention and revenue retention.
- RFM segmentation: recency, frequency, monetary value, quartile scores, and
  actionable customer segments.
- Market basket analysis: category pairs with support, directional confidence,
  and lift.
- ABC and inventory analysis: revenue concentration by product plus restocking
  priorities at size/color article level.
- Size and color demand: category-level sales patterns for article variants.
- Data quality: 12 checks covering revenue reconciliation, relationships,
  customer records, and inventory.

All analytical pages have date, category, label, and product-audience filters.
They also expose their SQL in the interface so the calculations can be studied.

## Run locally

Requirements: Python 3.11+ and PostgreSQL. The commands below assume PostgreSQL
is running locally on port `5432` and that the current database user can create a
database.

```bash
git clone https://github.com/vamos-julie/Webshop-streamlit-demo.git
cd Webshop-streamlit-demo

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

createdb webshop
pg_restore --no-owner --no-privileges -d webshop db_dump/mydb.dump

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
streamlit run main.py
```

The example configuration uses a local database named `webshop`, user
`postgres`, empty password, and port `5432`. Adjust the copied
`.streamlit/secrets.toml` for your PostgreSQL installation. The real secrets
file is ignored by Git. As an alternative, set a SQLAlchemy connection URL:

```bash
export DATABASE_URL='postgresql://postgres:password@localhost:5432/webshop'
streamlit run main.py
```

## Metric definitions

- Revenue is calculated from order positions as `amount × paid unit price`.
- Units sold is `SUM(order_positions.amount)`; it is not a row count.
- Orders is `COUNT(DISTINCT order_id)` whenever product-level joins are present.
- Cohorts use the first purchase inside the currently selected data slice.
- Customer retention divides active customers in cohort month N by the original
  cohort size.
- Revenue retention divides cohort revenue in month N by that cohort's month-0
  revenue, so it can exceed 100%.
- Basket pairs use distinct categories per order. An order with four categories
  produces six unique pairs.
- ABC classes are based on cumulative selected-period product revenue: A through
  80%, B through 95%, and C for the remainder.
- Estimated stock cover uses current stock and sales during the last 90 days of
  the selected slice. It is a prioritization indicator, not a forecast.

## Project structure

```text
main.py                         Management dashboard
app_core.py                     Shared connection and filter helpers
pages/1_Cohort_Retention.py     Customer and revenue cohorts
pages/2_RFM_Analysis.py         RFM customer segmentation
pages/3_Basket_Analysis.py      Category affinity metrics
pages/4_ABC_and_Inventory.py    Product ABC and variant restocking
pages/5_Size_and_Color.py       Variant demand patterns
pages/6_Data_Quality.py         Automated data checks
db_dump/mydb.dump               PostgreSQL demo data
```

## Important interpretation notes

The dashboard is descriptive. A relationship such as higher spending among
discounted orders does not prove that discounts caused the increase. Likewise,
observed size and color sales are influenced by availability; low sales can mean
low demand, low stock, or both.
