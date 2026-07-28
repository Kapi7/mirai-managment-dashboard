#!/usr/bin/env python3
"""
Fix the two structural delivery leaks in the General profile (dry-run default).

1. ASIA — the free-shipping rule is set to TOTAL_WEIGHT >= 80 KILOGRAMS, which
   no order can ever reach, so 21 countries have never had free shipping.
   Replacing it with a price rule. Asia is NOT one market though: shipping runs
   $7 (Japan, Malaysia) to $50 (Armenia, Iraq, Jordan), so a single threshold
   would leak. The cheap countries keep the Asia zone at a $60 threshold; the
   expensive ones move to a new "Asia — remote" zone at $150.

2. AFRICA / EUROPE — every Africa country costs ~$50 to ship, and seven Europe
   countries do too, against a shared $80 threshold: each free order loses
   ~$11. Africa's threshold moves to $150; the seven expensive Europe countries
   move to a new "Europe — remote" zone at $150.

Thresholds come from the break-even basket per country: basket x 48.6% blended
margin must cover the real shipping cost at that basket's weight.

Nothing else is touched — US, AU, UK, CA, Israel, Saudi Arabia are unchanged,
so the running price test stays clean.

Usage:
  python3 fix_delivery_zones.py            # preview
  python3 fix_delivery_zones.py --confirm  # apply
"""

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from organic_test_push import gql  # noqa: E402

PROFILE_ID = "gid://shopify/DeliveryProfile/122187514228"
LOCATION_GROUP = "gid://shopify/DeliveryLocationGroup/129945796980"

ZONE_AFRICA = "gid://shopify/DeliveryZone/568970412404"
ZONE_ASIA = "gid://shopify/DeliveryZone/568970576244"
ZONE_EUROPE = "gid://shopify/DeliveryZone/562427298164"

METHOD_AFRICA_FREE = "gid://shopify/DeliveryMethodDefinition/1039529050484"
METHOD_ASIA_FREE = "gid://shopify/DeliveryMethodDefinition/1039529247092"
COND_AFRICA_FREE = ("gid://shopify/DeliveryCondition/68210295156"
                    "?operator=greater_than_or_equal_to")
COND_ASIA_FREE = ("gid://shopify/DeliveryCondition/68210327924"
                  "?operator=greater_than_or_equal_to")

# break-even <= $45 -> these stay in the cheap Asia zone at a $60 threshold
ASIA_CHEAP = ["JP", "MY", "PH", "QA", "AE"]
# everything else in Asia (incl. countries with no rate data) -> remote at $150
ASIA_REMOTE = ["AM", "IQ", "JO", "KG", "LB", "BH", "BD", "KW", "OM", "PK",
               "CY", "AF", "AZ", "GE", "PS", "YE"]
# Europe countries costing ~$50 to ship (break-even $120) -> remote at $150
EUROPE_REMOTE = ["AL", "EE", "IS", "XK", "MD", "ME", "RS"]

NEW_AFRICA_THRESHOLD = 150.0
ASIA_THRESHOLD = 60.0
REMOTE_THRESHOLD = 150.0


def current_zone_countries(zone_id: str) -> list:
    Q = """{ deliveryProfiles(first:5){ nodes{ default profileLocationGroups{
      locationGroupZones(first:30){ nodes{ zone{ id
        countries{ code{ countryCode } } } } } } } } }"""
    for p in gql(Q)["data"]["deliveryProfiles"]["nodes"]:
        if not p["default"]:
            continue
        for lg in p["profileLocationGroups"]:
            for z in lg["locationGroupZones"]["nodes"]:
                if z["zone"]["id"] == zone_id:
                    return [c["code"]["countryCode"]
                            for c in z["zone"]["countries"] if c.get("code")]
    return []


def money(amount: float) -> dict:
    return {"amount": amount, "currencyCode": "USD"}


