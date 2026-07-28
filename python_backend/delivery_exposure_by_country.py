#!/usr/bin/env python3
"""
Per-country delivery exposure (analysis only).

Reads the LIVE delivery profile from Shopify (zones, flat rates, free-shipping
thresholds), then for every country we ship to asks two questions using the
real per-country shipping cost matrix:

  1. Typical basket — at a basket sized to the free-shipping threshold, filled
     with repriced products at today's prices, does the margin cover the real
     shipping cost?
  2. Worst product — which single product creates the biggest loss when a
     customer fills a free-shipping basket with it alone?

Usage: python3 delivery_exposure_by_country.py [--cohort treated]
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

# ISO alpha-2 -> name as spelled in the shipping matrix. Only the countries the
# store actually ships to. Entries mapping to None have no matrix rate.
ISO = {
    "AE": "United Arab Emirates", "AF": "Afghanistan", "AL": "Albania",
    "AM": "Armenia", "AT": "Austria", "AU": "Australia", "AZ": "Azerbaijan",
    "BD": "Bangladesh", "BE": "Belgium", "BH": "Bahrain", "CA": "Canada",
    "CH": "Switzerland", "CY": "Cyprus", "CZ": "Czech Republic",
    "DE": "Germany", "DK": "Denmark", "DZ": "Algeria", "EE": "Estonia",
    "EG": "Egypt", "EH": "Western Sahara", "ES": "Spain", "FI": "Finland",
    "FR": "France", "GB": "United Kingdom", "GE": "Georgia",
    "GI": "Gibraltar", "GR": "Greece", "HR": "Croatia", "HU": "Hungary",
    "IE": "Ireland", "IL": "Israel", "IM": "Isle of Man", "IQ": "Iraq",
    "IS": "Iceland", "IT": "Italy", "JO": "Jordan", "JP": "Japan",
    "KG": "Kyrgyzstan", "KW": "Kuwait", "LB": "Lebanon", "LR": "Liberia",
    "LT": "Lithuania", "LU": "Luxembourg", "LY": "Libya", "MA": "Morocco",
    "MC": "Monaco", "MD": "Moldova", "ME": "Montenegro", "MT": "Malta",
    "MW": "Malawi", "MY": "Malaysia", "NL": "Netherlands", "NO": "Norway",
    "OM": "Oman", "PH": "Philippines", "PK": "Pakistan", "PL": "Poland",
    "PS": "Palestine", "PT": "Portugal", "QA": "Qatar", "RO": "Romania",
    "RS": "Serbia", "RW": "Rwanda", "SA": "Saudi Arabia", "SD": "Sudan",
    "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia", "SM": "San Marino",
    "US": "United States", "VA": "Vatican City", "XK": "Kosovo", "YE": "Yemen",
}

FX = {"USD": 1.0, "AUD": 1.428577, "GBP": 0.744372, "CAD": 1.405478,
      "EUR": 0.92, "ILS": 3.7}


def load_matrix() -> dict:
    tiers = defaultdict(list)
    with open(MATRIX) as f:
        for row in csv.DictReader(f):
            try:
                tiers[row["geo"]].append((float(row["WEIGHT"]),
                                          float(row["STANDARD"])))
            except (ValueError, TypeError):
                continue
    for g in tiers:
        tiers[g].sort()
    return dict(tiers)


def ship_cost(tiers: dict, country: str, kg: float):
    t = tiers.get(country)
    if not t:
        return None
    for w, p in t:
        if kg <= w + 1e-9:
            return p
    return t[-1][1]


def live_zones() -> list:
    sys.path.insert(0, str(BASE_DIR))
    from organic_test_push import gql
    Q = """{ deliveryProfiles(first:5){ nodes{ default profileLocationGroups{
      locationGroupZones(first:30){ nodes{
        zone{ name countries{ code{ countryCode } } }
        methodDefinitions(first:10){ nodes{ name active
          methodConditions{ field conditionCriteria{
            ... on MoneyV2{ amount currencyCode } ... on Weight{ value unit } } }
          rateProvider{ ... on DeliveryRateDefinition{
            price{ amount currencyCode } } } } } } } } } } }"""
    profiles = gql(Q)["data"]["deliveryProfiles"]["nodes"]
    gen = next(p for p in profiles if p["default"])
    zones = []
    for lg in gen["profileLocationGroups"]:
        for z in lg["locationGroupZones"]["nodes"]:
            free_usd, free_field, flat_usd = None, None, None
            for m in z["methodDefinitions"]["nodes"]:
                if not m["active"]:
                    continue
                pr = (m["rateProvider"] or {}).get("price")
                if m["methodConditions"]:
                    c = m["methodConditions"][0]
                    free_field = c["field"]
                    crit = c["conditionCriteria"]
                    if "amount" in crit:
                        free_usd = float(crit["amount"]) / FX.get(
                            crit["currencyCode"], 1.0)
                elif pr:
                    flat_usd = float(pr["amount"]) / FX.get(pr["currencyCode"], 1.0)
            zones.append({
                "zone": z["zone"]["name"],
                "countries": [c["code"]["countryCode"]
                              for c in z["zone"]["countries"] if c.get("code")],
                "free_usd": free_usd, "free_field": free_field,
                "flat_usd": flat_usd,
            })
    return zones


def variants_without_free_shipping() -> set:
    """Variants assigned to a non-default delivery profile. Those profiles
    carry no free-shipping rate, so such variants cannot create a free
    basket and must be excluded from the leak scan."""
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


def repriced(cohort: str) -> list:
    reports = sorted(OUTPUTS_DIR.glob("geo_pricing_proposal_us_*.csv"))
    with open(reports[-1]) as f:
        play = {r["variant_id"]: r for r in csv.DictReader(f)}
    exposure = {}
    ep = OUTPUTS_DIR / "delivery_exposure.csv"
    if ep.exists():
        with open(ep) as f:
            exposure = {r["variant_id"]: r for r in csv.DictReader(f)}

    excluded = variants_without_free_shipping()
    out, skipped = [], []
    with open(OUTPUTS_DIR / f"organic_test_{cohort}.csv") as f:
        for row in csv.DictReader(f):
            for vid in (row.get("changed_variant_ids") or "").split(","):
                p, e = play.get(vid), exposure.get(vid)
                if not p or not e:
                    continue
                if vid in excluded:
                    skipped.append(row["title"])
                    continue
                kg = float(e["unit_kg"] or 0)
                price = float(e["new_price"] or 0)
                if kg <= 0 or price <= 0:
                    continue
                out.append({"id": vid, "product": row["title"], "kg": kg,
                            "price": price, "cogs": float(p["cogs_usd"] or 0)})
    if skipped:
        print(f"Excluded from the scan ({len(skipped)}) — already moved to a "
              f"no-free-shipping profile:")
        for s in sorted(set(skipped)):
            print(f"  • {s[:64]}")
        print()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="treated")
    a = ap.parse_args()

    tiers, zones, prods = load_matrix(), live_zones(), repriced(a.cohort)
    # blended kg per $ and margin rate across the repriced set
    kg_per_usd = sum(p["kg"] / p["price"] for p in prods) / len(prods)
    margin_rate = sum(1 - p["cogs"] / p["price"] for p in prods) / len(prods) \
        - PSP_FEE_RATE

    print(f"Repriced set: {len(prods)} variants | blended margin "
          f"{margin_rate*100:.1f}% | {kg_per_usd*1000:.0f} g per $1 of basket\n")

    rows, no_rate = [], []
    for z in zones:
        for cc in z["countries"]:
            name = ISO.get(cc)
            if not name or name not in tiers:
                no_rate.append((z["zone"], cc, name))
                continue
            if z["free_usd"] is None or z["free_field"] != "TOTAL_PRICE":
                rows.append({"zone": z["zone"], "country": name, "code": cc,
                             "threshold_usd": None, "typical_net": None,
                             "worst_net": None, "worst_product": "",
                             "note": "no price-based free shipping"
                                     if z["free_field"] != "TOTAL_PRICE"
                                     else "no free shipping"})
                continue

            thr = z["free_usd"]
            kg_typ = thr * kg_per_usd
            c_typ = ship_cost(tiers, name, kg_typ)
            typ_net = thr * margin_rate - c_typ

            worst, worst_net = None, None
            for p in prods:
                units = max(1, -(-thr // p["price"]))
                basket = units * p["price"]
                kg = units * p["kg"]
                cost = ship_cost(tiers, name, kg)
                net = basket * (1 - PSP_FEE_RATE) - p["cogs"] * units - cost
                if worst_net is None or net < worst_net:
                    worst, worst_net = p, net
            rows.append({"zone": z["zone"], "country": name, "code": cc,
                         "threshold_usd": round(thr, 2),
                         "typical_kg": round(kg_typ, 2),
                         "typical_ship": c_typ,
                         "typical_net": round(typ_net, 2),
                         "worst_net": round(worst_net, 2),
                         "worst_product": worst["product"][:48], "note": ""})

    out = OUTPUTS_DIR / "delivery_exposure_by_country.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    scored = [r for r in rows if r["typical_net"] is not None]
    bad_typ = sorted([r for r in scored if r["typical_net"] < 0],
                     key=lambda r: r["typical_net"])
    bad_worst = sorted([r for r in scored if r["worst_net"] < 0],
                       key=lambda r: r["worst_net"])

    print(f"{len(scored)} countries with price-based free shipping · "
          f"{len(rows)-len(scored)} without\n")
    print("A. TYPICAL basket at the free-shipping threshold — loses money in "
          f"{len(bad_typ)} countries:")
    for r in bad_typ[:20]:
        print(f"   {r['country'][:22]:23} {r['zone'][:12]:13} thr ${r['threshold_usd']:>6.0f} "
              f"{r['typical_kg']:>5.2f}kg ship ${r['typical_ship']:>5.0f} "
              f"-> net ${r['typical_net']:>8.2f}")
    if not bad_typ:
        print("   none")

    print(f"\nB. WORST single product filling a free basket — negative in "
          f"{len(bad_worst)} countries:")
    seen = set()
    for r in bad_worst[:25]:
        print(f"   {r['country'][:22]:23} net ${r['worst_net']:>8.2f}  "
              f"{r['worst_product'][:40]}")
        seen.add(r["worst_product"])
    print(f"\n   products responsible: {len(seen)}")
    for s in sorted(seen):
        n = sum(1 for r in bad_worst if r["worst_product"] == s)
        print(f"     {n:>3} countries  {s}")

    zone_note = [r for r in rows if r["note"]]
    if zone_note:
        print("\nC. Zones without price-based free shipping:")
        for z in sorted({(r['zone'], r['note']) for r in zone_note}):
            n = sum(1 for r in zone_note if r["zone"] == z[0])
            print(f"   {z[0]:16} {n:>3} countries — {z[1]}")

    if no_rate:
        print(f"\nD. {len(no_rate)} shipped countries with no rate in the "
              f"shipping matrix (cost unknown):")
        for zn, cc, nm in no_rate[:12]:
            print(f"   {zn:16} {cc}  {nm or '(no name mapping)'}")

    print(f"\n-> {out.name}")


if __name__ == "__main__":
    main()
