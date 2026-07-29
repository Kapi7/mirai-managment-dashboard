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

<div class="card pad" id="daypanel" style="display:none"></div>

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

<div class="bar">
  <input id="q" type="search" placeholder="Search products — COSRX, sunscreen, snail…"
         autocomplete="off">
  <button class="chip" data-f="all" aria-pressed="true">All</button>
  <button class="chip" data-f="treated">Group A</button>
  <button class="chip" data-f="control">Group B</button>
  <button class="chip" data-f="cut">Cuts</button>
  <button class="chip" data-f="raise">Raises</button>
  <button class="chip" data-f="sold">Sold in range</button>
  <button class="chip" data-f="risk">⚠ Delivery risk</button>
  <span class="spacer" id="count"></span>
</div>

<div class="tw"><table>
  <thead><tr>
    <th data-k="product">Product</th><th data-k="cohort">Grp</th><th data-k="case">Action</th>
    <th data-k="was">Was</th><th data-k="live">Now</th><th data-k="delta">Change</th>
    <th data-k="comp">Market</th><th data-k="margin">Margin</th>
    <th data-k="soldUnits">Units in range</th><th data-k="soldRev">Revenue in range</th>
    <th data-k="lostRev">vs old prices</th><th data-k="imp">Organic 90d</th>
  </tr></thead>
  <tbody id="body"></tbody>
</table></div>

<footer><p class="note">Margin is after cost of goods, before payment fees.
“vs old prices” compares revenue on units actually sold against what those same units
would have earned at the pre-test price — counted only from 28 Jul onward, since any
earlier difference is discount codes rather than the test. Data rebuilt from Shopify on each run — nothing is
lost if a run is missed. Built __STAMP__.</p></footer>
</div>
<script>
const DATA=__DATA__, DAILY=__DAILY__, DETAIL=__DETAIL__, CHANGE='__CHANGE__';
const $=s=>document.querySelector(s);
const money=v=>(v<0?'-$':'$')+Math.abs(v).toFixed(2);
const money0=v=>(v<0?'-$':'$')+Math.round(Math.abs(v)).toLocaleString();
let filter='all', sortK='soldRev', sortDir=-1, selDay=null;
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

function barChart(el,days,series,opts){
  const W=1000,H=opts.h||210,P={t:14,r:12,b:26,l:38};
  const iw=W-P.l-P.r, ih=H-P.t-P.b;
  const max=Math.max(1,...days.flatMap(d=>series.map(s=>s.get(d))));
  const step=iw/Math.max(days.length,1), bw=Math.max(2,Math.min(20,step/series.length-2));
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
    if(days.length<=32||i%Math.ceil(days.length/16)===0)
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
    {cls:'barB',get:d=>d.t_rev_old}],{h:170,fmt:v=>'$'+v});
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

function dayPanel(){
  const p=$('#daypanel');
  if(!selDay||!DETAIL[selDay]){p.style.display='none';return}
  const d=DAILY.find(x=>x.date===selDay), rows=DETAIL[selDay];
  const revGap=d.t_rev-d.t_rev_old;
  const cls=v=>v>=0?'pos':'neg';
  p.style.display='';
  p.innerHTML=`<div class="dayhead"><h2>${selDay}</h2>
      <span class="note">${d.after?'after the price change':'before the price change'}</span>
      <button class="close" id="closeday">clear selection ✕</button></div>
    <div class="split2" style="margin:12px 0">
      <div class="mini"><div class="l">Group A</div>
        <div class="v">${d.t_units} units · ${money(d.t_rev)}</div>
        <div class="note">${d.after?`at old prices the same units were ${money(d.t_rev_old)} →
          <span class="${cls(revGap)}">${money(revGap)}</span>.
          Margin kept: ${money(d.t_margin)}`:'prices unchanged this day'}</div></div>
      <div class="mini"><div class="l">Group B (control)</div>
        <div class="v">${d.c_units} units · ${money(d.c_rev)}</div>
        <div class="note">prices frozen all test</div></div>
    </div>
    <div class="tw"><table><thead><tr>
      <th style="cursor:default">Product</th><th style="cursor:default">Grp</th>
      <th style="cursor:default">Units</th><th style="cursor:default">Sold at</th>
      <th style="cursor:default">Old price</th><th style="cursor:default">Revenue</th>
      <th style="cursor:default">At old price</th><th style="cursor:default">Difference</th>
    </tr></thead><tbody>${rows.map(r=>{
      const g=r.revenue-r.revenue_old;
      return `<tr><td>${r.product}</td>
        <td>${r.cohort==='treated'?'A':'B'}</td><td>${r.units}</td>
        <td>${money(r.price)}</td><td>${money(r.old_price)}</td>
        <td>${money(r.revenue)}</td><td>${money(r.revenue_old)}</td>
        <td class="${g>=0?'pos':'neg'}">${r.cohort==='treated'&&d.after?money(g):'—'}</td></tr>`
    }).join('')}</tbody></table></div>`;
  $('#closeday').onclick=()=>{selDay=null;render()};
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
      if(filter==='cut'&&!(r.cohort==='treated'&&r.delta<-2))return false;
      if(filter==='raise'&&!(r.cohort==='treated'&&r.delta>2))return false;
      if(filter==='sold'&&r.soldUnits===0)return false;
      if(filter==='risk'&&r.risk==='ok')return false;
      return !q||r.product.toLowerCase().includes(q);
    }).sort((a,b)=>{const x=a[sortK],y=b[sortK];
      return typeof x==='string'?sortDir*x.localeCompare(y):sortDir*((x??-1e9)-(y??-1e9))});
  $('#count').textContent=`${rows.length} of ${DATA.length} products`;
  $('#body').innerHTML=rows.length?rows.map(r=>`<tr>
    <td>${r.product}</td><td>${r.cohort==='treated'?'A':'B'}</td><td>${tagFor(r)}</td>
    <td>${money(r.was)}</td><td>${money(r.live)}</td>
    <td class="${r.delta<0?'neg':r.delta>0?'pos':''}">${r.delta?r.delta.toFixed(1)+'%':'—'}</td>
    <td>${r.comp?money(r.comp):'—'}</td><td>${r.margin?r.margin.toFixed(0)+'%':'—'}</td>
    <td>${r.soldUnits||'—'}</td><td>${r.soldRev?money(r.soldRev):'—'}</td>
    <td class="${r.lostRev<0?'neg':r.lostRev>0?'pos':''}">${
      r.cohort==='treated'&&r.soldUnits?money(r.lostRev):'—'}</td>
    <td>${r.imp}</td></tr>`).join('')
    :`<tr><td colspan="12" class="empty">Nothing matches “${q}”.</td></tr>`;
}

function render(){
  $('#rangelabel').textContent=`${from} → ${to}`;
  kpis();drawCharts();dayPanel();renderTable();
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
setRange('30');
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
