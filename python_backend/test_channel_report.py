#!/usr/bin/env python3
"""
Channel & profitability read on the price test (analysis only).

For every order since the change that contains a test product:
  * traffic channel from landing/referring site: organic search / paid /
    direct / referral / shop app
  * item economics: revenue - COGS
  * order shipping economics: what the customer paid minus the real matrix
    cost for that country and weight

Usage: python3 test_channel_report.py [--start 2026-07-28]
"""

import argparse
import csv
import datetime
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
MATRIX = Path("/Users/kapi7/mirai_report/shipping_matrix_all.csv")
sys.path.insert(0, str(BASE_DIR))

PAID_MARKERS = ("gclid=", "fbclid=", "ttclid=", "msclkid=",
                "utm_medium=cpc", "utm_medium=paid", "utm_medium=ppc",
                "utm_source=facebook", "utm_source=instagram",
                "utm_source=tiktok", "utm_source=google_ads")
SEARCH_ENGINES = ("google.", "bing.", "duckduckgo.", "yahoo.", "ecosia.",
                  "baidu.", "yandex.")


def classify(order) -> str:
    src = (order.get("source_name") or "").lower()
    if src not in ("web", "", "online store"):
        return "shop_app" if "shop" in src else f"other:{src[:12]}"
    landing = (order.get("landing_site") or "").lower()
    referrer = (order.get("referring_site") or "").lower()
    if any(m in landing for m in PAID_MARKERS):
        return "paid"
    if any(e in referrer for e in SEARCH_ENGINES):
        return "organic"
    if referrer:
        return "referral"
    return "direct"


def load_matrix():
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
    return tiers


def ship_cost(tiers, country, kg):
    t = tiers.get(country)
    if not t or kg <= 0:
        return None
    for w, p in t:
        if kg <= w + 1e-9:
            return p
    return t[-1][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-07-28")
    a = ap.parse_args()

    from organic_test_readout import load_cohort, _token
    import time
    import urllib.request

    def fetch_full(start, end):
        # fetch_orders() trims fields for speed; this report needs the
        # attribution + shipping fields too
        orders, url = [], (
            "https://9dkd2w-g3.myshopify.com/admin/api/2024-10/orders.json"
            f"?status=any&created_at_min={start}T00:00:00Z"
            f"&created_at_max={end}T23:59:59Z&limit=250"
            "&fields=id,created_at,cancelled_at,financial_status,line_items,"
            "source_name,landing_site,referring_site,shipping_lines,"
            "shipping_address,total_weight")
        while url:
            resp = urllib.request.urlopen(urllib.request.Request(
                url, headers={"X-Shopify-Access-Token": _token()}))
            orders.extend(json.load(resp).get("orders", []))
            url = None
            for part in resp.headers.get("Link", "").split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]
            time.sleep(0.3)
        return orders

    fetch_orders = fetch_full
    arms = {"treated": load_cohort("treated"), "control": load_cohort("control")}
    meta = {}
    reports = sorted(OUTPUTS_DIR.glob("geo_pricing_proposal_us_*.csv"))
    with open(reports[-1]) as f:
        play = {r["variant_id"]: r for r in csv.DictReader(f)}
    tiers = load_matrix()

    start = datetime.date.fromisoformat(a.start)
    end = datetime.date.today()
    orders = fetch_orders(start, end)

    lines = []          # one row per test line item
    order_ship = []     # one row per order containing test items
    for o in orders:
        if o.get("cancelled_at") or o.get("financial_status") in ("voided", "refunded"):
            continue
        test_items = []
        for li in o.get("line_items") or []:
            vid = str(li.get("variant_id") or "")
            arm = ("treated" if vid in arms["treated"]
                   else "control" if vid in arms["control"] else None)
            if not arm:
                continue
            p = play.get(vid, {})
            qty = li.get("quantity") or 0
            disc = sum(float(d.get("amount") or 0)
                       for d in li.get("discount_allocations") or [])
            rev = float(li.get("price") or 0) * qty - disc
            cogs = float(p.get("cogs_usd") or 0) * qty
            test_items.append({
                "order": o["id"], "date": o["created_at"][:10],
                "channel": classify(o), "arm": arm, "vid": vid,
                "product": (li.get("title") or "")[:60],
                "case": p.get("note", "").replace("(proxy)", ""),
                "units": qty, "revenue": round(rev, 2),
                "product_margin": round(rev - cogs, 2),
            })
        if not test_items:
            continue
        lines.extend(test_items)
        country = (o.get("shipping_address") or {}).get("country") or ""
        kg = (o.get("total_weight") or 0) / 1000.0
        charged = sum(float(l.get("price") or 0)
                      for l in o.get("shipping_lines") or [])
        cost = ship_cost(tiers, country, kg)
        order_ship.append({
            "order": o["id"], "date": o["created_at"][:10],
            "channel": test_items[0]["channel"],
            "arms": sorted({t["arm"] for t in test_items}),
            "country": country, "kg": kg, "charged": charged,
            "ship_cost": cost,
            "ship_net": round(charged - cost, 2) if cost is not None else None,
        })

    out = {"generated": str(datetime.date.today()), "start": a.start,
           "lines": lines, "orders": order_ship}
    (OUTPUTS_DIR / "test_channel_report.json").write_text(json.dumps(out, indent=1))

    # ---- console summary
    def agg(rows, key):
        d = defaultdict(lambda: {"u": 0, "rev": 0.0, "pm": 0.0})
        for r in rows:
            x = d[key(r)]
            x["u"] += r["units"]; x["rev"] += r["revenue"]
            x["pm"] += r["product_margin"]
        return d

    print(f"window {a.start} .. {end} — {len(order_ship)} orders with test items\n")
    for arm in ("treated", "control"):
        rows = [r for r in lines if r["arm"] == arm]
        print(f"== {arm.upper()} by channel")
        for ch, x in sorted(agg(rows, lambda r: r["channel"]).items(),
                            key=lambda kv: -kv[1]["rev"]):
            print(f"   {ch:10} {x['u']:>3}u  rev ${x['rev']:>8.2f}  "
                  f"product margin ${x['pm']:>8.2f}")
    ship = [o for o in order_ship if o["ship_net"] is not None]
    tot_charged = sum(o['charged'] for o in ship)
    tot_cost = sum(o['ship_cost'] for o in ship)
    free = [o for o in ship if o["charged"] == 0]
    print(f"\n== SHIPPING on those orders: charged ${tot_charged:.2f} vs real cost "
          f"${tot_cost:.2f} -> net ${tot_charged-tot_cost:+.2f} "
          f"({len(free)} free-shipping orders)")
    print("\n== TREATED items sold, by product")
    for (prod, case), x in sorted(
            agg([r for r in lines if r["arm"] == "treated"],
                lambda r: (r["product"], r["case"])).items(),
            key=lambda kv: -kv[1]["rev"]):
        print(f"   {x['u']}u  ${x['rev']:>7.2f}  margin ${x['pm']:>7.2f}  "
              f"[{case or '—'}] {prod[:48]}")


if __name__ == "__main__":
    main()
