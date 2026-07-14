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
# A price *line*: the whole cell is just a number, optionally with a currency symbol.
# Korealy's xlsx export writes bare numbers ("19.0"); the older CSV export used "$19.00".
# This is anchored (^...$) so it never matches a size like "100ml" or "Product #553259".
PRICE_LINE_RE = re.compile(r"^\s*(?:US?\$|\$|USD|€|£)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s*$")
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
            price
            product {
              id
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

                # Get COGS (has_cogs distinguishes a real 0 from "never set")
                cogs = 0.0
                currency = "USD"
                has_cogs = False
                inv_item = node.get("inventoryItem") or {}
                uc = inv_item.get("unitCost")
                if uc and uc.get("amount") is not None:
                    cogs = float(uc.get("amount") or 0)
                    currency = uc.get("currencyCode", "USD")
                    has_cogs = cogs > 0

                # Extract numeric variant ID from GID
                gid = node["id"]
                match = re.search(r'(\d+)$', gid)
                variant_id = match.group(1) if match else gid

                variants[gid] = {
                    "variant_id": variant_id,
                    "item": item_name,
                    "cogs": cogs,
                    "has_cogs": has_cogs,
                    "currency": currency,
                    "sku": node.get("sku", ""),
                    "price": float(node.get("price") or 0),
                    "product_id": node["product"]["id"],
                    "product_title": product_title,
                    "product_status": node["product"].get("status", ""),
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
            # Skip price-only lines (currency-prefixed OR bare number)
            if PRICE_LINE_RE.match(s):
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
            s = (ln or "").strip()
            # A price is a line that is ONLY a number (bare or currency-prefixed).
            # Take the last such line in the card (matches Korealy's layout where the
            # price is the final line). Anchored match avoids grabbing sizes/ids.
            m = PRICE_LINE_RE.match(s)
            if m:
                try:
                    price_val = float(m.group(1).replace(",", ""))
                    currency = detect_currency(s)
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


def build_name_maps(shopify_variants: Dict[str, Dict]) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str], Dict[str, str]]:
    """
    Build exact, loose, product-only, and SKU mapping tables

    Returns:
        (exact_map, loose_map, product_map, sku_map) - all map normalized_name/sku -> variant_gid
    """
    exact_map = {}
    loose_map = {}
    product_map = {}  # Product title only (without variant)
    sku_map = {}  # SKU -> GID mapping

    for gid, info in shopify_variants.items():
        item_name = info["item"]
        sku = info.get("sku", "")

        # Exact match
        exact_key = normalize_name(item_name)
        exact_map[exact_key] = gid

        # Loose match (remove "— default title" suffix)
        loose_key = re.sub(r'\s+default title$', '', exact_key)
        loose_map[loose_key] = gid

        # Product-only map (split on " — " and take first part)
        parts = item_name.split(" — ")
        if parts:
            product_only = normalize_name(parts[0])
            if product_only not in product_map:  # Keep first match
                product_map[product_only] = gid

        # SKU map (if SKU exists)
        if sku and sku.strip():
            sku_lower = sku.strip().lower()
            sku_map[sku_lower] = gid

    return exact_map, loose_map, product_map, sku_map


