#!/usr/bin/env python3
"""
Organic price test — price push (dry-run by default).

Writes the treated cohort's proposed prices to the Shopify MASTER (base) price.
AU/UK/CA follow automatically via Markets FX, so nothing per-market is written.

Safety:
  * dry-run unless --confirm is passed
  * always snapshots current price + compareAtPrice to a rollback file BEFORE
    any write; --rollback <file> restores exactly those values
  * refuses to run if a proposed price would breach the margin floor
  * compareAtPrice is nulled when it would sit at or below the new price
    (Shopify rejects that, and it would show a fake "sale")

Usage:
  python3 organic_test_push.py                      # preview
  python3 organic_test_push.py --confirm            # apply
  python3 organic_test_push.py --rollback outputs/rollback_<ts>.json --confirm
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
STORE = "9dkd2w-g3.myshopify.com"
API = "2024-10"
MIN_MARGIN_FLOOR = 0.35   # hard stop: user's stated minimum
PSP_FEE_RATE = 0.05


def _token() -> str:
    return re.search(r"SHOPIFY_ACCESS_TOKEN=([^\s]+)",
                     (BASE_DIR / ".env").read_text()).group(1)


def gql(query: str, variables: dict = None) -> dict:
    req = urllib.request.Request(
        f"https://{STORE}/admin/api/{API}/graphql.json",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"X-Shopify-Access-Token": _token(),
                 "Content-Type": "application/json"})
    data = json.load(urllib.request.urlopen(req))
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data


def load_targets(cohort: str = "treated") -> list:
    """Changed variants of the cohort, joined to their proposal rows."""
    reports = sorted(OUTPUTS_DIR.glob("geo_pricing_proposal_us_*.csv"))
    if not reports:
        sys.exit("No US proposal report found — run run_geo_pricing.py report first.")
    with open(reports[-1]) as f:
        play = {r["variant_id"]: r for r in csv.DictReader(f)}

    path = OUTPUTS_DIR / f"organic_test_{cohort}.csv"
    targets = []
    with open(path) as f:
        for row in csv.DictReader(f):
            for vid in (row.get("changed_variant_ids") or "").split(","):
                p = play.get(vid)
                if not p:
                    continue
                new_price = float(p["proposed_USD"] or 0)
                cogs = float(p["cogs_usd"] or 0)
                if new_price <= 0:
                    continue
                targets.append({
                    "variant_id": vid, "item": p["item"],
                    "product": row["title"],
                    "new_price": round(new_price, 2),
                    "report_current": float(p["current_USD"] or 0),
                    "cogs": cogs, "case": p["note"].replace("(proxy)", ""),
                })
    return targets


def fetch_live(variant_ids: list) -> dict:
    """Live price / compareAtPrice / product id, in batches of 100."""
    out, Q = {}, """
    query($ids:[ID!]!){ nodes(ids:$ids){ ... on ProductVariant {
      legacyResourceId price compareAtPrice product { id } } } }
    """
    for i in range(0, len(variant_ids), 100):
        ids = [f"gid://shopify/ProductVariant/{v}" for v in variant_ids[i:i + 100]]
        for n in gql(Q, {"ids": ids})["data"]["nodes"]:
            if not n:
                continue
            out[str(n["legacyResourceId"])] = {
                "price": float(n["price"] or 0),
                "compare_at": float(n["compareAtPrice"]) if n["compareAtPrice"] else None,
                "product_gid": n["product"]["id"],
            }
        time.sleep(0.25)
    return out


def check_floor(t: dict) -> str:
    """Return a reason string if the price breaches the margin floor."""
    if t["cogs"] <= 0:
        return ""   # unknown cost — floor cannot be evaluated, not a breach
    margin = 1 - t["cogs"] / t["new_price"] - PSP_FEE_RATE
    if margin < MIN_MARGIN_FLOOR - 0.005:
        return f"margin {margin*100:.1f}% < {MIN_MARGIN_FLOOR*100:.0f}% floor"
    return ""


def apply_updates(plan: list, live: dict) -> tuple:
    """Write prices. Returns (ok, failures)."""
    M = """
    mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants { id price compareAtPrice }
        userErrors { field message } } }
    """
    ok, failures = 0, []
    for t in plan:
        l = live[t["variant_id"]]
        v = {"id": f"gid://shopify/ProductVariant/{t['variant_id']}",
             "price": f"{t['new_price']:.2f}"}
        # Shopify rejects compareAtPrice <= price, and it would fake a sale
        if l["compare_at"] is not None and l["compare_at"] <= t["new_price"]:
            v["compareAtPrice"] = None
        try:
            r = gql(M, {"productId": l["product_gid"], "variants": [v]})
            errs = r["data"]["productVariantsBulkUpdate"]["userErrors"]
            if errs:
                failures.append((t, errs))
            else:
                ok += 1
        except Exception as e:                      # noqa: BLE001 - report, continue
            failures.append((t, str(e)))
        time.sleep(0.3)
    return ok, failures


def rollback(path: Path, confirm: bool) -> None:
    snap = json.loads(path.read_text())
    entries = snap["variants"]
    print(f"Rollback from {path.name} ({snap['taken_at']}): {len(entries)} variants")
    M = """
    mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        userErrors { field message } } }
    """
    for e in entries[:10]:
        print(f"  {e['variant_id']}: -> ${e['price']:.2f} "
              f"(compare_at {e['compare_at']}) {e['item'][:44]}")
    if len(entries) > 10:
        print(f"  ... and {len(entries)-10} more")
    if not confirm:
        print("\nDRY RUN — pass --confirm to restore these prices.")
        return
    ok = 0
    for e in entries:
        v = {"id": f"gid://shopify/ProductVariant/{e['variant_id']}",
             "price": f"{e['price']:.2f}"}
        if e["compare_at"] is not None:
            v["compareAtPrice"] = f"{e['compare_at']:.2f}"
        r = gql(M, {"productId": e["product_gid"], "variants": [v]})
        if not r["data"]["productVariantsBulkUpdate"]["userErrors"]:
            ok += 1
        time.sleep(0.3)
    print(f"✅ restored {ok}/{len(entries)} variants")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="treated")
    ap.add_argument("--confirm", action="store_true", help="actually write to Shopify")
    ap.add_argument("--rollback", help="restore prices from a rollback snapshot")
    a = ap.parse_args()

    OUTPUTS_DIR.mkdir(exist_ok=True)
    if a.rollback:
        return rollback(Path(a.rollback), a.confirm)

    targets = load_targets(a.cohort)
    live = fetch_live([t["variant_id"] for t in targets])

    plan, skipped, drifted = [], [], []
    for t in targets:
        l = live.get(t["variant_id"])
        if not l:
            skipped.append((t, "variant not found in Shopify"))
            continue
        reason = check_floor(t)
        if reason:
            skipped.append((t, reason))
            continue
        if abs(l["price"] - t["new_price"]) < 0.005:
            skipped.append((t, "already at target price"))
            continue
        # the report's "current" is FX/base derived; flag if live differs a lot
        if t["report_current"] > 0 and \
                abs(l["price"] - t["report_current"]) / t["report_current"] > 0.02:
            drifted.append((t, l["price"]))
        t["live_price"] = l["price"]
        plan.append(t)

    print(f"\n{'PLAN':6} {len(plan)} price changes "
          f"({len(skipped)} skipped) — cohort '{a.cohort}', US master price\n")
    print(f"{'now':>8} {'new':>8} {'chg':>7}  {'case':11} product")
    ups = downs = 0
    for t in sorted(plan, key=lambda x: x["new_price"] - x["live_price"]):
        d = (t["new_price"] - t["live_price"]) / t["live_price"] * 100
        ups += d > 0
        downs += d < 0
        print(f"{t['live_price']:>8.2f} {t['new_price']:>8.2f} {d:>+6.1f}%  "
              f"{t['case']:11} {t['product'][:44]}")
    print(f"\n{downs} price cuts, {ups} price raises")
    if skipped:
        print(f"\nskipped ({len(skipped)}):")
        for t, why in skipped[:12]:
            print(f"  {why:38} {t['product'][:40]}")
        if len(skipped) > 12:
            print(f"  ... and {len(skipped)-12} more")
    if drifted:
        print(f"\n⚠️ {len(drifted)} variants whose live price differs from the report "
              f"(report is stale for these — live value is used):")
        for t, lp in drifted[:5]:
            print(f"  live ${lp:.2f} vs report ${t['report_current']:.2f}  "
                  f"{t['product'][:40]}")

    if not a.confirm:
        print("\n" + "=" * 66)
        print("DRY RUN — nothing was written. Re-run with --confirm to apply.")
        print("=" * 66)
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_path = OUTPUTS_DIR / f"rollback_{stamp}.json"
    snap_path.write_text(json.dumps({
        "taken_at": stamp, "cohort": a.cohort,
        "variants": [{"variant_id": t["variant_id"], "item": t["item"],
                      "price": live[t["variant_id"]]["price"],
                      "compare_at": live[t["variant_id"]]["compare_at"],
                      "product_gid": live[t["variant_id"]]["product_gid"]}
                     for t in plan]}, indent=1))
    print(f"\n💾 rollback snapshot: {snap_path.name}")

    ok, failures = apply_updates(plan, live)
    print(f"✅ updated {ok}/{len(plan)} variants")
    if failures:
        print(f"❌ {len(failures)} failed:")
        for t, err in failures[:10]:
            print(f"  {t['product'][:40]}: {err}")
    print(f"\nUndo with:\n  python3 organic_test_push.py "
          f"--rollback {snap_path.relative_to(BASE_DIR)} --confirm")


if __name__ == "__main__":
    main()
