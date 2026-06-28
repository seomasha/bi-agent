-- =============================================================================
-- Superstore Data Warehouse — Star Schema
-- PostgreSQL / Supabase-compatible
-- =============================================================================

-- ---------------------------------------------------------------------------
-- DIMENSION: dim_date
-- Covers Order Date and Ship Date (both date columns in the CSV).
-- A single shared date dimension avoids duplicating calendar logic.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.dim_date (
    date_key        INT PRIMARY KEY,          -- YYYYMMDD integer key for fast joins
    full_date       DATE        NOT NULL UNIQUE,
    day             SMALLINT    NOT NULL,
    month           SMALLINT    NOT NULL,
    quarter         SMALLINT    NOT NULL,
    year            SMALLINT    NOT NULL,
    day_of_week     SMALLINT    NOT NULL,     -- 0=Monday … 6=Sunday (Python convention)
    day_name        VARCHAR(10) NOT NULL,
    month_name      VARCHAR(10) NOT NULL,
    is_weekend      BOOLEAN     NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------------
-- DIMENSION: dim_customer
-- Natural key: customer_id (e.g. "CG-12520")
-- Segment (Consumer / Corporate / Home Office) lives here — it is a customer
-- attribute, not an order attribute.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.dim_customer (
    customer_key    SERIAL      PRIMARY KEY,
    customer_id     VARCHAR(20) NOT NULL UNIQUE,
    customer_name   VARCHAR(100) NOT NULL,
    segment         VARCHAR(50)  NOT NULL      -- Consumer | Corporate | Home Office
);

-- ---------------------------------------------------------------------------
-- DIMENSION: dim_geography
-- Captures the delivery/ship-to location.  City+State+Postal Code is the
-- natural grain; Region is a roll-up attribute added as a convenience column.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.dim_geography (
    geography_key   SERIAL      PRIMARY KEY,
    postal_code     VARCHAR(10),
    city            VARCHAR(100) NOT NULL,
    state           VARCHAR(100) NOT NULL,
    country         VARCHAR(100) NOT NULL DEFAULT 'United States',
    region          VARCHAR(50)  NOT NULL,     -- South | West | East | Central
    UNIQUE (postal_code, city, state)
);

-- ---------------------------------------------------------------------------
-- DIMENSION: dim_product
-- Three-level hierarchy: Category → Sub-Category → Product.
-- Natural key: product_id (e.g. "FUR-BO-10001798").
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.dim_product (
    product_key     SERIAL       PRIMARY KEY,
    product_id      VARCHAR(50)  NOT NULL UNIQUE,
    product_name    TEXT         NOT NULL,
    category        VARCHAR(50)  NOT NULL,     -- Furniture | Office Supplies | Technology
    sub_category    VARCHAR(50)  NOT NULL      -- Bookcases | Chairs | Labels | Tables …
);

-- ---------------------------------------------------------------------------
-- DIMENSION: dim_ship_mode
-- Small, slowly-changing set: Second Class | Standard Class | First Class |
-- Same Day.  Kept as its own dimension for clean normalisation and easy
-- filtering without string comparisons in the fact table.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.dim_ship_mode (
    ship_mode_key   SERIAL      PRIMARY KEY,
    ship_mode       VARCHAR(50) NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- FACT TABLE: fact_orders
-- Grain: one row per order line item (Row ID in the source CSV).
-- Additive measures: sales, quantity, discount, profit.
-- Two date FKs: order_date_key and ship_date_key.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.fact_orders (
    order_line_key  BIGSERIAL   PRIMARY KEY,

    -- Degenerate dimensions (no separate dim table needed)
    row_id          INT         NOT NULL,
    order_id        VARCHAR(20) NOT NULL,

    -- Foreign keys to dimensions
    order_date_key  INT         NOT NULL REFERENCES public.dim_date(date_key),
    ship_date_key   INT         NOT NULL REFERENCES public.dim_date(date_key),
    ship_mode_key   INT         NOT NULL REFERENCES public.dim_ship_mode(ship_mode_key),
    customer_key    INT         NOT NULL REFERENCES public.dim_customer(customer_key),
    geography_key   INT         NOT NULL REFERENCES public.dim_geography(geography_key),
    product_key     INT         NOT NULL REFERENCES public.dim_product(product_key),

    -- Measures (all additive)
    sales           NUMERIC(12, 4) NOT NULL,
    quantity        INT            NOT NULL,
    discount        NUMERIC(5, 4)  NOT NULL DEFAULT 0,
    profit          NUMERIC(12, 4) NOT NULL,

    -- Derived measure (stored for query convenience, redundant but common in DW)
    revenue_after_discount NUMERIC(12, 4) GENERATED ALWAYS AS (sales * (1 - discount)) STORED,

    -- Upsert safety: the source row_id is unique
    CONSTRAINT uq_fact_orders_row_id UNIQUE (row_id)
);

-- ---------------------------------------------------------------------------
-- INDEXES — on every FK column in the fact table for join performance
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_fact_order_date    ON public.fact_orders(order_date_key);
CREATE INDEX IF NOT EXISTS idx_fact_ship_date     ON public.fact_orders(ship_date_key);
CREATE INDEX IF NOT EXISTS idx_fact_ship_mode     ON public.fact_orders(ship_mode_key);
CREATE INDEX IF NOT EXISTS idx_fact_customer      ON public.fact_orders(customer_key);
CREATE INDEX IF NOT EXISTS idx_fact_geography     ON public.fact_orders(geography_key);
CREATE INDEX IF NOT EXISTS idx_fact_product       ON public.fact_orders(product_key);

-- Composite index for the most common BI query pattern: date + product
CREATE INDEX IF NOT EXISTS idx_fact_date_product  ON public.fact_orders(order_date_key, product_key);
