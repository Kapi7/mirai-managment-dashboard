#!/usr/bin/env python3
"""
Delivery exposure check for repriced products (analysis only).

Cutting product prices without touching delivery changes the shipping economics:
the same free-shipping threshold now buys MORE units, so the parcel is heavier
and costs more to ship, while carrying less margin per dollar.

For every repriced variant this asks: if a customer fills a basket to the free
-shipping threshold with this product, does the basket's margin still cover its
actual shipping cost? Anything that does not is a live leak.

Usage: python3 delivery_exposure.py [--cohort treated]
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
MATRIX = Path("/Users/kapi7/mirai_report/shipping_matrix_all.csv")
PSP_FEE_RATE = 0.05

# Live Shopify settings (read from the store's delivery profile, 2026-07-28).
# threshold is in the market's currency; usd_rate converts it to USD for the
# margin comparison.
MARKETS = {
    "United States": {"threshold": 80.0, "fx": 1.0,      "flat": 9.0},
    "Australia":     {"threshold": 124.0, "fx": 1.428577, "flat": 9.0},
    "United Kingdom": {"threshold": 61.0, "fx": 0.744372, "flat": 8.0},
    "Canada":        {"threshold": 113.0, "fx": 1.405478, "flat": 11.0},
}


def load_matrix() -> dict:
    tiers = defaultdict(list)
    with open(MATRIX) as f:
        for row in csv.DictReader(f):
            try:
                tiers[row["geo"]].append((float(row["WEIGHT"]), float(row["STANDARD"])))
            except (ValueError, TypeError):
                continue
    for g in tiers:
        tiers[g].sort()
    return tiers


def ship_cost(tiers: dict, country: str, kg: float) -> float:
    t = tiers.get(country)
    if not t:
        return 0.0
    for w, p in t:
        if kg <= w + 1e-9:
            return p
    return t[-1][1]


def variants_without_free_shipping() -> set:
    """Variants in a non-default delivery profile — those profiles have no
    free-shipping rate, so they cannot create a free basket."""
    sys.path.insert(0, str(BASE_DIR))
    from organic_test_push import gql
    Q = """{ deliveryProfiles(first:10){ nodes{ default
      profileItems(first:100){ edges{ node{ variants(first:50){
        edges{ node{ legacyResourceId } } } } } } } } }"""
    out = set()
    for p in gql(Q)["data"]["deliveryProfiles"]["nodes"]:
        if p["default"]:
            continue
        for item in p["profileItems"]["edges"]:
            for v in item["node"]["variants"]["edges"]:
                out.add(str(v["node"]["legacyResourceId"]))
    return out


def fetch_weights(variant_ids: list) -> dict:
    sys.path.insert(0, str(BASE_DIR))
    from organic_test_push import gql
    Q = """query($ids:[ID!]!){ nodes(ids:$ids){ ... on ProductVariant {
      legacyResourceId price
      inventoryItem { measurement { weight { value unit } } } } } }"""
    out = {}
    for i in range(0, len(variant_ids), 100):
        ids = [f"gid://shopify/ProductVariant/{v}" for v in variant_ids[i:i + 100]]
        for n in gql(Q, {"ids": ids})["data"]["nodes"]:
            if not n:
                continue
            grams = 0.0
            meas = (n.get("inventoryItem") or {}).get("measurement") or {}
            w = meas.get("weight")
            if w:
                val, unit = float(w["value"] or 0), (w["unit"] or "GRAMS").upper()
                grams = {"GRAMS": val, "KILOGRAMS": val * 1000,
                         "POUNDS": val * 453.59237,
                         "OUNCES": val * 28.349523125}.get(unit, val)
            out[str(n["legacyResourceId"])] = {"grams": grams,
                                               "price": float(n["price"] or 0)}
        time.sleep(0.25)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="treated")
    a = ap.parse_args()

    reports = sorted(OUTPUTS_DIR.glob("geo_pricing_proposal_us_*.csv"))
    with open(reports[-1]) as f:
        play = {r["variant_id"]: r for r in csv.DictReader(f)}

    excluded = variants_without_free_shipping()
    variants, skipped = [], set()
    with open(OUTPUTS_DIR / f"organic_test_{a.cohort}.csv") as f:
        for row in csv.DictReader(f):
            for vid in (row.get("changed_variant_ids") or "").split(","):
                if vid not in play:
                    continue
                if vid in excluded:
                    skipped.add(row["title"])
                    continue
                variants.append((vid, row["title"]))
    if skipped:
        print(f"Excluded ({len(skipped)}) — in a no-free-shipping profile: "
              + "; ".join(sorted(s[:44] for s in skipped)) + "\n")

    live = fetch_weights([v for v, _ in variants])
    tiers = load_matrix()

    rows, leaks = [], []
    for vid, title in variants:
        p = play[vid]
        info = live.get(vid)
        if not info or info["price"] <= 0:
            continue
        price_now, cogs = info["price"], float(p["cogs_usd"] or 0)
        old_price = float(p["current_USD"] or 0)
        kg_unit = info["grams"] / 1000.0
        if kg_unit <= 0:
            continue

        rec = {"variant_id": vid, "product": title[:60],
               "old_price": round(old_price, 2), "new_price": round(price_now, 2),
               "unit_kg": round(kg_unit, 3), "cogs": cogs}

        for country, m in MARKETS.items():
            thr_usd = m["threshold"] / m["fx"]
            # units needed to reach free shipping with this product alone
            units_now = max(1, -(-thr_usd // price_now))          # ceil
            units_old = max(1, -(-thr_usd // old_price)) if old_price > 0 else units_now
            kg_now, kg_old = units_now * kg_unit, units_old * kg_unit
            cost_now = ship_cost(tiers, country, kg_now)
            cost_old = ship_cost(tiers, country, kg_old)
            basket_now = units_now * price_now
            margin_now = basket_now * (1 - PSP_FEE_RATE) - cogs * units_now
            net = margin_now - cost_now
            key = country.split()[0][:2].lower()
            rec[f"{key}_units"] = int(units_now)
            rec[f"{key}_kg"] = round(kg_now, 2)
            rec[f"{key}_ship_now"] = cost_now
            rec[f"{key}_ship_before"] = cost_old
            rec[f"{key}_net"] = round(net, 2)
            if net < 0:
                leaks.append((country, title, basket_now, kg_now, cost_now, net))
        rows.append(rec)

    out = OUTPUTS_DIR / "delivery_exposure.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"Analysed {len(rows)} repriced variants against live free-shipping "
          f"thresholds\n")
    for country, m in MARKETS.items():
        key = country.split()[0][:2].lower()
        worse = [r for r in rows if r[f"{key}_ship_now"] > r[f"{key}_ship_before"]]
        avg_before = sum(r[f"{key}_ship_before"] for r in rows) / len(rows)
        avg_now = sum(r[f"{key}_ship_now"] for r in rows) / len(rows)
        neg = [r for r in rows if r[f"{key}_net"] < 0]
        thin = [r for r in rows if 0 <= r[f"{key}_net"] < 10]
        print(f"{country:16} free over {m['threshold']:.0f} | "
              f"avg ship cost of a free basket ${avg_before:.2f} -> ${avg_now:.2f} "
              f"({len(worse)} products now heavier) | "
              f"loss-making: {len(neg)} | thin (<$10): {len(thin)}")

    if leaks:
        print(f"\n⚠️ {len(leaks)} product×market combinations where a "
              f"free-shipping basket LOSES money:")
        for c, t, b, kg, cost, net in sorted(leaks, key=lambda x: x[5])[:15]:
            print(f"  {c[:14]:14} ${b:>6.0f} basket, {kg:>5.2f}kg, ship ${cost:>5.0f} "
                  f"-> net ${net:>7.2f}  {t[:38]}")
    else:
        print("\n✅ No product can create a loss-making free-shipping basket "
              "on its own.")

    print(f"\n-> {out.name}")


if __name__ == "__main__":
    main()