def price_condition(threshold: float, condition_id: str = None) -> dict:
    """A 'cart total >= threshold' condition. criteria is a Float plus a
    separate unit — not a MoneyInput."""
    c = {"criteria": threshold, "criteriaUnit": "USD",
         "operator": "GREATER_THAN_OR_EQUAL_TO"}
    if condition_id:
        c["id"] = condition_id          # updates must name the condition
    else:
        c["field"] = "TOTAL_PRICE"      # creates must name the field
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args()

    asia_now = current_zone_countries(ZONE_ASIA)
    europe_now = current_zone_countries(ZONE_EUROPE)
    asia_keep = [c for c in asia_now if c in ASIA_CHEAP]
    asia_move = [c for c in asia_now if c not in ASIA_CHEAP]
    europe_keep = [c for c in europe_now if c not in EUROPE_REMOTE]
    europe_move = [c for c in europe_now if c in EUROPE_REMOTE]

    print("\nPLANNED CHANGES to the General delivery profile\n" + "=" * 62)
    print(f"\n1. AFRICA — free-shipping threshold $80 → ${NEW_AFRICA_THRESHOLD:.0f}")
    print(f"   (all 8 priced countries cost ~$50 to ship; break-even is $120)")

    print(f"\n2. ASIA — rule changed from 'weight ≥ 80 KG' (unreachable) "
          f"to 'price ≥ ${ASIA_THRESHOLD:.0f}'")
    print(f"   stays in Asia ({len(asia_keep)}): {', '.join(asia_keep)}")
    print(f"   moves to new 'Asia — remote' zone at ${REMOTE_THRESHOLD:.0f} "
          f"({len(asia_move)}): {', '.join(asia_move)}")

    print(f"\n3. EUROPE — {len(europe_move)} high-cost countries move to a new "
          f"'Europe — remote' zone at ${REMOTE_THRESHOLD:.0f}")
    print(f"   moving: {', '.join(europe_move)}")
    print(f"   staying in Europe at $80: {len(europe_keep)} countries")

    print("\nUnchanged: US, Australia, Canada, United Kingdom, Israel, "
          "Saudi Arabia, US AL N HI")

    if not a.confirm:
        print("\n" + "=" * 62)
        print("DRY RUN — nothing changed. Re-run with --confirm to apply.")
        print("=" * 62)
        return

    M = """mutation($id: ID!, $profile: DeliveryProfileInput!){
      deliveryProfileUpdate(id: $id, profile: $profile){
        profile{ id } userErrors{ field message } } }"""

    def run(step: str, payload: dict):
        res = gql(M, {"id": PROFILE_ID, "profile": payload})["data"]["deliveryProfileUpdate"]
        if res["userErrors"]:
            print(f"❌ {step}: {json.dumps(res['userErrors'])}")
            return False
        print(f"✅ {step}")
        return True

    def remote_zone(name: str, codes: list, flat: float) -> dict:
        return {
            "name": name,
            "countries": [{"code": c, "includeAllProvinces": True} for c in codes],
            "methodDefinitionsToCreate": [
                {"name": f"{name} Shipping", "active": True,
                 "rateDefinition": {"price": money(flat)}},
                {"name": f"Free Shipping Over ${REMOTE_THRESHOLD:.0f}",
                 "active": True,
                 "rateDefinition": {"price": money(0.0)},
                 # creating a conditional rate uses priceConditionsToCreate
                 # (MoneyInput criteria), NOT conditionsToUpdate's flat Float
                 "priceConditionsToCreate": [
                     {"criteria": money(REMOTE_THRESHOLD),
                      "operator": "GREATER_THAN_OR_EQUAL_TO"}]},
            ],
        }

    # ONE atomic mutation. A country cannot belong to two zones, and Shopify
    # rejects a create that claims a country still held elsewhere — so the
    # shrink and the create must land together. Doing this in separate calls
    # leaves the moved countries with no zone at all between them, which takes
    # their checkout down.
    payload = {"locationGroupsToUpdate": [{
        "id": LOCATION_GROUP,
        "zonesToUpdate": [
            # Europe loses the high-cost countries
            {"id": ZONE_EUROPE,
             "countries": [{"code": c, "includeAllProvinces": True}
                           for c in europe_keep]},
            # Asia keeps only the cheap countries. Its free rate is keyed on
            # TOTAL_WEIGHT and Shopify will not let a condition change field,
            # so the broken rate is deleted and a price-based one created.
            {"id": ZONE_ASIA,
             "countries": [{"code": c, "includeAllProvinces": True}
                           for c in asia_keep],
             "methodDefinitionsToCreate": [{
                 "name": f"Free Shipping Over ${ASIA_THRESHOLD:.0f}",
                 "active": True,
                 "rateDefinition": {"price": money(0.0)},
                 "priceConditionsToCreate": [
                     {"criteria": money(ASIA_THRESHOLD),
                      "operator": "GREATER_THAN_OR_EQUAL_TO"}],
             }]},
            # (Africa's threshold is already $150 — applied on an earlier run.
            #  Updating a condition mints a NEW condition id, so re-sending a
            #  stale one fails the whole mutation.)
        ],
        "zonesToCreate": [remote_zone("Asia — remote", asia_move, 10.0),
                          remote_zone("Europe — remote", europe_move, 20.0)],
    }],
        # drop the unreachable "weight >= 80 KG" free rate
        "methodDefinitionsToDelete": [METHOD_ASIA_FREE]}

    if run("all changes (single atomic update)", payload):
        print("\nDone. Verify with delivery_exposure_by_country.py.")
    else:
        print("   nothing changed — coverage untouched")


if __name__ == "__main__":
    main()
