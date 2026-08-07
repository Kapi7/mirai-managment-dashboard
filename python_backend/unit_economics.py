#!/usr/bin/env python3
"""
Per-product unit economics, before vs after the price change.

The question this answers: the cuts shrank margin per unit — did the ad cost
per unit shrink by MORE? If so the cut paid for itself.

For each test product, in matched windows:
    margin/unit   = price - COGS      (from actual orders)
    ad cost/unit  = Google Shopping spend on that product / units sold
    NET/unit      = margin/unit - ad cost/unit      <-- the verdict
    AOV           = average value of orders containing the product

Product-level spend comes from shopping_performance_view segmented by
product_item_id, whose id ends in the Shopify variant id.

Usage: python3 unit_economics.py [--days 10]
"""

import argparse
import csv
import datetime
import json
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
CHANGE = "2026-07-28"
sys.path.insert(0, str(BASE_DIR))


def ads_by_product(start, end) -> dict:
    """{variant_id: {cost, clicks, conversions}} for a date window."""
    import google_ads_efficiency as g
    c = g.creds()
    tok = g.access_token(c)
    rows = g.search(c, tok, f"""
        SELECT segments.product_item_id, metrics.cost_micros, metrics.clicks,
               metrics.conversions, metrics.conversions_value
        FROM shopping_performance_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'""")
    out = defaultdict(lambda: {"cost": 0.0, "clicks": 0, "conv": 0.0})
    for r in rows:
        item = r["segments"].get("productItemId") or ""
        vid = item.rsplit("_", 1)[-1]          # shopify_zz_<product>_<variant>
        if not vid.isdigit():
            continue
        m = r["metrics"]
        o = out[vid]
        o["cost"] += int(m.get("costMicros", 0)) / 1e6
        o["clicks"] += int(m.get("clicks", 0))
        o["conv"] += float(m.get("conversions", 0))
    return dict(out)


def shopify_orders(start, end) -> list:
    from organic_test_readout import _token
    orders, url = [], (
        "https://9dkd2w-g3.myshopify.com/admin/api/2024-10/orders.json"
        f"?status=any&created_at_min={start}T00:00:00Z"
        f"&created_at_max={end}T23:59:59Z&limit=250"
        "&fields=id,created_at,cancelled_at,financial_status,line_items,"
        "subtotal_price")
    while url:
        resp = urllib.request.urlopen(urllib.request.Request(
            url, headers={"X-Shopify-Access-Token": _token()}))
        orders.extend(json.load(resp).get("orders", []))
        url = None
        for p in resp.headers.get("Link", "").split(","):
            if 'rel="next"' in p:
                url = p.split("<")[1].split(">")[0]
        time.sleep(0.3)
    return orders


def shopping_share(start, end) -> float:
    """Shopping spend as a share of ALL account spend in the window.
    Product-level costs only exist for Shopping, so per-unit ad cost must be
    grossed up by this to be comparable across windows — the campaign mix
    shifted a lot (38% Shopping before the change, 74% after)."""
    import google_ads_efficiency as g
    path = OUTPUTS_DIR / "ads_efficiency.json"
    acct = 0.0
    if path.exists():
        for r in json.loads(path.read_text())["daily"]:
            if str(start) <= r["date"] <= str(end):
                acct += r["cost"]
    c = g.creds()
    rows = g.search(c, g.access_token(c), f"""
        SELECT segments.date, metrics.cost_micros FROM shopping_performance_view
        WHERE segments.date BETWEEN '{start}' AND '{end}'""")
    shop = sum(int(r["metrics"].get("costMicros", 0)) for r in rows) / 1e6
    return (shop / acct) if acct else 1.0


