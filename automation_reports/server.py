# server.py
from __future__ import annotations

from datetime import datetime, timedelta, date
from calendar import monthrange
import os

import pytz
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

# Core orchestration (already talks to Shopify, PayPal, Google, Meta, PSP)
from master_report_mirai import build_month_rows, _google_spend_usd, compute_day_kpis, compute_mtd_kpis
from meta_client import fetch_meta_insights_day
from telegram_client import upsert_daily_summary


# ---------- Pydantic models ----------

class DateRangeRequest(BaseModel):
    """
    Request body for all date-range endpoints.
    Dates are inclusive and must be YYYY-MM-DD.
    """
    start_date: str
    end_date: str

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Dates must be in YYYY-MM-DD format")
        return v

    @property
    def start(self) -> date:
        return datetime.strptime(self.start_date, "%Y-%m-%d").date()

    @property
    def end(self) -> date:
        return datetime.strptime(self.end_date, "%Y-%m-%d").date()


# ---------- FastAPI app ----------

import asyncio

app = FastAPI(title="Mirai Report API", version="1.2.0")


# ---------- Background Sync Task ----------

def _do_sync_summary():
    """
    Synchronous function that does the heavy lifting.
    Run in thread pool to avoid blocking event loop.
    """
    # Use the same TZ resolution as the HTTP endpoints (_safe_shop_tz) — the
    # old SHOP_TZ/Europe/Berlin default bucketed days differently from the rest.
    shop_tz = _safe_shop_tz()
    anchor = datetime.now(pytz.timezone(shop_tz)).date()
    yday = anchor - timedelta(days=1)

    k_today = compute_day_kpis(anchor, shop_tz)
    k_yday = compute_day_kpis(yday, shop_tz)
    k_mtd = compute_mtd_kpis(anchor, shop_tz)

    upsert_daily_summary(
        today_kpi=k_today,
        yday_kpi=k_yday,
        mtd_kpi=k_mtd,
        pin=True,
        summary_key="DAILY"
    )
    return anchor, k_today


async def _sync_summary_task():
    """Background task that syncs Telegram summary every 30 minutes."""
    await asyncio.sleep(180)  # Wait 3 min after startup before first sync
    while True:
        try:
            # Run heavy sync in thread pool to avoid blocking health checks
            anchor, k_today = await asyncio.to_thread(_do_sync_summary)
            print(f"[Sync] Summary updated: {anchor} orders={k_today.orders} net={k_today.net}")
        except Exception as e:
            print(f"[Sync] Error updating summary: {e}")

        await asyncio.sleep(30 * 60)  # Every 30 minutes


# ---------- Background Order Monitor (per-order Telegram alerts) ----------
#
# Render runs a single web process (uvicorn server:app), so the standalone
# monitor_orders.py worker in start.sh never launches here. We run the same
# poll loop IN-PROCESS so per-order alerts work regardless of the start command
# — exactly how the summary sync above already works.

# Poll cadence + lookback window (env-overridable)
MONITOR_EVERY_SEC = int(os.getenv("ALERT_EVERY", "60"))
MONITOR_LOOKBACK_HOURS = int(os.getenv("ALERT_HOURS", "24"))


def _do_monitor_poll() -> int:
    """
    Synchronous one-shot poll of all Shopify stores → per-order Telegram alerts.
    Dedup is handled by monitor_orders' own seen-orders file, so re-polling the
    same 24h window won't resend. Run in a thread to avoid blocking the loop.
    """
    # Import lazily so server boot never fails on monitor's heavy imports.
    from monitor_orders import run as monitor_run
    return int(monitor_run(window_hours=MONITOR_LOOKBACK_HOURS) or 0)


async def _monitor_orders_task():
    """Background task that polls Shopify and sends per-order alerts."""
    await asyncio.sleep(30)  # Short delay so app is up before first poll
    while True:
        try:
            sent = await asyncio.to_thread(_do_monitor_poll)
            if sent:
                print(f"[MonitorTask] Sent {sent} new order alert(s).")
        except Exception as e:
            import traceback
            print(f"[MonitorTask] Poll error: {e}\n{traceback.format_exc()}")

        await asyncio.sleep(MONITOR_EVERY_SEC)


@app.on_event("startup")
async def startup_event():
    """Start background tasks: summary sync + per-order monitor."""
    if os.getenv("REPORTS_JOBS_ENABLED", "0") != "1":
        print("[Startup] Reports background jobs disabled")
        return
    asyncio.create_task(_sync_summary_task())
    asyncio.create_task(_monitor_orders_task())
    print(f"[Startup] Background tasks launched (monitor every {MONITOR_EVERY_SEC}s, "
          f"lookback {MONITOR_LOOKBACK_HOURS}h).")

