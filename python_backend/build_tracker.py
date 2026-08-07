#!/usr/bin/env python3
"""
Build the interactive price-test tracker (self-contained HTML).

Assembles every product in the test — treated and control — with its price
history, margin, competitor benchmark, organic traffic and delivery exposure,
then writes a single searchable/sortable page. Re-run it any time to refresh:
it appends a new snapshot to the history block rather than overwriting it.

Usage: python3 build_tracker.py [--out ../../tracker.html]
"""

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
HISTORY = OUTPUTS_DIR / "tracker_history.json"


def latest_report() -> dict:
    reports = sorted(OUTPUTS_DIR.glob("geo_pricing_proposal_us_*.csv"))
    with open(reports[-1]) as f:
        return {r["variant_id"]: r for r in csv.DictReader(f)}


def read_cohort(name: str) -> list:
    path = OUTPUTS_DIR / f"organic_test_{name}.csv"
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def read_delivery() -> dict:
    path = OUTPUTS_DIR / "delivery_exposure.csv"
    if not path.exists():
        return {}
    with open(path) as f:
        return {r["variant_id"]: r for r in csv.DictReader(f)}


def fetch_live_prices(variant_ids: list) -> dict:
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from organic_test_push import gql
    Q = """query($ids:[ID!]!){ nodes(ids:$ids){ ... on ProductVariant {
      legacyResourceId price } } }"""
    out = {}
    for i in range(0, len(variant_ids), 100):
        ids = [f"gid://shopify/ProductVariant/{v}" for v in variant_ids[i:i + 100]]
        for n in gql(Q, {"ids": ids})["data"]["nodes"]:
            if n:
                out[str(n["legacyResourceId"])] = float(n["price"] or 0)
        time.sleep(0.25)
    return out


def build_rows() -> list:
    play = latest_report()
    delivery = read_delivery()
    rows, ids = [], []

    for cohort in ("treated", "control"):
        for r in read_cohort(cohort):
            for vid in (r.get("changed_variant_ids") or "").split(","):
                p = play.get(vid)
                if not p:
                    continue
                ids.append(vid)
                d = delivery.get(vid, {})
                rows.append({
                    "id": vid,
                    "product": r["title"],
                    "cohort": cohort,
                    "case": p["note"].replace("(proxy)", ""),
                    "was": round(float(p["current_USD"] or 0), 2),
                    "target": round(float(p["proposed_USD"] or 0), 2),
                    "comp": round(float(p["comp_avg_USD"] or 0), 2),
                    "cogs": round(float(p["cogs_usd"] or 0), 2),
                    "margin": round(float(p["margin_pct_at_proposed"] or 0), 1),
                    "units": int(p["units_2026"] or 0),
                    "revenue": round(float(p["revenue_2026_usd"] or 0), 2),
                    "imp": int(r.get("impressions_90d") or 0),
                    "clicks": int(r.get("clicks_90d") or 0),
                    "pos": float(r.get("avg_position") or 0),
                    "kg": float(d.get("unit_kg") or 0),
                    "ship_net": float(d["un_net"]) if d.get("un_net") else None,
                })

    live = fetch_live_prices(ids)
    for row in rows:
        row["live"] = round(live.get(row["id"], 0.0), 2)
        base = row["was"] or row["live"]
        row["delta"] = round((row["live"] - base) / base * 100, 1) if base else 0.0
        row["applied"] = (row["cohort"] == "treated"
                          and abs(row["live"] - row["target"]) < 0.01)
        # which of the three bets this product belongs to
        d = row["delta"]
        row["bucket"] = ("raise" if d > 2 else "shallow" if d > -15
                         else "mid" if d > -30 else "deep") \
            if row["cohort"] == "treated" else "control"
        # margin dollars at 2026 volume, before and after — the break-even math
        u = row["units"]
        row["m_old"] = round((row["was"] - row["cogs"]) * u, 2)
        row["m_new"] = round((row["live"] - row["cogs"]) * u, 2)
        if row["ship_net"] is not None and row["ship_net"] < 0:
            row["risk"] = "loss"
        elif row["ship_net"] is not None and row["ship_net"] < 10:
            row["risk"] = "thin"
        else:
            row["risk"] = "ok"
    return rows


CHANGE_DATE = "2026-07-28"


def daily_detail(rows: list, days_back: int = 45) -> tuple:
    """Per-day totals plus per-day/per-product lines, with an old-price
    counterfactual: what the same units would have earned at the pre-test
    price. Rebuilt from Shopify each run, so a missed run loses nothing."""
    import collections
    import datetime
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from organic_test_readout import fetch_orders

    meta = {r["id"]: r for r in rows}
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days_back)

    lines = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"units": 0, "revenue": 0.0}))
    for o in fetch_orders(start, end):
        if o.get("cancelled_at") or o.get("financial_status") in ("voided", "refunded"):
            continue
        day = o["created_at"][:10]
        for li in o.get("line_items") or []:
            vid = str(li.get("variant_id") or "")
            m = meta.get(vid)
            if not m:
                continue
            qty = li.get("quantity") or 0
            disc = sum(float(d.get("amount") or 0)
                       for d in li.get("discount_allocations") or [])
            cell = lines[day][vid]
            cell["units"] += qty
            cell["revenue"] += float(li.get("price") or 0) * qty - disc

    detail, daily = {}, []
    for day in sorted(lines):
        rows_out, tot = [], {
            "t_units": 0, "c_units": 0, "t_rev": 0.0, "c_rev": 0.0,
            "t_margin": 0.0, "c_margin": 0.0,
            "t_rev_old": 0.0, "t_margin_old": 0.0}
        for vid, cell in sorted(lines[day].items(),
                                key=lambda kv: -kv[1]["revenue"]):
            m = meta[vid]
            units, rev = cell["units"], round(cell["revenue"], 2)
            cogs_total = m["cogs"] * units
            margin = rev - cogs_total
            # Counterfactual: the same units at the pre-test price. Only
            # meaningful after the change — before it, any difference is just
            # discount codes, which the price test did not cause.
            if day >= CHANGE_DATE and m["cohort"] == "treated":
                rev_old = round(m["was"] * units, 2)
            else:
                rev_old = rev
            margin_old = rev_old - cogs_total
            rows_out.append({
                "id": vid, "product": m["product"], "cohort": m["cohort"],
                "case": m["case"], "units": units, "revenue": rev,
                "price": round(rev / units, 2) if units else 0,
                "old_price": m["was"], "new_price": m["live"],
                "revenue_old": rev_old,
                "margin": round(margin, 2), "margin_old": round(margin_old, 2),
            })
            if m["cohort"] == "treated":
                tot["t_units"] += units
                tot["t_rev"] += rev
                tot["t_margin"] += margin
                tot["t_rev_old"] += rev_old
                tot["t_margin_old"] += margin_old
            else:
                tot["c_units"] += units
                tot["c_rev"] += rev
                tot["c_margin"] += margin
        detail[day] = rows_out
        daily.append({"date": day, "after": day >= CHANGE_DATE,
                      **{k: round(v, 2) for k, v in tot.items()}})
    return daily, detail


def delivery_data() -> dict:
    """Live delivery zones + the per-country exposure scan, for the dashboard."""
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from organic_test_push import gql

    Q = """{ deliveryProfiles(first:10){ nodes{ name default
      profileItems(first:20){ edges{ node{ product{ title } } } }
      profileLocationGroups{ locationGroupZones(first:30){ nodes{
        zone{ name countries{ code{ countryCode } } }
        methodDefinitions(first:10){ nodes{ name active
          methodConditions{ field conditionCriteria{
            ... on MoneyV2{ amount currencyCode } ... on Weight{ value unit } } }
          rateProvider{ ... on DeliveryRateDefinition{
            price{ amount currencyCode } } } } } } } } } } }"""
    zones, excluded = [], []
    for prof in gql(Q)["data"]["deliveryProfiles"]["nodes"]:
        if not prof["default"]:
            excluded += [e["node"]["product"]["title"]
                         for e in prof["profileItems"]["edges"]
                         if e["node"].get("product")]
            continue
        for lg in prof["profileLocationGroups"]:
            for z in lg["locationGroupZones"]["nodes"]:
                flat, free = None, None
                for m in z["methodDefinitions"]["nodes"]:
                    if not m["active"]:
                        continue
                    pr = (m["rateProvider"] or {}).get("price")
                    if m["methodConditions"]:
                        c = m["methodConditions"][0]
                        crit = c["conditionCriteria"]
                        free = {"field": c["field"],
                                "value": crit.get("amount") or crit.get("value"),
                                "unit": crit.get("currencyCode") or crit.get("unit")}
                    elif pr:
                        flat = {"amount": float(pr["amount"]),
                                "currency": pr["currencyCode"]}
                zones.append({
                    "zone": z["zone"]["name"].strip(),
                    "countries": len([c for c in z["zone"]["countries"]
                                      if c.get("code")]),
                    "codes": [c["code"]["countryCode"]
                              for c in z["zone"]["countries"] if c.get("code")],
                    "flat": flat, "free": free})

    countries = []
    path = OUTPUTS_DIR / "delivery_exposure_by_country.csv"
    if path.exists():
        with open(path) as f:
            for r in csv.DictReader(f):
                countries.append({
                    "country": r["country"], "zone": r["zone"].strip(),
                    "code": r["code"],
                    "threshold": float(r["threshold_usd"]) if r.get("threshold_usd") else None,
                    "kg": float(r["typical_kg"]) if r.get("typical_kg") else None,
                    "ship": float(r["typical_ship"]) if r.get("typical_ship") else None,
                    "net": float(r["typical_net"]) if r.get("typical_net") else None,
                    "worst": float(r["worst_net"]) if r.get("worst_net") else None,
                    "worst_product": r.get("worst_product", ""),
                    "note": r.get("note", "")})
    countries.sort(key=lambda c: (c["net"] is None, c["net"] if c["net"] is not None else 0))
    return {"zones": zones, "countries": countries, "excluded": excluded}


