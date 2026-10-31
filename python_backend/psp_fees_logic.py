"""Pure helpers for PSP store selection, daily-row reads, and backfill plans.

No Shopify client and no database session, so the store-id fix, the reader,
and the backfill plan can be tested without credentials.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pytz

# First day that still has a daily_psp_fees row. The backfill default.
DEFAULT_SINCE = date(2025, 1, 29)
# Days with no row at all; the dashboard falls back to 2.9% + $0.30 there.
GAP_START = date(2026, 2, 3)
GAP_END = date(2026, 7, 5)


def report_timezone_name() -> str:
    """Timezone the Telegram report buckets PSP fees in.

    ``REPORT_TZ`` wins when it is set. Otherwise the dashboard's ``SHOP_TZ``
    (Asia/Nicosia) so a service that only set SHOP_TZ still matches the bot.
    """
    name = (os.getenv("REPORT_TZ") or os.getenv("SHOP_TZ") or "Asia/Nicosia").strip()
    return name or "Asia/Nicosia"


def report_today() -> date:
    return datetime.now(pytz.timezone(report_timezone_name())).date()


def resolve_window(since: Optional[date], until: Optional[date]) -> tuple:
    start = since or DEFAULT_SINCE
    end = until or report_today()
    if end < start:
        raise ValueError(f"until {end} is before since {start}")
    return start, end


def shopify_numeric_id(value: Any) -> Optional[int]:
    """Numeric Shopify order id from an int, a digit string, or a GID."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return number if number > 0 else None
    match = re.search(r"(\d+)$", text)
    if not match:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


def resolve_skin_store(stores: Sequence[Any], shopify_domain: Optional[str] = None):
    """The skin store: key ``skin`` first, else the SHOPIFY_STORE domain.

    Never "whichever store the sync loop finished on". When several rows match,
    the lowest id wins so the choice is stable.
    """
    domain = (shopify_domain or "").strip().lower()

    def _key(store: Any) -> str:
        return (getattr(store, "key", None) or "").strip().lower()

    def _domain(store: Any) -> str:
        return (getattr(store, "shopify_domain", None) or "").strip().lower()

    def _id(store: Any) -> int:
        try:
            return int(store.id)
        except (TypeError, ValueError):
            return 0

    by_key = [store for store in stores if _key(store) == "skin"]
    if domain:
        keyed = [store for store in by_key if _domain(store) == domain]
        if keyed:
            return sorted(keyed, key=_id)[0]
    if by_key:
        return sorted(by_key, key=_id)[0]
    if domain:
        matched = [store for store in stores if _domain(store) == domain]
        if matched:
            return sorted(matched, key=_id)[0]
    return None


