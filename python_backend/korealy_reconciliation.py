"""
Korealy Reconciliation Module
Compares Korealy supplier prices (from local CSV) with Shopify COGS
Identifies mismatches and enables syncing updates back to Shopify
"""

import os
import re
import time
import requests
import csv
from typing import List, Dict, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

# Shopify config
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN") or os.getenv("SHOPIFY_TOKEN")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07")

# Local CSV file for Korealy source
# Check environment variable first, then try price-bot folder, then fall back to local
KOREALY_CSV_PATH = os.getenv("KOREALY_CSV_PATH")
if not KOREALY_CSV_PATH:
    # Try price-bot location
    price_bot_path = os.path.expanduser("~/price-bot/Korealy Products - Prices.csv")
    if os.path.exists(price_bot_path):
        KOREALY_CSV_PATH = price_bot_path
    else:
        # Fall back to local python_backend folder
        KOREALY_CSV_PATH = os.path.join(os.path.dirname(__file__), "Korealy Products - Prices.csv")

# Regex patterns for parsing Korealy data
# Match prices with currency symbols: $, US$, USD, €, £
PRICE_RE = re.compile(r"(?:US?\$|\$|USD|€|£)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)")
PROD_ID_RE = re.compile(r"\bProduct\s*#\s*(\d+)\b", re.IGNORECASE)
PID_RE = re.compile(r"\bShop\s*PID\s*#\s*(\d+)\b", re.IGNORECASE)


def _shopify_graphql(query: str, variables: Optional[Dict] = None):
    """Execute Shopify GraphQL query"""
    if not SHOPIFY_STORE or not SHOPIFY_TOKEN:
        raise RuntimeError("Missing SHOPIFY_STORE or SHOPIFY_TOKEN")

    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": SHOPIFY_TOKEN
    }

    response = requests.post(
        url,
        json={"query": query, "variables": variables or {}},
        headers=headers,
        timeout=60
    )
    response.raise_for_status()
    data = response.json()

    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")

    return data


def fetch_shopify_variants_with_cogs() -> Dict[str, Dict[str, Any]]:
    """
    Fetch all product variants from Shopify with COGS data

    Returns:
        Dict mapping variant_gid -> {item, cogs, currency, variant_id}
    """
    variants = {}
    cursor = None

    query = """
    query($cursor: String) {
      productVariants(first: 200, after: $cursor) {
        pageInfo { hasNextPage }
        edges {
          cursor
          node {
            id
            sku
            title
            product {
              title
              status
            }
            inventoryItem {
              id
              unitCost {
                amount
                currencyCode
              }
            }
          }
        }
      }
    }
    """

    while True:
        try:
            result = _shopify_graphql(query, {"cursor": cursor})
            variants_data = result["data"]["productVariants"]

            for edge in variants_data["edges"]:
                node = edge["node"]

                # Build item name
                product_title = node["product"]["title"]
                variant_title = node["title"]
                item_name = f"{product_title} — {variant_title}".strip(" — ")

                # Get COGS
                cogs = 0.0
                currency = "USD"
                inv_item = node.get("inventoryItem") or {}
                uc = inv_item.get("unitCost")
                if uc:
                    cogs = float(uc.get("amount") or 0)
                    currency = uc.get("currencyCode", "USD")

                # Extract numeric variant ID from GID
                gid = node["id"]
                match = re.search(r'(\d+)$', gid)
                variant_id = match.group(1) if match else gid

                variants[gid] = {
                    "variant_id": variant_id,
                    "item": item_name,
                    "cogs": cogs,
                    "currency": currency,
                    "sku": node.get("sku", "")
                }

            if not variants_data["pageInfo"]["hasNextPage"]:
                break

            cursor = variants_data["edges"][-1]["cursor"]
            time.sleep(0.05)

        except Exception as e:
            print(f"❌ Error fetching Shopify variants: {e}")
            break

    return variants


