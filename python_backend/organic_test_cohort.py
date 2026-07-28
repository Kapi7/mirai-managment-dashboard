#!/usr/bin/env python3
"""
Organic pricing test cohort builder (Phase 1 — analysis only, no writes).

Joins Google Search Console organic impressions per product page with the
per-variant pricing playbook, and emits:
  outputs/organic_test_treated.csv  — the products whose prices the test changes
  outputs/organic_test_control.csv  — matched holdout, prices frozen

Usage: python3 organic_test_cohort.py [--size 100] [--geo us]
"""

import argparse
import collections
import csv
import datetime
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
GSC_TOKEN = Path.home() / ".config" / "gsc-token.json"
GSC_SITE = "sc-domain:mirai-skin.com"
STORE = "9dkd2w-g3.myshopify.com"
CHANGE_CASES = ("raise", "cut", "floor-near")


def _shopify_token() -> str:
    env = (BASE_DIR / ".env").read_text()
    return re.search(r"SHOPIFY_ACCESS_TOKEN=([^\s]+)", env).group(1)


def fetch_gsc_pages(days: int = 90, end: datetime.date = None) -> dict:
    """{product handle: {impressions, clicks, ctr, position}} over the window."""
    t = json.loads(GSC_TOKEN.read_text())
    data = urllib.parse.urlencode({
        "client_id": t["client_id"], "client_secret": t["client_secret"],
        "refresh_token": t["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    access = json.load(urllib.request.urlopen(
        urllib.request.Request(t["token_uri"], data=data)))["access_token"]

    end = end or datetime.date.today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=days)
    site = urllib.parse.quote(GSC_SITE, safe="")
    body = json.dumps({"startDate": str(start), "endDate": str(end),
                       "dimensions": ["page"], "rowLimit": 25000}).encode()
    req = urllib.request.Request(
        f"https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query",
        data=body, headers={"Authorization": f"Bearer {access}",
                            "Content-Type": "application/json"})
    rows = json.load(urllib.request.urlopen(req)).get("rows", [])

    pages = {}
    for r in rows:
        url = r["keys"][0]
        if "/products/" not in url:
            continue
        handle = url.split("/products/")[-1].split("?")[0].strip("/")
        prev = pages.get(handle)
        if prev and prev["impressions"] >= r["impressions"]:
            continue
        pages[handle] = {
            "impressions": r["impressions"], "clicks": r["clicks"],
            "ctr": round(r["ctr"] * 100, 2), "position": round(r["position"], 1),
        }
    return pages


def fetch_active_products() -> list:
    token = _shopify_token()
    products, url = [], (
        f"https://{STORE}/admin/api/2024-10/products.json?limit=250"
        f"&fields=id,handle,title,status,variants")
    while url:
        resp = urllib.request.urlopen(urllib.request.Request(
            url, headers={"X-Shopify-Access-Token": token}))
        products.extend(json.load(resp).get("products", []))
        url = None
        for part in resp.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
        time.sleep(0.25)
    return [p for p in products if p.get("status") == "active"]


def load_playbook(geo: str, date_tag: str = None) -> dict:
    """Newest proposal report for the geo (or the given date tag)."""
    if date_tag:
        path = OUTPUTS_DIR / f"geo_pricing_proposal_{geo}_{date_tag}.csv"
    else:
        matches = sorted(OUTPUTS_DIR.glob(f"geo_pricing_proposal_{geo}_*.csv"))
        if not matches:
            raise FileNotFoundError(
                f"No proposal report for {geo} in {OUTPUTS_DIR} — "
                f"run: python3 run_geo_pricing.py report --geos {geo}")
        path = matches[-1]
    print(f"ℹ️ playbook: {path.name}")
    with open(path) as f:
        return {r["variant_id"]: r for r in csv.DictReader(f)}