def read_channel() -> dict:
    """Latest channel/profitability report (built by test_channel_report.py)."""
    path = OUTPUTS_DIR / "test_channel_report.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"generated": None, "lines": [], "orders": []}


def read_unit_econ() -> dict:
    path = OUTPUTS_DIR / "unit_economics.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def read_ads() -> dict:
    path = OUTPUTS_DIR / "ads_efficiency.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {"generated": None, "daily": [], "campaigns": []}


def load_history() -> list:
    if HISTORY.exists():
        try:
            return json.loads(HISTORY.read_text())
        except json.JSONDecodeError:
            pass
    return []


def append_snapshot(rows: list) -> list:
    hist = load_history()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    treated = [r for r in rows if r["cohort"] == "treated"]
    control = [r for r in rows if r["cohort"] == "control"]

    def agg(rs):
        return {
            "products": len(rs),
            "units_2026": sum(r["units"] for r in rs),
            "avg_margin": round(sum(r["margin"] for r in rs) / len(rs), 1) if rs else 0,
            "avg_price": round(sum(r["live"] for r in rs) / len(rs), 2) if rs else 0,
        }

    snap = {"date": stamp, "treated": agg(treated), "control": agg(control),
            "applied": sum(1 for r in treated if r["applied"])}
    hist = [h for h in hist if h["date"] != stamp] + [snap]
    hist.sort(key=lambda h: h["date"])
    HISTORY.write_text(json.dumps(hist, indent=1))
    return hist


