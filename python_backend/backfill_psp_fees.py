#!/usr/bin/env python3
"""
Backfill daily PSP fees and orders.psp_fee so they match the Telegram bot.

Daily totals come from get_psp_fees_daily in the report timezone. Each fee is
already USD (per balance-transaction currency). Rows are written on the skin
store only: fee_amount, currency, and created_at. The store 2 duplicate and
other non-skin rows for those dates are deleted. The 2026-02-03..2026-07-05
gap is filled when Shopify returns a fee for that day.

Per-order fees use psp_fx.charge_order_fee_usd (get_order_psp_fees), the same
calculation as the Telegram alert. Only orders.psp_fee is updated. Shipping
and every other order column are left alone.

Safe workflow (also POST /admin/backfill-psp-fees, admin only):
  dry run  -> prints the plan, writes nothing
  apply    -> writes a restorable JSON snapshot FIRST, then one transaction
  restore  -> puts that snapshot back (daily rows + orders.psp_fee only)

CLI (needs DATABASE_URL, Shopify credentials, and the same FX_*_TO_USD /
REPORT_TZ as the Telegram bot):

  python3 backfill_psp_fees.py --since 2025-01-29 --until 2026-10-31
  python3 backfill_psp_fees.py --since 2025-01-29 --until 2026-10-31 \\
      --apply --snapshot /tmp/psp_fee_backfill_before.json
  python3 backfill_psp_fees.py --restore /tmp/psp_fee_backfill_before.json

Default window is 2025-01-29 through today in the report timezone.
Dry run is the default. --apply refuses to write when the fetch returns no days.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from sqlalchemy import delete, select, text, update

from database.connection import get_db, init_db
from database.models import DailyPspFee, Order, Store
from psp_fees_logic import (
    plan_daily_backfill,
    plan_order_fee_updates,
    project_daily_fees,
    report_timezone_name,
    resolve_skin_store,
    resolve_window,
    utc_bounds,
    choose_daily_psp_rows,
)


def _parse_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _default_fetch_daily(since: date, until_exclusive: date, tz_name: str):
    """``{fees, complete, reason}``. ``complete`` is false when pagination stopped early."""
    from psp_fee import get_psp_fees_daily_result
    return get_psp_fees_daily_result(since, until_exclusive, tz_name=tz_name)


def _default_fetch_order_fees(since: date, until_exclusive: date, tz_name: str):
    from psp_fee import get_order_psp_fees_result
    return get_order_psp_fees_result(since, until_exclusive, tz_name=tz_name)


def _as_fetch(value):
    """Normalize a fetcher return into (mapping, complete, reason).

    A plain date→amount dict (the unit-test fetchers) is a complete fetch.
    Production fetchers return ``{fees, complete, reason}``.
    """
    if isinstance(value, tuple):
        fees = value[0] or {}
        complete = bool(value[1]) if len(value) > 1 else True
        reason = value[2] if len(value) > 2 else ""
        return fees, complete, reason
    if isinstance(value, dict) and "complete" in value and "fees" in value:
        return value.get("fees") or {}, bool(value["complete"]), value.get("reason") or ""
    return value or {}, True, ""


async def _resolve_fetch(fetch, *args):
    """Call a sync fetcher, or await one that already ran in a thread pool."""
    value = fetch(*args)
    if inspect.isawaitable(value):
        value = await value
    return value


def default_snapshot_path() -> str:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    directory = os.getenv("PSP_SNAPSHOT_DIR", "/tmp")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"psp_fee_backfill_{stamp}.json")


def write_snapshot(path: str, payload: Mapping[str, Any]) -> str:
    """Atomically write the before-image. Call this before any mutation."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        json.dump(payload, handle, indent=1, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def _october_total(rows, skin_store_id: int) -> Optional[float]:
    from psp_fee import interpret_stored_daily_fee
    chosen = choose_daily_psp_rows(rows, skin_store_id)
    total = 0.0
    count = 0
    for day, row in chosen.items():
        if getattr(day, "year", None) == 2026 and day.month == 10:
            total = round(total + interpret_stored_daily_fee(row.fee_amount, row.currency), 2)
            count += 1
    if count == 0:
        return None
    return total