def order_psp_fee_or_estimate(stored: Any, net: float) -> float:
    """Real per-order fee when we have one. Otherwise 2.9% + $0.30.

    ``0`` is a real fee (use it). ``None`` means the charge has not been
    stored yet, which is the only time the estimate applies.
    """
    if stored is not None and stored != "":
        try:
            return round(float(stored), 2)
        except (TypeError, ValueError):
            pass
    try:
        amount = float(net or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0:
        return 0.0
    return round(amount * 0.029 + 0.30, 2)


def order_line_profit(
    net: float,
    shipping: float,
    shipping_cost: float,
    cogs: float,
    psp_fee: float,
    shop_ad_cost: float = 0.0,
) -> float:
    """Same profit formula the order report and the Telegram alert use."""
    return net + shipping - shipping_cost - cogs - psp_fee - shop_ad_cost


def choose_daily_psp_rows(rows: Iterable[Any], skin_store_id: Optional[int]) -> Dict[Any, Any]:
    """One daily_psp_fees row per date.

    Rows are ordered by (date, store_id, id) first, so two rows for the same
    date cannot overwrite each other based on whatever order the database
    happened to return. The skin store wins when it has that date. Otherwise
    the lowest store_id, then the lowest id, is kept — a date that exists only
    on the legacy store is still visible until the backfill moves it.
    Duplicate dates are not summed: Jan 2026 has the same day on two stores,
    and adding them would double the fee.
    """
    def sort_key(row: Any):
        store_id = row.store_id if row.store_id is not None else 0
        row_id = row.id if row.id is not None else 0
        return (row.date, int(store_id), int(row_id))

    chosen: Dict[Any, Any] = {}
    for row in sorted(rows, key=sort_key):
        current = chosen.get(row.date)
        if current is None:
            chosen[row.date] = row
            continue
        if (
            skin_store_id is not None
            and row.store_id == skin_store_id
            and current.store_id != skin_store_id
        ):
            chosen[row.date] = row
    return chosen


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _currency(value: Any) -> str:
    return (value or "").strip().upper()


def _daily_snapshot(row: Any, reason: str) -> dict:
    created = getattr(row, "created_at", None)
    if isinstance(created, datetime):
        created = created.isoformat()
    on = row.date
    return {
        "id": row.id,
        "date": on.isoformat() if isinstance(on, date) else str(on)[:10],
        "store_id": row.store_id,
        "fee_amount": _money(row.fee_amount),
        "currency": row.currency,
        "created_at": created,
        "reason": reason,
    }


def plan_daily_backfill(
    existing: Sequence[Any],
    fetched: Mapping[date, float],
    skin_store_id: int,
    since: date,
    until: date,
) -> Dict[str, Any]:
    """Plan skin-store fee_amount / currency updates. Does not write.

    Non-skin rows (the store 2 duplicates and the legacy EUR rows) are deleted
    only when the skin store already has that date or the fetch just supplied
    one. A non-skin row that is the only copy of a date the fetch did not
    return is kept and reported, so a short fetch cannot wipe history.
    """
    in_window = [row for row in existing if since <= row.date <= until]
    skin_by_date: Dict[date, List[Any]] = {}
    for row in in_window:
        if row.store_id == skin_store_id:
            skin_by_date.setdefault(row.date, []).append(row)

    fetched_in = {
        day: _money(amount)
        for day, amount in fetched.items()
        if since <= day <= until
    }

    updates: List[dict] = []
    inserts: List[dict] = []
    deletes: List[dict] = []
    unchanged = 0

    for day in sorted(fetched_in):
        amount = fetched_in[day]
        skins = sorted(skin_by_date.get(day) or [], key=lambda row: row.id or 0)
        if not skins:
            inserts.append({
                "date": day.isoformat(),
                "store_id": skin_store_id,
                "fee_amount": amount,
                "currency": "USD",
            })
            continue
        primary = skins[0]
        for extra in skins[1:]:
            deletes.append(_daily_snapshot(extra, "duplicate_skin"))
        old_fee = _money(primary.fee_amount)
        if old_fee != amount or _currency(primary.currency) != "USD":
            updates.append({
                "id": primary.id,
                "date": day.isoformat(),
                "store_id": skin_store_id,
                "old_fee": old_fee,
                "old_currency": primary.currency,
                "new_fee": amount,
                "new_currency": "USD",
            })
        else:
            unchanged += 1

    skin_dates = set(skin_by_date) | set(fetched_in)
    for row in in_window:
        if row.store_id == skin_store_id:
            continue
        if row.date in skin_dates:
            deletes.append(_daily_snapshot(row, "non_skin_duplicate"))

    seen = set()
    unique_deletes = []
    for row in deletes:
        if row.get("id") in seen:
            continue
        seen.add(row.get("id"))
        unique_deletes.append(row)

    deleted_ids = {row["id"] for row in unique_deletes}
    kept = [
        _daily_snapshot(row, "kept_no_replacement")
        for row in in_window
        if row.store_id != skin_store_id and row.id not in deleted_ids
    ]
    gap_inserts = [
        row for row in inserts
        if GAP_START <= date.fromisoformat(row["date"]) <= GAP_END
    ]
    return {
        "updates": updates,
        "inserts": inserts,
        "deletes": unique_deletes,
        "kept_legacy": kept,
        "unchanged": unchanged,
        "gap_inserts": len(gap_inserts),
        "fetched_days": len(fetched_in),
        "before_daily": [_daily_snapshot(row, "before") for row in in_window],
    }


def plan_order_fee_updates(orders: Sequence[Any], fee_index: Mapping[int, float]) -> List[dict]:
    """Orders whose stored psp_fee differs from the Telegram charge fee.

    Orders with no charge in the index are left untouched (NULL stays NULL,
    so the reader keeps the estimate). Only ``psp_fee`` is in the change.
    """
    changes = []
    for order in orders:
        oid = shopify_numeric_id(getattr(order, "shopify_gid", None))
        if oid is None or oid not in fee_index:
            continue
        new = _money(fee_index[oid])
        old_raw = getattr(order, "psp_fee", None)
        old = None if old_raw is None else _money(old_raw)
        if old is not None and abs(old - new) < 0.005:
            continue
        changes.append({
            "id": order.id,
            "order_name": getattr(order, "order_name", None),
            "shopify_gid": getattr(order, "shopify_gid", None),
            "old": old,
            "new": new,
        })
    return changes


def project_daily_fees(existing: Sequence[Any], plan: Mapping[str, Any]) -> List[Any]:
    """Rows that would exist after the plan, without writing.

    Used to preview the October total on a dry run.
    """
    deleted = {row["id"] for row in plan.get("deletes") or [] if row.get("id") is not None}
    updated = {row["id"]: row for row in plan.get("updates") or []}
    projected: List[Any] = []
    for row in existing:
        if row.id in deleted:
            continue
        change = updated.get(row.id)
        if change is None:
            projected.append(row)
            continue
        projected.append(_Projected(
            id=row.id,
            on=row.date,
            store_id=row.store_id,
            fee_amount=change["new_fee"],
            currency=change["new_currency"],
        ))
    for row in plan.get("inserts") or []:
        projected.append(_Projected(
            id=None,
            on=date.fromisoformat(row["date"]),
            store_id=row["store_id"],
            fee_amount=row["fee_amount"],
            currency=row["currency"],
        ))
    return projected


class _Projected:
    def __init__(self, id, on, store_id, fee_amount, currency):
        self.id = id
        self.date = on
        self.store_id = store_id
        self.fee_amount = fee_amount
        self.currency = currency


def utc_bounds(since: date, until: date, tz_name: str):
    """Local calendar window (until inclusive) as naive UTC datetimes."""
    tz = pytz.timezone(tz_name)
    start_utc = tz.localize(datetime.combine(since, datetime.min.time())).astimezone(pytz.UTC).replace(tzinfo=None)
    end_utc = tz.localize(
        datetime.combine(until + timedelta(days=1), datetime.min.time())
    ).astimezone(pytz.UTC).replace(tzinfo=None)
    return start_utc, end_utc
