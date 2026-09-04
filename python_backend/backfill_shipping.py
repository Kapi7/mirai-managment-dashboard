#!/usr/bin/env python3
"""
Backfill orders.shipping_cost from the shipping matrix (live Korealy sheet).

Rules match sync_orders.py exactly:
  - weight fallback: items x DEFAULT_ITEM_WEIGHT_KG when total_weight_g is 0
  - GEO-miss fallback: 80% of shipping_charged (never $0 "free shipping")

Safe workflow (also exposed as POST /admin/backfill-shipping-costs):
  plan    -> per-order old/new for a date window, nothing written (dry run)
  apply   -> writes only the changed rows in ONE transaction; the plan you
             applied doubles as the rollback snapshot (old values inside)
  restore -> puts saved values back (POST /admin/restore-shipping-costs)

CLI (needs DATABASE_URL):
  python3 backfill_shipping.py --since 2026-08-01                 # dry run
  python3 backfill_shipping.py --since 2026-08-01 --apply --snapshot aug_sep.json
  python3 backfill_shipping.py --restore 3          # roll back stored run 3 (or a snapshot file)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
from sqlalchemy import and_, func, select, update

from database.connection import get_db, init_db
from database.models import Order, OrderLineItem, ShippingBackfillRun

DEFAULT_ITEM_WEIGHT_KG = float(os.getenv("DEFAULT_ITEM_WEIGHT_KG", "0.25") or 0.25)
SHOP_TZ = os.getenv("SHOP_TZ", "Asia/Nicosia")


def _tz():
    return pytz.timezone(SHOP_TZ)


def _utc_bounds(since: Optional[date], until: Optional[date]):
    """Local calendar window (until inclusive) -> naive UTC datetimes, same as get_daily_kpis."""
    tz = _tz()
    start_utc = end_utc = None
    if since:
        start_utc = tz.localize(datetime.combine(since, datetime.min.time())).astimezone(pytz.UTC).replace(tzinfo=None)
    if until:
        end_utc = tz.localize(datetime.combine(until + timedelta(days=1), datetime.min.time())).astimezone(pytz.UTC).replace(tzinfo=None)
    return start_utc, end_utc


def _local_date(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(_tz()).date().isoformat()


def _parse_date(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


def _matrix_stamp() -> Optional[dict]:
    try:
        from shipping_matrix_source import read_stamp
        from master_report_mirai import _MATRIX_PATH
        return read_stamp(_MATRIX_PATH)
    except Exception:
        return None


def _cost_for(geo: str, weight_kg: float, charged: float, lookup) -> tuple[float, str]:
    cost = round(lookup(geo, weight_kg), 2)
    if cost <= 0 and charged > 0:
        return round(charged * 0.8, 2), "geo_miss_80pct"
    return cost, "matrix"


async def plan_backfill(db, since: Optional[date] = None, until: Optional[date] = None,
                        refresh_matrix: bool = True) -> Dict[str, Any]:
    """Compute old/new shipping_cost for every order in the window. Writes nothing."""
    from master_report_mirai import _canonical_geo, _lookup_matrix_shipping_usd, reload_shipping_matrix

    # make sure we price with the sheet as of right now, not a cached copy
    await asyncio.to_thread(reload_shipping_matrix, refresh_matrix)

    start_utc, end_utc = _utc_bounds(since, until)
    conds = []
    if start_utc:
        conds.append(Order.created_at >= start_utc)
    if end_utc:
        conds.append(Order.created_at < end_utc)
    where = and_(*conds) if conds else True

    qty_rows = await db.execute(
        select(OrderLineItem.order_id, func.sum(OrderLineItem.quantity))
        .join(Order, Order.id == OrderLineItem.order_id)
        .where(where)
        .group_by(OrderLineItem.order_id)
    )
    qty_by_order = {oid: int(q or 0) for oid, q in qty_rows.all()}

    result = await db.execute(select(Order).where(where).order_by(Order.created_at))
    orders = result.scalars().all()

    rows: List[Dict[str, Any]] = []
    by_month: Dict[str, Dict[str, float]] = defaultdict(lambda: {"orders": 0, "changed": 0, "old": 0.0, "new": 0.0})
    n_weight_fallback = n_geo_fallback = n_cancelled = 0

    for o in orders:
        weight_kg = (o.total_weight_g or 0) / 1000.0
        weight_src = "shopify"
        if weight_kg <= 0:
            weight_kg = qty_by_order.get(o.id, 0) * DEFAULT_ITEM_WEIGHT_KG
            weight_src = "items_x_default"
            n_weight_fallback += 1
        geo = _canonical_geo(o.country or "", o.country_code or "")
        charged = float(o.shipping_charged or 0)
        new, src = _cost_for(geo, weight_kg, charged, _lookup_matrix_shipping_usd)
        if src != "matrix":
            n_geo_fallback += 1
        if o.cancelled_at:
            n_cancelled += 1
        old = round(float(o.shipping_cost or 0), 2)
        changed = abs(new - old) >= 0.005
        d = _local_date(o.created_at)
        ym = d[:7] if d else "?"
        m = by_month[ym]
        m["orders"] += 1
        m["changed"] += int(changed)
        m["old"] += old
        m["new"] += new
        rows.append({
            "id": o.id, "order_name": o.order_name, "date": d,
            "country": o.country, "country_code": o.country_code, "geo": geo,
            "weight_kg": round(weight_kg, 3), "weight_src": weight_src,
            "shipping_charged": charged, "old": old, "new": new,
            "delta": round(new - old, 2), "changed": changed, "cost_src": src,
            "cancelled": bool(o.cancelled_at),
        })

    old_total = round(sum(r["old"] for r in rows), 2)
    new_total = round(sum(r["new"] for r in rows), 2)
    for m in by_month.values():
        m["old"] = round(m["old"], 2)
        m["new"] = round(m["new"], 2)
        m["delta"] = round(m["new"] - m["old"], 2)

    summary = {
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "shop_tz": SHOP_TZ,
        "orders": len(rows),
        "changed": sum(1 for r in rows if r["changed"]),
        "cancelled": n_cancelled,
        "weight_fallback": n_weight_fallback,
        "geo_fallback": n_geo_fallback,
        "old_total": old_total,
        "new_total": new_total,
        "delta": round(new_total - old_total, 2),
        "by_month": dict(sorted(by_month.items())),
        "matrix_stamp": _matrix_stamp(),
        "planned_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    return {"summary": summary, "rows": rows}


async def apply_backfill(db, plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Write `new` for every changed row and persist the plan as a ShippingBackfillRun
    (the rollback snapshot), all in ONE transaction. Returns {applied, run_id}.
    """
    rows = plan["rows"]
    summary = plan["summary"]
    run = ShippingBackfillRun(
        since=summary.get("since"), until=summary.get("until"),
        summary=summary,
        rows=[{k: r[k] for k in ("id", "order_name", "date", "old", "new", "changed")} for r in rows],
    )
    db.add(run)
    n = 0
    for r in rows:
        if not r.get("changed"):
            continue
        await db.execute(update(Order).where(Order.id == int(r["id"])).values(shipping_cost=float(r["new"])))
        n += 1
    run.applied = n
    await db.commit()
    return {"applied": n, "run_id": run.id}


