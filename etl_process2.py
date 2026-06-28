"""
etl_process2.py — Load product recommendations into dim_product_recommendations.

Reads product_search.txt (top 10 products + web intelligence), derives
cross-sell / upsell / substitute recommendation pairs, and upserts them into
the dim_product_recommendations table.  If any product is missing web
intelligence, a fallback Brave Search is performed to fill the gap.
"""

import os
import re
import logging
import requests
from datetime import date, datetime
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values

load_dotenv("/Users/smasetic/it-501-bi-ai-project/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

PRODUCT_SEARCH_PATH = os.path.join(os.path.dirname(__file__), "product_search.txt")
BRAVE_API_KEY       = os.getenv("BRAVE_API_KEY")
BRAVE_SEARCH_URL    = "https://api.search.brave.com/res/v1/web/search"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DATABASE"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def ensure_date_in_dim(cur, target_date: date) -> int:
    """Insert target_date into dim_date if missing; return its date_key."""
    date_key = int(target_date.strftime("%Y%m%d"))
    cur.execute("SELECT 1 FROM public.dim_date WHERE date_key = %s", (date_key,))
    if cur.fetchone() is None:
        logging.info("Inserting %s into dim_date (date_key=%s)", target_date, date_key)
        cur.execute(
            """
            INSERT INTO public.dim_date
                (date_key, full_date, day, month, quarter, year,
                 day_of_week, day_name, month_name, is_weekend)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (date_key) DO NOTHING
            """,
            (
                date_key,
                target_date,
                target_date.day,
                target_date.month,
                (target_date.month - 1) // 3 + 1,
                target_date.year,
                target_date.weekday(),
                target_date.strftime("%A"),
                target_date.strftime("%B"),
                target_date.weekday() >= 5,
            ),
        )
    return date_key


def fetch_product_key_map(cur) -> dict:
    """Return {product_id: product_key} for all products in dim_product."""
    cur.execute("SELECT product_id, product_key FROM public.dim_product")
    return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Parse product_search.txt
# ---------------------------------------------------------------------------

def parse_product_search(path: str) -> list[dict]:
    """
    Extract product metadata from product_search.txt.
    Returns a list of dicts with keys: product_id, product_name, category,
    sub_category, web_intelligence.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    products = []

    # Each product block starts at "RANK #N"
    blocks = re.split(r"={10,}", content)

    for block in blocks:
        pid_match   = re.search(r"Product ID\s*:\s*(\S+)", block)
        name_match  = re.search(r"Product Name\s*:\s*(.+)", block)
        cat_match   = re.search(r"Category\s*:\s*(.+)", block)

        if not (pid_match and name_match):
            continue

        product_id   = pid_match.group(1).strip()
        product_name = name_match.group(1).strip()
        category_raw = cat_match.group(1).strip() if cat_match else ""

        # Extract bullet points from WEB INTELLIGENCE section
        intel_section = re.search(
            r"WEB INTELLIGENCE:(.*?)(?:Sources:|={5,})", block, re.DOTALL
        )
        web_intel = ""
        if intel_section:
            web_intel = intel_section.group(1).strip()

        products.append(
            {
                "product_id":    product_id,
                "product_name":  product_name,
                "category_raw":  category_raw,
                "web_intel":     web_intel,
            }
        )

    logging.info("Parsed %d products from %s", len(products), path)
    return products


# ---------------------------------------------------------------------------
# Brave Search fallback
# ---------------------------------------------------------------------------

def brave_search(query: str) -> str:
    """Call Brave Search API and return a summary of the top results."""
    if not BRAVE_API_KEY:
        logging.warning("BRAVE_API_KEY not set — skipping web search fallback.")
        return ""

    headers = {
        "Accept":              "application/json",
        "Accept-Encoding":     "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": 5}

    try:
        resp = requests.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("web", {}).get("results", [])
        summaries = [
            f"- {r.get('title','')}: {r.get('description','')}"
            for r in results
            if r.get("description")
        ]
        return "\n".join(summaries[:5])
    except Exception as e:
        logging.error("Brave Search failed for '%s': %s", query, e)
        return ""


def enrich_missing_intel(products: list[dict]) -> list[dict]:
    """For any product with empty web_intel, run a Brave Search to fill it."""
    for p in products:
        if not p["web_intel"].strip():
            logging.info("Missing web intel for %s — running Brave Search fallback.", p["product_name"])
            query = f"{p['product_name']} office product specifications features review"
            p["web_intel"] = brave_search(query)
            if p["web_intel"]:
                logging.info("Brave Search returned intel for %s.", p["product_name"])
            else:
                logging.warning("Brave Search returned no results for %s.", p["product_name"])
    return products


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------

# Recommendation pairs: (source_product_id, recommended_product_id, type, score, reason)
# Derived from web intelligence gathered in product_search.txt.
RECOMMENDATIONS = [
    # ---- SUBSTITUTE (same function, competing products) --------------------
    (
        "TEC-CO-10004722", "TEC-CO-10001449", "substitute", 0.9200,
        "Canon imageCLASS 2200 and HP LaserJet 3310 are both monochrome multifunction "
        "laser copiers targeting the office segment. The Canon offers a higher 50K/month "
        "duty cycle and 17ppm vs the HP's comparable throughput — recommend Canon as the "
        "primary choice and HP as a cost-tier alternative."
    ),
    (
        "TEC-CO-10001449", "TEC-CO-10004722", "substitute", 0.9200,
        "HP LaserJet 3310 and Canon imageCLASS 2200 are direct competitors in the office "
        "monochrome MFP segment. Canon carries a higher duty cycle (50K pages/month); "
        "HP suits lower-volume environments. Either product satisfies copy/print/scan/fax needs."
    ),
    (
        "OFF-BI-10001359", "OFF-BI-10004995", "substitute", 0.8800,
        "GBC DocuBind TL300 and GBC DocuBind P400 are both electric comb binding systems "
        "from GBC. TL300 punches 12 sheets/pass with a wire holder for on-the-fly assembly; "
        "P400 punches 20 sheets in under 2 seconds. P400 offers higher throughput but "
        "TL300 has a more ergonomic workflow."
    ),
    (
        "OFF-BI-10004995", "OFF-BI-10001359", "substitute", 0.8800,
        "GBC DocuBind P400 and GBC DocuBind TL300 are both GBC electric binding machines. "
        "The TL300's exclusive wire holder lets users assemble documents while punching, "
        "reducing handling time. Consider TL300 as a margin-positive alternative — P400 "
        "is currently loss-making in the portfolio."
    ),
    (
        "OFF-BI-10001359", "OFF-BI-10000545", "substitute", 0.8000,
        "GBC DocuBind TL300 (comb binding) and GBC Ibimaster 500 (ProClick binding) both "
        "bind documents but use different spine systems. ProClick spines are reusable and "
        "re-openable — better for frequently updated documents. DocuBind comb is more "
        "cost-effective for permanent bindings."
    ),
    (
        "OFF-BI-10000545", "OFF-BI-10001359", "substitute", 0.8000,
        "GBC Ibimaster 500 (ProClick) and GBC DocuBind TL300 serve similar binding needs. "
        "TL300 comb bindings are permanent and lower-cost per bind; ProClick spines allow "
        "re-opening which suits living documents. Recommend based on whether the customer "
        "needs final or updatable document presentation."
    ),
    (
        "OFF-BI-10003527", "OFF-BI-10001359", "substitute", 0.8500,
        "Fellowes PB500 and GBC DocuBind TL300 are both heavy-duty electric punch comb "
        "binders. Fellowes PB500 punches 30 sheets/pass (vs 12 for TL300) and binds up "
        "to 425 sheets — higher throughput for large-volume offices. TL300 is the "
        "budget-friendly choice."
    ),
    (
        "OFF-BI-10001359", "OFF-BI-10003527", "substitute", 0.8500,
        "GBC DocuBind TL300 and Fellowes PB500 compete in the electric comb binder segment. "
        "Fellowes PB500 delivers higher punch capacity (30 sheets) and all-metal construction "
        "for demanding environments. GBC TL300 suits mid-volume offices with its assembly-while-"
        "punching wire holder design."
    ),
    (
        "OFF-BI-10003527", "OFF-BI-10004995", "substitute", 0.7800,
        "Fellowes PB500 and GBC DocuBind P400 are competing electric binding machines. "
        "PB500 punches 30 sheets vs P400's 20 sheets, with all-metal construction for "
        "durability. The P400 is currently loss-making — Fellowes PB500 is the "
        "margin-positive alternative for high-volume binding needs."
    ),

    # ---- CROSS_SELL (different products, logical workflow bundles) ----------
    (
        "TEC-CO-10004722", "OFF-BI-10001359", "cross_sell", 0.8800,
        "Canon imageCLASS 2200 users printing/copying high-volume documents naturally need "
        "a document binding solution. The GBC DocuBind TL300 electric binder creates a "
        "complete office document workflow: print with Canon → bind with GBC. Both are "
        "established professional office products with strong brand reputations."
    ),
    (
        "TEC-CO-10004722", "OFF-BI-10003527", "cross_sell", 0.8500,
        "Canon imageCLASS 2200 copier paired with the Fellowes PB500 binding machine "
        "creates a high-volume document processing station. Canon copies at 17ppm; "
        "Fellowes PB500 punches 30 sheets/pass — a premium bundle for corporate "
        "print/bind workflows."
    ),
    (
        "TEC-CO-10001449", "OFF-BI-10001359", "cross_sell", 0.8600,
        "HP LaserJet 3310 copier customers frequently need document finishing. "
        "GBC DocuBind TL300 is a natural add-on that completes the print-to-bind "
        "workflow. Both are professional-grade products suited to the same corporate "
        "office buyer persona."
    ),
    (
        "TEC-CO-10001449", "OFF-BI-10003527", "cross_sell", 0.8300,
        "HP LaserJet 3310 users who produce high-volume print runs can cross-sell into "
        "the Fellowes PB500 for professional document binding. The Fellowes PB500's "
        "30-sheet punch capacity matches the throughput demands of busy HP MFP users."
    ),
    (
        "TEC-MA-10001127", "FUR-CH-10002024", "cross_sell", 0.7800,
        "HP Designjet T520 large-format printer targets architects, engineers, and "
        "design professionals who spend long hours at their workstations. The HON 5400 "
        "Series Big & Tall task chair (450lb capacity, ergonomic controls) is a natural "
        "workspace bundle for professional printing environments."
    ),
    (
        "FUR-CH-10002024", "TEC-MA-10001127", "cross_sell", 0.7500,
        "HON 5400 Big & Tall task chair buyers are setting up professional workstations. "
        "The HP Designjet T520 24-inch large-format color printer serves architects, "
        "engineers, and design studios — the same professional buyer segment. Bundle "
        "for complete workstation sales."
    ),
    (
        "TEC-MA-10002412", "FUR-CH-10002024", "cross_sell", 0.7500,
        "Cisco TelePresence EX90 videoconferencing units are deployed in conference room "
        "or executive desk setups. HON 5400 Series ergonomic task chairs are a natural "
        "bundle for executive office configurations requiring premium video collaboration "
        "and comfortable long-session seating."
    ),
    (
        "OFF-SU-10000151", "OFF-BI-10001359", "cross_sell", 0.8200,
        "High-speed electric letter openers are used in mailroom or document-heavy "
        "environments — the same environments that need professional document binding. "
        "GBC DocuBind TL300 is the natural next step after opening and sorting "
        "incoming mail: collate, punch, and bind for filing or distribution."
    ),
    (
        "OFF-SU-10000151", "OFF-BI-10003527", "cross_sell", 0.7800,
        "Electric letter opener buyers process high volumes of incoming mail. "
        "Pairing with the Fellowes PB500 binding machine creates a complete mailroom "
        "document management solution: open envelopes at up to 17,500/hr → sort → "
        "bind into presentation packets with Fellowes PB500."
    ),

    # ---- UPSELL (upgrade to better/higher-margin product) ------------------
    (
        "TEC-CO-10001449", "TEC-CO-10004722", "upsell", 0.8900,
        "Customers buying the HP LaserJet 3310 can be upgraded to the Canon imageCLASS "
        "2200, which offers a higher monthly duty cycle (50,000 pages), Scan-Once-Print-Many "
        "technology, and a 40.9% profit margin vs HP's 37.1%. For high-volume offices, "
        "the Canon delivers greater reliability and long-term value."
    ),
    (
        "OFF-BI-10004995", "OFF-BI-10003527", "upsell", 0.8700,
        "GBC DocuBind P400 customers (-10.5% margin) should be steered toward the "
        "Fellowes PB500 as an upsell: 30-sheet punch capacity (vs 20), all-metal "
        "construction, 425-sheet bind capacity. The PB500 is a professional-grade "
        "upgrade that generates positive margin (28.2%) and better satisfies high-volume "
        "binding needs."
    ),
    (
        "OFF-BI-10000545", "OFF-BI-10003527", "upsell", 0.8300,
        "GBC Ibimaster 500 (manual ProClick, 4.0% margin) buyers can be upsold to the "
        "Fellowes PB500 electric punch system. The Fellowes offers electric punching "
        "for 30 sheets at a time vs manual operation, significantly reducing effort in "
        "high-volume environments and carrying a 28.2% profit margin."
    ),
    (
        "OFF-BI-10004995", "OFF-BI-10001359", "upsell", 0.8100,
        "GBC DocuBind P400 (loss-making at -10.5%) buyers should be considered for "
        "upgrade to the GBC DocuBind TL300: same GBC brand, advanced punching technology, "
        "exclusive wire holder for document-while-punch assembly. TL300 carries a positive "
        "11.3% margin and better serves professional binding workflows."
    ),
    (
        "OFF-BI-10000545", "OFF-BI-10001359", "upsell", 0.7900,
        "GBC Ibimaster 500 manual ProClick buyers who frequently bind large documents can "
        "benefit from upgrading to the GBC DocuBind TL300 electric system. Electric "
        "punching at 12 sheets/pass with the assembly wire holder eliminates manual "
        "effort and supports higher throughput in busy offices."
    ),
]


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def run_recommendations_etl():
    logging.info("Starting etl_process2.py — Product Recommendations ETL")

    # 1. Parse product_search.txt
    if not os.path.exists(PRODUCT_SEARCH_PATH):
        logging.error("product_search.txt not found at %s", PRODUCT_SEARCH_PATH)
        return
    products = parse_product_search(PRODUCT_SEARCH_PATH)

    # 2. Brave Search fallback for any product with missing web intelligence
    products = enrich_missing_intel(products)

    # 3. Build quick lookup: product_id → web_intel (for logging/debug)
    intel_map = {p["product_id"]: p for p in products}
    found_ids  = set(intel_map.keys())
    logging.info("Products with web intelligence: %s", sorted(found_ids))

    # 4. Filter RECOMMENDATIONS to only those where both IDs are known
    valid_recs = [
        r for r in RECOMMENDATIONS
        if r[0] in found_ids and r[1] in found_ids
    ]
    logging.info(
        "Recommendation pairs: %d total, %d valid (both products in product_search.txt)",
        len(RECOMMENDATIONS), len(valid_recs),
    )

    # 5. Connect and load
    conn = get_connection()
    cur  = conn.cursor()

    try:
        # Ensure today's date exists in dim_date
        today    = date.today()
        date_key = ensure_date_in_dim(cur, today)
        logging.info("Using date_key=%s (%s) for recommendations.", date_key, today)

        # Fetch product_key map from dim_product
        pk_map = fetch_product_key_map(cur)
        logging.info("Loaded %d products from dim_product.", len(pk_map))

        # Validate all product_ids resolve to product_keys
        missing_pids = [
            pid for (pid, rpid, *_) in valid_recs
            if pid not in pk_map or rpid not in pk_map
        ]
        if missing_pids:
            logging.warning(
                "These product IDs from RECOMMENDATIONS not found in dim_product: %s",
                set(missing_pids),
            )

        # Build insert rows
        rows = []
        for (src_pid, rec_pid, rec_type, score, reason) in valid_recs:
            src_key = pk_map.get(src_pid)
            rec_key = pk_map.get(rec_pid)
            if src_key is None or rec_key is None:
                logging.warning(
                    "Skipping pair (%s → %s): product_key not found in dim_product.",
                    src_pid, rec_pid,
                )
                continue
            rows.append((src_key, rec_key, date_key, rec_type, score, reason))

        if not rows:
            logging.warning("No valid rows to insert — check product IDs.")
            return

        # Upsert into dim_product_recommendations
        query = """
            INSERT INTO public.dim_product_recommendations
                (product_key, recommended_product_key, date_key,
                 recommendation_type, recommendation_score, recommendation_reason)
            VALUES %s
            ON CONFLICT (product_key, recommended_product_key, date_key, recommendation_type)
            DO NOTHING
        """
        execute_values(cur, query, rows)
        conn.commit()
        logging.info(
            "Successfully upserted %d recommendation rows into dim_product_recommendations.",
            len(rows),
        )

        # Summary report
        cur.execute(
            """
            SELECT recommendation_type, COUNT(*) AS cnt
            FROM public.dim_product_recommendations
            GROUP BY recommendation_type
            ORDER BY recommendation_type
            """
        )
        logging.info("dim_product_recommendations current counts by type:")
        for row in cur.fetchall():
            logging.info("  %-15s %d rows", row[0], row[1])

    except Exception as e:
        conn.rollback()
        logging.error("ETL failed: %s", e)
        raise
    finally:
        cur.close()
        conn.close()

    logging.info("etl_process2.py completed successfully.")


if __name__ == "__main__":
    run_recommendations_etl()