def map_korealy_to_shopify(
    korealy_title: str,
    exact_map: Dict[str, str],
    loose_map: Dict[str, str],
    shop_pid: Optional[str] = None,
    shopify_variants: Optional[Dict[str, Dict]] = None,
    product_map: Optional[Dict[str, str]] = None,
    sku_map: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """
    Map Korealy title to Shopify variant GID using multiple strategies

    Args:
        korealy_title: Product title from Korealy
        exact_map: Exact name -> GID mapping
        loose_map: Loose name -> GID mapping
        shop_pid: Shopify variant ID from Korealy (direct match)
        shopify_variants: Dict of all Shopify variants for fallback matching
        product_map: Product-only name -> GID mapping
        sku_map: SKU -> GID mapping

    Returns:
        variant_gid or None if no match
    """
    # 1. Try direct match via shop_pid (most reliable)
    if shop_pid:
        gid = f"gid://shopify/ProductVariant/{shop_pid}"
        if shopify_variants and gid in shopify_variants:
            return gid

    if not korealy_title:
        return None

    normalized = normalize_name(korealy_title)

    # 2. Try exact match
    if normalized in exact_map:
        return exact_map[normalized]

    # 3. Try loose match (without "default title")
    if normalized in loose_map:
        return loose_map[normalized]

    # 4. Try product-only match (product title without variant)
    if product_map and normalized in product_map:
        return product_map[normalized]

    # 5. Try partial matching - remove common suffixes and try again
    # Remove size info like "(100ml)", "[50g]", etc.
    partial = re.sub(r'\s*[\(\[][^)]*[\)\]]\s*', ' ', normalized)
    partial = re.sub(r'\s+', ' ', partial).strip()
    if partial:
        if partial in loose_map:
            return loose_map[partial]
        if product_map and partial in product_map:
            return product_map[partial]

    # 6. Try matching without brand prefix (first word)
    words = normalized.split()
    if len(words) > 2:
        without_brand = ' '.join(words[1:])
        if without_brand in loose_map:
            return loose_map[without_brand]
        if product_map and without_brand in product_map:
            return product_map[without_brand]

    # 7. Try substring containment - see if Korealy title is contained in any Shopify name
    if shopify_variants and len(normalized) >= 10:
        for gid, info in shopify_variants.items():
            shopify_name = normalize_name(info["item"])
            # Check if Korealy title is a substantial substring
            if normalized in shopify_name or shopify_name in normalized:
                return gid

    # 8. Token-based fuzzy match (>75% of words match)
    if shopify_variants and len(words) >= 3:
        korealy_tokens = set(words)
        best_match = None
        best_score = 0.75  # Minimum threshold

        for gid, info in shopify_variants.items():
            shopify_name = normalize_name(info["item"])
            shopify_tokens = set(shopify_name.split())

            if not shopify_tokens:
                continue

            # Calculate Jaccard-like score
            common = len(korealy_tokens & shopify_tokens)
            total = min(len(korealy_tokens), len(shopify_tokens))  # Use smaller set

            if total > 0:
                score = common / total
                if score > best_score:
                    best_score = score
                    best_match = gid

        if best_match:
            return best_match

    return None


def reconcile(
    korealy_records: List[Dict],
    shopify_variants: Dict[str, Dict],
    exact_map: Dict[str, str],
    loose_map: Dict[str, str],
    product_map: Optional[Dict[str, str]] = None,
    sku_map: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """
    Reconcile Korealy prices with Shopify COGS.

    A Korealy match is expanded to ALL variants of the matched product
    (variants of one product share the same supplier cost), so a 45-shade
    cushion produces 45 rows — not just the first variant.

    After the Korealy pass, every Shopify variant not covered by a Korealy
    record is audited:
      - PRICE_AT_COGS: storefront price ≈ known cost (zero margin!)
      - MISSING_COGS:  variant has no COGS set (fillable from a sibling
        variant's cost when one exists)

    Returns:
        List of reconciliation records with status, delta, pct_diff
    """
    results = []
    covered_gids = set()

    # Group variants by product for sibling expansion
    product_variants: Dict[str, List[str]] = {}
    # Numeric-product-id -> its variant gids. Korealy's "Shop PID #" is the
    # Shopify PRODUCT id, so this is the authoritative, exact join key.
    product_by_num: Dict[str, List[str]] = {}
    for gid, info in shopify_variants.items():
        pid_full = info.get("product_id") or gid
        product_variants.setdefault(pid_full, []).append(gid)
        m = re.search(r"(\d+)$", pid_full or "")
        if m:
            product_by_num.setdefault(m.group(1), []).append(gid)

    match_methods = {"shop_pid": 0, "name": 0, "none": 0}

    def _row(status, k_title, k_cogs, k_currency, record, s_info=None, gid=None,
             delta=None, pct_diff=None, cogs_source="korealy"):
        s_info = s_info or {}
        price = s_info.get("price")
        known_cost = k_cogs or (s_info.get("cogs") if s_info.get("has_cogs") else None)
        margin_pct = None
        if price and known_cost:
            margin_pct = (price - known_cost) / price * 100
        # Storefront price at/below supplier cost — selling with no margin
        zero_margin = bool(price and known_cost and price <= known_cost * 1.05)
        return {
            "status": status,
            "korealy_title": k_title,
            "korealy_cogs": k_cogs,
            "korealy_currency": k_currency,
            "korealy_product_id": (record or {}).get("korealy_product_id", ""),
            "korealy_shop_pid": (record or {}).get("shop_pid", ""),
            "variant_gid": gid,
            "variant_id": s_info.get("variant_id"),
            "shopify_item": s_info.get("item"),
            "shopify_cogs": (s_info.get("cogs") if s_info.get("has_cogs") else None) if s_info else None,
            "shopify_currency": s_info.get("currency"),
            "shopify_price": price,
            "product_status": s_info.get("product_status"),
            "margin_pct": margin_pct,
            "zero_margin": zero_margin,
            "cogs_source": cogs_source,
            "delta": delta,
            "pct_diff": pct_diff
        }

    for record in korealy_records:
        k_title = record.get("title", "")
        shop_pid = record.get("shop_pid")
        k_cogs = record.get("cogs")
        k_currency = record.get("currency", "USD")

        # 1) Shop PID = Shopify PRODUCT id — exact, authoritative match.
        sibling_gids = None
        if shop_pid and str(shop_pid) in product_by_num:
            sibling_gids = product_by_num[str(shop_pid)]
            match_methods["shop_pid"] += 1
        else:
            # 2) Fall back to name-based matching (fuzzy) only when the PID is
            #    missing or points at a product no longer in the store.
            variant_gid = map_korealy_to_shopify(
                k_title, exact_map, loose_map,
                shop_pid=shop_pid,
                shopify_variants=shopify_variants,
                product_map=product_map,
                sku_map=sku_map
            )
            if variant_gid:
                matched_product = shopify_variants[variant_gid].get("product_id")
                sibling_gids = product_variants.get(matched_product, [variant_gid])
                match_methods["name"] += 1

        if not sibling_gids:
            match_methods["none"] += 1
            results.append(_row("NO_MAPPING", k_title, k_cogs, k_currency, record))
            continue

        for gid in sibling_gids:
            covered_gids.add(gid)
            s_info = shopify_variants[gid]
            s_cogs = s_info.get("cogs", 0)
            s_has_cogs = s_info.get("has_cogs", s_cogs > 0)

            if k_cogs is not None and s_has_cogs:
                delta = k_cogs - s_cogs
                pct_diff = (delta / s_cogs) * 100 if s_cogs > 0 else 0
                status = "MATCH" if abs(delta) <= 1e-9 else "MISMATCH"
            elif k_cogs is None and s_has_cogs:
                delta, pct_diff, status = None, None, "NO_COGS_IN_KOREALY"
            elif k_cogs is not None and not s_has_cogs:
                delta, pct_diff, status = None, None, "NO_COGS_IN_SHOPIFY"
            else:
                delta, pct_diff, status = None, None, "NO_COGS_BOTH"

            results.append(_row(status, k_title, k_cogs, k_currency, record,
                                s_info=s_info, gid=gid, delta=delta, pct_diff=pct_diff))

    # ---- Shopify-side coverage pass ----
    # Variants the Korealy CSV never touched (e.g. products added after the
    # CSV export). Without this, missing COGS never shows in the dashboard.
    for gid, s_info in shopify_variants.items():
        if gid in covered_gids:
            continue
        if s_info.get("product_status") == "ARCHIVED":
            continue

        # Best-known cost: own COGS, else the max sibling COGS on the same product
        own_cost = s_info["cogs"] if s_info.get("has_cogs") else None
        sibling_cost = None
        sibling_name = None
        for sib_gid in product_variants.get(s_info.get("product_id"), []):
            sib = shopify_variants[sib_gid]
            if sib_gid != gid and sib.get("has_cogs"):
                if sibling_cost is None or sib["cogs"] > sibling_cost:
                    sibling_cost = sib["cogs"]
                    sibling_name = sib["item"]
        known_cost = own_cost if own_cost else sibling_cost

        price = s_info.get("price") or 0

        # Zero-margin alert: storefront price is (about) the supplier cost
        if known_cost and price and price <= known_cost * 1.05:
            results.append(_row(
                "PRICE_AT_COGS",
                f"(cost from sibling: {sibling_name})" if not own_cost and sibling_name else "(own COGS)",
                known_cost, s_info.get("currency", "USD"), None,
                s_info=s_info, gid=gid,
                cogs_source="shopify" if own_cost else "sibling"
            ))
            continue

        # Missing COGS: suggest the sibling cost as the fill value when we have one
        if not s_info.get("has_cogs"):
            results.append(_row(
                "MISSING_COGS",
                f"(cost from sibling: {sibling_name})" if sibling_name else "(not in Korealy CSV)",
                sibling_cost, s_info.get("currency", "USD") if sibling_cost else None, None,
                s_info=s_info, gid=gid,
                cogs_source="sibling" if sibling_cost else "none"
            ))

    print(f"🔗 Korealy match methods → Shop PID: {match_methods['shop_pid']}, "
          f"name-fallback: {match_methods['name']}, no-match: {match_methods['none']}")
    return results


def run_reconciliation() -> Dict[str, Any]:
    """
    Run complete Korealy reconciliation workflow

    Returns:
        Dict with reconciliation results and summary stats
    """
    try:
        # Step 0: Check if Korealy CSV exists
        if not os.path.exists(KOREALY_CSV_PATH):
            print(f"❌ Korealy CSV not found at: {KOREALY_CSV_PATH}")
            return {
                "success": False,
                "results": [],
                "stats": {},
                "message": f"Korealy CSV file not found. Expected at: {KOREALY_CSV_PATH}. Please upload the CSV or set KOREALY_CSV_PATH environment variable."
            }

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
        exact_map, loose_map, product_map, sku_map = build_name_maps(shopify_variants)

        # Step 5: Reconcile
        print("📊 Reconciling prices...")
        results = reconcile(korealy_records, shopify_variants, exact_map, loose_map, product_map, sku_map)

        # Step 6: Calculate summary stats
        stats = {
            "total": len(results),
            "MATCH": sum(1 for r in results if r["status"] == "MATCH"),
            "MISMATCH": sum(1 for r in results if r["status"] == "MISMATCH"),
            "NO_MAPPING": sum(1 for r in results if r["status"] == "NO_MAPPING"),
            "NO_COGS_IN_KOREALY": sum(1 for r in results if r["status"] == "NO_COGS_IN_KOREALY"),
            "NO_COGS_IN_SHOPIFY": sum(1 for r in results if r["status"] == "NO_COGS_IN_SHOPIFY"),
            "NO_COGS_BOTH": sum(1 for r in results if r["status"] == "NO_COGS_BOTH"),
            "MISSING_COGS": sum(1 for r in results if r["status"] == "MISSING_COGS"),
            "PRICE_AT_COGS": sum(1 for r in results if r["status"] == "PRICE_AT_COGS"),
            "ZERO_MARGIN": sum(1 for r in results if r.get("zero_margin")),
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


def apply_cogs_and_price(variant_id: str, new_cogs: Optional[float],
                         new_price: Optional[float] = None) -> Dict[str, Any]:
    """Set a single variant's COGS (and optionally price) in Shopify.

    Uses ONE productVariantsBulkUpdate call to set both unit cost and price
    (the API allows inventoryItem.cost + price together). Skips any field that
    already matches. Returns a result dict; raises only on hard Shopify errors.
    """
    variant_gid = f"gid://shopify/ProductVariant/{variant_id}"
    q = """
    query($id: ID!) {
        productVariant(id: $id) {
            id title price
            product { id title }
            inventoryItem { unitCost { amount currencyCode } }
        }
    }
    """
    data = _shopify_graphql(q, {"id": variant_gid}).get("data", {}).get("productVariant")
    if not data:
        raise RuntimeError(f"Variant not found in Shopify: {variant_gid}")

    product_gid = data["product"]["id"]
    item_name = f"{data['product']['title']} — {data['title']}".strip(" — ")
    old_price = float(data.get("price") or 0)
    uc = (data.get("inventoryItem") or {}).get("unitCost")
    old_cogs = float(uc["amount"]) if uc and uc.get("amount") is not None else 0.0

    want_cogs = new_cogs is not None and abs(old_cogs - float(new_cogs)) >= 0.01
    price_val = float(new_price) if new_price not in (None, "") else None
    want_price = price_val is not None and abs(old_price - price_val) >= 0.01

    if not want_cogs and not want_price:
        return {"variant_id": variant_id, "item": item_name, "status": "skipped",
                "old_cogs": old_cogs, "new_cogs": old_cogs, "old_price": old_price,
                "new_price": old_price, "message": "Already up to date"}

    vinput: Dict[str, Any] = {"id": variant_gid}
    if want_price:
        vinput["price"] = f"{price_val:.2f}"
    if want_cogs:
        vinput["inventoryItem"] = {"cost": float(new_cogs)}

    mutation = """
    mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
        productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants { id price inventoryItem { unitCost { amount } } }
            userErrors { field message }
        }
    }
    """
    res = _shopify_graphql(mutation, {"productId": product_gid, "variants": [vinput]})
    payload = res.get("data", {}).get("productVariantsBulkUpdate", {})
    errs = payload.get("userErrors") or []
    if errs:
        raise RuntimeError("; ".join(e.get("message", str(e)) for e in errs))

    got = (payload.get("productVariants") or [{}])[0]
    got_price = float(got.get("price") or old_price)
    guc = (got.get("inventoryItem") or {}).get("unitCost")
    got_cogs = float(guc["amount"]) if guc and guc.get("amount") is not None else old_cogs

    # Log COGS change in the Korealy-tagged format the update log recognises
    if want_cogs:
        try:
            from pricing_logic import log_price_update
            log_price_update(
                variant_id=variant_id, item=item_name,
                old_price=old_cogs, new_price=float(new_cogs),
                old_compare_at=0.0, new_compare_at=0.0, status="success",
                notes=f"KOREALY_COGS|{old_cogs:.2f}|{float(new_cogs):.2f}",
            )
        except Exception as log_err:
            print(f"⚠️ log_price_update failed for {variant_id}: {log_err}")

    parts = []
    if want_cogs:
        parts.append(f"COGS ${old_cogs:.2f}→${got_cogs:.2f}")
    if want_price:
        parts.append(f"price ${old_price:.2f}→${got_price:.2f}")
    return {"variant_id": variant_id, "item": item_name, "status": "success",
            "old_cogs": old_cogs, "new_cogs": got_cogs, "old_price": old_price,
            "new_price": got_price, "message": "Updated " + ", ".join(parts)}


def sync_korealy_to_shopify(variant_ids: List[str], korealy_cogs_map: Dict[str, float],
                            price_map: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Sync selected Korealy COGS (and optionally prices) to Shopify.

    Args:
        variant_ids: variant IDs to update
        korealy_cogs_map: variant_id -> new COGS
        price_map: optional variant_id -> new price (e.g. 2x COGS)

    Returns:
        Dict with updated_count, failed_count, details
    """
    price_map = price_map or {}
    updated_count = failed_count = skipped_count = 0
    details = []
    print(f"🔄 Starting Korealy sync for {len(variant_ids)} variants (price updates: {len(price_map)})")

    for variant_id in variant_ids:
        if variant_id not in korealy_cogs_map:
            failed_count += 1
            details.append({"variant_id": variant_id, "status": "failed",
                            "message": "No Korealy COGS provided"})
            continue
        try:
            r = apply_cogs_and_price(variant_id, korealy_cogs_map[variant_id],
                                     price_map.get(variant_id))
            details.append(r)
            if r["status"] == "success":
                updated_count += 1
            else:
                skipped_count += 1
            time.sleep(0.15)
        except Exception as e:
            failed_count += 1
            details.append({"variant_id": variant_id, "status": "failed", "message": str(e)})
            print(f"❌ Failed to update {variant_id}: {e}")

    message = f"Updated {updated_count} variants"
    if skipped_count:
        message += f", {skipped_count} already up to date"
    if failed_count:
        message += f", {failed_count} failed"
    print(f"🏁 Korealy sync complete: {message}")
    return {"updated_count": updated_count, "failed_count": failed_count,
            "skipped_count": skipped_count, "message": message, "details": details}