async def restore_backfill(db, values: Optional[List[Dict[str, Any]]] = None,
                           run_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Roll back: from a stored run (run_id -> its rows' `old`), or from explicit
    values (plan rows with `old`, or [{id, shipping_cost}]). One transaction.
    """
    run = None
    if run_id is not None:
        run = await db.get(ShippingBackfillRun, int(run_id))
        if run is None:
            raise ValueError(f"backfill run {run_id} not found")
        values = run.rows or []
    n = 0
    for r in values or []:
        v = r.get("shipping_cost", r.get("old"))
        if v is None:
            continue
        await db.execute(update(Order).where(Order.id == int(r["id"])).values(shipping_cost=float(v)))
        n += 1
    if run is not None:
        run.restored_at = datetime.utcnow()
    await db.commit()
    return {"restored": n, "run_id": run_id}


def _print_summary(s: Dict[str, Any]) -> None:
    print(f"window {s['since'] or '-inf'} .. {s['until'] or 'today'} ({s['shop_tz']}): "
          f"{s['orders']} orders, {s['changed']} change, {s['cancelled']} cancelled, "
          f"weight fallback {s['weight_fallback']}, geo fallback {s['geo_fallback']}")
    print(f"shipping_cost total: {s['old_total']:.2f} -> {s['new_total']:.2f} (delta {s['delta']:+.2f})")
    for ym, m in s["by_month"].items():
        print(f"  {ym}: {m['orders']} orders, {m['changed']} changed, {m['old']:.2f} -> {m['new']:.2f} ({m['delta']:+.2f})")
    st = s.get("matrix_stamp") or {}
    print(f"matrix fetched_at: {st.get('fetched_at', 'unknown')}")


async def _main(a) -> None:
    await init_db()
    async with get_db() as db:
        if a.restore:
            if a.restore.isdigit():
                out = await restore_backfill(db, run_id=int(a.restore))
            else:
                with open(a.restore) as f:
                    saved = json.load(f)
                out = await restore_backfill(db, values=saved.get("rows", saved))
            print(f"restored shipping_cost on {out['restored']} orders ({a.restore})")
            return
        plan = await plan_backfill(db, _parse_date(a.since), _parse_date(a.until), refresh_matrix=not a.no_refresh)
        _print_summary(plan["summary"])
        if a.snapshot:
            with open(a.snapshot, "w") as f:
                json.dump(plan, f, indent=1, default=str)
            print(f"snapshot (old+new per order) -> {a.snapshot}")
        if a.apply:
            out = await apply_backfill(db, plan)
            print(f"APPLIED: updated {out['applied']} orders; rollback with --restore {out['run_id']}")
        else:
            print("dry run — nothing written (add --apply)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="first local date, YYYY-MM-DD (default: all history)")
    ap.add_argument("--until", help="last local date inclusive (default: today)")
    ap.add_argument("--apply", action="store_true", help="write changes (default is dry run)")
    ap.add_argument("--snapshot", help="write the plan (old+new per order) to this JSON file")
    ap.add_argument("--restore", help="roll back: a stored run id, or a snapshot JSON file")
    ap.add_argument("--no-refresh", action="store_true", help="do not re-fetch the sheet first")
    asyncio.run(_main(ap.parse_args()))
