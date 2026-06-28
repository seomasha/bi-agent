import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

CSV_PATH = os.path.join(os.path.dirname(__file__), "Sample - Superstore.csv")
BATCH_SIZE = 1000


def get_connection():
    """Establish a connection to the PostgreSQL database."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DATABASE"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def load_csv(path: str) -> pd.DataFrame:
    """Load the Superstore CSV with UTF-8 fallback to latin-1."""
    for encoding in ("utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=encoding)
            logging.info(f"Loaded CSV with encoding={encoding}: {len(df)} rows, {len(df.columns)} columns")
            return df
        except (UnicodeDecodeError, Exception) as e:
            # Pandas may raise a generic Exception wrapping a codec error
            if "codec" in str(e).lower() or "decode" in str(e).lower() or "unicode" in str(e).lower():
                logging.warning(f"Encoding {encoding} failed, trying next…")
                continue
            raise  # re-raise non-encoding errors immediately
    raise RuntimeError(f"Could not decode {path} with utf-8 or latin-1")


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Parse dates, drop nulls on key columns, clean up types."""
    df = df.drop_duplicates()

    # Parse date columns
    df["Order Date"] = pd.to_datetime(df["Order Date"], format="%m/%d/%Y", errors="coerce")
    df["Ship Date"]  = pd.to_datetime(df["Ship Date"],  format="%m/%d/%Y", errors="coerce")

    # Drop rows missing critical keys
    before = len(df)
    df = df.dropna(subset=["Order Date", "Ship Date", "Customer ID", "Product ID"])
    dropped = before - len(df)
    if dropped:
        logging.warning(f"Dropped {dropped} rows with null Order Date / Ship Date / Customer ID / Product ID")

    # Integer date keys (YYYYMMDD)
    df["order_date_key"] = df["Order Date"].dt.strftime("%Y%m%d").astype(int)
    df["ship_date_key"]  = df["Ship Date"].dt.strftime("%Y%m%d").astype(int)

    # Normalise string columns
    df["Customer ID"]   = df["Customer ID"].str.strip()
    df["Product ID"]    = df["Product ID"].str.strip()
    df["Ship Mode"]     = df["Ship Mode"].str.strip()
    df["Postal Code"]   = df["Postal Code"].astype(str).str.strip()

    logging.info(f"Clean dataset: {len(df)} rows")
    return df


def insert_batches(cur, query: str, data: list, batch_size: int = BATCH_SIZE, table_name: str = ""):
    """Insert data in batches via execute_values."""
    total = len(data)
    if total == 0:
        logging.info(f"No data to insert into {table_name}.")
        return
    for i in range(0, total, batch_size):
        batch = data[i : i + batch_size]
        execute_values(cur, query, batch)
        logging.info(f"  {table_name}: {min(i + batch_size, total)}/{total} rows inserted")


# ---------------------------------------------------------------------------
# Dimension loaders
# ---------------------------------------------------------------------------

def load_dim_date(cur, df: pd.DataFrame) -> None:
    """Populate dim_date from all unique order/ship dates."""
    all_dates = pd.concat([df["Order Date"], df["Ship Date"]]).drop_duplicates().dropna()

    date_rows = []
    for d in all_dates:
        date_rows.append((
            int(d.strftime("%Y%m%d")),   # date_key
            d.date(),                     # full_date
            int(d.day),                   # day
            int(d.month),                 # month
            int(d.quarter),               # quarter
            int(d.year),                  # year
            int(d.dayofweek),             # day_of_week (0=Mon … 6=Sun)
            d.strftime("%A"),             # day_name
            d.strftime("%B"),             # month_name
            d.dayofweek >= 5,             # is_weekend
        ))

    insert_batches(cur, """
        INSERT INTO public.dim_date
            (date_key, full_date, day, month, quarter, year,
             day_of_week, day_name, month_name, is_weekend)
        VALUES %s
        ON CONFLICT (date_key) DO NOTHING
    """, date_rows, table_name="dim_date")