# Get CORS origins from environment or use defaults
cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
if "*" not in cors_origins:
    cors_origins.extend([
        "https://mirai-managment-dashboard.onrender.com",
        "http://localhost:3001",
        "http://localhost:5173"
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print(f"🔓 CORS enabled for origins: {cors_origins}")


# ---------- Small helpers ----------

def _safe_shop_tz() -> str:
    """
    Resolve the Shopify/store timezone that all KPIs are based on.
    Falls back to UTC if env is wrong.
    """
    tz_name = (os.getenv("REPORT_TZ") or "UTC").strip()
    try:
        pytz.timezone(tz_name)
    except Exception:
        tz_name = "UTC"
    return tz_name


def _month_last(d: date) -> date:
    """Return the last day of the month for the given date."""
    last = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


def _collect_kpis_range(start_date: date, end_date: date, shop_tz: str):
    """
    Call build_month_rows for each month touched by [start_date, end_date]
    and merge all KPIs into a single {date -> KPIs} dict.
    This is where Shopify + Meta + Google + PayPal + PSP are all combined.
    """
    all_kpis: dict[date, object] = {}

    # start from the 1st of the first month in the range
    cur = start_date.replace(day=1)

    while cur <= end_date:
        month_end = _month_last(cur)
        anchor = min(month_end, end_date)

        # build KPIs up to "anchor" within this month
        _, _, _, _, kpi_by_date = build_month_rows(anchor, shop_tz)

        # keep only the days that fall inside the requested range
        for d, k in kpi_by_date.items():
            if start_date <= d <= end_date:
                all_kpis[d] = k

        # move to first day of next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)

    return all_kpis


# ---------- Health ----------

@app.get("/health")
async def health():
    return {"status": "ok", "message": "FastAPI is running"}


# ---------- Sync Telegram Summary ----------

@app.post("/sync-summary")
async def sync_summary():
    """
    Refresh the Telegram daily summary with current KPIs.
    Call this periodically (e.g., every 30-60 min) to keep summary updated.
    """
    try:
        # Run heavy sync in thread pool to avoid blocking
        anchor, k_today = await asyncio.to_thread(_do_sync_summary)

        return {
            "ok": True,
            "date": anchor.isoformat(),
            "orders_today": k_today.orders,
            "net_today": float(k_today.net),
        }
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{e}\n{traceback.format_exc()}")


# ---------- Force backfill orders (sends per-order messages) ----------

@app.post("/force-backfill-today")
async def force_backfill_today(hours: int = 24, force: bool = False):
    """
    One-shot backfill: scans the last `hours` of Shopify orders and sends
    Telegram alerts for any that weren't alerted yet.

    Dedup-safe by default: re-running won't double-send. Pass force=true to
    ignore the seen-orders file.

    Query params:
      - hours: how far back to scan (default 24)
      - force: ignore seen-orders file (default false)
    """
    try:
        # Import here (not at module import time) so server boot never fails
        # even if monitor file has optional deps or heavy imports.
        from monitor_orders import backfill_today_and_send  # type: ignore

        sent_count = backfill_today_and_send(hours=hours, force=force)
        return {"ok": True, "sent": int(sent_count), "hours": hours, "force": force}

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import backfill_today_and_send from monitor_orders.py: {e}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Main daily report endpoint ----------

@app.post("/daily-report")
async def daily_report(req: DateRangeRequest):
    """
    Return one object per day in the range with full KPIs.

    Each object includes (per day):
      - date (YYYY-MM-DD)
      - label (human readable, e.g. "Mon, Nov 18")
      - orders, gross, discounts, refunds, net, cogs
      - shipping_charged, shipping_cost
      - google_spend, meta_spend, total_spend
      - google_pur, meta_pur, google_cpa, meta_cpa, general_cpa
      - psp_usd
      - operational_profit, net_margin, margin_pct
      - aov, returning_customers
    """
    try:
        if req.start > req.end:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        shop_tz = _safe_shop_tz()

        # Collect KPIs per calendar day across all relevant months
        kpis_by_date = _collect_kpis_range(req.start, req.end, shop_tz)

        data = []
        current = req.start
        while current <= req.end:
            k = kpis_by_date.get(current)
            if k is not None:
                # NOTE: k.* fields come from master_report_mirai.KPIs dataclass
                day_obj = {
                    "date": current.isoformat(),          # canonical date
                    "label": k.day,                       # pretty label from local_day_window
                    "orders": k.orders,
                    "gross": k.gross,
                    "discounts": k.discounts,
                    "refunds": k.refunds,
                    "net": k.net,
                    "cogs": k.cogs,
                    "shipping_charged": k.shipping_charged,
                    # Matrix estimate feeds Operational (dashboard parity);
                    # the PayPal cash figure stays available separately.
                    "shipping_cost": k.shipping_estimated,
                    "shipping_estimated": k.shipping_estimated,
                    "shipping_cost_paypal": k.shipping_cost,
                    "google_spend": k.google_spend,
                    "meta_spend": k.meta_spend,
                    "shop_spend": k.shop_spend,
                    "total_spend": k.total_spend,
                    "google_pur": k.google_pur,
                    "meta_pur": k.meta_pur,
                    "shop_pur": k.shop_pur,
                    "google_cpa": k.google_cpa,
                    "meta_cpa": k.meta_cpa,
                    "shop_cpa": k.shop_cpa,
                    "general_cpa": k.general_cpa,
                    "psp_usd": k.psp_usd,
                    "operational": k.operational,
                    "margin": k.margin,
                    "operational_profit": k.operational,
                    "net_margin": k.margin,
                    "margin_pct": k.margin_pct,
                    "aov": k.aov,
                    "returning_customers": k.returning_count,
                }
                data.append(day_obj)

            current += timedelta(days=1)

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        # Safe fallback; helpful for debugging from Deno / Postman
        return {"error": str(e), "data": []}


# ---------- Supporting endpoint: raw ad spend only ----------

@app.post("/ad-spend")
async def ad_spend(req: DateRangeRequest):
    """
    Simple helper to fetch ad spend for a single day / short range.
    Still used by some tools; dashboard can rely on /daily-report instead.
    """
    try:
        if req.start > req.end:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        shop_tz = _safe_shop_tz()

        # Google Ads spend (helper expects single day + tz)
        google_spend = _google_spend_usd(req.start_date, shop_tz)

        # Meta Ads spend over the range (your meta_client already aligns by day)
        meta = fetch_meta_insights_day(req.start_date, req.end_date) or {}

        return {
            "google_spend": google_spend,
            "meta_spend": meta.get("meta_spend", 0.0),
            "meta_purchases": meta.get("meta_purchases", 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "google_spend": 0.0,
            "meta_spend": 0.0,
            "meta_purchases": 0,
            "error": str(e),
        }


# ---------- Debug endpoint for PSP Fees ----------

@app.get("/debug/shop-campaign-cost")
async def debug_shop_campaign_cost(days: int = 30):
    """
    EXACT Shop Campaigns ad spend per day, straight from Shopify ShopifyQL
    (shop_campaign_insights). This is the primary cost source.
    """
    try:
        import shop_campaign_cost
        m = shop_campaign_cost.daily_spend_map()
        if m is None:
            return {"available": False, "note": "ShopifyQL unavailable (check API version/scope)"}
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        recent = {d: v for d, v in sorted(m.items()) if d >= cutoff}
        return {
            "available": True,
            "api_version": shop_campaign_cost._QL_API_VERSION,
            "total": round(sum(recent.values()), 2),
            "days": recent,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.get("/debug/shop-bills")
async def debug_shop_bills(days: int = 60, raw: bool = False):
    """
    FALLBACK source. Scan Gmail for Shopify billing emails and show parsed
    Shop Campaigns charges + the effective rate. ?raw=true includes snippets.
    """
    try:
        import shop_bills
        from master_report_mirai import _shop_effective_rate, _SHOP_RATE_CACHE
        state = shop_bills.scan_bills(days=days, keep_raw=raw, force=True)
        bills = list((state.get("bills") or {}).values())
        bills.sort(key=lambda b: b.get("date") or "", reverse=True)
        # bust the rate cache so the next summary refresh uses fresh bill data
        _SHOP_RATE_CACHE["ts"] = 0.0
        rate = _shop_effective_rate(_safe_shop_tz())
        return {
            "count": len(bills),
            "billed_total_30d": shop_bills.billed_total(30, state),
            "effective_rate": rate,
            "bills": bills,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.get("/debug/psp-fees")
async def debug_psp_fees(day: str = None):
    """
    Debug endpoint to test PSP fee fetch.
    Usage: GET /debug/psp-fees?day=2026-02-08
    """
    from datetime import date, timedelta
    from psp_fee import get_psp_fees_daily

    shop_tz = _safe_shop_tz()

    if day:
        test_day = datetime.strptime(day, "%Y-%m-%d").date()
    else:
        test_day = datetime.now(pytz.timezone(shop_tz)).date()

    result = {
        "test_day": test_day.isoformat(),
        "shop_tz": shop_tz,
        "psp_fees_eur": {},
        "error": None,
    }

    try:
        # Fetch PSP fees for the day
        end_date = test_day + timedelta(days=1)
        daily_fees = get_psp_fees_daily(test_day, end_date)
        result["psp_fees_eur"] = {k.isoformat(): v for k, v in daily_fees.items()}
        result["total_eur"] = sum(daily_fees.values())
    except Exception as e:
        result["error"] = str(e)
        import traceback
        result["traceback"] = traceback.format_exc()

    return result


# ---------- Debug endpoint for Telegram Summary ----------

@app.get("/debug/telegram-summary")
async def debug_telegram_summary():
    """
    Debug endpoint to check Telegram summary state.
    """
    import json
    from pathlib import Path

    state_file = Path(os.getenv("SUMMARY_STATE_FILE", "/app/outputs/.telegram_summary_state.json"))

    result = {
        "state_file": str(state_file),
        "state_exists": state_file.exists(),
        "state_content": None,
        "env_vars": {
            "TELEGRAM_BOT_TOKEN": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "TELEGRAM_SUMMARY_CHAT_ID": os.getenv("TELEGRAM_SUMMARY_CHAT_ID"),
            "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID"),
        }
    }

    if state_file.exists():
        try:
            result["state_content"] = json.loads(state_file.read_text())
        except Exception as e:
            result["state_error"] = str(e)

    return result


@app.post("/debug/set-summary-message-id")
async def set_summary_message_id(message_id: int, chat_id: str = None):
    """
    Manually set the Telegram summary message_id to edit instead of creating new.
    Usage: POST /debug/set-summary-message-id?message_id=950&chat_id=-1003181220966
    """
    import json
    from pathlib import Path

    state_file = Path(os.getenv("SUMMARY_STATE_FILE", "/app/outputs/.telegram_summary_state.json"))
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Use provided chat_id or fall back to env var
    if not chat_id:
        chat_id = os.getenv("TELEGRAM_SUMMARY_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

    if not chat_id:
        return {"ok": False, "error": "No chat_id provided and no TELEGRAM_CHAT_ID in env"}

    state = {"DAILY": {"message_id": message_id, "chat_id": chat_id}}

    try:
        state_file.write_text(json.dumps(state, indent=2))
        return {"ok": True, "state": state, "file": str(state_file)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------- Debug endpoint for Google Ads ----------

@app.get("/debug/google-ads")
async def debug_google_ads(day: str = None, clear_cache: bool = False):
    """
    Debug endpoint to test Google Ads spend fetch and see detailed logs.
    Usage: GET /debug/google-ads?day=2026-01-05&clear_cache=true
    """
    import io
    import sys
    from contextlib import redirect_stdout, redirect_stderr

    # Capture all print statements
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    shop_tz = _safe_shop_tz()
    test_day = day or datetime.now(pytz.timezone(shop_tz)).date().isoformat()

    result = {
        "test_day": test_day,
        "shop_tz": shop_tz,
        "cache_cleared": False,
        "google_spend": 0.0,
        "error": None,
        "logs": [],
    }

    try:
        # Clear cache if requested
        if clear_cache:
            from master_report_mirai import _GADS_CACHE
            cache_size = len(_GADS_CACHE)
            _GADS_CACHE.clear()
            result["cache_cleared"] = True
            result["cache_entries_cleared"] = cache_size

        # Capture output
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            spend = _google_spend_usd(test_day, shop_tz)
            result["google_spend"] = spend

        # Get captured logs
        stdout_val = stdout_capture.getvalue()
        stderr_val = stderr_capture.getvalue()

        if stdout_val:
            result["logs"].extend(stdout_val.strip().split('\n'))
        if stderr_val:
            result["logs"].extend(["STDERR: " + line for line in stderr_val.strip().split('\n')])

    except Exception as e:
        result["error"] = str(e)
        result["error_type"] = type(e).__name__
        import traceback
        result["traceback"] = traceback.format_exc()

    return result


@app.get("/debug/cache-status")
async def debug_cache_status():
    """
    Show current cache status for Google Ads spend.
    """
    from master_report_mirai import _GADS_CACHE

    cache_info = []
    for key, value in _GADS_CACHE.items():
        if isinstance(value, tuple):
            spend, timestamp = value
            age_minutes = (datetime.now() - timestamp).total_seconds() / 60
            cache_info.append({
                "key": key,
                "spend": f"${spend:.2f}",
                "age_minutes": round(age_minutes, 1),
                "cached_at": timestamp.isoformat(),
            })
        else:
            cache_info.append({
                "key": key,
                "value": value,
                "format": "old (float)"
            })

    return {
        "cache_entries": len(_GADS_CACHE),
        "cache_ttl_minutes": int(os.getenv("GOOGLE_ADS_CACHE_TTL_MINUTES", "30")),
        "entries": cache_info,
    }


# ---------- Local dev entrypoint ----------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
