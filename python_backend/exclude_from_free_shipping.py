#!/usr/bin/env python3
"""
Move heavy products into their own delivery profile so they never ship free.

Shopify has no per-product "exclude from free shipping" switch. The supported
way is a second delivery profile: products in it use ITS rates instead of the
General profile's, and we simply don't give it a free-shipping rate.

The new profile mirrors the General profile's zones and country coverage
exactly — so no country loses shipping options — but carries only the paid
rates. Carts mixing these products with normal ones are charged both profiles'
rates, which is the intended outcome.

Dry-run by default. Reversible: deleting the profile returns the products to
the General profile.

Usage:
  python3 exclude_from_free_shipping.py                 # preview
  python3 exclude_from_free_shipping.py --confirm       # create
  python3 exclude_from_free_shipping.py --delete <gid> --confirm   # undo
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from organic_test_push import gql  # noqa: E402

PROFILE_NAME = "Heavy items — shipping always charged"

# Products to exclude, matched on title substring (case-insensitive).
TARGETS = [
    "Folligen Plus Shampoo SET",
    "AHA-BHA-PHA 30 Days Miracle Acne Body Cleanser",
]


def find_products(needles: list) -> list:
    Q = """query($q: String!){ products(first: 20, query: $q){
      edges{ node{ id title totalInventory
        variants(first: 20){ edges{ node{ id title } } } } } } }"""
    found = []
    for needle in needles:
        # search on a distinctive word, then match precisely client-side
        term = needle.split()[0]
        res = gql(Q, {"q": f"title:*{term}*"})["data"]["products"]["edges"]
        hits = [e["node"] for e in res
                if needle.lower() in e["node"]["title"].lower()]
        if not hits:
            print(f"⚠️  no product matched {needle!r}")
        for h in hits:
            found.append(h)
    return found


def general_zones() -> list:
    """Zones of the default profile, with only their PAID rates."""
    Q = """{ deliveryProfiles(first:5){ nodes{ id name default
      profileLocationGroups{ locationGroup{ id }
        locationGroupZones(first:30){ nodes{
          zone{ name countries{ code{ countryCode } provinces{ code } } }
          methodDefinitions(first:10){ nodes{ name active
            methodConditions{ field }
            rateProvider{ ... on DeliveryRateDefinition{
              price{ amount currencyCode } } } } } } } } } } }"""
    profiles = gql(Q)["data"]["deliveryProfiles"]["nodes"]
    gen = next(p for p in profiles if p["default"])
    zones, claimed = [], set()
    for lg in gen["profileLocationGroups"]:
        for z in lg["locationGroupZones"]["nodes"]:
            countries = z["zone"]["countries"]
            paid = []
            for m in z["methodDefinitions"]["nodes"]:
                if not m["active"] or m["methodConditions"]:
                    continue          # conditional == the free-shipping rate
                pr = (m["rateProvider"] or {}).get("price")
                if pr:
                    paid.append({"name": m["name"],
                                 "amount": float(pr["amount"]),
                                 "currency": pr["currencyCode"]})
            if not paid:
                continue
            # A country may appear in only one zone per profile. The General
            # profile has province-scoped duplicates (e.g. "US AL N HI" repeats
            # US); first zone wins, later duplicates are dropped.
            codes = [c["code"]["countryCode"] for c in countries
                     if c.get("code") and c["code"]["countryCode"] not in claimed]
            if not codes:
                continue
            claimed.update(codes)
            zones.append({"name": z["zone"]["name"], "countries": codes,
                          "rates": paid})
    return zones


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--delete", help="profile GID to delete (undo)")
    a = ap.parse_args()

    if a.delete:
        if not a.confirm:
            print(f"DRY RUN — would delete profile {a.delete}. Add --confirm.")
            return
        M = """mutation($id: ID!){ deliveryProfileRemove(id: $id){
          job{ id done } userErrors{ field message } } }"""
        r = gql(M, {"id": a.delete})["data"]["deliveryProfileRemove"]
        if r["userErrors"]:
            print(f"❌ {r['userErrors']}")
        else:
            print(f"✅ profile removed — products return to the General profile")
        return

    products = find_products(TARGETS)
    zones = general_zones()
    variant_gids = [v["node"]["id"] for p in products
                    for v in p["variants"]["edges"]]

    print(f"\nNew delivery profile: {PROFILE_NAME!r}\n")
    print("Products moved into it (they lose free shipping everywhere):")
    for p in products:
        print(f"  • {p['title'][:66]}  ({len(p['variants']['edges'])} variant(s))")
    print(f"\nZones mirrored from the General profile "
          f"({len(zones)} zones, paid rates only):")
    for z in zones:
        rates = ", ".join(f"{r['amount']:.0f} {r['currency']}" for r in z["rates"])
        print(f"  {z['name']:18} {len(z['countries']):>3} countries → {rates}")
    total = sum(len(z["countries"]) for z in zones)
    print(f"\n  {total} countries covered · no free-shipping rate in this profile")

    if not a.confirm:
        print("\n" + "=" * 62)
        print("DRY RUN — nothing created. Re-run with --confirm to apply.")
        print("=" * 62)
        return

    # the location group must carry the shipping-origin location, otherwise
    # Shopify refuses to save the zones
    locs = gql("""{ locations(first:10){ nodes{ id shipsInventory isActive } } }"""
               )["data"]["locations"]["nodes"]
    origin = [l["id"] for l in locs if l["shipsInventory"] and l["isActive"]]
    if not origin:
        print("❌ no active shipping location found")
        return

    M = """mutation($profile: DeliveryProfileInput!){
      deliveryProfileCreate(profile: $profile){
        profile{ id name } userErrors{ field message } } }"""
    payload = {
        "name": PROFILE_NAME,
        "variantsToAssociate": variant_gids,
        "locationGroupsToCreate": [{
            "locations": origin,
            "zonesToCreate": [{
                "name": z["name"],
                # countries that have provinces must declare them; mirroring
                # the General profile means all provinces are included
                "countries": [{"code": c, "includeAllProvinces": True}
                              for c in z["countries"]],
                "methodDefinitionsToCreate": [{
                    "name": r["name"],
                    "active": True,
                    "rateDefinition": {"price": {"amount": r["amount"],
                                                 "currencyCode": r["currency"]}},
                } for r in z["rates"]],
            } for z in zones],
        }],
    }
    res = gql(M, {"profile": payload})["data"]["deliveryProfileCreate"]
    if res["userErrors"]:
        print(f"❌ {json.dumps(res['userErrors'], indent=1)}")
        return
    prof = res["profile"]
    print(f"\n✅ created {prof['name']!r}\n   {prof['id']}")
    print(f"\nUndo with:\n  python3 exclude_from_free_shipping.py "
          f"--delete {prof['id']} --confirm")


if __name__ == "__main__":
    main()
