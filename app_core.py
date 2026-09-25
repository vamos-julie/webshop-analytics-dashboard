import os

import streamlit as st


@st.cache_resource
def get_connection():
    db_url = os.environ.get("DATABASE_URL")

    if db_url is None:
        return st.connection("postgresql", type="sql")

    return st.connection(
        "postgresql",
        type="sql",
        url=db_url.replace("postgres://", "postgresql://"),
    )


def get_dataset_bounds(conn):
    return conn.query(
        """
        SELECT
            MIN(ordertimestamp)::date AS min_date,
            MAX(ordertimestamp)::date AS max_date
        FROM webshop."order"
        """,
        ttl=3600,
    ).iloc[0]


def render_sidebar_filters(conn, key_prefix):
    bounds = get_dataset_bounds(conn)
    min_date = bounds["min_date"]
    max_date = bounds["max_date"]

    categories = conn.query(
        "SELECT DISTINCT category::text AS category FROM webshop.products ORDER BY 1",
        ttl=3600,
    )["category"].tolist()
    labels = conn.query(
        "SELECT name FROM webshop.labels ORDER BY name",
        ttl=3600,
    )["name"].tolist()
    audiences = conn.query(
        """
        SELECT DISTINCT gender::text AS audience
        FROM webshop.products
        WHERE gender IS NOT NULL
        ORDER BY 1
        """,
        ttl=3600,
    )["audience"].tolist()

    st.sidebar.header("Filters")
    selected_dates = st.sidebar.date_input(
        "Order period",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        key=f"{key_prefix}_dates",
    )
    selected_categories = st.sidebar.multiselect(
        "Product categories",
        categories,
        default=categories,
        key=f"{key_prefix}_categories",
    )
    selected_labels = st.sidebar.multiselect(
        "Labels",
        labels,
        default=labels,
        key=f"{key_prefix}_labels",
    )
    selected_audiences = st.sidebar.multiselect(
        "Product audience",
        audiences,
        default=audiences,
        help="Target audience stored in the product data: female, male, or unisex.",
        key=f"{key_prefix}_audiences",
    )

    if len(selected_dates) == 2:
        date_from, date_to = selected_dates
    else:
        date_from = date_to = selected_dates[0]

    st.sidebar.caption(f"Dataset coverage: {min_date} to {max_date}")

    return {
        "date_from": date_from,
        "date_to": date_to,
        "categories": selected_categories,
        "labels": selected_labels,
        "audiences": selected_audiences,
    }


def sales_filter_sql(order_alias="o", product_alias="p", label_alias="l"):
    return f"""
        {order_alias}.ordertimestamp::date BETWEEN :date_from AND :date_to
        AND {product_alias}.category::text = ANY(CAST(:categories AS text[]))
        AND {product_alias}.gender::text = ANY(CAST(:audiences AS text[]))
        AND {label_alias}.name = ANY(CAST(:labels AS text[]))
    """


def filter_params(filters):
    return {
        "date_from": filters["date_from"],
        "date_to": filters["date_to"],
        "categories": filters["categories"],
        "labels": filters["labels"],
        "audiences": filters["audiences"],
    }