PAGE = """<title>Mirai Skin — Price Test Dashboard</title>
<style>
:root{color-scheme:light;--ground:#F7F8F6;--card:#fff;--line:#E2E6E0;--ink:#20261F;
 --ink2:#5A6157;--ink3:#8A9186;--accent:#2F6B4F;--accent-soft:#E8F0EB;
 --a:#2a78d6;--a-soft:#E7EEF8;--b:#008300;--b-soft:#E7F1E7;
 --warn:#8A6100;--warn-soft:#F8EFD9;--bad:#B3261E;--bad-soft:#FBE9E7;--grid:#EDEFEA;}
@media(prefers-color-scheme:dark){:root:where(:not([data-theme=light])){color-scheme:dark;
 --ground:#171B19;--card:#1F2421;--line:#333A34;--ink:#ECEFEA;--ink2:#A6ADA3;--ink3:#767D73;
 --accent:#6FB58E;--accent-soft:#24312A;--a:#3987e5;--a-soft:#212B38;--b:#35A035;
 --b-soft:#223126;--warn:#D4A72C;--warn-soft:#332D1C;--bad:#F2B8B5;--bad-soft:#3A2422;
 --grid:#2A302C;}}
:root[data-theme=dark]{color-scheme:dark;--ground:#171B19;--card:#1F2421;--line:#333A34;
 --ink:#ECEFEA;--ink2:#A6ADA3;--ink3:#767D73;--accent:#6FB58E;--accent-soft:#24312A;
 --a:#3987e5;--a-soft:#212B38;--b:#35A035;--b-soft:#223126;--warn:#D4A72C;
 --warn-soft:#332D1C;--bad:#F2B8B5;--bad-soft:#3A2422;--grid:#2A302C;}
:root[data-theme=light]{color-scheme:light;--ground:#F7F8F6;--card:#fff;--line:#E2E6E0;
 --ink:#20261F;--ink2:#5A6157;--ink3:#8A9186;--accent:#2F6B4F;--accent-soft:#E8F0EB;
 --a:#2a78d6;--a-soft:#E7EEF8;--b:#008300;--b-soft:#E7F1E7;--warn:#8A6100;
 --warn-soft:#F8EFD9;--bad:#B3261E;--bad-soft:#FBE9E7;--grid:#EDEFEA;}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);margin:0;padding:28px 18px 70px;
 font-family:"Avenir Next",Seravek,system-ui,sans-serif;line-height:1.5;}
.wrap{max-width:1220px;margin:0 auto;display:flex;flex-direction:column;gap:20px;}
h1{font-family:Charter,Georgia,serif;font-size:1.65rem;margin:0;}
h2{font-family:Charter,Georgia,serif;font-size:1.1rem;margin:0;}
.sub{color:var(--ink2);font-size:.9rem;margin:0;}
.eyebrow{font-size:.68rem;letter-spacing:.13em;text-transform:uppercase;color:var(--accent);
 font-weight:600;margin:0;}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;}
.pad{padding:16px 18px;}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:10px;}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:13px 15px;}
.kpi .l{font-size:.66rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink3);
 font-weight:600;}
.kpi .v{font-family:Charter,Georgia,serif;font-size:1.5rem;font-weight:700;
 font-variant-numeric:tabular-nums;line-height:1.25;}
.kpi .n{font-size:.74rem;color:var(--ink2);}
.pos{color:var(--b)}.neg{color:var(--bad)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;
 padding:6px 13px;font-size:.79rem;font-weight:600;color:var(--ink2);cursor:pointer;
 font-family:inherit;}
.chip[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff;}
input[type=date],input[type=search]{background:var(--card);border:1px solid var(--line);
 border-radius:8px;padding:7px 11px;color:var(--ink);font-size:.85rem;font-family:inherit;}
input[type=search]{flex:1;min-width:200px}
input:focus{outline:2px solid var(--accent);outline-offset:1px;}
.spacer{margin-left:auto;font-size:.8rem;color:var(--ink3);font-variant-numeric:tabular-nums;}
.legend{display:flex;gap:16px;font-size:.78rem;color:var(--ink2);align-items:center;
 flex-wrap:wrap;}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:6px;}
.chartwrap{position:relative;}
svg{display:block;width:100%;height:auto;overflow:visible;}
.gridline{stroke:var(--grid);stroke-width:1;}
.axis{fill:var(--ink3);font-size:10px;font-family:inherit;}
@media(max-width:760px){.axis{font-size:13px}.changetxt{font-size:13px}}
.barA{fill:var(--a);}
.barB{fill:var(--b);}
.barSel{stroke:var(--ink);stroke-width:2;}
.hit{fill:transparent;cursor:pointer;}
.hit:hover~.hover,.hit:hover{outline:none}
.changeline{stroke:var(--accent);stroke-width:2;stroke-dasharray:4 3;}
.changetxt{fill:var(--accent);font-size:10px;font-weight:600;}
#tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line);
 border-radius:8px;padding:8px 11px;font-size:.78rem;box-shadow:0 4px 14px rgba(0,0,0,.12);
 opacity:0;transition:opacity .12s;white-space:nowrap;z-index:5;}
#tip b{font-variant-numeric:tabular-nums}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:11px;background:var(--card);}
table{border-collapse:collapse;width:100%;font-size:.84rem;}
th,td{padding:8px 11px;text-align:right;border-top:1px solid var(--line);white-space:nowrap;}
th{border-top:none;position:sticky;top:0;background:var(--card);cursor:pointer;
 font-size:.66rem;letter-spacing:.07em;text-transform:uppercase;color:var(--ink3);
 font-weight:600;user-select:none;z-index:2}
th:hover{color:var(--accent);}
th[aria-sort=ascending]::after{content:" ▲";font-size:.7em;}
th[aria-sort=descending]::after{content:" ▼";font-size:.7em;}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:215px;}
td{font-variant-numeric:tabular-nums;}
tbody tr:hover{background:var(--accent-soft);}
.tag{font-size:.66rem;font-weight:700;padding:2px 7px;border-radius:999px;display:inline-block;}
.t-cut{background:var(--a-soft);color:var(--a);}
.t-raise{background:var(--b-soft);color:var(--b);}
.t-floor{background:var(--warn-soft);color:var(--warn);}
.t-ctrl{background:var(--accent-soft);color:var(--ink2);}
.risk-loss{background:var(--bad-soft);color:var(--bad);font-weight:700;padding:2px 7px;
 border-radius:999px;font-size:.66rem;}
.risk-thin{background:var(--warn-soft);color:var(--warn);padding:2px 7px;border-radius:999px;
 font-size:.66rem;}

/* view panels + navigation */
.panel{display:none;flex-direction:column;gap:20px}
.panel.on{display:flex}
.vtabs{position:sticky;top:0;z-index:30;display:flex;gap:6px;flex-wrap:wrap;
 background:var(--ground);padding:6px 0 10px;border-bottom:1px solid var(--line)}
.vtab{background:var(--card);border:1px solid var(--line);border-radius:999px;
 padding:7px 15px;font-size:.83rem;font-weight:600;color:var(--ink2);cursor:pointer;
 font-family:inherit;display:flex;align-items:center;gap:7px}
.vtab .mi{font-size:15px;line-height:1}
.vtab.on{background:var(--accent);border-color:var(--accent);color:#fff}
@media(max-width:760px){
  body{padding:16px 8px 120px}
  .pad{padding:13px 11px}
  h1{font-size:1.3rem}
  .vtabs{position:fixed;bottom:calc(11px + env(safe-area-inset-bottom));left:50%;
   top:auto;transform:translateX(-50%);width:auto;z-index:996;gap:2px;
   background:var(--card);border:1px solid var(--line);border-bottom:1px solid var(--line);
   border-radius:999px;padding:5px 7px;box-shadow:0 10px 30px rgba(0,0,0,.22);
   flex-wrap:nowrap;transition:transform .25s ease,opacity .25s ease}
  .vtabs.shrunk{transform:translateX(-50%) scale(.84);opacity:.85}
  .vtab{padding:9px 14px;font-size:0;border:none;background:none;gap:0}
  .vtab .vl{display:none}
  .vtab .mi{font-size:21px}
  .vtab.on{background:var(--accent-soft);color:var(--accent)}
  .kpi .v{font-size:1.22rem}
  .cards{grid-template-columns:repeat(2,minmax(0,1fr))}
  th,td{padding:7px 7px;font-size:.78rem}
  th:first-child,td:first-child{min-width:150px}
  table.sub th:first-child,table.sub td:first-child{min-width:130px}
  .grid4{grid-template-columns:repeat(2,minmax(0,1fr))}
  .bar{gap:6px}
  .chip{padding:5px 11px;font-size:.75rem}
  input[type=date]{font-size:.78rem;padding:6px 8px}
  /* compact tables lose the least-important columns on a phone */
  #dailybody tr td:nth-child(5),#dailytbl th:nth-child(5),
  .panel#p-daily thead th:nth-child(5),.panel#p-daily tbody td:nth-child(5),
  .panel#p-daily thead th:nth-child(7),.panel#p-daily tbody td:nth-child(7){display:none}
  #p-products thead th:nth-child(3),#p-products tbody .prow td:nth-child(3){display:none}
  #ctrybody tr td:nth-child(4),#p-delivery thead th:nth-child(4){display:none}
}
.drow,.prow{cursor:pointer}
.caret{color:var(--ink3);font-size:.8em;display:inline-block;width:11px}
.openrow{background:var(--accent-soft)}
.openrow td{font-weight:600}
.openrow .caret{color:var(--accent)}
.detailrow td{padding:0;background:var(--ground);border-top:none}
.detailrow .inner{padding:13px 15px 16px}
table.sub{font-size:.79rem;background:var(--card);border:1px solid var(--line);
 border-radius:8px;overflow:hidden}
table.sub th{position:static;background:var(--card)}
table.sub th:first-child,table.sub td:first-child{min-width:190px}
table.sub tbody tr:hover{background:var(--accent-soft)}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(122px,1fr));gap:8px}
.grid4 .mini{background:var(--card);border:1px solid var(--line)}
.grid4 .mini .v{font-size:1rem}
.note{font-size:.78rem;color:var(--ink3);}
.empty{padding:24px;text-align:center;color:var(--ink3);}
.dayhead{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;}
.dayhead .close{margin-left:auto;cursor:pointer;font-size:.78rem;color:var(--accent);
 font-weight:600;background:none;border:none;font-family:inherit;}
.split2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.mini{background:var(--ground);border-radius:9px;padding:11px 13px;}
.mini .l{font-size:.66rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);
 font-weight:600}
.mini .v{font-family:Charter,Georgia,serif;font-size:1.25rem;font-weight:700;
 font-variant-numeric:tabular-nums}
footer{border-top:1px solid var(--line);padding-top:16px;}
@media(max-width:700px){.split2{grid-template-columns:1fr}body{padding:18px 10px 50px}
 th,td{padding:7px 8px}}
</style>
<div class="wrap">
<header>
  <p class="eyebrow">Live experiment · built __STAMP__</p>
  <h1>Price Test Dashboard</h1>
  <p class="sub"><b>Group A</b> — 101 products repriced on 28 Jul 2026.
  <b>Group B</b> — 100 matched products, prices frozen. Click any bar to open that day.</p>
</header>

<nav class="vtabs" id="vtabs">
  <button class="vtab on" data-v="overview"><span class="mi">📈</span><span class="vl">Overview</span></button>
  <button class="vtab" data-v="daily"><span class="mi">🗓</span><span class="vl">Daily</span></button>
  <button class="vtab" data-v="products"><span class="mi">🧴</span><span class="vl">Products</span></button>
  <button class="vtab" data-v="report"><span class="mi">📊</span><span class="vl">Report</span></button>
  <button class="vtab" data-v="delivery"><span class="mi">🚚</span><span class="vl">Delivery</span></button>
</nav>

<div class="panel on" id="p-overview">
<div class="bar">
  <button class="chip" data-range="7">7 days</button>
  <button class="chip" data-range="14">14 days</button>
  <button class="chip" data-range="30" aria-pressed="true">30 days</button>
  <button class="chip" data-range="all">All</button>
  <button class="chip" data-range="since">Since change</button>
  <input type="date" id="from"> <span class="note">to</span> <input type="date" id="to">
  <span class="spacer" id="rangelabel"></span>
</div>

<div class="cards" id="kpis"></div>

<div class="card pad">
  <div class="dayhead"><h2>The three bets</h2>
    <span class="note">since the change vs the same number of days before</span></div>
  <div class="tw" style="border:none;margin-top:9px"><table><thead><tr>
    <th style="cursor:default;min-width:118px">Bet</th>
    <th style="cursor:default">Items</th>
    <th style="cursor:default">Units before</th><th style="cursor:default">Units after</th>
    <th style="cursor:default">Change</th><th style="cursor:default">Needs</th>
    <th style="cursor:default">Verdict</th>
  </tr></thead><tbody id="betbody"></tbody></table></div>
  <p class="note" id="bethint"></p>
</div>

<div class="card pad">
  <div class="dayhead"><h2>Daily units</h2>
    <div class="legend" style="margin-left:auto">
      <span><span class="sw" style="background:var(--a)"></span>Group A (repriced)</span>
      <span><span class="sw" style="background:var(--b)"></span>Group B (control)</span>
    </div>
  </div>
  <div class="chartwrap"><div id="chart"></div><div id="tip"></div></div>
  <p class="note" id="charthint">Click a bar to see what sold that day and what it
  would have earned at the old prices.</p>
</div>

</div><!-- /overview -->

<div class="panel" id="p-daily">
<div class="card pad">
  <div class="dayhead"><h2>Daily sales</h2>
    <span class="note">Click a row to see the products sold that day</span>
    <span class="spacer" id="dailycount"></span></div>
  <div class="tw" style="border:none"><table>
    <thead><tr>
      <th style="cursor:default;min-width:120px">Date</th>
      <th style="cursor:default">A units</th><th style="cursor:default">B units</th>
      <th style="cursor:default">A revenue</th><th style="cursor:default">B revenue</th>
      <th style="cursor:default">vs old prices</th><th style="cursor:default">A margin</th>
    </tr></thead><tbody id="dailybody"></tbody></table></div>
</div>

<div class="card pad">
  <div class="dayhead"><h2>Revenue: actual vs old prices</h2>
    <div class="legend" style="margin-left:auto">
      <span><span class="sw" style="background:var(--a)"></span>At new prices</span>
      <span><span class="sw" style="background:var(--ink3)"></span>Same units at old prices</span>
    </div>
  </div>
  <div class="chartwrap"><div id="chart2"></div></div>
  <p class="note">Group A only. The gap is what the price change gave up (or gained)
  on the units that actually sold — it does not include any extra units the lower
  prices may have won.</p>
</div>

</div><!-- /daily -->

<div class="panel" id="p-products">
<div class="bar">
  <input id="q" type="search" placeholder="Search products — COSRX, sunscreen, snail…"
         autocomplete="off">
  <button class="chip" data-f="all" aria-pressed="true">All</button>
  <button class="chip" data-f="treated">Group A</button>
  <button class="chip" data-f="control">Group B</button>
  <button class="chip" data-f="raise">Raises</button>
  <button class="chip" data-f="shallow">Shallow</button>
  <button class="chip" data-f="mid">Mid cuts</button>
  <button class="chip" data-f="deep">Deep cuts</button>
  <button class="chip" data-f="sold">Sold in range</button>
  <button class="chip" data-f="risk">⚠ Delivery risk</button>
  <span class="spacer" id="count"></span>
</div>

<div class="tw"><table>
  <thead><tr>
    <th data-k="product">Product</th><th data-k="cohort">Grp</th><th data-k="case">Action</th>
    <th data-k="live">Price</th><th data-k="delta">Change</th>
    <th data-k="soldUnits">Units</th><th data-k="soldRev">Revenue</th>
  </tr></thead>
  <tbody id="body"></tbody>
</table></div>

</div><!-- /products -->

<div class="panel" id="p-report">
  <div class="card pad" id="flash"></div>
  <div class="card pad">
    <div class="dayhead"><h2>Google Ads efficiency</h2>
      <span class="note">the paid side of the bet: cheaper prices should convert better and pull CPA down</span></div>
    <div class="tw" style="border:none;margin-top:8px"><table><thead><tr>
      <th style="cursor:default;min-width:120px">Window</th><th style="cursor:default">Spend</th>
      <th style="cursor:default">Clicks</th><th style="cursor:default">Conversions</th>
      <th style="cursor:default">Conv. rate</th><th style="cursor:default">CPA</th>
      <th style="cursor:default">ROAS</th>
    </tr></thead><tbody id="adsbody"></tbody></table></div>
    <p class="note" id="adsnote"></p>
  </div>
  <div class="card pad">
    <div class="dayhead"><h2>Is the cut worth it? — unit economics</h2>
      <span class="note" id="uewin"></span></div>
    <p class="note" style="margin:6px 0 10px">Margin per unit fell by design. The cut
    only pays off if ad cost per unit fell by <b>more</b>. Ad cost is Google Shopping
    spend on each product, grossed up to full account spend.</p>
    <div class="tw" style="border:none"><table><thead><tr>
      <th style="cursor:default;min-width:105px">Bucket</th>
      <th style="cursor:default">Units</th>
      <th style="cursor:default">Margin/unit</th><th style="cursor:default">Δ margin</th>
      <th style="cursor:default">Ad/unit</th><th style="cursor:default">Δ ad</th>
      <th style="cursor:default">NET/unit</th><th style="cursor:default">Verdict</th>
    </tr></thead><tbody id="uebody"></tbody></table></div>
    <p class="note" id="uenote"></p>
  </div>
  <div class="card pad">
    <div class="dayhead"><h2>Sales by channel</h2>
      <span class="note">since the price change · organic = search engine referrer, no ad tags</span></div>
    <div class="tw" style="border:none"><table><thead><tr>
      <th style="cursor:default;min-width:110px">Channel</th>
      <th style="cursor:default">A units</th><th style="cursor:default">A revenue</th>
      <th style="cursor:default">A margin</th>
      <th style="cursor:default">B units</th><th style="cursor:default">B revenue</th>
    </tr></thead><tbody id="chanbody"></tbody></table></div>
  </div>
  <div class="cards" id="shipcards"></div>
  <div class="card pad">
    <div class="dayhead"><h2>Store orders by country</h2>
      <span class="note">every order since the change, test products or not — organic shows up here first</span></div>
    <div class="tw" style="border:none"><table><thead><tr>
      <th style="cursor:default;min-width:95px">Country</th><th style="cursor:default">Orders</th>
      <th style="cursor:default">Revenue</th><th style="cursor:default">Organic</th>
      <th style="cursor:default">Paid</th><th style="cursor:default">Other</th>
    </tr></thead><tbody id="ctrystore"></tbody></table></div>
  </div>
  <div class="card pad">
    <div class="dayhead"><h2>Items sold since the change</h2>
      <span class="note">Group A · product margin = revenue − cost of goods</span></div>
    <div class="tw" style="border:none"><table><thead><tr>
      <th style="cursor:default;min-width:210px">Product</th><th style="cursor:default">Action</th>
      <th style="cursor:default">Units</th><th style="cursor:default">Revenue</th>
      <th style="cursor:default">Margin</th><th style="cursor:default">Margin %</th>
    </tr></thead><tbody id="itembody"></tbody></table></div>
  </div>
</div><!-- /report -->

<div class="panel" id="p-delivery">
  <div class="cards" id="dkpis"></div>
  <div class="card pad">
    <div class="dayhead"><h2>Shipping zones</h2>
      <span class="note">live from Shopify · free-delivery threshold per zone</span></div>
    <div class="tw" style="border:none"><table><thead><tr>
      <th style="cursor:default;min-width:130px">Zone</th>
      <th style="cursor:default">Countries</th><th style="cursor:default">Paid rate</th>
      <th style="cursor:default">Free over</th>
    </tr></thead><tbody id="zonebody"></tbody></table></div>
  </div>
  <div class="card pad">
    <div class="dayhead"><h2>Country exposure</h2>
      <span class="note">Does a threshold-sized basket still cover its shipping?</span>
      <span class="spacer"><label class="note"><input type="checkbox" id="onlyrisk">
        only problems</label></span></div>
    <div class="tw" style="border:none"><table><thead><tr>
      <th style="cursor:default;min-width:135px">Country</th><th style="cursor:default">Zone</th>
      <th style="cursor:default">Free over</th><th style="cursor:default">Basket kg</th>
      <th style="cursor:default">Ship cost</th><th style="cursor:default">Net</th>
    </tr></thead><tbody id="ctrybody"></tbody></table></div>
  </div>
  <div class="card pad" id="excluded"></div>
</div><!-- /delivery -->

<footer><p class="note">Margin is after cost of goods, before payment fees.
“vs old prices” compares revenue on units actually sold against what those same units
would have earned at the pre-test price — counted only from 28 Jul onward, since any
earlier difference is discount codes rather than the test. Data rebuilt from Shopify on each run — nothing is
lost if a run is missed. Built __STAMP__.</p></footer>
</div>
<script>
const DATA=__DATA__, DAILY=__DAILY__, DETAIL=__DETAIL__, CHANGE='__CHANGE__';
const DELIV=__DELIV__;
const CHAN=__CHAN__;
const ADS=__ADS__;
const UE=__UE__;
const $=s=>document.querySelector(s);
const money=v=>(v<0?'-$':'$')+Math.abs(v).toFixed(2);
const money0=v=>(v<0?'-$':'$')+Math.round(Math.abs(v)).toLocaleString();
let filter='all', sortK='soldRev', sortDir=-1, selDay=null, selProd=null;
let from=null, to=null;

const dates=DAILY.map(d=>d.date);
const MIN=dates[0], MAX=dates[dates.length-1];

function setRange(kind){
  if(kind==='all'){from=MIN;to=MAX}
  else if(kind==='since'){from=CHANGE;to=MAX}
  else{const d=new Date(MAX);d.setDate(d.getDate()-(+kind-1));
       from=d.toISOString().slice(0,10);to=MAX}
  if(from<MIN)from=MIN;
  $('#from').value=from;$('#to').value=to;
  render();
}
function inRange(d){return d>=from&&d<=to}
function visibleDays(){return DAILY.filter(d=>inRange(d.date))}

function kpis(){
  const days=visibleDays();
  const s=days.reduce((a,d)=>({
    tu:a.tu+d.t_units, cu:a.cu+d.c_units, tr:a.tr+d.t_rev, cr:a.cr+d.c_rev,
    tm:a.tm+d.t_margin, tro:a.tro+d.t_rev_old, tmo:a.tmo+d.t_margin_old
  }),{tu:0,cu:0,tr:0,cr:0,tm:0,tro:0,tmo:0});
  const after=days.filter(d=>d.after).length;
  const revGap=s.tr-s.tro;
  const cls=v=>v>=0?'pos':'neg';
  const cards=[
    ['Group A units',s.tu,`${days.length} day${days.length===1?'':'s'} in view`],
    ['Group B units',s.cu,'control'],
    ['Group A revenue',money0(s.tr),`vs ${money0(s.tro)} at old prices`],
    ['Given up vs old prices',`<span class="${cls(revGap)}">${money0(revGap)}</span>`,
      after?'on units sold since the change':'no post-change days in view'],
    ['Group A margin',money0(s.tm),
      s.tr?`${(s.tm/s.tr*100).toFixed(0)}% of revenue`:'—'],
    ['Days since change',after,after?`from ${CHANGE}`:'not started in range'],
  ];
  $('#kpis').innerHTML=cards.map(([l,v,n])=>
    `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div>
     <div class="n">${n}</div></div>`).join('');
}

const isPhone=()=>window.innerWidth<=760;
function barChart(el,days,series,opts){
  // The SVG scales to the container width, so a wide viewBox on a 375px screen
  // collapses the height. Phones get a near-square viewBox instead.
  const W=isPhone()?440:1000;
  const H=isPhone()?(opts.hm||330):(opts.h||210);
  const P=isPhone()?{t:14,r:8,b:30,l:34}:{t:14,r:12,b:26,l:38};
  const iw=W-P.l-P.r, ih=H-P.t-P.b;
  const max=Math.max(1,...days.flatMap(d=>series.map(s=>s.get(d))));
  const step=iw/Math.max(days.length,1);
  const bw=Math.max(isPhone()?4:2,Math.min(isPhone()?26:20,step/series.length-2));
  const ticks=[0,.5,1].map(f=>Math.round(max*f));
  let s=`<svg viewBox="0 0 ${W} ${H}" role="img">`;
  ticks.forEach(t=>{const y=P.t+ih-(t/max)*ih;
    s+=`<line class="gridline" x1="${P.l}" y1="${y}" x2="${W-P.r}" y2="${y}"/>
        <text class="axis" x="${P.l-7}" y="${y+3}" text-anchor="end">${opts.fmt?opts.fmt(t):t}</text>`});
  days.forEach((d,i)=>{
    const x0=P.l+i*step;
    series.forEach((ser,j)=>{
      const v=ser.get(d), h=(v/max)*ih, x=x0+step/2-(series.length*bw)/2+j*bw;
      if(v>0) s+=`<rect class="${ser.cls}${selDay===d.date?' barSel':''}" x="${x}"
        y="${P.t+ih-h}" width="${bw}" height="${h}" rx="2"/>`;
    });
    if(d.date===CHANGE){
      s+=`<line class="changeline" x1="${x0}" y1="${P.t-4}" x2="${x0}" y2="${P.t+ih}"/>
          <text class="changetxt" x="${x0+4}" y="${P.t+4}">prices changed</text>`;
    }
    const every=isPhone()?Math.ceil(days.length/6):Math.ceil(days.length/16);
    if((isPhone()?days.length<=8:days.length<=32)||i%every===0)
      s+=`<text class="axis" x="${x0+step/2}" y="${H-8}" text-anchor="middle">${d.date.slice(5)}</text>`;
    s+=`<rect class="hit" data-d="${d.date}" x="${x0}" y="${P.t}" width="${step}" height="${ih}"/>`;
  });
  s+='</svg>';
  el.innerHTML=s;
}

function drawCharts(){
  const days=visibleDays();
  barChart($('#chart'),days,[
    {cls:'barA',get:d=>d.t_units},{cls:'barB',get:d=>d.c_units}],{h:210});
  barChart($('#chart2'),days,[
    {cls:'barA',get:d=>d.t_rev},
    {cls:'barB',get:d=>d.t_rev_old}],{h:170,hm:260,fmt:v=>'$'+v});
  // grey out the counterfactual series
  $('#chart2').querySelectorAll('.barB').forEach(r=>r.style.fill='var(--ink3)');
  document.querySelectorAll('.hit').forEach(h=>{
    h.onclick=()=>{selDay=(selDay===h.dataset.d)?null:h.dataset.d;render()};
    h.onmousemove=e=>showTip(e,h.dataset.d);
    h.onmouseleave=()=>{$('#tip').style.opacity=0};
  });
}

function showTip(e,date){
  const d=DAILY.find(x=>x.date===date); if(!d)return;
  const t=$('#tip'); const r=e.currentTarget.ownerSVGElement.getBoundingClientRect();
  t.innerHTML=`<b>${date}</b>${d.after?' · after change':' · before'}<br>
    A: <b>${d.t_units}</b> units · ${money(d.t_rev)}<br>
    B: <b>${d.c_units}</b> units · ${money(d.c_rev)}
    ${d.after?`<br>at old prices: <b>${money(d.t_rev_old)}</b>`:''}`;
  t.style.opacity=1;
  t.style.left=Math.min(e.clientX-r.left+12,r.width-190)+'px';
  t.style.top=(e.clientY-r.top-10)+'px';
}

function renderDaily(){
  const days=visibleDays().slice().reverse();
  $('#dailycount').textContent=`${days.length} day${days.length===1?'':'s'}`;
  $('#dailybody').innerHTML=days.length?days.map(d=>{
    const gap=d.t_rev-d.t_rev_old, open=selDay===d.date;
    const head=`<tr class="drow ${open?'openrow':''}" data-d="${d.date}">
      <td><span class="caret">${open?'▾':'▸'}</span> ${d.date}
        ${d.date===CHANGE?'<span class="tag t-raise">changed</span>':''}</td>
      <td>${d.t_units||'—'}</td><td>${d.c_units||'—'}</td>
      <td>${d.t_rev?money(d.t_rev):'—'}</td><td>${d.c_rev?money(d.c_rev):'—'}</td>
      <td class="${gap<0?'neg':gap>0?'pos':''}">${d.after&&d.t_units?money(gap):'—'}</td>
      <td>${d.t_margin?money(d.t_margin):'—'}</td></tr>`;
    if(!open) return head;
    const rows=DETAIL[d.date]||[];
    return head+`<tr class="detailrow"><td colspan="7">
      <div class="inner">
        <div class="note" style="margin-bottom:8px">${d.after
          ? `At the old prices these ${d.t_units} units would have brought
             ${money(d.t_rev_old)} instead of ${money(d.t_rev)}.`
          : 'This day is before the price change — prices were the old ones.'}</div>
        <table class="sub"><thead><tr>
          <th style="cursor:default">Product</th><th style="cursor:default">Grp</th>
          <th style="cursor:default">Units</th><th style="cursor:default">Sold at</th>
          <th style="cursor:default">Old price</th><th style="cursor:default">Revenue</th>
          <th style="cursor:default">At old price</th><th style="cursor:default">Diff</th>
        </tr></thead><tbody>${rows.map(r=>{
          const g=r.revenue-r.revenue_old;
          return `<tr><td>${r.product}</td><td>${r.cohort==='treated'?'A':'B'}</td>
            <td>${r.units}</td><td>${money(r.price)}</td><td>${money(r.old_price)}</td>
            <td>${money(r.revenue)}</td><td>${money(r.revenue_old)}</td>
            <td class="${g<0?'neg':g>0?'pos':''}">${
              r.cohort==='treated'&&d.after?money(g):'—'}</td></tr>`}).join('')}
        </tbody></table></div></td></tr>`;
  }).join(''):'<tr><td colspan="7" class="empty">No sales in this range.</td></tr>';
  document.querySelectorAll('.drow').forEach(tr=>tr.onclick=()=>{
    selDay=(selDay===tr.dataset.d)?null:tr.dataset.d; render()});
}

function soldInRange(){
  const agg={};
  DAILY.filter(d=>inRange(d.date)).forEach(d=>{
    (DETAIL[d.date]||[]).forEach(r=>{
      const a=agg[r.id]||(agg[r.id]={u:0,rev:0,old:0});
      a.u+=r.units;a.rev+=r.revenue;a.old+=r.revenue_old;
    });
  });
  return agg;
}

function tagFor(r){
  if(r.cohort==='control')return '<span class="tag t-ctrl">control</span>';
  const m={raise:'t-raise',cut:'t-cut','floor-near':'t-floor'}[r.case]||'t-ctrl';
  return `<span class="tag ${m}">${r.case==='floor-near'?'floor':r.case}</span>`;
}

function renderTable(){
  const q=$('#q').value.trim().toLowerCase(), sold=soldInRange();
  const rows=DATA.map(r=>{const s=sold[r.id]||{u:0,rev:0,old:0};
    return {...r,soldUnits:s.u,soldRev:+s.rev.toFixed(2),
            lostRev:+(s.rev-s.old).toFixed(2)}})
    .filter(r=>{
      if(filter==='treated'&&r.cohort!=='treated')return false;
      if(filter==='control'&&r.cohort!=='control')return false;
      if(['raise','shallow','mid','deep'].includes(filter)&&r.bucket!==filter)return false;
      if(filter==='sold'&&r.soldUnits===0)return false;
      if(filter==='risk'&&r.risk==='ok')return false;
      return !q||r.product.toLowerCase().includes(q);
    }).sort((a,b)=>{const x=a[sortK],y=b[sortK];
      return typeof x==='string'?sortDir*x.localeCompare(y):sortDir*((x??-1e9)-(y??-1e9))});
  $('#count').textContent=`${rows.length} of ${DATA.length} products`;
  $('#body').innerHTML=rows.length?rows.map(r=>{
    const open=selProd===r.id;
    const head=`<tr class="prow ${open?'openrow':''}" data-p="${r.id}">
      <td><span class="caret">${open?'▾':'▸'}</span> ${r.product}</td>
      <td>${r.cohort==='treated'?'A':'B'}</td><td>${tagFor(r)}</td>
      <td>${money(r.live)}</td>
      <td class="${r.delta<0?'neg':r.delta>0?'pos':''}">${
        r.delta?r.delta.toFixed(1)+'%':'—'}</td>
      <td>${r.soldUnits||'—'}</td><td>${r.soldRev?money(r.soldRev):'—'}</td></tr>`;
    if(!open) return head;
    const cell=(l,v)=>`<div class="mini"><div class="l">${l}</div><div class="v">${v}</div></div>`;
    const riskTxt=r.ship_net===null?'no weight data'
      : r.risk==='loss'?`<span class="risk-loss">${money(r.ship_net)}</span>`
      : r.risk==='thin'?`<span class="risk-thin">${money(r.ship_net)}</span>`
      : money(r.ship_net);
    return head+`<tr class="detailrow"><td colspan="7"><div class="inner">
      <div class="grid4">
        ${cell('Was',money(r.was))}
        ${cell('Now',money(r.live))}
        ${cell('Market avg',r.comp?money(r.comp):'—')}
        ${cell('Cost',money(r.cogs))}
        ${cell('Margin now',r.margin?r.margin.toFixed(0)+'%':'—')}
        ${cell('Weight',r.kg?r.kg.toFixed(2)+' kg':'—')}
        ${cell('Units 2026',r.units)}
        ${cell('Revenue 2026',money0(r.revenue))}
        ${cell('Organic 90d',`${r.imp} imp · ${r.clicks} clicks`)}
        ${cell('Avg position',r.pos?r.pos.toFixed(1):'—')}
        ${cell('Free-ship net',riskTxt)}
        ${cell('vs old prices',r.cohort==='treated'&&r.soldUnits
          ? `<span class="${r.lostRev<0?'neg':'pos'}">${money(r.lostRev)}</span>` : '—')}
      </div>
      <div class="note" style="margin-top:9px">${
        r.cohort==='control'
          ? 'Control product — price frozen for the duration of the test.'
          : `Priced at ${money(r.live)}, which is ${
              r.comp?(r.live<r.comp?`${((1-r.live/r.comp)*100).toFixed(0)}% under`
                     :`${((r.live/r.comp-1)*100).toFixed(0)}% over`):'—'} the market average.`}
      </div></div></td></tr>`;
  }).join('')
    :`<tr><td colspan="7" class="empty">Nothing matches \u201c${q}\u201d.</td></tr>`;
  document.querySelectorAll('.prow').forEach(tr=>tr.onclick=()=>{
    selProd=(selProd===tr.dataset.p)?null:tr.dataset.p; renderTable()});
}

function render(){
  $('#rangelabel').textContent=`${from} → ${to}`;
  kpis();renderBets();drawCharts();renderDaily();renderTable();
}

document.querySelectorAll('[data-range]').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('[data-range]').forEach(o=>o.setAttribute('aria-pressed',o===b));
  setRange(b.dataset.range)});
document.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{
  filter=b.dataset.f;
  document.querySelectorAll('[data-f]').forEach(o=>o.setAttribute('aria-pressed',o===b));
  renderTable()});
document.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{
  const k=th.dataset.k; sortDir=(sortK===k)?-sortDir:-1; sortK=k;
  document.querySelectorAll('th').forEach(o=>o.removeAttribute('aria-sort'));
  th.setAttribute('aria-sort',sortDir===1?'ascending':'descending');
  renderTable()});
$('#q').oninput=renderTable;
$('#from').onchange=e=>{from=e.target.value;render()};
$('#to').onchange=e=>{to=e.target.value;render()};
$('#from').min=MIN;$('#from').max=MAX;$('#to').min=MIN;$('#to').max=MAX;

// ---------- views ----------
function showView(v){
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('on',p.id==='p-'+v));
  document.querySelectorAll('.vtab').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  if(v==='delivery') renderDelivery();
  if(v==='report') renderReport();
  window.scrollTo({top:0,behavior:'instant'});
}
document.querySelectorAll('.vtab').forEach(b=>b.onclick=()=>showView(b.dataset.v));
// shrink the floating pill while scrolling (matches the president dashboard)
let stimer=null;
addEventListener('scroll',()=>{const n=$('#vtabs');n.classList.add('shrunk');
  clearTimeout(stimer);stimer=setTimeout(()=>n.classList.remove('shrunk'),650)},{passive:true});


// ---------- the three bets ----------
const BETS=[
  ['raise','Raises','#'],
  ['shallow','Shallow cuts (0-15%)','#'],
  ['mid','Mid cuts (15-30%)','#'],
  ['deep','Deep cuts (30%+)','#'],
];
function renderBets(){
  const post=DAILY.filter(d=>d.after);
  const pre=DAILY.filter(d=>!d.after).slice(-post.length);
  const bucketOf={}; DATA.forEach(r=>bucketOf[r.id]=r.bucket);
  const count=(days)=>{const o={};days.forEach(d=>(DETAIL[d.date]||[]).forEach(r=>{
    const b=bucketOf[r.id]; if(!b||b==='control')return; o[b]=(o[b]||0)+r.units}));return o};
  const A=count(post), B=count(pre);
  // break-even from margin dollars at 2026 volume
  const need={};
  DATA.filter(r=>r.cohort==='treated').forEach(r=>{
    const n=need[r.bucket]||(need[r.bucket]={o:0,n:0});
    n.o+=r.m_old; n.n+=r.m_new});
  $('#betbody').innerHTML=BETS.map(([k,label])=>{
    const items=DATA.filter(r=>r.bucket===k).length;
    const b=B[k]||0, a=A[k]||0;
    const chg=b?((a/b-1)*100):null;
    const nd=need[k], req=nd&&nd.n>0?(nd.o/nd.n-1)*100:0;
    const reqTxt=k==='raise'?'—':`+${req.toFixed(0)}%`;
    let verdict='<span class="note">too early</span>';
    if(k==='raise') verdict='<span class="pos">free margin</span>';
    else if(chg!==null&&post.length>=14)
      verdict=chg>=req?'<span class="pos">paying off</span>':'<span class="neg">behind</span>';
    return `<tr><td>${label}</td><td>${items}</td><td>${b}</td><td>${a}</td>
      <td class="${chg===null?'':chg<0?'neg':'pos'}">${chg===null?'—':chg.toFixed(0)+'%'}</td>
      <td>${reqTxt}</td><td>${verdict}</td></tr>`}).join('');
  $('#bethint').textContent = post.length<14
    ? `Only ${post.length} day${post.length===1?'':'s'} since the change — these numbers are `
      +`noise until about two weeks. "Needs" is the unit lift each group must reach just to `
      +`hold its old margin.`
    : `"Needs" is the unit lift required to hold the old margin. Groups behind that line after `
      +`4 weeks are candidates to pull back.`;
}


// ---------- report (channels + profitability + flash) ----------
const CHLABEL={organic:'Organic search',organic_likely:'Organic (likely)',subscription:'Subscription',paid:'Paid ads',direct:'Direct',
  referral:'Referral','other:3890849':'Shop app','other:subscription':'Subscription'};
function chName(c){return CHLABEL[c]||c.replace('other:','')}
function renderReport(){
  if(!CHAN.lines.length){
    $('#flash').innerHTML='<p class="note">No channel data yet — it refreshes with the daily job.</p>';
    return;
  }
  // channel table
  const agg={};
  CHAN.lines.forEach(r=>{
    const a=agg[r.channel]||(agg[r.channel]={au:0,ar:0,am:0,bu:0,br:0});
    if(r.arm==='treated'){a.au+=r.units;a.ar+=r.revenue;a.am+=r.product_margin}
    else{a.bu+=r.units;a.br+=r.revenue}});
  const rows=Object.entries(agg).sort((x,y)=>(y[1].ar+y[1].br)-(x[1].ar+x[1].br));
  $('#chanbody').innerHTML=rows.map(([c,a])=>`<tr>
    <td>${chName(c)}${c==='organic'?' 🌱':''}</td>
    <td>${a.au||'—'}</td><td>${a.ar?money(a.ar):'—'}</td><td>${a.am?money(a.am):'—'}</td>
    <td>${a.bu||'—'}</td><td>${a.br?money(a.br):'—'}</td></tr>`).join('');

  // shipping cards
  const ship=CHAN.orders.filter(o=>o.ship_net!==null);
  const charged=ship.reduce((s,o)=>s+o.charged,0), cost=ship.reduce((s,o)=>s+o.ship_cost,0);
  const freeN=ship.filter(o=>o.charged===0).length;
  const pmA=CHAN.lines.filter(r=>r.arm==='treated').reduce((s,r)=>s+r.product_margin,0);
  const pmB=CHAN.lines.filter(r=>r.arm==='control').reduce((s,r)=>s+r.product_margin,0);
  const shipNet=charged-cost;
  $('#shipcards').innerHTML=[
    ['Product margin A',money0(pmA),'revenue − cost of goods'],
    ['Product margin B',money0(pmB),'control'],
    ['Shipping charged',money0(charged),`across ${ship.length} test orders`],
    ['Real shipping cost',money0(cost),`${freeN} free-shipping orders`],
    ['Shipping net',`<span class="${shipNet<0?'neg':'pos'}">${money0(shipNet)}</span>`,'charged − real cost'],
    ['Net incl. shipping',`<span class="${pmA+pmB+shipNet<0?'neg':'pos'}">${money0(pmA+pmB+shipNet)}</span>`,'both groups'],
  ].map(([l,v,n])=>`<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div>
    <div class="n">${n}</div></div>`).join('');

  // item table (treated)
  const items={};
  CHAN.lines.filter(r=>r.arm==='treated').forEach(r=>{
    const k=r.product; const x=items[k]||(items[k]={case:r.case,u:0,rev:0,pm:0});
    x.u+=r.units;x.rev+=r.revenue;x.pm+=r.product_margin});
  $('#itembody').innerHTML=Object.entries(items).sort((a,b)=>b[1].rev-a[1].rev)
    .map(([prod,x])=>{
      const tag=x.case==='raise'?'t-raise':x.case==='cut'?'t-cut':'t-floor';
      return `<tr><td>${prod}</td>
        <td><span class="tag ${tag}">${x.case==='floor-near'?'floor':x.case||'—'}</span></td>
        <td>${x.u}</td><td>${money(x.rev)}</td><td>${money(x.pm)}</td>
        <td>${x.rev?Math.round(100*x.pm/x.rev)+'%':'—'}</td></tr>`}).join('');


  // ---- unit economics: did the CPA saving beat the margin loss?
  if(UE.buckets){
    const LBL={raise:'Raises',shallow:'Shallow cuts',mid:'Mid cuts',deep:'Deep cuts',control:'Control'};
    const per=(x,f)=>x&&x.units?x[f]/x.units:0;
    const rows=['raise','shallow','mid','deep','control'].map(k=>{
      const b=UE.buckets[k]||{}; const p=b.pre, q=b.post;
      if(!p&&!q) return '';
      const mp=per(p,'margin'), mq=per(q,'margin');
      const ap=per(p,'ad'),     aq=per(q,'ad');
      const np=mp-ap,           nq=mq-aq;
      const dm=mq-mp, da=aq-ap;
      // the cut pays off when the ad saving (-da) exceeds the margin loss (-dm)
      const win=nq>np;
      const verdict=k==='control'
        ? '<span class="note">baseline</span>'
        : win?'<span class="pos">pays off</span>':'<span class="neg">costs more</span>';
      return `<tr><td>${LBL[k]}</td>
        <td>${p?p.units:0}→${q?q.units:0}</td>
        <td>${money(mp)}→${money(mq)}</td>
        <td class="${dm>=0?'pos':'neg'}">${money(dm)}</td>
        <td>${money(ap)}→${money(aq)}</td>
        <td class="${da<=0?'pos':'neg'}">${money(da)}</td>
        <td class="${win?'pos':'neg'}"><b>${money(np)}→${money(nq)}</b></td>
        <td>${verdict}</td></tr>`}).join('');
    $('#uebody').innerHTML=rows;
    const sh=UE.shopping_share||{};
    $('#uewin').textContent=`${UE.pre?UE.pre.join(' → '):''}  vs  ${UE.post?UE.post.join(' → '):''}`;
    const ctl=UE.buckets.control||{};
    const cAdP=per(ctl.pre,'ad'), cAdQ=per(ctl.post,'ad');
    $('#uenote').innerHTML=`Shopping was ${Math.round((sh.pre||0)*100)}% of ad spend before and `
      +`${Math.round((sh.post||0)*100)}% after, so per-product costs are scaled to match. `
      +`<b>Read the control row first:</b> its ad cost/unit also fell (${money(cAdP)}→${money(cAdQ)}) `
      +`with no price change — so most of the ad-efficiency gain is the budget cut and campaign `
      +`mix, not the prices. Small samples: judge direction, not decimals.`;
  }

  // google ads efficiency
  if(ADS.daily.length){
    const post=ADS.daily.filter(d=>d.date>=CHANGE);
    const pre=ADS.daily.filter(d=>d.date<CHANGE).slice(-post.length);
    const row=(label,rows)=>{
      const cost=rows.reduce((s,r)=>s+r.cost,0), clk=rows.reduce((s,r)=>s+r.clicks,0);
      const conv=rows.reduce((s,r)=>s+r.conversions,0), val=rows.reduce((s,r)=>s+r.conv_value,0);
      return {label,cost,clk,conv,cr:clk?100*conv/clk:0,cpa:conv?cost/conv:0,roas:cost?val/cost:0}};
    const A=row(`Before (${pre.length}d)`,pre), B=row(`After (${post.length}d)`,post);
    $('#adsbody').innerHTML=[A,B].map(r=>`<tr><td>${r.label}</td>
      <td>${money0(r.cost)}</td><td>${r.clk}</td><td>${r.conv.toFixed(1)}</td>
      <td>${r.cr.toFixed(1)}%</td><td>${money(r.cpa)}</td><td>${r.roas.toFixed(2)}</td></tr>`).join('')
      +(()=>{const paidByDay={};(CHAN.store||[]).forEach(o=>{
          if(o.channel==='paid')paidByDay[o.date]=(paidByDay[o.date]||0)+1});
        const cnt=rows=>rows.reduce((s,r)=>s+(paidByDay[r.date]||0),0);
        const pa=cnt(pre), pb=cnt(post);
        const ta=pa?A.cost/pa:0, tb=pb?B.cost/pb:0;
        return `<tr><td><b>True CPA (Shopify)</b></td><td class="note" colspan="3">
          spend ÷ paid-attributed orders — no attribution lag</td>
          <td>${pa}→${pb} orders</td>
          <td class="${tb<ta?'pos':'neg'}"><b>${money(ta)}→${money(tb)}</b></td>
          <td class="${tb<ta?'pos':'neg'}">${ta?Math.round(100*(tb/ta-1)):0}%</td></tr>`})()
      +`<tr><td><b>Change</b></td><td class="${B.cost<A.cost?'neg':''}">${A.cost?Math.round(100*(B.cost/A.cost-1)):0}%</td>
        <td>${A.clk?Math.round(100*(B.clk/A.clk-1)):0}%</td>
        <td>${A.conv?Math.round(100*(B.conv/A.conv-1)):0}%</td>
        <td class="${B.cr>A.cr?'pos':'neg'}">${A.cr?(B.cr-A.cr).toFixed(1):0} pts</td>
        <td class="${B.cpa<A.cpa?'pos':'neg'}"><b>${A.cpa?Math.round(100*(B.cpa/A.cpa-1)):0}%</b></td>
        <td class="${B.roas>A.roas?'pos':'neg'}">${A.roas?Math.round(100*(B.roas/A.roas-1)):0}%</b></td></tr>`;
    const spendDrop=A.cost&&B.cost/A.cost<0.75;
    $('#adsnote').textContent=(spendDrop
      ? `⚠ Spend fell ${Math.round(100*(1-B.cost/A.cost))}% in the after-window — CPA moves partly reflect budget changes, not only the prices. `
      : '')+`CPA is the cleanest paid-efficiency signal: conversions per dollar with cheaper products in the cart.`;
  }

  // store orders by country
  const st=CHAN.store||[];
  const byC={};
  st.forEach(o=>{const x=byC[o.country]||(byC[o.country]={n:0,rev:0,org:0,paid:0,oth:0});
    x.n++;x.rev+=o.revenue;
    if(o.channel==='organic'||o.channel==='organic_likely')x.org++;
    else if(o.channel==='paid')x.paid++;else x.oth++});
  $('#ctrystore').innerHTML=Object.entries(byC).sort((a,b)=>b[1].rev-a[1].rev)
    .map(([c,x])=>`<tr><td>${c}</td><td>${x.n}</td><td>${money0(x.rev)}</td>
      <td class="${x.org?'pos':''}">${x.org||'—'}</td><td>${x.paid||'—'}</td>
      <td>${x.oth||'—'}</td></tr>`).join('');

  // flash summary — bizdev style, computed fresh from the data
  const post=DAILY.filter(d=>d.after), pre=DAILY.filter(d=>!d.after).slice(-post.length);
  const au=post.reduce((s,d)=>s+d.t_units,0), auPre=pre.reduce((s,d)=>s+d.t_units,0);
  const bu=post.reduce((s,d)=>s+d.c_units,0), buPre=pre.reduce((s,d)=>s+d.c_units,0);
  const gap=post.reduce((s,d)=>s+d.t_rev-d.t_rev_old,0);
  const orgU=(agg.organic?agg.organic.au+agg.organic.bu:0)
    +((agg.organic_likely&&agg.organic_likely.au+agg.organic_likely.bu)||0);
  const orgStore=(CHAN.store||[]).filter(o=>o.channel==='organic'||o.channel==='organic_likely');
  const paidShare=agg.paid&&au?Math.round(100*agg.paid.au/au):0;
  const early=post.length<14;
  const line=(e,t,b)=>`<div style="margin:7px 0"><b>${e} ${t}</b><br>
    <span style="font-size:.88rem;color:var(--ink2)">${b}</span></div>`;
  $('#flash').innerHTML=`<div class="dayhead"><h2>Flash summary</h2>
    <span class="note">auto-generated from the data below · day ${post.length} of 84</span></div>`
    +line(early?'🟡':'🔵','Overall',
      `Group A ${au}u vs ${auPre}u in the ${pre.length} days before (${auPre?Math.round(100*(au/auPre-1)):0}%). `
      +`Control ${bu}u vs ${buPre}u. Given up vs old prices: ${money(gap)}. `
      +(early?'Too few units for a verdict before day 14.':'Compare against each bet\u2019s break-even in Overview.'))
    +line(orgU>0?'🟢':orgStore.length?'🟡':'🔴','Organic',
      orgU>0?`${orgU} organic units on test products — the SEO channel is starting to move.`
      :orgStore.length?`No organic sales on TEST products yet, but ${orgStore.length} organic `
        +`order${orgStore.length===1?'':'s'} store-wide (${[...new Set(orgStore.map(o=>o.country))].join(', ')}) `
        +`— search traffic is buying, just not the test items so far.`
      :'Zero organic-search sales anywhere yet. Google takes weeks to recrawl prices; '
        +'watch GSC impressions, not orders.')
    +(()=>{ // budget confound: the arms differ in paid dependence
       if(!ADS.daily.length) return '';
       const po=ADS.daily.filter(d=>d.date>=CHANGE), pr=ADS.daily.filter(d=>d.date<CHANGE).slice(-po.length);
       const ca=pr.reduce((s,x)=>s+x.cost,0), cb=po.reduce((s,x)=>s+x.cost,0);
       if(!ca||cb/ca>0.8) return '';
       const aPaid=agg.paid?agg.paid.au:0, aTot=au||1, bPaid=agg.paid?agg.paid.bu:0, bTot=bu||1;
       return line('⚠️','Budget confound',
         `Ad spend fell ${Math.round(100*(1-cb/ca))}% in this window. Group A takes `
         +`${Math.round(100*aPaid/aTot)}% of its units from paid vs Group B's ${Math.round(100*bPaid/bTot)}% — `
         +`so the spend cut penalises A more than B. The A-vs-B unit gap is NOT a clean `
         +`price read until spend is stable.`)})()
    +line(paidShare>50?'🟡':'🔵','Channel mix',
      `${paidShare}% of Group A units came from paid ads — while that holds, the cuts are `
      +`mostly discounting traffic that was already converting.`)
    +(ADS.daily.length?(()=>{const post=ADS.daily.filter(d=>d.date>=CHANGE);
      const pre=ADS.daily.filter(d=>d.date<CHANGE).slice(-post.length);
      const cpa=r=>{const c=r.reduce((s,x)=>s+x.cost,0),v=r.reduce((s,x)=>s+x.conversions,0);
        return v?c/v:0};
      const a=cpa(pre),b=cpa(post),ch=a?100*(b/a-1):0;
      return line(Math.abs(ch)<5?'🔵':ch<0?'🟢':'🔴','Google CPA',
        `${money(a)} before → ${money(b)} after (${ch>0?'+':''}${ch.toFixed(1)}%). `
        +(Math.abs(ch)<5?'Flat so far — the conversion-rate gain from cheaper prices hasn\u2019t shown up yet.'
          :ch<0?'Falling — cheaper prices are converting paid clicks more efficiently.'
          :'Rising — watch it; may be budget shifts rather than price effect.'))})():'')
    +line(shipNet<0?'🔴':'🟢','Shipping',
      `Charged ${money(charged)} vs real cost ${money(cost)} on test orders → ${money(shipNet)}. `
      +(shipNet<0?'Mostly the old US/AU free-shipping thresholds, frozen during the test.':'Covered.'));
}

// ---------- delivery ----------
function renderDelivery(){
  const z=DELIV.zones, c=DELIV.countries;
  const scored=c.filter(x=>x.net!==null);
  const bad=scored.filter(x=>x.net<0), thin=scored.filter(x=>x.net>=0&&x.net<10);
  const noFree=c.filter(x=>x.net===null);
  $('#dkpis').innerHTML=[
    ['Shipping zones',z.length,'in the main profile'],
    ['Countries served',new Set(z.flatMap(x=>x.codes)).size,'with a rate'],
    ['Losing money',`<span class="${bad.length?'neg':'pos'}">${bad.length}</span>`,
      bad.length?'on a typical free basket':'none — all covered'],
    ['Thin margin',thin.length,'under $10 left after shipping'],
    ['No free shipping',noFree.length,'countries pay every time'],
  ].map(([l,v,n])=>`<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div>
    <div class="n">${n}</div></div>`).join('');

  $('#zonebody').innerHTML=z.map(x=>{
    const free=x.free
      ? (x.free.field==='TOTAL_PRICE'
          ? `${x.free.value} ${x.free.unit}`
          : `<span class="risk-loss">${x.free.value} ${x.free.unit} (weight!)</span>`)
      : '<span class="note">never free</span>';
    return `<tr><td>${x.zone}</td><td>${x.countries}</td>
      <td>${x.flat?x.flat.amount.toFixed(0)+' '+x.flat.currency:'—'}</td>
      <td>${free}</td></tr>`}).join('');

  const only=$('#onlyrisk').checked;
  const rows=c.filter(x=>!only||x.net===null||x.net<10);
  $('#ctrybody').innerHTML=rows.length?rows.map(x=>{
    const cls=x.net===null?'':x.net<0?'neg':x.net<10?'':'pos';
    return `<tr><td>${x.country}</td><td class="note">${x.zone}</td>
      <td>${x.threshold?money(x.threshold):'<span class="note">'+(x.note||'—')+'</span>'}</td>
      <td>${x.kg?x.kg.toFixed(2):'—'}</td><td>${x.ship?money(x.ship):'—'}</td>
      <td class="${cls}">${x.net===null?'—':money(x.net)}</td></tr>`}).join('')
    :'<tr><td colspan="6" class="empty">Nothing to flag.</td></tr>';

  $('#excluded').innerHTML=`<div class="dayhead"><h2>Excluded from free shipping</h2></div>
    <p class="note" style="margin-top:8px">These heavy products sit in their own delivery
    profile and always pay shipping, in every country — without that they lose money on a
    free basket.</p>
    <ul style="margin:9px 0 0;padding-left:19px;font-size:.86rem">
      ${DELIV.excluded.map(t=>`<li>${t}</li>`).join('')||'<li class="note">none</li>'}</ul>`;
}
$('#onlyrisk').onchange=renderDelivery;

(function(){
  const def=isPhone()?'14':'30';
  document.querySelectorAll('[data-range]').forEach(b=>
    b.setAttribute('aria-pressed', b.dataset.range===def));
  setRange(def);
})();
addEventListener('resize',()=>{clearTimeout(window.__rz);
  window.__rz=setTimeout(drawCharts,180)});
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASE_DIR.parent / "price_test_tracker.html"))
    a = ap.parse_args()

    rows = build_rows()
    hist = append_snapshot(rows)
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y")
    daily, detail = daily_detail(rows)
    html = (PAGE.replace("__DATA__", json.dumps(rows))
                .replace("__DAILY__", json.dumps(daily))
                .replace("__DETAIL__", json.dumps(detail))
                .replace("__CHANGE__", CHANGE_DATE)
                .replace("__DELIV__", json.dumps(delivery_data()))
                .replace("__CHAN__", json.dumps(read_channel()))
                .replace("__ADS__", json.dumps(read_ads()))
                .replace("__UE__", json.dumps(read_unit_econ(), default=float))
                .replace("__STAMP__", stamp))
    out = Path(a.out)
    out.write_text(html)
    treated = [r for r in rows if r["cohort"] == "treated"]
    print(f"✅ tracker: {len(rows)} products "
          f"({len(treated)} changed, {len(rows)-len(treated)} control), "
          f"{sum(1 for r in rows if r['risk']=='loss')} delivery leaks, "
          f"{len(hist)} snapshot(s)")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