def load_dim_customer(cur, df: pd.DataFrame) -> None:
    """Populate dim_customer."""
    customers = (
        df[["Customer ID", "Customer Name", "Segment"]]
        .drop_duplicates(subset=["Customer ID"])
        .dropna(subset=["Customer ID"])
    )
    rows = [
        (row["Customer ID"], row["Customer Name"], row["Segment"])
        for _, row in customers.iterrows()
    ]
    insert_batches(cur, """
        INSERT INTO public.dim_customer (customer_id, customer_name, segment)
        VALUES %s
        ON CONFLICT (customer_id) DO UPDATE
            SET customer_name = EXCLUDED.customer_name,
                segment       = EXCLUDED.segment
    """, rows, table_name="dim_customer")


def load_dim_geography(cur, df: pd.DataFrame) -> None:
    """Populate dim_geography."""
    geo = (
        df[["Postal Code", "City", "State", "Country", "Region"]]
        .drop_duplicates(subset=["Postal Code", "City", "State"])
    )
    rows = [
        (row["Postal Code"], row["City"], row["State"], row["Country"], row["Region"])
        for _, row in geo.iterrows()
    ]
    insert_batches(cur, """
        INSERT INTO public.dim_geography (postal_code, city, state, country, region)
        VALUES %s
        ON CONFLICT (postal_code, city, state) DO NOTHING
    """, rows, table_name="dim_geography")


def load_dim_product(cur, df: pd.DataFrame) -> None:
    """Populate dim_product."""
    products = (
        df[["Product ID", "Product Name", "Category", "Sub-Category"]]
        .drop_duplicates(subset=["Product ID"])
        .dropna(subset=["Product ID"])
    )
    rows = [
        (row["Product ID"], row["Product Name"], row["Category"], row["Sub-Category"])
        for _, row in products.iterrows()
    ]
    insert_batches(cur, """
        INSERT INTO public.dim_product (product_id, product_name, category, sub_category)
        VALUES %s
        ON CONFLICT (product_id) DO UPDATE
            SET product_name = EXCLUDED.product_name,
                category     = EXCLUDED.category,
                sub_category = EXCLUDED.sub_category
    """, rows, table_name="dim_product")


def load_dim_ship_mode(cur, df: pd.DataFrame) -> None:
    """Populate dim_ship_mode."""
    modes = df["Ship Mode"].drop_duplicates().dropna().tolist()
    rows = [(m,) for m in modes]
    insert_batches(cur, """
        INSERT INTO public.dim_ship_mode (ship_mode)
        VALUES %s
        ON CONFLICT (ship_mode) DO NOTHING
    """, rows, table_name="dim_ship_mode")


# ---------------------------------------------------------------------------
# Surrogate key maps
# ---------------------------------------------------------------------------

def build_lookup_maps(cur) -> dict:
    """Fetch surrogate key maps from all dimension tables."""
    maps = {}

    cur.execute("SELECT date_key FROM public.dim_date")
    maps["date"] = {row[0]: row[0] for row in cur.fetchall()}  # key == value (YYYYMMDD IS the key)

    cur.execute("SELECT customer_key, customer_id FROM public.dim_customer")
    maps["customer"] = {row[1]: row[0] for row in cur.fetchall()}

    cur.execute("SELECT geography_key, postal_code, city, state FROM public.dim_geography")
    maps["geography"] = {(row[1], row[2], row[3]): row[0] for row in cur.fetchall()}

    cur.execute("SELECT product_key, product_id FROM public.dim_product")
    maps["product"] = {row[1]: row[0] for row in cur.fetchall()}

    cur.execute("SELECT ship_mode_key, ship_mode FROM public.dim_ship_mode")
    maps["ship_mode"] = {row[1]: row[0] for row in cur.fetchall()}

    logging.info(
        f"Lookup maps built — dates: {len(maps['date'])}, customers: {len(maps['customer'])}, "
        f"geographies: {len(maps['geography'])}, products: {len(maps['product'])}, "
        f"ship_modes: {len(maps['ship_mode'])}"
    )
    return maps


