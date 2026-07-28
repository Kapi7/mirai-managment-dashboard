#!/usr/bin/env python3
"""
Organic pricing test readout (analysis only — no writes).

Difference-in-differences on units, revenue and contribution margin between the
treated and control cohorts, comparing an equal-length window before and after
the price change. Seasonality and site-wide effects cancel between the arms.

Usage:
  python3 organic_test_readout.py --start 2026-08-01 --weeks 4
      --start is the date prices changed (the test's day 0).

Prints per-arm pre/post figures, the lift in each, and the diff-in-diff — plus
the margin guardrail: whether extra units actually paid for the price cut.
"""

import argparse
import csv
import datetime
import json
import re
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
STORE = "9dkd2w-g3.myshopify.com"


def _token() -> str:
    return re.search(r"SHOPIFY_ACCESS_TOKEN=([^\s]+)",
                     (BASE_DIR / ".env").read_text()).group(1)


def load_cohort(name: str) -> dict:
    """{variant_id: cohort_row} for the changed variants of a cohort."""
    path = OUTPUTS_DIR / f"organic_test_{name}.csv"
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            for vid in (r.get("changed_variant_ids") or "").split(","):
                if vid:
                    out[vid] = r
    return out


def fetch_orders(start: datetime.date, end: datetime.date) -> list:
    token, orders = _token(), []
    url = (f"https://{STORE}/admin/api/2024-10/orders.json?status=any"
           f"&created_at_min={start}T00:00:00Z&created_at_max={end}T23:59:59Z"
           f"&limit=250&fields=id,created_at,cancelled_at,financial_status,line_items")
    while url:
        resp = urllib.request.urlopen(urllib.request.Request(
            url, headers={"X-Shopify-Access-Token": token}))
        orders.extend(json.load(resp).get("orders", []))
        url = None
        for part in resp.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
        time.sleep(0.3)
    return orders


def measure(orders: list, variant_ids: set, cogs: dict) -> dict:
    units = revenue = margin = 0.0
    for o in orders:
        if o.get("cancelled_at") or o.get("financial_status") in ("voided", "refunded"):
            continue
        for li in o.get("line_items") or []:
            vid = str(li.get("variant_id") or "")
            if vid not in variant_ids:
                continue
            qty = li.get("quantity") or 0
            disc = sum(float(d.get("amount") or 0)
                       for d in li.get("discount_allocations") or [])
            rev = float(li.get("price") or 0) * qty - disc
            units += qty
            revenue += rev
            margin += rev - cogs.get(vid, 0.0) * qty
    return {"units": int(units), "revenue": round(revenue, 2),
            "margin": round(margin, 2)}


def cogs_map(variant_ids: set) -> dict:
    """Per-variant unit cost, read from the latest proposal report."""
    matches = sorted(OUTPUTS_DIR.glob("geo_pricing_proposal_us_*.csv"))
    if not matches:
        return {}
    with open(matches[-1]) as f:
        return {r["variant_id"]: float(r["cogs_usd"] or 0)
                for r in csv.DictReader(f) if r["variant_id"] in variant_ids}


def pct(new: float, old: float) -> float:
    return ((new - old) / old * 100) if old else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True,
                    help="date prices changed, YYYY-MM-DD (test day 0)")
    ap.add_argument("--weeks", type=int, default=4)
    a = ap.parse_args()

    day0 = datetime.date.fromisoformat(a.start)
    span = datetime.timedelta(weeks=a.weeks)
    pre_start, pre_end = day0 - span, day0 - datetime.timedelta(days=1)
    post_start, post_end = day0, day0 + span - datetime.timedelta(days=1)

    arms = {n: load_cohort(n) for n in ("treated", "control")}
    all_ids = set().union(*[set(v) for v in arms.values()])
    cogs = cogs_map(all_ids)

    print(f"pre : {pre_start} .. {pre_end}")
    print(f"post: {post_start} .. {post_end}\n")
    pre_orders = fetch_orders(pre_start, pre_end)
    post_orders = fetch_orders(post_start, post_end)

    results = {}
    for arm, rows in arms.items():
        ids = set(rows)
        pre = measure(pre_orders, ids, cogs)
        post = measure(post_orders, ids, cogs)
        results[arm] = {"pre": pre, "post": post,
                        "units_lift_pct": round(pct(post["units"], pre["units"]), 1),
                        "margin_lift_pct": round(pct(post["margin"], pre["margin"]), 1)}
        print(f"{arm.upper():8} pre  {pre['units']:>5} units  "
              f"${pre['revenue']:>9,.0f}  margin ${pre['margin']:>9,.0f}")
        print(f"{'':8} post {post['units']:>5} units  "
              f"${post['revenue']:>9,.0f}  margin ${post['margin']:>9,.0f}")
        print(f"{'':8} lift {results[arm]['units_lift_pct']:>+5.1f}% units, "
              f"{results[arm]['margin_lift_pct']:>+5.1f}% margin\n")

    did_units = results["treated"]["units_lift_pct"] - results["control"]["units_lift_pct"]
    did_margin = results["treated"]["margin_lift_pct"] - results["control"]["margin_lift_pct"]
    print(f"DIFF-IN-DIFF   units {did_units:+.1f} pts | margin {did_margin:+.1f} pts")
    print("\nVerdict rule: margin diff-in-diff > 0 means the extra units paid for "
          "the price cut — roll out. Units up but margin down means the cuts were "
          "too deep — raise the floor. Neither moves — price was not the blocker.")

    results["diff_in_diff"] = {"units_pts": round(did_units, 1),
                               "margin_pts": round(did_margin, 1)}
    out = OUTPUTS_DIR / f"organic_test_readout_{post_end}.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"\n-> {out.name}")


if __name__ == "__main__":
    main()
