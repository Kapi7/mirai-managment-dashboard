"""
Geo Competitor Scan Module (Phase 1 — research only, no Shopify writes)

Per-country Google Shopping competitor research via SerpAPI.
Extends the US-only scan in pricing_execution.check_competitor_prices to
multiple geos, storing results per geo in competitor_data_geo.json.

Geos are keyed by SerpAPI `gl` codes: us, au, gb, ca.
Results come back in the local currency of the geo's Google domain.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from smart_pricing import filter_outlier_prices, is_trusted_seller

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY")

BASE_DIR = Path(__file__).resolve().parent
GEO_DATA_FILE = BASE_DIR / "competitor_data_geo.json"
LEGACY_US_FILE = BASE_DIR / "competitor_data.json"

# geo -> SerpAPI params. Currency is what Google Shopping returns for that geo.
GEO_CONFIG = {
    "us": {"gl": "us", "hl": "en", "google_domain": "google.com", "currency": "USD"},
    "au": {"gl": "au", "hl": "en", "google_domain": "google.com.au", "currency": "AUD"},
    "gb": {"gl": "uk", "hl": "en", "google_domain": "google.co.uk", "currency": "GBP"},
    "ca": {"gl": "ca", "hl": "en", "google_domain": "google.ca", "currency": "CAD"},
}


# ================== persistence ==================

def load_geo_data() -> Dict[str, Dict[str, Any]]:
    """Load per-geo competitor store: {geo: {variant_id: {...}}}"""
    if GEO_DATA_FILE.exists():
        try:
            with open(GEO_DATA_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_geo_data(data: Dict[str, Dict[str, Any]]) -> None:
    with open(GEO_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_legacy_us_data() -> Dict[str, Any]:
    """Legacy US-only competitor_data.json (variant_id -> stats, USD)."""
    if LEGACY_US_FILE.exists():
        try:
            with open(LEGACY_US_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_competitor_stats(geo: str, variant_id: str) -> Optional[Dict[str, Any]]:
    """
    Competitor stats for a variant in a geo.
    Falls back to the legacy US file for geo == "us".
    """
    data = load_geo_data()
    stats = data.get(geo, {}).get(str(variant_id))
    if stats:
        return stats
    if geo == "us":
        legacy = load_legacy_us_data().get(str(variant_id))
        if legacy and legacy.get("comp_avg"):
            return {
                "comp_low": legacy.get("comp_low", 0.0),
                "comp_avg": legacy.get("comp_avg", 0.0),
                "comp_high": legacy.get("comp_high", 0.0),
                "currency": "USD",
                "trusted_count": legacy.get("trusted_count", 0),
                "filtered_count": legacy.get("filtered_count", 0),
                "top_sellers": legacy.get("top_sellers", []),
                "scanned_at": legacy.get("scanned_at", ""),
                "source": "legacy_us_file",
            }
    return None


# ================== SerpAPI ==================

def parse_shopping_results(shopping_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Turn raw SerpAPI shopping_results into filtered price stats.
    Same filtering as the US scanner: drop untrusted sellers, then outliers.
    """
    raw_prices: List[float] = []
    trusted_prices: List[float] = []
    seller_counts: Dict[str, int] = {}

    for item in shopping_results:
        price = item.get("extracted_price")
        if not price or price <= 0:
            continue
        raw_prices.append(float(price))
        seller = item.get("source") or item.get("seller") or ""
        if is_trusted_seller(seller):
            trusted_prices.append(float(price))
            if seller:
                seller_counts[seller] = seller_counts.get(seller, 0) + 1

    filtered = filter_outlier_prices(trusted_prices)
    top_sellers = sorted(seller_counts.items(), key=lambda kv: -kv[1])[:5]

    if not filtered:
        return {
            "comp_low": 0.0, "comp_avg": 0.0, "comp_high": 0.0,
            "raw_count": len(raw_prices), "trusted_count": len(trusted_prices),
            "filtered_count": 0, "top_sellers": top_sellers,
        }

    return {
        "comp_low": round(min(filtered), 2),
        "comp_avg": round(sum(filtered) / len(filtered), 2),
        "comp_high": round(max(filtered), 2),
        "raw_count": len(raw_prices),
        "trusted_count": len(trusted_prices),
        "filtered_count": len(filtered),
        "top_sellers": top_sellers,
    }