def _summary(plan: Mapping[str, Any], since: date, until: date, tz_name: str, october) -> Dict[str, Any]:
    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "timezone": tz_name,
        "fetched_days": plan["fetched_days"],
        "daily_updates": len(plan["updates"]),
        "daily_inserts": len(plan["inserts"]),
        "daily_deletes": len(plan["deletes"]),
        "daily_unchanged": plan["unchanged"],
        "gap_inserts": plan["gap_inserts"],
        "kept_legacy": len(plan["kept_legacy"]),
        "order_fee_updates": len(plan["order_changes"]),
        "october_2026_psp_usd": october,
        "fetch_complete": plan.get("fetch_complete", True),
        "fetch_reason": plan.get("fetch_reason") or "",
    }


def _print_summary(summary: Mapping[str, Any], dry_run: bool) -> None:
    if summary.get("fetch_complete") is False:
        print("*** INCOMPLETE SHOPIFY FETCH — do not apply. Partial totals are not safe. ***")
        print(f"    {summary.get('fetch_reason') or 'pagination stopped early'}")
    print(
        f"window {summary['since']} .. {summary['until']} ({summary['timezone']}): "
        f"fetched {summary['fetched_days']} days, "
        f"update {summary['daily_updates']}, insert {summary['daily_inserts']}, "
        f"delete {summary['daily_deletes']}, unchanged {summary['daily_unchanged']}, "
        f"gap inserts {summary['gap_inserts']}, kept legacy {summary['kept_legacy']}, "
        f"order psp_fee updates {summary['order_fee_updates']}"
    )
    october = summary.get("october_2026_psp_usd")
    if october is not None:
        print(f"October 2026 PSP after this plan: ${october:.2f}")
    if summary.get("kept_legacy"):
        print(f"  {summary['kept_legacy']} non-skin rows were NOT deleted (fetch did not replace that date)")
    print("dry run — nothing written" if dry_run else "apply")


async def build_plan(
    db,
    since: date,
    until: date,
    *,
    fetch_daily: Callable = _default_fetch_daily,
    fetch_order_fees: Callable = _default_fetch_order_fees,
) -> Dict[str, Any]:
    tz_name = report_timezone_name()
    stores = (await db.execute(select(Store))).scalars().all()
    skin = resolve_skin_store(stores, os.getenv("SHOPIFY_STORE", ""))
    if skin is None:
        raise ValueError("skin store not found (key 'skin' or SHOPIFY_STORE domain)")

    until_exclusive = until + timedelta(days=1)
    # Daily buckets stop at `until`. Order charges sometimes post just after
    # local midnight, so the per-order fetch looks one day further.
    # The admin endpoint passes fetchers that already ran in run_in_threadpool.
    fetched_raw = await _resolve_fetch(fetch_daily, since, until_exclusive, tz_name)
    order_raw = await _resolve_fetch(
        fetch_order_fees, since, until_exclusive + timedelta(days=1), tz_name
    )
    fetched, daily_complete, daily_reason = _as_fetch(fetched_raw)
    order_index, order_complete, order_reason = _as_fetch(order_raw)
    fetch_complete = bool(daily_complete and order_complete)
    fetch_reason = "; ".join(part for part in (daily_reason, order_reason) if part)

    fee_rows = (
        await db.execute(
            select(DailyPspFee)
            .where(DailyPspFee.date >= since, DailyPspFee.date <= until)
            .order_by(DailyPspFee.date, DailyPspFee.store_id, DailyPspFee.id)
        )
    ).scalars().all()

    start_utc, end_utc = utc_bounds(since, until, tz_name)
    orders = (
        await db.execute(
            select(Order).where(Order.created_at >= start_utc, Order.created_at < end_utc)
        )
    ).scalars().all()

    daily = plan_daily_backfill(fee_rows, fetched, skin.id, since, until)
    order_changes = plan_order_fee_updates(orders, order_index)
    projected = project_daily_fees(fee_rows, daily)
    october = _october_total(projected, skin.id)
    snapshot = {
        "kind": "psp_fee_backfill",
        "since": since.isoformat(),
        "until": until.isoformat(),
        "timezone": tz_name,
        "skin_store_id": skin.id,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "daily_psp_fees": daily["before_daily"],
        # Old psp_fee only. Shipping and other order fields are not in here
        # and restore will not write them.
        "order_psp_fees": [
            {"id": row["id"], "order_name": row["order_name"], "psp_fee": row["old"]}
            for row in order_changes
        ],
        # Restore touches only these. Rows the cron inserts later are not listed
        # and must not be deleted. inserts[].id is filled after flush, before commit.
        "restore": {
            "updates": [
                {
                    "id": row["id"],
                    "old_fee": row["old_fee"],
                    "old_currency": row.get("old_currency"),
                    "old_created_at": row.get("old_created_at"),
                }
                for row in daily["updates"]
            ],
            "deletes": daily["deletes"],
            "inserts": [],
        },
    }
    plan = {
        **daily,
        "order_changes": order_changes,
        "skin_store_id": skin.id,
        "timezone": tz_name,
        "since": since,
        "until": until,
        "snapshot": snapshot,
        "october_2026_psp_usd": october,
        "fetch_complete": fetch_complete,
        "fetch_reason": fetch_reason,
    }
    return plan


