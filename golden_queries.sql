-- =============================================================================
-- Superstore Data Warehouse — Golden Queries
-- 10 benchmark NL→SQL pairs used to evaluate BI agent performance.
-- Each query is valid PostgreSQL against the star schema in schema.sql.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- GQ-01  SIMPLE AGGREGATION
-- Business Question:
--   What is the total revenue, total profit, and overall profit margin
--   across all orders?
-- Business Purpose:
--   Top-level KPI snapshot — the first number any executive asks for.
-- -----------------------------------------------------------------------------
SELECT
    ROUND(SUM(sales)::NUMERIC,        2) AS total_revenue,
    ROUND(SUM(profit)::NUMERIC,       2) AS total_profit,
    ROUND((SUM(profit) / NULLIF(SUM(sales), 0) * 100)::NUMERIC, 2) AS profit_margin_pct
FROM public.fact_orders;


-- -----------------------------------------------------------------------------
-- GQ-02  GROUP BY — SINGLE DIMENSION
-- Business Question:
--   Which product category generates the most revenue and which is the
--   most profitable?  Show revenue, profit, and margin per category.
-- Business Purpose:
--   Guides portfolio investment — know where to push growth vs. fix margins.
-- -----------------------------------------------------------------------------
SELECT
    p.category,
    ROUND(SUM(fo.sales)::NUMERIC,   2) AS total_revenue,
    ROUND(SUM(fo.profit)::NUMERIC,  2) AS total_profit,
    ROUND((SUM(fo.profit) / NULLIF(SUM(fo.sales), 0) * 100)::NUMERIC, 2) AS profit_margin_pct
FROM public.fact_orders fo
JOIN public.dim_product p ON fo.product_key = p.product_key
GROUP BY p.category
ORDER BY total_revenue DESC;


-- -----------------------------------------------------------------------------
-- GQ-03  GROUP BY — MULTI-DIMENSION WITH RANKING
-- Business Question:
--   Who are the top 10 customers by total profit, and what segment do
--   they belong to?
-- Business Purpose:
--   Identifies high-value customers for retention and upsell programs.
-- -----------------------------------------------------------------------------
SELECT
    c.customer_name,
    c.segment,
    ROUND(SUM(fo.profit)::NUMERIC, 2) AS total_profit,
    ROUND(SUM(fo.sales)::NUMERIC,  2) AS total_revenue,
    COUNT(DISTINCT fo.order_id)        AS number_of_orders
FROM public.fact_orders fo
JOIN public.dim_customer c ON fo.customer_key = c.customer_key
GROUP BY c.customer_name, c.segment
ORDER BY total_profit DESC
LIMIT 10;


-- -----------------------------------------------------------------------------
-- GQ-04  TIME-SERIES — YEAR-OVER-YEAR TREND
-- Business Question:
--   How have annual sales and profit changed year over year?
--   Show the percentage change from the prior year.
-- Business Purpose:
--   Reveals growth trajectory and whether profitability tracks revenue.
-- -----------------------------------------------------------------------------
WITH yearly AS (
    SELECT
        d.year,
        SUM(fo.sales)  AS revenue,
        SUM(fo.profit) AS profit
    FROM public.fact_orders fo
    JOIN public.dim_date d ON fo.order_date_key = d.date_key
    GROUP BY d.year
)
SELECT
    year,
    ROUND(revenue::NUMERIC, 2)  AS total_revenue,
    ROUND(profit::NUMERIC, 2)   AS total_profit,
    ROUND(
        (revenue - LAG(revenue) OVER (ORDER BY year))
        / NULLIF(LAG(revenue) OVER (ORDER BY year), 0) * 100, 2
    ) AS revenue_yoy_pct_change,
    ROUND(
        (profit - LAG(profit) OVER (ORDER BY year))
        / NULLIF(LAG(profit) OVER (ORDER BY year), 0) * 100, 2
    ) AS profit_yoy_pct_change
FROM yearly
ORDER BY year;


-- -----------------------------------------------------------------------------
-- GQ-05  GEOGRAPHY — REGIONAL PERFORMANCE
-- Business Question:
--   Which US states have a negative total profit (loss-making states),
--   and how large are the losses?
-- Business Purpose:
--   Pinpoints geographic markets that are destroying value — prime targets
--   for pricing, discount, or exit decisions.
-- -----------------------------------------------------------------------------
SELECT
    g.state,
    g.region,
    ROUND(SUM(fo.sales)::NUMERIC,  2) AS total_revenue,
    ROUND(SUM(fo.profit)::NUMERIC, 2) AS total_profit,
    COUNT(DISTINCT fo.order_id)        AS order_count
FROM public.fact_orders fo
JOIN public.dim_geography g ON fo.geography_key = g.geography_key
GROUP BY g.state, g.region
HAVING SUM(fo.profit) < 0
ORDER BY total_profit ASC;


-- -----------------------------------------------------------------------------
-- GQ-06  PRODUCT — SUB-CATEGORY DEEP DIVE WITH DISCOUNT ANALYSIS
-- Business Question:
--   For each product sub-category, what is the average discount granted
--   and the resulting profit margin?  Show them sorted by margin ascending
--   so the most discounted/unprofitable sub-categories surface first.
-- Business Purpose:
--   Exposes where excessive discounting erodes margins — input for pricing
--   policy and sales incentive redesign.
-- -----------------------------------------------------------------------------
SELECT
    p.category,
    p.sub_category,
    ROUND(AVG(fo.discount) * 100, 2)                                     AS avg_discount_pct,
    ROUND(SUM(fo.sales)::NUMERIC, 2)                                     AS total_revenue,
    ROUND(SUM(fo.profit)::NUMERIC, 2)                                    AS total_profit,
    ROUND((SUM(fo.profit) / NULLIF(SUM(fo.sales), 0) * 100)::NUMERIC, 2) AS profit_margin_pct