def window(orders, ads, cohort_ids, meta, gross_up=1.0) -> dict:
    """Aggregate per variant: units, revenue, margin, ad cost, AOV basket."""
    agg = defaultdict(lambda: {"units": 0, "rev": 0.0, "cogs": 0.0,
                               "orders": 0, "basket": 0.0})
    for o in orders:
        if o.get("cancelled_at") or o.get("financial_status") in ("voided", "refunded"):
            continue
        sub = float(o.get("subtotal_price") or 0)
        hit = set()
        for li in o.get("line_items") or []:
            vid = str(li.get("variant_id") or "")
            if vid not in cohort_ids:
                continue
            qty = li.get("quantity") or 0
            disc = sum(float(d.get("amount") or 0)
                       for d in li.get("discount_allocations") or [])
            a = agg[vid]
            a["units"] += qty
            a["rev"] += float(li.get("price") or 0) * qty - disc
            a["cogs"] += meta[vid]["cogs"] * qty
            hit.add(vid)
        for vid in hit:
            agg[vid]["orders"] += 1
            agg[vid]["basket"] += sub
    for vid, a in agg.items():
        ad = ads.get(vid, {})
        a["ad_cost"] = round(ad.get("cost", 0.0) / gross_up, 2)
        a["margin"] = round(a["rev"] - a["cogs"], 2)
        a["m_per_unit"] = a["margin"] / a["units"] if a["units"] else 0
        a["ad_per_unit"] = a["ad_cost"] / a["units"] if a["units"] else 0
        a["net_per_unit"] = a["m_per_unit"] - a["ad_per_unit"]
        a["aov"] = a["basket"] / a["orders"] if a["orders"] else 0
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    a = ap.parse_args()

    from organic_test_readout import load_cohort
    reports = sorted(OUTPUTS_DIR.glob("geo_pricing_proposal_us_*.csv"))
    with open(reports[-1]) as f:
        play = {r["variant_id"]: r for r in csv.DictReader(f)}

    meta, cohort = {}, {}
    for arm in ("treated", "control"):
        rows = load_cohort(arm)
        for vid, row in rows.items():
            p = play.get(vid)
            if not p:
                continue
            cohort[vid] = arm
            d = float(p["delta_pct"] or 0)
            meta[vid] = {
                "product": row["title"], "arm": arm,
                "cogs": float(p["cogs_usd"] or 0),
                "was": float(p["current_USD"] or 0),
                "now": float(p["proposed_USD"] or 0),
                "bucket": ("raise" if d > 2 else "shallow" if d > -15
                           else "mid" if d > -30 else "deep") if arm == "treated"
                          else "control",
            }

    change = datetime.date.fromisoformat(CHANGE)
    post_end = datetime.date.today()
    post_start = change
    ndays = min(a.days, (post_end - post_start).days + 1)
    post_start = post_end - datetime.timedelta(days=ndays - 1)
    pre_end = change - datetime.timedelta(days=1)
    pre_start = pre_end - datetime.timedelta(days=ndays - 1)

    print(f"PRE  {pre_start} .. {pre_end}   POST {post_start} .. {post_end}"
          f"   ({ndays} days each)\n")

    ids = set(cohort)
    sh_pre = shopping_share(pre_start, pre_end)
    sh_post = shopping_share(post_start, post_end)
    print(f"Shopping share of ad spend: pre {sh_pre*100:.0f}%  post {sh_post*100:.0f}%"
          f"  (per-product costs grossed up by this)\n")
    pre = window(shopify_orders(pre_start, pre_end),
                 ads_by_product(pre_start, pre_end), ids, meta, sh_pre)
    post = window(shopify_orders(post_start, post_end),
                  ads_by_product(post_start, post_end), ids, meta, sh_post)

    # ---- bucket rollup: the verdict view
    def roll(agg, keyfn):
        out = defaultdict(lambda: {"units": 0, "rev": 0.0, "margin": 0.0,
                                   "ad": 0.0, "orders": 0, "basket": 0.0})
        for vid, x in agg.items():
            k = keyfn(vid)
            o = out[k]
            o["units"] += x["units"]; o["rev"] += x["rev"]
            o["margin"] += x["margin"]; o["ad"] += x["ad_cost"]
            o["orders"] += x["orders"]; o["basket"] += x["basket"]
        return out

    bk = lambda vid: meta[vid]["bucket"]
    rp, rq = roll(pre, bk), roll(post, bk)
    order = ["raise", "shallow", "mid", "deep", "control"]

    print(f"{'bucket':9} {'units':>11} {'margin/unit':>16} {'ad/unit':>15} "
          f"{'NET/unit':>17} {'AOV':>15}")
    print(f"{'':9} {'pre  post':>11} {'pre    post':>16} {'pre   post':>15} "
          f"{'pre    post':>17} {'pre    post':>15}")
    totals = {}
    for k in order:
        p, q = rp.get(k), rq.get(k)
        if not p and not q:
            continue
        f = lambda x, fld: (x[fld] if x else 0)
        mu_p = f(p, "margin") / f(p, "units") if f(p, "units") else 0
        mu_q = f(q, "margin") / f(q, "units") if f(q, "units") else 0
        ad_p = f(p, "ad") / f(p, "units") if f(p, "units") else 0
        ad_q = f(q, "ad") / f(q, "units") if f(q, "units") else 0
        aov_p = f(p, "basket") / f(p, "orders") if f(p, "orders") else 0
        aov_q = f(q, "basket") / f(q, "orders") if f(q, "orders") else 0
        net_p, net_q = mu_p - ad_p, mu_q - ad_q
        totals[k] = dict(units_p=f(p, "units"), units_q=f(q, "units"),
                         net_p=net_p, net_q=net_q, ad_p=f(p, "ad"), ad_q=f(q, "ad"),
                         mgn_p=f(p, "margin"), mgn_q=f(q, "margin"))
        flag = "  <-- better" if net_q > net_p else "  <-- worse" if net_q < net_p else ""
        print(f"{k:9} {f(p,'units'):>5}{f(q,'units'):>6} "
              f"${mu_p:>6.2f}${mu_q:>8.2f} ${ad_p:>6.2f}${ad_q:>7.2f} "
              f"${net_p:>7.2f}${net_q:>8.2f} ${aov_p:>6.2f}${aov_q:>7.2f}{flag}")

    print()
    for k in ("raise", "shallow", "mid", "deep"):
        t = totals.get(k)
        if not t:
            continue
        tp = t["mgn_p"] - t["ad_p"]
        tq = t["mgn_q"] - t["ad_q"]
        print(f"  {k:8} total contribution (margin - ad spend): "
              f"${tp:>8.2f} -> ${tq:>8.2f}  ({tq-tp:+.2f})")

    out = {"generated": str(datetime.date.today()),
           "shopping_share": {"pre": sh_pre, "post": sh_post},
           "pre": [str(pre_start), str(pre_end)],
           "post": [str(post_start), str(post_end)],
           "buckets": {k: {"pre": rp.get(k), "post": rq.get(k)} for k in order},
           "products": [{
               "id": vid, **{kk: meta[vid][kk] for kk in
                             ("product", "arm", "bucket", "was", "now", "cogs")},
               "pre": pre.get(vid), "post": post.get(vid)}
               for vid in sorted(ids, key=lambda v: -(post.get(v, {}).get("rev", 0)))
               if pre.get(vid) or post.get(vid)]}
    (OUTPUTS_DIR / "unit_economics.json").write_text(json.dumps(out, indent=1, default=float))
    print(f"\n-> unit_economics.json")


if __name__ == "__main__":
    main()