def serpapi_shopping_search(query: str, geo: str,
                            mock_response: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """One Google Shopping search for a geo. Returns raw shopping_results."""
    if mock_response is not None:
        return mock_response.get("shopping_results", [])

    if not SERPAPI_KEY:
        raise RuntimeError(
            "SERPAPI_KEY not configured. It exists only in the Render env — "
            "add it to python_backend/.env to run real scans locally, "
            "or use --mock."
        )

    cfg = GEO_CONFIG[geo]
    params = {
        "engine": "google_shopping",
        "q": query,
        "gl": cfg["gl"],
        "hl": cfg["hl"],
        "google_domain": cfg["google_domain"],
        "num": 100,
        "api_key": SERPAPI_KEY,
    }
    resp = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
    resp.raise_for_status()
    return resp.json().get("shopping_results", [])


# ================== scan orchestration ==================

def build_search_query(product_title: str, variant_title: str, sku: str = "") -> str:
    """Same query construction as the US scanner."""
    q = product_title
    if variant_title and variant_title.lower() not in ("default title", "default"):
        q += f" {variant_title}"
    if sku:
        q += f" {sku}"
    return q.strip()


def scan_variants(variants: List[Dict[str, Any]], geos: List[str],
                  mock: bool = False, sleep_s: float = 1.0,
                  progress: bool = True) -> Dict[str, Dict[str, Any]]:
    """
    Scan competitor prices for variants across geos.

    variants: [{variant_id, product_title, variant_title, sku}, ...]
    Returns and persists the updated geo store.
    """
    unknown = [g for g in geos if g not in GEO_CONFIG]
    if unknown:
        raise ValueError(f"Unknown geos {unknown}; supported: {list(GEO_CONFIG)}")

    data = load_geo_data()
    scanned = 0
    for geo in geos:
        data.setdefault(geo, {})
        for v in variants:
            query = build_search_query(
                v.get("product_title", ""), v.get("variant_title", ""), v.get("sku", "")
            )
            if not query:
                continue
            try:
                if mock:
                    results = _mock_shopping_results(query, geo)
                else:
                    results = serpapi_shopping_search(query, geo)
            except Exception as e:
                print(f"❌ {geo} scan failed for {query!r}: {e}")
                continue

            stats = parse_shopping_results(results)
            stats["currency"] = GEO_CONFIG[geo]["currency"]
            stats["query"] = query
            stats["scanned_at"] = datetime.utcnow().isoformat() + "Z"
            data[geo][str(v["variant_id"])] = stats
            scanned += 1
            if progress:
                print(f"  [{geo}] {query[:50]:50} "
                      f"avg={stats['comp_avg']} {stats['currency']} "
                      f"(n={stats['filtered_count']})")
            if not mock:
                time.sleep(sleep_s)

    save_geo_data(data)
    print(f"✅ Scanned {scanned} variant×geo combinations; saved to {GEO_DATA_FILE.name}")
    return data


# ================== mock fixtures (testing without SERPAPI_KEY) ==================

_MOCK_FX_VS_USD = {"us": 1.0, "au": 1.52, "gb": 0.79, "ca": 1.37}


def _mock_shopping_results(query: str, geo: str) -> List[Dict[str, Any]]:
    """Deterministic canned results: a spread of sellers around a base price."""
    base_usd = 20.0 + (sum(ord(c) for c in query) % 30)  # 20–50 USD, query-stable
    fx = _MOCK_FX_VS_USD[geo]
    base = base_usd * fx
    return [
        {"source": "YesStyle.com", "extracted_price": round(base * 0.95, 2)},
        {"source": "Stylevana", "extracted_price": round(base * 1.00, 2)},
        {"source": "Amazon.com - Seller", "extracted_price": round(base * 1.10, 2)},
        {"source": "Olive Young Global", "extracted_price": round(base * 1.05, 2)},
        {"source": "eBay - somereseller", "extracted_price": round(base * 0.90, 2)},
        {"source": "temu", "extracted_price": round(base * 0.30, 2)},       # untrusted
        {"source": "Random Shop", "extracted_price": round(base * 9.0, 2)},  # outlier
    ]