def build(size: int = 100, geo: str = "us", date_tag: str = None,
          min_impressions: int = 25, min_units: int = 3) -> dict:
    cur = {"us": "USD", "au": "AUD", "gb": "GBP", "ca": "CAD"}[geo]
    gsc = fetch_gsc_pages()
    products = fetch_active_products()
    play = load_playbook(geo, date_tag)

    ranked = []
    for p in products:
        g = gsc.get(p["handle"])
        if not g:
            continue
        cases = collections.Counter()
        changed, deltas, price_rows = [], [], []
        for v in p.get("variants", []):
            r = play.get(str(v["id"]))
            if not r:
                continue
            case = r["note"].replace("(proxy)", "")
            cases[case] += 1
            price_rows.append(r)
            if case in CHANGE_CASES:
                changed.append(str(v["id"]))
                deltas.append(float(r["delta_pct"]))
        if not price_rows:
            continue
        lead = max(price_rows, key=lambda r: float(r["revenue_2026_usd"] or 0))
        units = sum(int(play[v]["units_2026"] or 0) for v in changed if v in play)
        revenue = sum(float(play[v]["revenue_2026_usd"] or 0)
                      for v in changed if v in play)
        ranked.append({
            "units_2026": units,
            "revenue_2026_usd": round(revenue, 2),
            "handle": p["handle"],
            "title": p["title"][:70],
            "impressions_90d": int(g["impressions"]),
            "clicks_90d": int(g["clicks"]),
            "ctr_pct": g["ctr"],
            "avg_position": g["position"],
            "variants_changed": len(changed),
            "avg_delta_pct": round(sum(deltas) / len(deltas), 1) if deltas else 0.0,
            f"lead_current_{cur}": lead[f"current_{cur}"],
            f"lead_proposed_{cur}": lead[f"proposed_{cur}"],
            f"lead_comp_avg_{cur}": lead[f"comp_avg_{cur}"],
            "margin_now_pct": lead["margin_pct_current"],
            "margin_new_pct": lead["margin_pct_at_proposed"],
            "case": lead["note"].replace("(proxy)", ""),
            "cases_all": json.dumps(dict(cases)),
            "changed_variant_ids": ",".join(changed),
        })

    # Selection: the product must have real organic presence (that is the
    # thesis under test) AND enough sales volume that a 4-week readout can
    # actually detect a change. Organic clicks alone are far too sparse to
    # measure conversion on: the whole eligible pool draws ~1.3 clicks/day.
    eligible = [r for r in ranked
                if r["variants_changed"] > 0
                and r["impressions_90d"] >= min_impressions
                and r["units_2026"] >= min_units]

    # Match on units sold — the metric the readout uses. Matching on
    # impressions instead leaves the arms 30% apart on units, which would
    # swamp the effect we are trying to see.
    eligible.sort(key=lambda r: -r["units_2026"])

    # Outliers would swamp a split this size, on either axis: a product
    # holding more than a fifth of the pool's units OR of its impressions is
    # pulled out and reported on its own. (The scalp serum is 60%+ of all
    # organic impressions — leaving it in either arm would wreck the balance.)
    pool = eligible[:size * 2]
    pool_units = sum(r["units_2026"] for r in pool) or 1
    pool_impr = sum(r["impressions_90d"] for r in pool) or 1
    flagship = [r for r in eligible
                if r["units_2026"] > 0.20 * pool_units
                or r["impressions_90d"] > 0.20 * pool_impr]
    rest = [r for r in eligible if r not in flagship]

    # Pair-matched assignment: walk the sorted list two at a time and split
    # each pair, alternating which side gets the bigger seller.
    treated, control = [], []
    for i in range(0, min(len(rest), size * 2), 2):
        pair = rest[i:i + 2]
        if len(pair) < 2:
            break
        hi, lo = pair
        if (i // 2) % 2 == 0:
            treated.append(hi); control.append(lo)
        else:
            treated.append(lo); control.append(hi)
    treated, control = treated[:size], control[:size]

    for r in flagship:
        r["cohort_note"] = "FLAGSHIP — measured separately, excluded from A/B"
    if flagship:
        path = OUTPUTS_DIR / "organic_test_flagship.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(flagship[0].keys()))
            w.writeheader(); w.writerows(flagship)
        print(f"⭐ flagship (own case study): "
              f"{', '.join(r['handle'] for r in flagship)} "
              f"({sum(r['impressions_90d'] for r in flagship):,} imp/90d) "
              f"-> {path.name}")

    OUTPUTS_DIR.mkdir(exist_ok=True)
    for name, rows in (("treated", treated), ("control", control)):
        path = OUTPUTS_DIR / f"organic_test_{name}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"✅ {name}: {len(rows)} products, "
              f"{sum(r['units_2026'] for r in rows):,} units/2026 "
              f"({sum(r['units_2026'] for r in rows)/210*28:.0f} per 4wk), "
              f"{sum(r['impressions_90d'] for r in rows):,} imp/90d, "
              f"{sum(r['variants_changed'] for r in rows)} changes -> {path.name}")
    return {"treated": treated, "control": control}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--geo", default="us")
    ap.add_argument("--date-tag", default=None)
    ap.add_argument("--min-impressions", type=int, default=25,
                    help="organic presence floor (GSC impressions / 90d)")
    ap.add_argument("--min-units", type=int, default=3,
                    help="sales-volume floor so the readout can detect change")
    a = ap.parse_args()
    build(a.size, a.geo, a.date_tag, a.min_impressions, a.min_units)
