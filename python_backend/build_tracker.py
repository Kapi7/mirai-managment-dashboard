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


def daily_units(rows: list, days_back: int = 30) -> list:
    """Units per day for each arm, from the price-change date minus days_back.
    Rebuilt from Shopify each run, so a missed run loses nothing."""
    import collections
    import datetime
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from organic_test_readout import fetch_orders

    treated = {r["id"] for r in rows if r["cohort"] == "treated"}
    control = {r["id"] for r in rows if r["cohort"] == "control"}
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days_back)
    counts = collections.defaultdict(lambda: {"t": 0, "c": 0})
    for o in fetch_orders(start, end):
        if o.get("cancelled_at") or o.get("financial_status") in ("voided", "refunded"):
            continue
        day = o["created_at"][:10]
        for li in o.get("line_items") or []:
            vid, qty = str(li.get("variant_id") or ""), li.get("quantity") or 0
            if vid in treated:
                counts[day]["t"] += qty
            elif vid in control:
                counts[day]["c"] += qty
    return [{"date": d, "treated": v["t"], "control": v["c"]}
            for d, v in sorted(counts.items())]


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


PAGE = """<title>Mirai Skin — Price Test Tracker</title>
<style>
:root{color-scheme:light;--ground:#F7F8F6;--card:#fff;--line:#E2E6E0;--ink:#20261F;
 --ink2:#5A6157;--ink3:#8A9186;--accent:#2F6B4F;--accent-soft:#E8F0EB;
 --up:#008300;--up-soft:#E7F1E7;--down:#2a78d6;--down-soft:#E7EEF8;
 --warn:#8A6100;--warn-soft:#F8EFD9;--bad:#B3261E;--bad-soft:#FBE9E7;}
@media(prefers-color-scheme:dark){:root:where(:not([data-theme=light])){color-scheme:dark;
 --ground:#171B19;--card:#1F2421;--line:#333A34;--ink:#ECEFEA;--ink2:#A6ADA3;--ink3:#767D73;
 --accent:#6FB58E;--accent-soft:#24312A;--up:#35A035;--up-soft:#223126;--down:#3987e5;
 --down-soft:#212B38;--warn:#D4A72C;--warn-soft:#332D1C;--bad:#F2B8B5;--bad-soft:#3A2422;}}
:root[data-theme=dark]{color-scheme:dark;--ground:#171B19;--card:#1F2421;--line:#333A34;
 --ink:#ECEFEA;--ink2:#A6ADA3;--ink3:#767D73;--accent:#6FB58E;--accent-soft:#24312A;
 --up:#35A035;--up-soft:#223126;--down:#3987e5;--down-soft:#212B38;--warn:#D4A72C;
 --warn-soft:#332D1C;--bad:#F2B8B5;--bad-soft:#3A2422;}
:root[data-theme=light]{color-scheme:light;--ground:#F7F8F6;--card:#fff;--line:#E2E6E0;
 --ink:#20261F;--ink2:#5A6157;--ink3:#8A9186;--accent:#2F6B4F;--accent-soft:#E8F0EB;
 --up:#008300;--up-soft:#E7F1E7;--down:#2a78d6;--down-soft:#E7EEF8;--warn:#8A6100;
 --warn-soft:#F8EFD9;--bad:#B3261E;--bad-soft:#FBE9E7;}
body{background:var(--ground);color:var(--ink);margin:0;padding:32px 18px 70px;
 font-family:"Avenir Next",Seravek,system-ui,sans-serif;line-height:1.5;}
.wrap{max-width:1180px;margin:0 auto;display:flex;flex-direction:column;gap:22px;}
h1{font-family:Charter,Georgia,serif;font-size:1.7rem;margin:0;}
.sub{color:var(--ink2);font-size:.92rem;margin:0;}
.eyebrow{font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);
 font-weight:600;margin:0;}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;}
.c{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 15px;}
.c .l{font-size:.68rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink3);
 font-weight:600;}
.c .v{font-family:Charter,Georgia,serif;font-size:1.45rem;font-weight:700;
 font-variant-numeric:tabular-nums;}
.c .n{font-size:.76rem;color:var(--ink2);}
.controls{display:flex;flex-wrap:wrap;gap:9px;align-items:center;}
#q{flex:1;min-width:210px;background:var(--card);border:1px solid var(--line);
 border-radius:8px;padding:9px 13px;color:var(--ink);font-size:.9rem;font-family:inherit;}
#q:focus{outline:2px solid var(--accent);outline-offset:1px;}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;
 padding:6px 14px;font-size:.8rem;font-weight:600;color:var(--ink2);cursor:pointer;
 font-family:inherit;}
.chip[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff;}
.count{font-size:.82rem;color:var(--ink3);margin-left:auto;font-variant-numeric:tabular-nums;}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:11px;background:var(--card);}
table{border-collapse:collapse;width:100%;font-size:.85rem;}
th,td{padding:9px 12px;text-align:right;border-top:1px solid var(--line);white-space:nowrap;}
th{border-top:none;position:sticky;top:0;background:var(--card);cursor:pointer;
 font-size:.68rem;letter-spacing:.07em;text-transform:uppercase;color:var(--ink3);
 font-weight:600;user-select:none;}
th:hover{color:var(--accent);}
th[aria-sort=ascending]::after{content:" ▲";font-size:.7em;}
th[aria-sort=descending]::after{content:" ▼";font-size:.7em;}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:230px;}
td{font-variant-numeric:tabular-nums;}
tbody tr:hover{background:var(--accent-soft);}
.tag{font-size:.68rem;font-weight:700;padding:2px 7px;border-radius:999px;
 display:inline-block;}
.t-cut{background:var(--down-soft);color:var(--down);}
.t-raise{background:var(--up-soft);color:var(--up);}
.t-floor{background:var(--warn-soft);color:var(--warn);}
.t-ctrl{background:var(--accent-soft);color:var(--ink2);}
.d-neg{color:var(--down);font-weight:600;}
.d-pos{color:var(--up);font-weight:600;}
.risk-loss{background:var(--bad-soft);color:var(--bad);font-weight:700;
 padding:2px 7px;border-radius:999px;font-size:.68rem;}
.risk-thin{background:var(--warn-soft);color:var(--warn);padding:2px 7px;
 border-radius:999px;font-size:.68rem;}
.live-ok{color:var(--up);}
.note{font-size:.78rem;color:var(--ink3);}
.empty{padding:26px;text-align:center;color:var(--ink3);}
footer{border-top:1px solid var(--line);padding-top:15px;}
@media(max-width:640px){body{padding:20px 10px 50px;}th,td{padding:7px 8px;}}
</style>
<div class="wrap">
<header>
  <p class="eyebrow">Live experiment · updated __STAMP__</p>
  <h1>Price Test Tracker</h1>
  <p class="sub">Every product in the experiment. Type to search, click any column to sort.
  <b>Group A</b> got new prices on 28 Jul 2026; <b>Group B</b> is the untouched control —
  leave those prices alone or the comparison breaks.</p>
</header>
<div class="cards" id="cards"></div>
<div class="tw" id="dailywrap"><table>
  <thead><tr><th style="min-width:110px">Date</th><th>Group A units</th>
  <th>Group B units</th><th>Note</th></tr></thead>
  <tbody id="daily"></tbody></table></div>
<div class="controls">
  <input id="q" type="search" placeholder="Search product, e.g. COSRX, sunscreen, snail…"
         autocomplete="off">
  <button class="chip" data-f="all" aria-pressed="true">All</button>
  <button class="chip" data-f="treated" aria-pressed="false">Group A · changed</button>
  <button class="chip" data-f="control" aria-pressed="false">Group B · control</button>
  <button class="chip" data-f="cut" aria-pressed="false">Cuts</button>
  <button class="chip" data-f="raise" aria-pressed="false">Raises</button>
  <button class="chip" data-f="risk" aria-pressed="false">⚠ Delivery risk</button>
  <span class="count" id="count"></span>
</div>
<div class="tw">
  <table>
    <thead><tr>
      <th data-k="product">Product</th>
      <th data-k="cohort">Group</th>
      <th data-k="case">Action</th>
      <th data-k="was">Was</th>
      <th data-k="live">Now</th>
      <th data-k="delta">Change</th>
      <th data-k="comp">Market avg</th>
      <th data-k="margin">Margin</th>
      <th data-k="units">Units 2026</th>
      <th data-k="imp">Organic 90d</th>
      <th data-k="kg">Weight</th>
      <th data-k="ship_net">Free-ship net</th>
    </tr></thead>
    <tbody id="body"></tbody>
  </table>
</div>
<p class="note" id="foot"></p>
<footer><p class="note">Margin is after 5% payment fees. “Free-ship net” is what a
basket of this product alone would earn after paying real US shipping once it crosses the
$80 free-delivery threshold — negative means that basket loses money.
Data: __STAMP__.</p></footer>
</div>
<script>
const DATA = __DATA__, HIST = __HIST__, DAILY = __DAILY__;
const $ = s => document.querySelector(s);
const money = v => v ? '$' + v.toFixed(2) : '—';
let filter = 'all', sortK = 'units', sortDir = -1;

function stats(){
  const t = DATA.filter(r => r.cohort === 'treated');
  const applied = t.filter(r => r.applied).length;
  const risk = DATA.filter(r => r.risk === 'loss').length;
  const avgD = t.reduce((a,r)=>a+r.delta,0) / (t.length||1);
  const avgM = t.reduce((a,r)=>a+r.margin,0) / (t.length||1);
  const cards = [
    ['Products changed', applied, `of ${t.length} in Group A`],
    ['Average change', avgD.toFixed(1)+'%', 'on repriced products'],
    ['Average margin', avgM.toFixed(0)+'%', 'after payment fees'],
    ['Delivery leaks', risk, risk ? 'free baskets that lose money' : 'none found'],
    ['Snapshots', HIST.length, 'refreshes recorded'],
  ];
  $('#cards').innerHTML = cards.map(([l,v,n]) =>
    `<div class="c"><div class="l">${l}</div><div class="v">${v}</div>
     <div class="n">${n}</div></div>`).join('');
}

function tagFor(r){
  if(r.cohort === 'control') return '<span class="tag t-ctrl">control</span>';
  const c = r.case;
  if(c === 'raise') return '<span class="tag t-raise">raise</span>';
  if(c === 'cut') return '<span class="tag t-cut">cut</span>';
  if(c === 'floor-near') return '<span class="tag t-floor">floor</span>';
  return `<span class="tag t-ctrl">${c}</span>`;
}

function matches(r, q){
  if(filter === 'treated' && r.cohort !== 'treated') return false;
  if(filter === 'control' && r.cohort !== 'control') return false;
  if(filter === 'cut' && !(r.cohort==='treated' && r.delta < -2)) return false;
  if(filter === 'raise' && !(r.cohort==='treated' && r.delta > 2)) return false;
  if(filter === 'risk' && r.risk === 'ok') return false;
  return !q || r.product.toLowerCase().includes(q);
}

function render(){
  const q = $('#q').value.trim().toLowerCase();
  const rows = DATA.filter(r => matches(r,q)).sort((a,b) => {
    const x = a[sortK], y = b[sortK];
    if(typeof x === 'string') return sortDir * x.localeCompare(y);
    return sortDir * ((x ?? -1e9) - (y ?? -1e9));
  });
  $('#count').textContent = `${rows.length} of ${DATA.length} products`;
  $('#body').innerHTML = rows.length ? rows.map(r => `<tr>
    <td>${r.product}</td>
    <td>${r.cohort === 'treated' ? 'A' : 'B'}</td>
    <td>${tagFor(r)}</td>
    <td>${money(r.was)}</td>
    <td class="${r.applied?'live-ok':''}">${money(r.live)}</td>
    <td class="${r.delta<0?'d-neg':r.delta>0?'d-pos':''}">${r.delta?r.delta.toFixed(1)+'%':'—'}</td>
    <td>${money(r.comp)}</td>
    <td>${r.margin?r.margin.toFixed(0)+'%':'—'}</td>
    <td>${r.units}</td>
    <td>${r.imp}</td>
    <td>${r.kg?r.kg.toFixed(2)+'kg':'—'}</td>
    <td>${r.ship_net===null?'—':r.risk==='loss'
        ? `<span class="risk-loss">${money(r.ship_net)}</span>`
        : r.risk==='thin' ? `<span class="risk-thin">${money(r.ship_net)}</span>`
        : money(r.ship_net)}</td></tr>`).join('')
    : `<tr><td colspan="12" class="empty">No products match “${q}”.</td></tr>`;
}

document.querySelectorAll('.chip').forEach(b => b.onclick = () => {
  filter = b.dataset.f;
  document.querySelectorAll('.chip').forEach(o =>
    o.setAttribute('aria-pressed', o === b));
  render();
});
document.querySelectorAll('th').forEach(th => th.onclick = () => {
  const k = th.dataset.k;
  sortDir = (sortK === k) ? -sortDir : -1;
  sortK = k;
  document.querySelectorAll('th').forEach(o => o.removeAttribute('aria-sort'));
  th.setAttribute('aria-sort', sortDir === 1 ? 'ascending' : 'descending');
  render();
});
$('#q').oninput = render;
$('#foot').textContent = HIST.length > 1
  ? `History: ${HIST.map(h=>h.date).join(' → ')}`
  : 'First snapshot recorded — re-run the builder to add more.';

const CHANGE_DATE = '2026-07-28';
document.querySelector('#daily').innerHTML = DAILY.length
  ? DAILY.slice(-21).reverse().map(d => `<tr>
      <td>${d.date}${d.date===CHANGE_DATE?' <span class="tag t-raise">prices changed</span>':''}</td>
      <td>${d.treated}</td><td>${d.control}</td>
      <td class="note">${d.date < CHANGE_DATE ? 'before' : 'after'}</td></tr>`).join('')
  : '<tr><td colspan="4" class="empty">No daily data yet.</td></tr>';
stats(); render();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASE_DIR.parent / "price_test_tracker.html"))
    a = ap.parse_args()

    rows = build_rows()
    hist = append_snapshot(rows)
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y")
    daily = daily_units(rows)
    html = (PAGE.replace("__DATA__", json.dumps(rows))
                .replace("__HIST__", json.dumps(hist))
                .replace("__DAILY__", json.dumps(daily))
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
