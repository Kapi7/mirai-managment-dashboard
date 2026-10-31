"""Convert Shopify Payments fees to USD using each fee's own currency.

Balance-transaction ``fee`` is denominated in that transaction's ``currency``
(USD, CAD, AUD, EUR, …). Multiplying every fee by ``FX_EUR_TO_USD`` overstates
non-EUR fees. Order 6455 was CAD 7.70, reported as $9.01 (7.70 × 1.17).

Rates come from ``FX_<CUR>_TO_USD``. When that variable is unset or not a
number, a fallback table is used. USD is always 1. A missing currency is
treated as EUR, which is what these reports assumed before. An unknown
currency is left unconverted and logged once — it is not run through the EUR rate.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

# currency → USD. Used only when FX_<CUR>_TO_USD is missing or invalid.
# EUR matches the rate the reports already apply via FX_EUR_TO_USD (1.17).
_FALLBACK_TO_USD: Dict[str, float] = {
    "EUR": 1.17,
    "CAD": 0.72,
    "AUD": 0.65,
    "GBP": 1.33,
    "ILS": 0.30,
    "HKD": 0.128,
    "JPY": 0.0066,
    "TRY": 0.024,
    "NZD": 0.59,
    "CHF": 1.25,
}

_CHARGE_TYPES = ("charge", "payment", "sale")
_ORDER_ID_KEYS = ("order_id", "source_order_id", "source_id")

_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message in _warned:
        return
    _warned.add(message)
    print(f"[psp_fx] {message}")


def _rate_for(currency: Optional[str]) -> float:
    cur = (currency or "").strip().upper()
    if not cur:
        _warn_once("balance transaction has no currency; assuming EUR")
        cur = "EUR"
    if cur == "USD":
        return 1.0
    raw = os.getenv(f"FX_{cur}_TO_USD")
    if raw is not None and str(raw).strip() != "":
        try:
            return float(raw)
        except ValueError:
            _warn_once(f"FX_{cur}_TO_USD={raw!r} is not a number; using fallback")
    if cur in _FALLBACK_TO_USD:
        return _FALLBACK_TO_USD[cur]
    _warn_once(f"no FX rate for {cur}; leaving fee unconverted")
    return 1.0


def fee_to_usd(amount: float, currency: Optional[str] = None) -> float:
    """Convert ``amount`` from ``currency`` to USD, rounded to cents."""
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return 0.0
    return round(amt * _rate_for(currency), 2)


def transaction_fee_usd(txn: dict) -> Optional[float]:
    """USD value of one balance transaction's fee, or None if it has no fee.

    The absolute value is used, matching the previous daily and per-order sums.
    """
    if not isinstance(txn, dict):
        return None
    fee = txn.get("fee")
    if fee is None or fee == "":
        return None
    try:
        amt = abs(float(fee))
    except (TypeError, ValueError):
        return None
    return fee_to_usd(amt, txn.get("currency"))


def sum_transaction_fees_usd(txns) -> float:
    """Sum fees that are already in the window, converting each by its currency.

    Rounded after each addition, same as the daily buckets.
    """
    total = 0.0
    for txn in txns or []:
        fee = transaction_fee_usd(txn)
        if fee is None:
            continue
        total = round(total + fee, 2)
    return total


def charge_order_fee_usd(txn: dict) -> Optional[Tuple[int, float]]:
    """``(order_id, fee_usd)`` for a charge-like balance transaction, else None.

    Refunds and other types are omitted here. The daily total still includes
    them via ``transaction_fee_usd``.
    """
    if not isinstance(txn, dict):
        return None
    typ = (txn.get("type") or "").lower()
    if typ not in _CHARGE_TYPES:
        return None
    fee_usd = transaction_fee_usd(txn)
    if fee_usd is None:
        return None
    for key in _ORDER_ID_KEYS:
        oid = txn.get(key)
        if isinstance(oid, int) and oid > 0:
            return oid, fee_usd
    return None


def interpret_stored_daily_fee(amount: float, currency: Optional[str] = None) -> float:
    """Turn a ``daily_psp_fees`` row into USD.

    Rows written after per-currency conversion are stored as USD and must not
    be converted again. Older rows are a raw mixed-currency sum labeled EUR
    (or blank) and were multiplied by ``FX_EUR_TO_USD`` on read; keep that
    until the next sync rewrites them.
    """
    cur = (currency or "").strip().upper()
    if cur == "USD":
        try:
            return round(float(amount), 2)
        except (TypeError, ValueError):
            return 0.0
    return fee_to_usd(amount, cur or None)