async def apply_mutations(db, plan: Mapping[str, Any]) -> Dict[str, int]:
    """Write fee_amount/currency/created_at, delete non-skin duplicates, set orders.psp_fee.

    Does not touch shipping_cost or any other order column.
    """
    now = datetime.utcnow()
    inserted = []
    for row in plan["updates"]:
        await db.execute(
            update(DailyPspFee)
            .where(DailyPspFee.id == int(row["id"]))
            .values(fee_amount=float(row["new_fee"]), currency="USD", created_at=now)
        )
    for row in plan["inserts"]:
        record = DailyPspFee(
            date=date.fromisoformat(row["date"]),
            store_id=int(row["store_id"]),
            fee_amount=float(row["fee_amount"]),
            currency="USD",
            created_at=now,
        )
        db.add(record)
        inserted.append(record)
    for row in plan["deletes"]:
        if row.get("id") is None:
            continue
        await db.execute(delete(DailyPspFee).where(DailyPspFee.id == int(row["id"])))
    for row in plan["order_changes"]:
        await db.execute(
            update(Order).where(Order.id == int(row["id"])).values(psp_fee=float(row["new"]))
        )
    await db.flush()
    return {
        "updated": len(plan["updates"]),
        "inserted": len(plan["inserts"]),
        "deleted": len(plan["deletes"]),
        "order_fees": len(plan["order_changes"]),
        "inserted_ids": [int(record.id) for record in inserted if record.id is not None],
    }


async def run_backfill(
    db,
    since: Optional[date] = None,
    until: Optional[date] = None,
    *,
    apply: bool = False,
    snapshot_path: Optional[str] = None,
    fetch_daily: Callable = _default_fetch_daily,
    fetch_order_fees: Callable = _default_fetch_order_fees,
    mutate: Callable = apply_mutations,
) -> Dict[str, Any]:
    """Dry run by default. --apply writes the snapshot file before any mutation."""
    since, until = resolve_window(since, until)
    plan = await build_plan(
        db, since, until, fetch_daily=fetch_daily, fetch_order_fees=fetch_order_fees
    )
    summary = _summary(plan, since, until, plan["timezone"], plan["october_2026_psp_usd"])
    result: Dict[str, Any] = {
        "dry_run": not apply,
        "applied": False,
        "refused": False,
        "snapshot_path": None,
        "snapshot": plan["snapshot"],
        **summary,
        "updates": plan["updates"],
        "inserts": plan["inserts"],
        "deletes": plan["deletes"],
        "kept_legacy_rows": plan["kept_legacy"],
        "order_changes": plan["order_changes"],
    }
    if not apply:
        return result
    if not plan.get("fetch_complete", True):
        result["dry_run"] = True
        result["refused"] = True
        result["reason"] = (
            "incomplete Shopify fetch; refusing to apply so a partial day is not stored "
            "and its store 2 row is not deleted"
            + (f" ({plan.get('fetch_reason')})" if plan.get("fetch_reason") else "")
        )
        return result
    if plan["fetched_days"] == 0:
        result["dry_run"] = True
        result["refused"] = True
        result["reason"] = "fetch returned no PSP days; refusing to apply so legacy rows are not deleted"
        return result

    path = snapshot_path or default_snapshot_path()
    # Snapshot first. If the write fails, nothing in the database has changed.
    write_snapshot(path, plan["snapshot"])
    result["snapshot_path"] = path
    try:
        counts = await mutate(db, plan)
        # Record only the rows this apply inserted, then commit. A cron row
        # written later has a different id and restore will leave it alone.
        inserted_ids = list((counts or {}).get("inserted_ids") or [])
        plan["snapshot"].setdefault("restore", {})["inserts"] = [
            {"id": int(row_id)} for row_id in inserted_ids
        ]
        write_snapshot(path, plan["snapshot"])
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    result["applied"] = True
    result["counts"] = counts
    return result


def _parse_dt(value: Optional[str]):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


