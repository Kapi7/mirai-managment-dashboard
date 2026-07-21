#!/usr/bin/env python3
"""
Geo Pricing CLI (Phase 1 — research & dry-run only)

Usage:
  python3 run_geo_pricing.py sales                      # (re)build 2026 sales weights
  python3 run_geo_pricing.py scan --geos au,gb --top 50 [--mock]
  python3 run_geo_pricing.py report --geos us,au,gb,ca

There is intentionally NO apply/write command in Phase 1 — nothing here
touches Shopify prices, price lists, or delivery settings.
"""

import argparse
import json
import sys

from geo_competitor_scan import GEO_CONFIG, scan_variants
from geo_pricing_report import (
    build_sales_weights, generate_market_report, get_fx_rates,
    load_sales_weights, top_variants_by_revenue,
)


def _parse_geos(arg: str):
    geos = [g.strip().lower() for g in arg.split(",") if g.strip()]
    bad = [g for g in geos if g not in GEO_CONFIG]
    if bad:
        sys.exit(f"Unknown geos {bad}; supported: {list(GEO_CONFIG)}")
    return geos


def cmd_sales(_args):
    from config import SHOPIFY_STORE, SHOPIFY_ACCESS_TOKEN
    if not SHOPIFY_STORE or not SHOPIFY_ACCESS_TOKEN:
        sys.exit("Missing SHOPIFY_STORE / SHOPIFY_ACCESS_TOKEN in .env")
    build_sales_weights(SHOPIFY_STORE, SHOPIFY_ACCESS_TOKEN)


def cmd_scan(args):
    geos = _parse_geos(args.geos)
    if not load_sales_weights()["variants"]:
        print("No sales weights yet — building them first...")
        cmd_sales(args)
    targets = top_variants_by_revenue(args.top)
    if not targets:
        sys.exit("No scan targets found (sales weights empty).")
    est = len(targets) * len(geos)
    print(f"Scanning top {len(targets)} variants × {geos} "
          f"= {est} SerpAPI searches{' (MOCK)' if args.mock else ''}")
    scan_variants(targets, geos, mock=args.mock)


def cmd_report(args):
    geos = _parse_geos(args.geos)
    from pricing_logic import fetch_items
    items = fetch_items(use_cache=not args.refresh_items)
    fx = get_fx_rates()

    # US first: its proposals define the master (base) price that other
    # markets ride via FX unless they diverge past MASTER_TOLERANCE.
    ordered = (["us"] if "us" in geos else []) + [g for g in geos if g != "us"]
    master: dict = {}
    summaries = []
    for g in ordered:
        s = generate_market_report(g, items, fx,
                                   master_prices_usd=master or None)
        summaries.append(s)
        if g == "us":
            import csv as _csv
            with open(s["csv"]) as f:
                master = {r["variant_id"]: float(r["proposed_USD"])
                          for r in _csv.DictReader(f)
                          if float(r["proposed_USD"] or 0) > 0}
    print(json.dumps(summaries, indent=1))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sales", help="(Re)build 2026 per-variant sales weights")

    ps = sub.add_parser("scan", help="Scan competitor prices per geo")
    ps.add_argument("--geos", default="au,gb,ca", help="Comma list: us,au,gb,ca")
    ps.add_argument("--top", type=int, default=50,
                    help="Scan top-N variants by 2026 revenue (cost control)")
    ps.add_argument("--mock", action="store_true",
                    help="Use canned fixtures instead of SerpAPI")

    pr = sub.add_parser("report", help="Generate dry-run price proposal per market")
    pr.add_argument("--geos", default="us,au,gb,ca")
    pr.add_argument("--refresh-items", action="store_true",
                    help="Bypass Shopify items cache")

    args = p.parse_args()
    {"sales": cmd_sales, "scan": cmd_scan, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