FROM public.fact_orders fo
JOIN public.dim_product p ON fo.product_key = p.product_key
GROUP BY p.category, p.sub_category
ORDER BY profit_margin_pct ASC;


-- -----------------------------------------------------------------------------
-- GQ-07  SHIPPING — MODE EFFICIENCY & COST IMPACT
-- Business Question:
--   How does shipping mode affect order profitability?  Show average profit
--   per order line, average days to ship, and total order count for each
--   shipping mode.
-- Business Purpose:
--   Informs fulfilment strategy — balancing customer SLA expectations against
--   the margin impact of faster shipping options.
-- -----------------------------------------------------------------------------
SELECT
    sm.ship_mode,
    COUNT(*)                                                           AS order_line_count,
    COUNT(DISTINCT fo.order_id)                                        AS unique_orders,
    ROUND(AVG(fo.profit)::NUMERIC, 2)                                  AS avg_profit_per_line,
    ROUND(AVG(fo.sales)::NUMERIC,  2)                                  AS avg_revenue_per_line,
    ROUND(AVG(
        (ship_d.full_date - order_d.full_date)
    )::NUMERIC, 1)                                                     AS avg_days_to_ship
FROM public.fact_orders fo
JOIN public.dim_ship_mode sm    ON fo.ship_mode_key   = sm.ship_mode_key
JOIN public.dim_date      order_d ON fo.order_date_key = order_d.date_key
JOIN public.dim_date      ship_d  ON fo.ship_date_key  = ship_d.date_key
GROUP BY sm.ship_mode
ORDER BY avg_profit_per_line DESC;


-- -----------------------------------------------------------------------------
-- GQ-08  CUSTOMER SEGMENT — QUARTERLY REVENUE TREND
-- Business Question:
--   How does quarterly revenue break down across customer segments
--   (Consumer, Corporate, Home Office) over time?
-- Business Purpose:
--   Tracks segment mix shift over time — critical input for marketing budget
--   allocation and segment-specific strategy pivots.
-- -----------------------------------------------------------------------------
SELECT
    d.year,
    d.quarter,
    c.segment,
    ROUND(SUM(fo.sales)::NUMERIC,  2) AS total_revenue,
    ROUND(SUM(fo.profit)::NUMERIC, 2) AS total_profit,
    COUNT(DISTINCT fo.order_id)        AS order_count
FROM public.fact_orders fo
JOIN public.dim_date     d ON fo.order_date_key = d.date_key
JOIN public.dim_customer c ON fo.customer_key   = c.customer_key
GROUP BY d.year, d.quarter, c.segment
ORDER BY d.year, d.quarter, c.segment;


-- -----------------------------------------------------------------------------
-- GQ-09  SUBQUERY / CTE — TOP PRODUCT PER CATEGORY
-- Business Question:
--   What is the single best-selling product (by revenue) within each
--   product category?
-- Business Purpose:
--   Surfaces star products driving category performance — useful for
--   featuring in promotions, ensuring stock availability, and benchmarking.
-- -----------------------------------------------------------------------------
WITH product_revenue AS (
    SELECT
        p.category,
        p.product_name,
        ROUND(SUM(fo.sales)::NUMERIC,  2) AS total_revenue,
        ROUND(SUM(fo.profit)::NUMERIC, 2) AS total_profit,
        SUM(fo.quantity)                   AS total_units_sold
    FROM public.fact_orders fo
    JOIN public.dim_product p ON fo.product_key = p.product_key
    GROUP BY p.category, p.product_name
),
ranked AS (
    SELECT *,
           RANK() OVER (PARTITION BY category ORDER BY total_revenue DESC) AS revenue_rank
    FROM product_revenue
)
SELECT
    category,
    product_name,
    total_revenue,
    total_profit,
    total_units_sold
FROM ranked
WHERE revenue_rank = 1
ORDER BY total_revenue DESC;


-- -----------------------------------------------------------------------------
-- GQ-10  COMPLEX MULTI-JOIN — DISCOUNT THRESHOLD PROFITABILITY ANALYSIS
-- Business Question:
--   Compare the total profit and order count for order lines where the
--   discount is zero, moderate (1–20 %), or heavy (> 20 %), broken down
--   by customer segment and region.  Which discount-segment-region
--   combinations are most damaging to profit?
-- Business Purpose:
--   Quantifies the combined effect of discount depth, customer segment, and
--   geography on profitability — the most actionable input for a targeted
--   discount policy that protects margins without losing strategic customers.
-- -----------------------------------------------------------------------------
SELECT
    CASE
        WHEN fo.discount = 0              THEN 'No Discount'
        WHEN fo.discount <= 0.20          THEN 'Moderate (1–20%)'
        ELSE                                   'Heavy (>20%)'
    END                                             AS discount_tier,
    c.segment,
    g.region,
    COUNT(*)                                        AS order_line_count,
    ROUND(SUM(fo.sales)::NUMERIC,  2)               AS total_revenue,
    ROUND(SUM(fo.profit)::NUMERIC, 2)               AS total_profit,
    ROUND((SUM(fo.profit) / NULLIF(SUM(fo.sales), 0) * 100)::NUMERIC, 2) AS profit_margin_pct
FROM public.fact_orders fo
JOIN public.dim_customer  c  ON fo.customer_key  = c.customer_key
JOIN public.dim_geography g  ON fo.geography_key = g.geography_key
GROUP BY discount_tier, c.segment, g.region
ORDER BY total_profit ASC;
