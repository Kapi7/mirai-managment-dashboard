# config.py — shared config for Mirai Skin + Mirai Cosmetics

from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------
# Load .env as soon as config is imported
# --------------------------------------------------------------------

# Assume .env is in the project root (same folder as this file)
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"

# load_dotenv() will silently succeed even if the file is missing
load_dotenv(dotenv_path=env_path)

# --------------------------------------------------------------------
# Shopify configuration (single + multi store)
# --------------------------------------------------------------------

# API version used everywhere
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07").strip()

# Main store (Mirai Skin)
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "").strip()              # e.g. "9dkd2w-g3.myshopify.com"
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()

# Second store (Mirai Cosmetics)
SHOPIFY_STORE_C = os.getenv("SHOPIFY_STORE_C", "").strip()          # e.g. "shop-revamp-xt4ng.myshopify.com"
SHOPIFY_ACCESS_TOKEN_C = os.getenv("SHOPIFY_ACCESS_TOKEN_C", "").strip()

# Optional explicit keys (mostly cosmetic, if some code wants to refer to them)
SHOPIFY_STORES_MAIN_KEY = os.getenv("SHOPIFY_STORES_MAIN", "skin").strip()
SHOPIFY_STORES_COSMETICS_KEY = os.getenv("SHOPIFY_STORES_COSMETICS", "cosmetics").strip()

# Normalized multi-store list used by orders_alert.py and master_report_mirai.py
# Each entry: {"key", "label", "domain", "access_token"}
SHOPIFY_STORES = []

# Primary store (Mirai Skin)
if SHOPIFY_STORE and SHOPIFY_ACCESS_TOKEN:
    SHOPIFY_STORES.append(
        {
            "key": SHOPIFY_STORES_MAIN_KEY or "skin",
            "label": "Mirai Skin",
            "domain": SHOPIFY_STORE,
            "access_token": SHOPIFY_ACCESS_TOKEN,
        }
    )

# Secondary store (Mirai Cosmetics)
if SHOPIFY_STORE_C and SHOPIFY_ACCESS_TOKEN_C:
    SHOPIFY_STORES.append(
        {
            "key": SHOPIFY_STORES_COSMETICS_KEY or "cosmetics",
            "label": "Mirai Cosmetics",
            "domain": SHOPIFY_STORE_C,
            "access_token": SHOPIFY_ACCESS_TOKEN_C,
        }
    )

# Default label for contexts that only know "the shop"
if len(SHOPIFY_STORES) == 1:
    SHOP_LABEL = SHOPIFY_STORES[0]["label"]
elif len(SHOPIFY_STORES) > 1:
    SHOP_LABEL = "Mirai Skin + Mirai Cosmetics"
else:
    SHOP_LABEL = "Mirai"

# Optional safety log so you can see if something is misconfigured
if not SHOPIFY_STORES:
    print("[config] WARNING: SHOPIFY_STORES is empty. Check SHOPIFY_STORE / SHOPIFY_ACCESS_TOKEN in your .env")
else:
    stores_debug = ", ".join(f"{s['label']} ({s['domain']})" for s in SHOPIFY_STORES)
    print(f"[config] Loaded Shopify stores: {stores_debug}")