def fetch_korealy_data_from_csv() -> List[List[str]]:
    """
    Read raw Korealy data from local CSV file

    Returns:
        2D list of cell values (each row contains one cell with the line content)
    """
    try:
        if not os.path.exists(KOREALY_CSV_PATH):
            raise RuntimeError(f"Korealy CSV file not found at: {KOREALY_CSV_PATH}")

        values = []
        with open(KOREALY_CSV_PATH, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                # CSV has one value per line, convert to list format parser expects
                if row:  # Skip empty rows
                    values.append([row[0]] if row else [''])

        print(f"✅ Fetched {len(values)} rows from Korealy CSV")
        return values

    except Exception as e:
        raise RuntimeError(f"Failed to read Korealy CSV: {e}")


def parse_korealy_sheet(values_2d: List[List[str]]) -> List[Dict[str, Any]]:
    """
    Parse Korealy sheet using improved state machine (matching price-bot logic)

    Open a new card when:
      1) first non-empty cell == 'Product Image'
      2) or first non-empty startswith 'Supplier' AND current card already had Supplier
      3) or a 'Product #' line appears while current card already had a Product #
      4) or a 'Shop PID #' line appears while current card already had a Shop PID

    Args:
        values_2d: 2D list of cell values from CSV

    Returns:
        List of dicts with keys: korealy_product_id, shop_pid, title, cogs, currency
    """
    # Regex for metadata lines to skip when finding title
    META_LINE_RE = re.compile(
        r"^(?:product\s*image|supplier\s*:|supplier$|product\s*#|shop\s*pid|product\s*id|shop\s*product\s*id)\b",
        re.IGNORECASE
    )

    def _first_nonempty_cell_lower(row: List[str]) -> str:
        for c in row or []:
            s = (c or "").strip()
            if s:
                return s.lower()
        return ""

    def _first_meaningful_title(lines: List[str]) -> Optional[str]:
        """Find first non-metadata line as title"""
        for ln in lines:
            s = (ln or "").strip()
            if not s:
                continue
            if META_LINE_RE.match(s):
                continue
            # Skip price-only lines
            if PRICE_RE.match(s):
                continue
            return s
        return None

    def detect_currency(text: str) -> str:
        """Detect currency from price string"""
        if "€" in text or "EUR" in text.upper():
            return "EUR"
        elif "£" in text or "GBP" in text.upper():
            return "GBP"
        else:
            return "USD"

    records = []

    # State for current card
    current_lines: List[str] = []
    seen_supplier = False
    seen_prod_id = False
    seen_pid = False

    starts_by = {"product_image": 0, "supplier_repeat": 0, "product_id_repeat": 0, "pid_repeat": 0}

    def push_block():
        """Save current card and reset state"""
        nonlocal current_lines, seen_supplier, seen_prod_id, seen_pid

        if not current_lines or all(not (ln or "").strip() for ln in current_lines):
            return

        text = "\n".join(current_lines)

        m_prod = PROD_ID_RE.search(text)
        m_pid = PID_RE.search(text)
        title = _first_meaningful_title(current_lines)

        price_val = None
        currency = None
        for ln in current_lines:
            for m in PRICE_RE.finditer(ln):
                raw = m.group(0)
                num = m.group(1)
                try:
                    price_val = float(num.replace(",", ""))
                    currency = detect_currency(raw)
                except Exception:
                    pass

        records.append({
            "korealy_product_id": m_prod.group(1) if m_prod else None,
            "shop_pid": m_pid.group(1) if m_pid else None,
            "title": title or None,
            "cogs": price_val,
            "currency": currency if price_val is not None else None,
        })

        # Reset state
        current_lines = []
        seen_supplier = False
        seen_prod_id = False
        seen_pid = False

    # Process each row
    for row in values_2d:
        first = _first_nonempty_cell_lower(row)
        cells = [c.strip() for c in (row or []) if (c or "").strip()]
        line = " | ".join(cells) if cells else ""

        # Boundary check: "Product Image"
        if first.startswith("product image"):
            push_block()
            starts_by["product_image"] += 1
            if line:
                current_lines.append(line)
            continue

        # Track tokens inside current card and detect boundaries
        if line:
            # Check for supplier repeat
            if first.startswith("supplier"):
                if seen_supplier:
                    push_block()
                    starts_by["supplier_repeat"] += 1
                seen_supplier = True

            # Check for Product # repeat
            if PROD_ID_RE.search(line):
                if seen_prod_id:
                    push_block()
                    starts_by["product_id_repeat"] += 1
                seen_prod_id = True

            # Check for Shop PID repeat
            if PID_RE.search(line):
                if seen_pid:
                    push_block()
                    starts_by["pid_repeat"] += 1
                seen_pid = True

            current_lines.append(line)
        else:
            current_lines.append("")

    # Flush last card
    push_block()

    total_cards = len(records)
    print(f"🔎 Card starts → Product Image: {starts_by['product_image']}, "
          f"Supplier repeat: {starts_by['supplier_repeat']}, "
          f"Product# repeat: {starts_by['product_id_repeat']}, "
          f"Shop PID repeat: {starts_by['pid_repeat']}. "
          f"Total cards: {total_cards}")

    # Filter out records without valid data
    valid_records = [r for r in records if r.get("title") or r.get("korealy_product_id")]

    print(f"✅ Parsed {len(valid_records)} Korealy products")
    return valid_records


def normalize_name(name: str) -> str:
    """Normalize product name for matching"""
    # Remove dashes, lowercase, collapse whitespace
    normalized = re.sub(r'[-—]+', ' ', name)
    normalized = normalized.lower()
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()


def build_name_maps(shopify_variants: Dict[str, Dict]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build exact and loose name mapping tables

    Returns:
        (exact_map, loose_map) - both map normalized_name -> variant_gid
    """
    exact_map = {}
    loose_map = {}

    for gid, info in shopify_variants.items():
        item_name = info["item"]

        # Exact match
        exact_key = normalize_name(item_name)
        exact_map[exact_key] = gid

        # Loose match (remove "— default title" suffix)
        loose_key = re.sub(r'\s+default title$', '', exact_key)
        loose_map[loose_key] = gid

    return exact_map, loose_map


def map_korealy_to_shopify(
    korealy_title: str,
    exact_map: Dict[str, str],
    loose_map: Dict[str, str]
) -> Optional[str]:
    """
    Map Korealy title to Shopify variant GID

    Returns:
        variant_gid or None if no match
    """
    normalized = normalize_name(korealy_title)

    # Try exact match first
    if normalized in exact_map:
        return exact_map[normalized]

    # Try loose match
    if normalized in loose_map:
        return loose_map[normalized]

    return None


def reconcile(
    korealy_records: List[Dict],
    shopify_variants: Dict[str, Dict],
    exact_map: Dict[str, str],
    loose_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Reconcile Korealy prices with Shopify COGS

    Returns:
        List of reconciliation records with status, delta, pct_diff
    """
    results = []

    for record in korealy_records:
        k_title = record.get("title", "")
        k_cogs = record.get("cogs")
        k_currency = record.get("currency", "USD")

        # Try to map to Shopify
        variant_gid = map_korealy_to_shopify(k_title, exact_map, loose_map)

        if not variant_gid:
            results.append({
                "status": "NO_MAPPING",
                "korealy_title": k_title,
                "korealy_cogs": k_cogs,
                "korealy_currency": k_currency,
                "korealy_product_id": record.get("korealy_product_id", ""),
                "korealy_shop_pid": record.get("shop_pid", ""),
                "variant_gid": None,
                "variant_id": None,
                "shopify_item": None,
                "shopify_cogs": None,
                "shopify_currency": None,
                "delta": None,
                "pct_diff": None
            })
            continue

        # Get Shopify data
        s_info = shopify_variants[variant_gid]
        s_cogs = s_info.get("cogs", 0)
        s_currency = s_info.get("currency", "USD")
        s_item = s_info.get("item", "")
        s_variant_id = s_info.get("variant_id", "")

        # Calculate delta and status
        if k_cogs is not None and s_cogs > 0:
            delta = k_cogs - s_cogs
            pct_diff = (delta / s_cogs) * 100 if s_cogs > 0 else 0

            # Check if match (within floating point tolerance)
            if abs(delta) <= 1e-9:
                status = "MATCH"
            else:
                status = "MISMATCH"
        elif k_cogs is None and s_cogs > 0:
            delta = None
            pct_diff = None
            status = "NO_COGS_IN_KOREALY"
        elif k_cogs is not None and s_cogs == 0:
            delta = None
            pct_diff = None
            status = "NO_COGS_IN_SHOPIFY"
        else:
            delta = None
            pct_diff = None
            status = "NO_COGS_BOTH"

        results.append({
            "status": status,
            "korealy_title": k_title,
            "korealy_cogs": k_cogs,
            "korealy_currency": k_currency,
            "korealy_product_id": record.get("korealy_product_id", ""),
            "korealy_shop_pid": record.get("shop_pid", ""),
            "variant_gid": variant_gid,
            "variant_id": s_variant_id,
            "shopify_item": s_item,
            "shopify_cogs": s_cogs,
            "shopify_currency": s_currency,
            "delta": delta,
            "pct_diff": pct_diff
        })

    return results


def run_reconciliation() -> Dict[str, Any]:
    """
    Run complete Korealy reconciliation workflow

    Returns:
        Dict with reconciliation results and summary stats
    """
    try:
        # Step 1: Fetch Shopify data
        print("📊 Fetching Shopify variants...")
        shopify_variants = fetch_shopify_variants_with_cogs()

        # Step 2: Fetch Korealy data
        print("📊 Fetching Korealy data from CSV...")
        raw_data = fetch_korealy_data_from_csv()

        # Step 3: Parse Korealy data
        print("📊 Parsing Korealy data...")
        korealy_records = parse_korealy_sheet(raw_data)

        # Step 4: Build name maps
        print("📊 Building name maps...")
        exact_map, loose_map = build_name_maps(shopify_variants)

        # Step 5: Reconcile
        print("📊 Reconciling prices...")
        results = reconcile(korealy_records, shopify_variants, exact_map, loose_map)

        # Step 6: Calculate summary stats
        stats = {
            "total": len(results),
            "MATCH": sum(1 for r in results if r["status"] == "MATCH"),
            "MISMATCH": sum(1 for r in results if r["status"] == "MISMATCH"),
            "NO_MAPPING": sum(1 for r in results if r["status"] == "NO_MAPPING"),
            "NO_COGS_IN_KOREALY": sum(1 for r in results if r["status"] == "NO_COGS_IN_KOREALY"),
            "NO_COGS_IN_SHOPIFY": sum(1 for r in results if r["status"] == "NO_COGS_IN_SHOPIFY"),
            "NO_COGS_BOTH": sum(1 for r in results if r["status"] == "NO_COGS_BOTH")
        }

        print(f"✅ Reconciliation complete: {stats}")

        return {
            "success": True,
            "results": results,
            "stats": stats,
            "message": f"Reconciled {len(results)} Korealy products with Shopify"
        }

    except Exception as e:
        print(f"❌ Reconciliation failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "results": [],
            "stats": {},
            "message": f"Reconciliation failed: {str(e)}"
        }


def sync_korealy_to_shopify(variant_ids: List[str], korealy_cogs_map: Dict[str, float]) -> Dict[str, Any]:
    """
    Sync selected Korealy COGS to Shopify

    Args:
        variant_ids: List of variant IDs to update
        korealy_cogs_map: Dict mapping variant_id -> new_cogs_value

    Returns:
        Dict with updated_count, failed_count, details
    """
    updated_count = 0
    failed_count = 0
    details = []

    for variant_id in variant_ids:
        if variant_id not in korealy_cogs_map:
            failed_count += 1
            details.append({
                "variant_id": variant_id,
                "status": "failed",
                "message": "No Korealy COGS provided"
            })
            continue

        try:
            variant_gid = f"gid://shopify/ProductVariant/{variant_id}"
            new_cogs = float(korealy_cogs_map[variant_id])

            # Get inventory item ID
            inv_query = """
            query($id: ID!) {
                productVariant(id: $id) {
                    inventoryItem {
                        id
                    }
                }
            }
            """
            inv_result = _shopify_graphql(inv_query, {"id": variant_gid})
            inv_item_id = inv_result["data"]["productVariant"]["inventoryItem"]["id"]

            # Update unit cost
            cost_mutation = """
            mutation inventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
                inventoryItemUpdate(id: $id, input: $input) {
                    inventoryItem {
                        id
                        unitCost {
                            amount
                        }
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
            """
            cost_result = _shopify_graphql(cost_mutation, {
                "id": inv_item_id,
                "input": {"cost": str(new_cogs)}
            })

            cost_errors = cost_result["data"]["inventoryItemUpdate"]["userErrors"]
            if cost_errors:
                raise RuntimeError("; ".join([e["message"] for e in cost_errors]))

            updated_count += 1
            details.append({
                "variant_id": variant_id,
                "status": "success",
                "message": f"Updated COGS to ${new_cogs:.2f}"
            })

            time.sleep(0.1)  # Rate limiting

        except Exception as e:
            failed_count += 1
            details.append({
                "variant_id": variant_id,
                "status": "failed",
                "message": str(e)
            })
            print(f"❌ Failed to update {variant_id}: {e}")

    message = f"Updated {updated_count} variants"
    if failed_count > 0:
        message += f", {failed_count} failed"

    return {
        "updated_count": updated_count,
        "failed_count": failed_count,
        "message": message,
        "details": details
    }