async def _put_back_daily(db, row: Mapping[str, Any]) -> None:
    """Reinsert a deleted daily row, or put its saved columns back. Nothing else."""
    fee_date = date.fromisoformat(str(row["date"])[:10])
    values = dict(
        date=fee_date,
        store_id=row.get("store_id"),
        fee_amount=float(row["fee_amount"]),
        currency=row.get("currency"),
        created_at=_parse_dt(row.get("created_at")),
    )
    existing = None
    if row.get("id") is not None:
        existing = await db.get(DailyPspFee, int(row["id"]))
    if existing is None:
        db.add(DailyPspFee(id=row.get("id"), **values))
        return
    existing.date = values["date"]
    existing.store_id = values["store_id"]
    existing.fee_amount = values["fee_amount"]
    existing.currency = values["currency"]
    existing.created_at = values["created_at"]


async def restore_snapshot(db, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Roll back only rows this apply changed.

    Deletes the inserted ids, restores updated fees, and reinserts deleted
    rows. A daily row the cron wrote afterwards has a different id and is
    left in place. Shipping and every other order column are not written.
    """
    restore = snapshot.get("restore") or {}
    restored_daily = 0
    if restore:
        for inserted in restore.get("inserts") or []:
            if inserted.get("id") is None:
                continue
            existing = await db.get(DailyPspFee, int(inserted["id"]))
            if existing is None:
                continue
            await db.delete(existing)
            restored_daily += 1
        await db.flush()
        for updated in restore.get("updates") or []:
            existing = await db.get(DailyPspFee, int(updated["id"]))
            if existing is None:
                continue
            existing.fee_amount = float(updated["old_fee"])
            existing.currency = updated.get("old_currency")
            if "old_created_at" in updated:
                existing.created_at = _parse_dt(updated.get("old_created_at"))
            restored_daily += 1
        for deleted in restore.get("deletes") or []:
            await _put_back_daily(db, deleted)
            restored_daily += 1
        await db.flush()
    else:
        # Older snapshot with a full before-image and no insert list. Put those
        # rows back, but do not delete ids that are missing from it.
        for row in snapshot.get("daily_psp_fees") or []:
            await _put_back_daily(db, row)
            restored_daily += 1
        await db.flush()

    restored_orders = 0
    for row in snapshot.get("order_psp_fees") or []:
        fee = row.get("psp_fee")
        await db.execute(
            update(Order)
            .where(Order.id == int(row["id"]))
            .values(psp_fee=None if fee is None else float(fee))
        )
        restored_orders += 1

    dialect = ""
    try:
        bind = db.bind
        dialect = bind.dialect.name if bind is not None else ""
    except Exception:
        dialect = ""
    if dialect == "postgresql":
        await db.execute(text(
            "SELECT setval(pg_get_serial_sequence('daily_psp_fees','id'), "
            "COALESCE((SELECT MAX(id) FROM daily_psp_fees), 1))"
        ))
    await db.commit()
    return {"restored_daily": restored_daily, "restored_orders": restored_orders}


def load_snapshot(path: str) -> dict:
    with open(path) as handle:
        return json.load(handle)


async def _main(args) -> None:
    await init_db()
    async with get_db() as db:
        if args.restore:
            snapshot = load_snapshot(args.restore)
            out = await restore_snapshot(db, snapshot)
            print(
                f"restored {out['restored_daily']} daily_psp_fees rows and "
                f"psp_fee on {out['restored_orders']} orders from {args.restore}"
            )
            return
        result = await run_backfill(
            db,
            _parse_date(args.since),
            _parse_date(args.until),
            apply=args.apply,
            snapshot_path=args.snapshot,
        )
        _print_summary(result, dry_run=result["dry_run"])
        if result.get("refused"):
            print(f"REFUSED: {result['reason']}")
            raise SystemExit(2)
        if result.get("snapshot_path"):
            print(f"snapshot (restore with --restore) -> {result['snapshot_path']}")
            print(
                "APPLIED: "
                f"daily updated {result['counts']['updated']}, "
                f"inserted {result['counts']['inserted']}, "
                f"deleted {result['counts']['deleted']}, "
                f"order psp_fee {result['counts']['order_fees']}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", help="first report-timezone date, YYYY-MM-DD (default 2025-01-29)")
    parser.add_argument("--until", help="last date inclusive (default: today in the report timezone)")
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry run)")
    parser.add_argument("--snapshot", help="where to write the before-image JSON on --apply")
    parser.add_argument("--restore", help="roll back from a snapshot JSON file")
    asyncio.run(_main(parser.parse_args()))