# ---------------------------------------------------------------------------
# Main ETL orchestrator
# ---------------------------------------------------------------------------

def run_etl():
    logging.info("=== Superstore ETL — starting ===")

    # 1. Load & clean source data
    df = load_csv(CSV_PATH)
    df = clean_dataframe(df)

    # Rename columns to safe attribute names for itertuples later
    # (pandas replaces spaces with underscores when accessing via namedtuple)
    # We need the originals for dict lookups, so we work on a renamed copy only for facts.

    conn = get_connection()
    cur = conn.cursor()

    try:
        # 2. Load dimensions (order matters for FK references)
        logging.info("--- Loading dim_date ---")
        load_dim_date(cur, df)

        logging.info("--- Loading dim_customer ---")
        load_dim_customer(cur, df)

        logging.info("--- Loading dim_geography ---")
        load_dim_geography(cur, df)

        logging.info("--- Loading dim_product ---")
        load_dim_product(cur, df)

        logging.info("--- Loading dim_ship_mode ---")
        load_dim_ship_mode(cur, df)

        conn.commit()
        logging.info("All dimensions committed.")

        # 3. Build surrogate key lookup maps
        logging.info("--- Building surrogate key maps ---")
        maps = build_lookup_maps(cur)

        # 4. Prepare a column-renamed copy for safe itertuples access
        fact_df = df.rename(columns={
            "Row ID":        "Row_ID",
            "Order ID":      "Order_ID",
            "Ship Mode":     "Ship_Mode",
            "Customer ID":   "Customer_ID",
            "Customer Name": "Customer_Name",
            "Product ID":    "Product_ID",
            "Product Name":  "Product_Name",
            "Sub-Category":  "Sub_Category",
            "Postal Code":   "Postal_Code",
            "Order Date":    "Order_Date",
            "Ship Date":     "Ship_Date",
        })

        # Build fact rows directly from renamed df
        fact_rows = []
        skipped = 0

        for row in fact_df.itertuples(index=False):
            order_date_key = row.order_date_key
            ship_date_key  = row.ship_date_key
            customer_id    = row.Customer_ID
            product_id     = row.Product_ID
            ship_mode      = row.Ship_Mode
            postal_code    = str(row.Postal_Code)
            city           = row.City
            state          = row.State

            customer_key  = maps["customer"].get(customer_id)
            product_key   = maps["product"].get(product_id)
            geography_key = maps["geography"].get((postal_code, city, state))
            ship_mode_key = maps["ship_mode"].get(ship_mode)

            if None in (customer_key, product_key, geography_key, ship_mode_key):
                skipped += 1
                continue

            fact_rows.append((
                int(row.Row_ID),
                str(row.Order_ID),
                int(order_date_key),
                int(ship_date_key),
                int(ship_mode_key),
                int(customer_key),
                int(geography_key),
                int(product_key),
                float(row.Sales),
                int(row.Quantity),
                float(row.Discount),
                float(row.Profit),
            ))

        if skipped:
            logging.warning(f"Skipped {skipped} fact rows due to unresolved FK lookups")

        logging.info(f"--- Loading fact_orders ({len(fact_rows)} rows) ---")
        insert_batches(cur, """
            INSERT INTO public.fact_orders
                (row_id, order_id, order_date_key, ship_date_key, ship_mode_key,
                 customer_key, geography_key, product_key,
                 sales, quantity, discount, profit)
            VALUES %s
            ON CONFLICT (row_id) DO NOTHING
        """, fact_rows, table_name="fact_orders")

        conn.commit()
        logging.info("=== ETL completed successfully ===")

    except Exception as e:
        conn.rollback()
        logging.error(f"ETL failed — rolled back. Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run_etl()
