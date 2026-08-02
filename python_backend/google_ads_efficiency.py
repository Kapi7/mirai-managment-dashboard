#!/usr/bin/env python3
"""
Google Ads efficiency pull (REST, no client library needed).

Daily spend / clicks / conversions / conversion value for the Mirai account,
so the dashboard can show CPA and ROAS before vs after the price change.
The thesis: cheaper prices -> higher conversion rate -> Google CPA falls.

Writes outputs/ads_efficiency.json. Usage: python3 google_ads_efficiency.py [--days 45]
"""

import argparse
import datetime
import json
import re
import urllib.request
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
CUSTOMER_ID = "8138907450"          # Mirai Skin live account
API = "v21"


def creds() -> dict:
    y = (BASE_DIR / "google-ads.yaml").read_text()
    d = dict(re.findall(r"^(\w+):\s*(\S+)", y, re.M))
    return {k: v.strip("'\"") for k, v in d.items()}


def access_token(c: dict) -> str:
    data = urllib.parse.urlencode({
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": c["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data)))
    return r["access_token"]


def search(c: dict, token: str, query: str) -> list:
    req = urllib.request.Request(
        f"https://googleads.googleapis.com/{API}/customers/{CUSTOMER_ID}"
        f"/googleAds:searchStream",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "developer-token": c["developer_token"],
                 "login-customer-id": c["login_customer_id"].replace("-", ""),
                 "Content-Type": "application/json"})
    chunks = json.load(urllib.request.urlopen(req))
    rows = []
    for ch in chunks:
        rows.extend(ch.get("results", []))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    a = ap.parse_args()

    c = creds()
    token = access_token(c)
    today = datetime.date.today().isoformat()
    since = (datetime.date.today() - datetime.timedelta(days=a.days)).isoformat()

    daily = search(c, token, f"""
        SELECT segments.date, metrics.cost_micros, metrics.clicks,
               metrics.impressions, metrics.conversions,
               metrics.conversions_value
        FROM customer
        WHERE segments.date BETWEEN '{since}' AND '{today}'
        ORDER BY segments.date""")
    by_day = [{
        "date": r["segments"]["date"],
        "cost": round(int(r["metrics"].get("costMicros", 0)) / 1e6, 2),
        "clicks": int(r["metrics"].get("clicks", 0)),
        "impressions": int(r["metrics"].get("impressions", 0)),
        "conversions": round(float(r["metrics"].get("conversions", 0)), 2),
        "conv_value": round(float(r["metrics"].get("conversionsValue", 0)), 2),
    } for r in daily]

    by_campaign = search(c, token, f"""
        SELECT campaign.name, segments.date, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date BETWEEN '{since}' AND '{today}' AND metrics.cost_micros > 0
        ORDER BY segments.date""")
    camp = [{
        "date": r["segments"]["date"],
        "campaign": r["campaign"]["name"],
        "cost": round(int(r["metrics"].get("costMicros", 0)) / 1e6, 2),
        "conversions": round(float(r["metrics"].get("conversions", 0)), 2),
        "conv_value": round(float(r["metrics"].get("conversionsValue", 0)), 2),
    } for r in by_campaign]

    out = {"generated": str(datetime.date.today()),
           "customer_id": CUSTOMER_ID, "daily": by_day, "campaigns": camp}
    OUTPUTS_DIR.mkdir(exist_ok=True)
    (OUTPUTS_DIR / "ads_efficiency.json").write_text(json.dumps(out, indent=1))

    CHANGE = "2026-07-28"
    pre = [d for d in by_day if d["date"] < CHANGE]
    post = [d for d in by_day if d["date"] >= CHANGE]
    pre = pre[-len(post):] if post else []

    def block(rows, label):
        cost = sum(r["cost"] for r in rows)
        conv = sum(r["conversions"] for r in rows)
        val = sum(r["conv_value"] for r in rows)
        cpa = cost / conv if conv else 0
        roas = val / cost if cost else 0
        print(f"{label:18} spend ${cost:>8.2f}  conv {conv:>6.1f}  "
              f"CPA ${cpa:>6.2f}  ROAS {roas:>4.2f}")
        return cpa

    print(f"Google Ads {CUSTOMER_ID} — {len(by_day)} days\n")
    cpa_pre = block(pre, f"before ({len(pre)}d)")
    cpa_post = block(post, f"after  ({len(post)}d)")
    if cpa_pre and cpa_post:
        print(f"\nCPA change since the price cut: "
              f"{100 * (cpa_post / cpa_pre - 1):+.1f}%")
    print(f"\n-> ads_efficiency.json")


if __name__ == "__main__":
    main()
