# server.py
from __future__ import annotations

from datetime import datetime, timedelta, date
from calendar import monthrange
import os
import json
import jwt
import httpx
from typing import List, Optional, Dict, Any

import pytz
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator

# Core orchestration - imported lazily inside endpoints to avoid startup failures
# from master_report_mirai import build_month_rows, _google_spend_usd
# from meta_client import fetch_meta_insights_day

# ==================== AUTH CONFIGURATION ====================

# JWT Settings
JWT_SECRET = os.getenv("JWT_SECRET", "mirai-dashboard-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 1 week

# Google OAuth Settings
GOOGLE_CLIENT_ID = os.getenv("VITE_GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
FIRST_ADMIN_EMAIL = os.getenv("FIRST_ADMIN_EMAIL", "kapoosha@gmail.com")
ALLOWED_EMAILS = [e.strip() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()]
if FIRST_ADMIN_EMAIL and FIRST_ADMIN_EMAIL not in ALLOWED_EMAILS:
    ALLOWED_EMAILS.append(FIRST_ADMIN_EMAIL)

security = HTTPBearer(auto_error=False)

# Database service (with graceful fallback)
try:
    from database.service import db_service
    DB_SERVICE_AVAILABLE = True
    print("✅ Database service imported successfully")
except ImportError as e:
    DB_SERVICE_AVAILABLE = False
    db_service = None
    print(f"⚠️ Database service not available: {e}")


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


# Pricing-specific models
class PriceUpdate(BaseModel):
    """Single price update"""
    variant_id: str
    new_price: float
    new_compare_at: Optional[float] = None
    compare_at_policy: str = "D"  # B, D, or Manual
    new_cogs: Optional[float] = None
    notes: str = ""
    item: str = ""
    current_price: float = 0.0


class ExecuteUpdatesRequest(BaseModel):
    """Request body for executing price updates"""
    updates: List[PriceUpdate]


class ProductAction(BaseModel):
    """Single product action (add or delete)"""
    action: str  # "add" or "delete"
    variant_id: str = ""
    title: str = ""
    price: float = 0.0
    sku: str = ""
    inventory: int = 0


class ProductActionsRequest(BaseModel):
    """Request body for product actions"""
    actions: List[ProductAction]


class CompetitorPriceCheckRequest(BaseModel):
    """Request body for competitor price check"""
    variant_ids: List[str]


class KorealySyncRequest(BaseModel):
    """Request body for syncing Korealy COGS to Shopify"""
    updates: List[Dict[str, Any]]  # List of {variant_id, new_cogs}


# ---------- FastAPI app ----------

app = FastAPI(title="Mirai Report API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",  # Allow all origins
        "https://mirai-managment-dashboard.onrender.com",
        "http://localhost:3001",
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== AUTH HELPERS ====================

class GoogleAuthRequest(BaseModel):
    token: str  # Google ID token from frontend


class AddUserRequest(BaseModel):
    email: str
    is_admin: bool = False


async def verify_google_token(token: str) -> dict:
    """Verify Google ID token and return user info"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={token}"
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid Google token")

            data = response.json()

            if GOOGLE_CLIENT_ID and data.get("aud") != GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=401, detail="Token not for this application")

            return {
                "email": data.get("email"),
                "name": data.get("name"),
                "picture": data.get("picture"),
                "google_id": data.get("sub")
            }
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify token: {e}")


def create_jwt_token(user_data: dict) -> str:
    """Create JWT token for authenticated user"""
    payload = {
        "sub": user_data["email"],
        "name": user_data.get("name", ""),
        "picture": user_data.get("picture", ""),
        "is_admin": user_data.get("is_admin", False),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    """Get current user from JWT token"""
    if not credentials:
        return None

    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "email": payload.get("sub"),
            "name": payload.get("name"),
            "picture": payload.get("picture"),
            "is_admin": payload.get("is_admin", False)
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_auth(user: dict = Depends(get_current_user)) -> dict:
    """Require authentication"""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(user: dict = Depends(require_auth)) -> dict:
    """Require admin role"""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


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
    # Lazy import to avoid startup failures
    from master_report_mirai import build_month_rows

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


# ==================== AUTH ENDPOINTS ====================

@app.post("/auth/google")
async def google_login(req: GoogleAuthRequest):
    """Login with Google ID token. Returns JWT token if user is allowed."""
    try:
        google_user = await verify_google_token(req.token)
        email = google_user["email"]

        print(f"🔐 Login attempt: {email}")

        if DB_SERVICE_AVAILABLE:
            from database.connection import get_db
            from database.models import User
            from sqlalchemy import select, func

            async with get_db() as db:
                result = await db.execute(select(User).where(func.lower(User.email) == email.lower().strip()))
                user = result.scalar_one_or_none()

                if not user:
                    user_count = await db.execute(select(User))
                    is_first_user = not user_count.scalars().all()
                    is_first_admin = email.strip().lower() == FIRST_ADMIN_EMAIL.strip().lower()
                    is_allowed = email.strip() in ALLOWED_EMAILS or is_first_user or is_first_admin

                    if not is_allowed:
                        print(f"❌ Email not allowed: {email}")
                        raise HTTPException(status_code=403, detail="Email not authorized. Contact admin to be added.")

                    make_admin = is_first_user or is_first_admin
                    user = User(
                        email=email,
                        name=google_user.get("name"),
                        picture=google_user.get("picture"),
                        google_id=google_user.get("google_id"),
                        is_admin=make_admin,
                        is_active=True
                    )
                    db.add(user)
                    await db.commit()
                    await db.refresh(user)
                    print(f"✅ Created new user: {email} (admin={make_admin})")
                else:
                    if not user.is_active:
                        raise HTTPException(status_code=403, detail="Account is disabled")

                    user.last_login = datetime.utcnow()
                    user.name = google_user.get("name") or user.name
                    user.picture = google_user.get("picture") or user.picture
                    await db.commit()
                    print(f"✅ User logged in: {email}")

                token = create_jwt_token({
                    "email": user.email,
                    "name": user.name,
                    "picture": user.picture,
                    "is_admin": user.is_admin
                })

                return {
                    "success": True,
                    "token": token,
                    "user": {
                        "email": user.email,
                        "name": user.name,
                        "picture": user.picture,
                        "is_admin": user.is_admin
                    }
                }
        else:
            if email.strip() not in [e.strip() for e in ALLOWED_EMAILS if e.strip()]:
                raise HTTPException(status_code=403, detail="Email not authorized")

            token = create_jwt_token({
                "email": email,
                "name": google_user.get("name"),
                "picture": google_user.get("picture"),
                "is_admin": True
            })

            return {
                "success": True,
                "token": token,
                "user": {
                    "email": email,
                    "name": google_user.get("name"),
                    "picture": google_user.get("picture"),
                    "is_admin": True
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Auth error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/auth/me")
async def get_me(user: dict = Depends(require_auth)):
    """Get current user info"""
    return {"user": user}


@app.get("/auth/users")
async def list_users(user: dict = Depends(require_admin)):
    """List all users (admin only)"""
    if not DB_SERVICE_AVAILABLE:
        return {"users": [], "message": "Database not available"}

    from database.connection import get_db
    from database.models import User
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(select(User).order_by(User.created_at.desc()))
        users = result.scalars().all()

        return {
            "users": [
                {
                    "id": u.id,
                    "email": u.email,
                    "name": u.name,
                    "picture": u.picture,
                    "is_active": u.is_active,
                    "is_admin": u.is_admin,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "last_login": u.last_login.isoformat() if u.last_login else None
                }
                for u in users
            ]
        }


@app.post("/auth/users")
async def add_user(req: AddUserRequest, user: dict = Depends(require_admin)):
    """Add a new allowed user (admin only)"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import User
    from sqlalchemy import select, func

    email_clean = req.email.strip().lower()

    async with get_db() as db:
        result = await db.execute(select(User).where(func.lower(User.email) == email_clean))
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=400, detail="User already exists")

        new_user = User(
            email=email_clean,
            is_admin=req.is_admin,
            is_active=True
        )
        db.add(new_user)
        await db.commit()

        print(f"✅ Added new user: {email_clean} (admin={req.is_admin})")

        return {"success": True, "message": f"User {email_clean} added successfully"}


@app.delete("/auth/users/{user_id}")
async def delete_user(user_id: int, user: dict = Depends(require_admin)):
    """Delete a user (admin only)"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import User
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        target_user = result.scalar_one_or_none()

        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        if target_user.email == user["email"]:
            raise HTTPException(status_code=400, detail="Cannot delete yourself")

        await db.delete(target_user)
        await db.commit()

        return {"success": True, "message": f"User {target_user.email} deleted"}


@app.put("/auth/users/{user_id}/toggle-admin")
async def toggle_admin(user_id: int, user: dict = Depends(require_admin)):
    """Toggle admin status for a user (admin only)"""
    if not DB_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")

    from database.connection import get_db
    from database.models import User
    from sqlalchemy import select

    async with get_db() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        target_user = result.scalar_one_or_none()

        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        if target_user.email == user["email"]:
            raise HTTPException(status_code=400, detail="Cannot modify your own admin status")

        target_user.is_admin = not target_user.is_admin
        await db.commit()

        return {"success": True, "is_admin": target_user.is_admin}


# ---------- NEW: Force backfill today orders (sends per-order messages) ----------

@app.post("/force-backfill-today")
async def force_backfill_today():
    """
    One-time operation:
    - Fetch all orders from "today" (store timezone)
    - Send per-order Telegram messages
    - Must be dedup-safe (so re-running doesn't spam)

    This endpoint expects monitor_orders.py to expose:
        backfill_today_and_send() -> int

    It should return number of order alerts sent.
    """
    try:
        # Import here (not at module import time) so server boot never fails
        # even if monitor file has optional deps or heavy imports.
        from monitor_orders import backfill_today_and_send  # type: ignore

        sent_count = backfill_today_and_send()
        return {"ok": True, "sent": int(sent_count)}

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
                    "shipping_cost": k.shipping_cost,
                    "google_spend": k.google_spend,
                    "meta_spend": k.meta_spend,
                    "total_spend": k.total_spend,
                    "google_pur": k.google_pur,
                    "meta_pur": k.meta_pur,
                    "google_cpa": k.google_cpa,
                    "meta_cpa": k.meta_cpa,
                    "general_cpa": k.general_cpa,
                    "psp_usd": k.psp_usd,
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


# ---------- Debug endpoint: show orders for a specific day ----------

class DebugDayRequest(BaseModel):
    date: str  # YYYY-MM-DD


@app.post("/debug/day-orders")
async def debug_day_orders(req: DebugDayRequest):
    """
    Debug endpoint to show exactly which orders are counted for a specific day.
    Shows order names and their timestamps in both UTC and local (Nicosia) time.
    """
    try:
        from master_report_mirai import SHOPIFY_STORES, _parse_dt
        from shopify_client import fetch_orders_created_between_for_store

        shop_tz = _safe_shop_tz()
        tz = pytz.timezone(shop_tz)

        day = datetime.strptime(req.date, "%Y-%m-%d").date()
        start_local = tz.localize(datetime.combine(day, datetime.min.time()))
        end_local = tz.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))

        # Convert to UTC for display
        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = end_local.astimezone(pytz.UTC)

        orders_debug = []
        all_orders = []

        for store in SHOPIFY_STORES:
            domain = store["domain"]
            token = store["access_token"]

            # Fetch orders using the same method as the report
            created = fetch_orders_created_between_for_store(
                domain, token, start_local.isoformat(), end_local.isoformat(), exclude_cancelled=False
            )
            all_orders.extend(created)

        # Process each order
        in_window_count = 0
        for o in all_orders:
            dt = _parse_dt(o.get("createdAt"))
            if not dt:
                continue
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            dt_local = dt.astimezone(tz)

            in_window = start_local <= dt_local < end_local
            if in_window:
                in_window_count += 1

            is_cancelled = bool(o.get("cancelledAt"))

            orders_debug.append({
                "order_name": o.get("name"),
                "created_at_utc": o.get("createdAt"),
                "created_at_local": dt_local.isoformat(),
                "in_window": in_window,
                "is_cancelled": is_cancelled,
                "counted": in_window and not is_cancelled,
                "total_price": o.get("totalPriceSet", {}).get("shopMoney", {}).get("amount"),
            })

        # Sort by created time
        orders_debug.sort(key=lambda x: x["created_at_utc"] or "")

        return {
            "date": req.date,
            "timezone": shop_tz,
            "window": {
                "start_local": start_local.isoformat(),
                "end_local": end_local.isoformat(),
                "start_utc": start_utc.isoformat(),
                "end_utc": end_utc.isoformat(),
            },
            "orders_fetched": len(all_orders),
            "orders_in_window": in_window_count,
            "orders_counted": sum(1 for o in orders_debug if o["counted"]),
            "orders": orders_debug
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


# ---------- Supporting endpoint: raw ad spend only ----------

@app.post("/ad-spend")
async def ad_spend(req: DateRangeRequest):
    """
    Simple helper to fetch ad spend for a single day / short range.
    Still used by some tools; dashboard can rely on /daily-report instead.
    """
    try:
        # Lazy imports to avoid startup failures
        from master_report_mirai import _google_spend_usd
        from meta_client import fetch_meta_insights_day

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
        # Lazy import
        from master_report_mirai import _google_spend_usd, _GADS_CACHE

        # Clear cache if requested
        if clear_cache:
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


# ---------- Pricing Endpoints ----------

# GET endpoints for data fetching
@app.get("/pricing/markets")
async def get_markets():
    """Get available markets"""
    try:
        from pricing_logic import get_available_markets
        markets = get_available_markets()
        return {"data": markets, "markets": markets}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/countries")
async def get_countries():
    """Get available countries for target pricing"""
    try:
        from pricing_logic import get_available_countries
        countries = get_available_countries()
        return {"data": countries, "countries": countries}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/items")
async def get_items(market: Optional[str] = None, use_cache: bool = True):
    """
    Get product variants from Shopify
    Optional market filter
    """
    try:
        from pricing_logic import fetch_items
        items = fetch_items(market_filter=market, use_cache=use_cache)
        return {"data": items, "items": items}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/price-updates")
async def get_price_updates():
    """Get pending price updates"""
    try:
        from pricing_logic import fetch_price_updates
        updates = fetch_price_updates()
        return {"data": updates, "updates": updates}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/update-log")
async def get_update_log(limit: Optional[int] = None):
    """Get price update history"""
    try:
        from pricing_logic import fetch_update_log
        log = fetch_update_log(limit=limit)
        return {"data": log, "log": log}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pricing/target-prices")
async def get_target_prices(country: str = "US", use_cache: bool = True):
    """
    Calculate target prices based on Shopify data
    Returns calculated metrics for each variant
    """
    try:
        from pricing_logic import fetch_target_prices
        target_prices = fetch_target_prices(country_filter=country, use_cache=use_cache)
        return {"data": target_prices, "target_prices": target_prices}  # Support both formats
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Could not import pricing_logic: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# POST endpoints for actions
@app.post("/pricing/execute-updates")
async def execute_price_updates(req: ExecuteUpdatesRequest):
    """
    Execute price updates to Shopify

    Updates product variant prices based on the provided updates.
    Logs all changes to Google Sheets UpdatesLog.
    """
    try:
        # Import here to avoid circular dependencies
        from pricing_execution import execute_updates

        result = execute_updates(req.updates)

        return {
            "success": True,
            "updated_count": result["updated_count"],
            "failed_count": result["failed_count"],
            "message": result["message"],
            "details": result.get("details", [])
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import pricing_execution module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute price updates: {str(e)}"
        )


@app.post("/pricing/product-actions")
async def execute_product_actions(req: ProductActionsRequest):
    """
    Add or delete products from Shopify

    Executes batch product operations (add new products or delete existing ones).
    """
    try:
        # Import here to avoid circular dependencies
        from pricing_execution import execute_product_actions

        result = execute_product_actions(req.actions)

        return {
            "success": True,
            "added_count": result["added_count"],
            "deleted_count": result["deleted_count"],
            "failed_count": result["failed_count"],
            "message": result["message"],
            "details": result.get("details", [])
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import pricing_execution module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute product actions: {str(e)}"
        )


@app.post("/pricing/check-competitor-prices")
async def check_competitor_prices(req: CompetitorPriceCheckRequest):
    """
    Check competitor prices for specified variant IDs via SerpAPI

    This endpoint triggers a price scan using the smart filtering logic:
    - Trusted sellers only (excludes P2P marketplaces)
    - Outlier removal (median-based filtering)
    - Returns low/avg/high prices
    """
    try:
        # Import here to avoid circular dependencies
        from pricing_execution import check_competitor_prices

        result = check_competitor_prices(req.variant_ids)

        return {
            "success": True,
            "scanned_count": result["scanned_count"],
            "results": result["results"],
            "message": result["message"]
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import pricing_execution module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check competitor prices: {str(e)}"
        )


@app.get("/pricing/korealy-reconciliation")
async def get_korealy_reconciliation():
    """
    Run Korealy reconciliation

    Fetches Korealy supplier prices from Google Sheets,
    compares with Shopify COGS, and returns mismatch analysis.
    """
    try:
        from korealy_reconciliation import run_reconciliation

        result = run_reconciliation()

        return {
            "success": result["success"],
            "results": result["results"],
            "stats": result["stats"],
            "message": result["message"]
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import korealy_reconciliation module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run Korealy reconciliation: {str(e)}"
        )


@app.post("/pricing/korealy-sync")
async def sync_korealy_to_shopify(req: KorealySyncRequest):
    """
    Sync selected Korealy COGS to Shopify

    Updates Shopify COGS with Korealy supplier prices for selected products.
    """
    try:
        from korealy_reconciliation import sync_korealy_to_shopify

        # Build variant_ids list and cogs_map from updates
        variant_ids = []
        korealy_cogs_map = {}

        for update in req.updates:
            variant_id = update.get("variant_id")
            new_cogs = update.get("new_cogs")

            if variant_id and new_cogs is not None:
                variant_ids.append(str(variant_id))
                korealy_cogs_map[str(variant_id)] = float(new_cogs)

        result = sync_korealy_to_shopify(variant_ids, korealy_cogs_map)

        return {
            "success": True,
            "updated_count": result["updated_count"],
            "failed_count": result["failed_count"],
            "message": result["message"],
            "details": result.get("details", [])
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not import korealy_reconciliation module: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync Korealy COGS: {str(e)}"
        )


# ---------- Meta Ads Decision Engine ----------

# Lazy import: from meta_decision_engine import create_engine, EngineConfig

class MetaAdsConfigRequest(BaseModel):
    """Configuration for decision engine"""
    target_cpa: Optional[float] = 18.50
    max_cpa: Optional[float] = 25.0
    min_ctr: Optional[float] = 0.8
    auto_pause_underperformers: Optional[bool] = False
    auto_scale_winners: Optional[bool] = False


# Helper to get marketing token
def _get_marketing_token():
    """Get Meta access token for marketing operations"""
    return os.getenv("META_ACCESS_TOKEN")


@app.get("/meta-ads/status")
async def meta_ads_quick_status(date_range: str = "today"):
    """
    Get quick campaign status overview

    Returns spend, clicks, CTR, conversions, CPA, health score
    """
    try:
        from meta_decision_engine import create_engine

        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        status = engine.get_quick_status(date_range)
        return status

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@app.get("/meta-ads/analysis")
async def meta_ads_full_analysis(date_range: str = "today", campaign_id: str = None):
    """
    Run full campaign analysis with AI recommendations

    Returns metrics, decisions, alerts, and recommendations
    """
    try:
        from meta_decision_engine import create_engine

        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        report = engine.analyze_campaign(campaign_id, date_range)
        return report

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze: {str(e)}")


@app.get("/meta-ads/diagnose")
async def meta_ads_diagnose_cpm(date_range: str = "last_7d"):
    """
    Diagnose why CPM is high and get actionable recommendations

    Returns:
    - Quality/relevance scores for each ad
    - Audience analysis
    - Specific issues identified
    - Actionable recommendations
    """
    try:
        from meta_decision_engine import create_engine

        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        diagnosis = engine.diagnose_high_cpm(date_range)
        return diagnosis

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to diagnose: {str(e)}")


@app.post("/meta-ads/setup-test-adsets")
async def meta_ads_setup_tests(campaign_id: str, source_adset_id: str, pixel_id: str = None):
    """
    Create test ad sets for CPM optimization:
    1. Advantage+ Audience (US broad)
    2. UK Test (lower CPM geo)

    Both ad sets will:
    - Copy all ads from the source ad set
    - Be created in PAUSED state for review
    - Have Advantage+ targeting enabled

    Args:
        campaign_id: The campaign ID to add ad sets to
        source_adset_id: Existing ad set to copy ads from
        pixel_id: Optional pixel ID (auto-detected from source if not provided)
    """
    try:
        from meta_decision_engine import create_engine

        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        results = engine.setup_test_adsets(campaign_id, source_adset_id, pixel_id)

        return {
            "success": len(results.get("errors", [])) == 0,
            "message": "Test ad sets created (PAUSED). Review and activate in Ads Manager.",
            "results": results,
            "next_steps": [
                "1. Review the new ad sets in Meta Ads Manager",
                "2. Verify targeting looks correct",
                "3. Activate both ad sets",
                "4. Monitor for 3-5 days",
                "5. Compare CPM: Current vs Advantage+ vs UK"
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to setup: {str(e)}")


@app.post("/meta-ads/setup-uk-test")
async def meta_ads_setup_uk_only():
    """
    ONE-CLICK: Create UK test ad set with full Advantage+

    Automatically:
    1. Finds the active campaign
    2. Finds an ad set with ads to copy from
    3. Creates UK Women 21-60 ad set with Advantage+ everything
    4. Copies all ads with Advantage+ Creative enabled

    Uses campaign budget (CBO) - no additional spend, shares €20/day
    """
    try:
        from meta_decision_engine import create_engine
        import json

        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)

        # Step 1: Find active campaign
        campaigns = engine.get_campaigns()
        active_campaign = None
        for c in campaigns:
            if c.get("effective_status") == "ACTIVE":
                active_campaign = c
                break

        if not active_campaign:
            # Try any campaign with "Mirai" or "Korean" in name
            for c in campaigns:
                if "mirai" in c.get("name", "").lower() or "korean" in c.get("name", "").lower():
                    active_campaign = c
                    break

        if not active_campaign:
            return {
                "success": False,
                "error": "No active campaign found",
                "campaigns": [{"id": c.get("id"), "name": c.get("name"), "status": c.get("effective_status")} for c in campaigns]
            }

        campaign_id = active_campaign["id"]
        print(f"[SETUP] Using campaign: {active_campaign.get('name')} ({campaign_id})")

        # Step 2: Find ad set with ads to copy from
        adsets = engine.get_adsets(campaign_id)
        source_adset = None
        source_ads = []

        for adset in adsets:
            ads = engine.get_ads_with_creatives(adset["id"])
            if ads:
                source_adset = adset
                source_ads = ads
                break

        if not source_adset:
            return {
                "success": False,
                "error": "No ad set with ads found to copy from",
                "adsets": [{"id": a.get("id"), "name": a.get("name")} for a in adsets]
            }

        print(f"[SETUP] Copying from ad set: {source_adset.get('name')} ({len(source_ads)} ads)")

        # Step 3: Get pixel ID from source
        adset_details = engine._request(f"/{source_adset['id']}?fields=promoted_object")
        promoted_obj = adset_details.get("promoted_object", {})
        pixel_id = promoted_obj.get("pixel_id")
        promoted_object = {"pixel_id": pixel_id} if pixel_id else None

        # Step 4: Create UK test ad set with FULL Advantage+
        uk_targeting = {
            "age_min": 21,
            "age_max": 60,
            "genders": [1],  # Women
            "geo_locations": {
                "countries": ["GB"],
                "location_types": ["home"]
            }
            # NO interests = Advantage+ Audience will expand
        }

        uk_result = engine.create_adset_cbo(
            campaign_id=campaign_id,
            name="TEST - UK Women 21-60 Advantage+",
            targeting=uk_targeting,
            optimization_goal="OFFSITE_CONVERSIONS",
            status="PAUSED",  # Start paused for review
            advantage_audience=True,
            promoted_object=promoted_object,
            url_tags="utm_source=meta&utm_medium=paid&utm_campaign=mirai_quiz&utm_content=uk_advplus"
        )

        ads_created = []
        if uk_result.get("success"):
            # Step 5: Copy ads with Advantage+ Creative
            ads_created = engine.duplicate_ads_to_adset(
                source_adset_id=source_adset["id"],
                target_adset_id=uk_result["id"],
                name_suffix="(UK Adv+)",
                status="ACTIVE",
                use_advantage_creative=True
            )

        return {
            "success": uk_result.get("success", False),
            "message": "UK test ad set created with FULL Advantage+" if uk_result.get("success") else "Failed to create",
            "campaign": {
                "id": campaign_id,
                "name": active_campaign.get("name")
            },
            "source_adset": {
                "id": source_adset["id"],
                "name": source_adset.get("name"),
                "ads_count": len(source_ads)
            },
            "uk_adset": uk_result,
            "ads_created": ads_created,
            "advantage_plus_features": [
                "✅ Advantage+ Audience (targeting expansion)",
                "✅ Advantage+ Placements (auto placements)",
                "✅ Advantage+ Creative (image/text optimization)"
            ],
            "next_steps": [
                "1. Go to Meta Ads Manager",
                "2. Find 'TEST - UK Women 21-60 Advantage+'",
                "3. Review and ACTIVATE the ad set",
                "4. Monitor CPM for 2-3 days",
                "5. Compare: Current €80 CPM vs UK test"
            ]
        }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@app.get("/meta-ads/list-adsets")
async def meta_ads_list_adsets(campaign_id: str = None):
    """
    List all ad sets with their IDs for use with setup-test-adsets

    Returns ad set id, name, status, and daily budget
    """
    try:
        from meta_decision_engine import create_engine

        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        adsets = engine.get_adsets(campaign_id)

        return {
            "adsets": [
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "status": a.get("effective_status"),
                    "daily_budget": int(a.get("daily_budget", 0)) / 100 if a.get("daily_budget") else None,
                    "campaign_id": a.get("campaign_id")
                }
                for a in adsets
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list: {str(e)}")


@app.get("/meta-ads/decisions")
async def meta_ads_get_decisions(date_range: str = "today"):
    """
    Get optimization decisions only

    Returns list of recommended actions (scale, pause, maintain)
    """
    try:
        from meta_decision_engine import create_engine

        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        engine = create_engine(access_token)
        report = engine.analyze_campaign(date_range=date_range)

        return {
            "timestamp": report["timestamp"],
            "health_score": report["health_score"],
            "decisions": report["decisions"],
            "alerts": report["alerts"],
            "recommendations": report["recommendations"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get decisions: {str(e)}")


@app.post("/meta-ads/execute-decision")
async def meta_ads_execute_decision(entity_id: str, action: str):
    """
    Execute a specific decision (pause/activate an ad/adset)

    Args:
        entity_id: The ad/adset/campaign ID
        action: PAUSE or ACTIVE
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        if action not in ["PAUSE", "ACTIVE", "PAUSED"]:
            raise HTTPException(status_code=400, detail="Action must be PAUSE or ACTIVE")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")
        result = client.update_status(entity_id, action.replace("PAUSE", "PAUSED"))

        return {"success": True, "entity_id": entity_id, "new_status": action}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute: {str(e)}")


@app.get("/meta-ads/campaigns")
async def meta_ads_get_campaigns():
    """
    Get all campaigns with their ad sets and ads
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        campaigns = client.get_campaigns()
        result = []

        for campaign in campaigns:
            campaign_data = {
                "id": campaign["id"],
                "name": campaign["name"],
                "status": campaign.get("effective_status"),
                "objective": campaign.get("objective"),
                "adsets": []
            }

            adsets = client.get_adsets(campaign["id"])
            for adset in adsets:
                adset_data = {
                    "id": adset["id"],
                    "name": adset["name"],
                    "status": adset.get("effective_status"),
                    "ads": []
                }

                ads = client.get_ads(adset["id"])
                for ad in ads:
                    adset_data["ads"].append({
                        "id": ad["id"],
                        "name": ad["name"],
                        "status": ad.get("effective_status")
                    })

                campaign_data["adsets"].append(adset_data)

            result.append(campaign_data)

        return {"campaigns": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get campaigns: {str(e)}")


# ---------- Meta Ads Campaign Creation Endpoints ----------

class CreateCampaignRequest(BaseModel):
    """Request body for creating a campaign"""
    name: str
    objective: str = "OUTCOME_SALES"  # OUTCOME_SALES, OUTCOME_LEADS, OUTCOME_AWARENESS
    status: str = "PAUSED"  # Start paused for safety


class CreateAdSetRequest(BaseModel):
    """Request body for creating an ad set"""
    campaign_id: str
    name: str
    daily_budget: int  # In cents (2500 = €25)
    targeting: Dict[str, Any]
    optimization_goal: str = "OFFSITE_CONVERSIONS"
    status: str = "PAUSED"


class CreateAdRequest(BaseModel):
    """Request body for creating an ad"""
    adset_id: str
    creative_id: str
    name: str
    status: str = "PAUSED"


class UpdateBudgetRequest(BaseModel):
    """Request body for updating ad set budget"""
    adset_id: str
    daily_budget: int  # In cents


@app.post("/meta-ads/campaigns/create")
async def meta_ads_create_campaign(req: CreateCampaignRequest):
    """
    Create a new Meta Ads campaign

    Default status is PAUSED for safety - activate manually after review.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        result = client.create_campaign(
            name=req.name,
            objective=req.objective,
            status=req.status
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", str(result["error"])))

        return {
            "success": True,
            "campaign_id": result.get("id"),
            "name": req.name,
            "status": req.status
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create campaign: {str(e)}")


@app.post("/meta-ads/adsets/create")
async def meta_ads_create_adset(req: CreateAdSetRequest):
    """
    Create a new ad set within a campaign

    Targeting should include: age_min, age_max, genders, geo_locations, etc.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        result = client.create_adset(
            campaign_id=req.campaign_id,
            name=req.name,
            daily_budget=req.daily_budget,
            targeting=req.targeting,
            optimization_goal=req.optimization_goal,
            status=req.status
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", str(result["error"])))

        return {
            "success": True,
            "adset_id": result.get("id"),
            "name": req.name,
            "daily_budget": req.daily_budget,
            "status": req.status
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ad set: {str(e)}")


@app.post("/meta-ads/ads/create")
async def meta_ads_create_ad(req: CreateAdRequest):
    """
    Create a new ad within an ad set

    Requires an existing creative_id from the account.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        result = client.create_ad(
            adset_id=req.adset_id,
            creative_id=req.creative_id,
            name=req.name,
            status=req.status
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", str(result["error"])))

        return {
            "success": True,
            "ad_id": result.get("id"),
            "name": req.name,
            "status": req.status
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ad: {str(e)}")


@app.get("/meta-ads/creatives")
async def meta_ads_get_creatives(limit: int = 50):
    """
    Get available ad creatives from the account

    These can be used when creating new ads.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        creatives = client.get_creatives(limit=limit)

        return {
            "success": True,
            "count": len(creatives),
            "creatives": creatives
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get creatives: {str(e)}")


@app.get("/meta-ads/interests")
async def meta_ads_search_interests(q: str, limit: int = 20):
    """
    Search for targeting interests by keyword

    Use these interest IDs in ad set targeting.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        interests = client.get_targeting_interests(query=q, limit=limit)

        return {
            "success": True,
            "query": q,
            "count": len(interests),
            "interests": interests
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search interests: {str(e)}")


@app.get("/meta-ads/audiences")
async def meta_ads_get_audiences(limit: int = 50):
    """
    Get custom audiences (lookalikes, website visitors, etc.)

    These can be used for ad set targeting.
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        audiences = client.get_custom_audiences(limit=limit)

        return {
            "success": True,
            "count": len(audiences),
            "audiences": audiences
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get audiences: {str(e)}")


@app.post("/meta-ads/budget")
async def meta_ads_update_budget(req: UpdateBudgetRequest):
    """
    Update an ad set's daily budget

    Budget is in cents (e.g., 2500 = €25)
    """
    try:
        access_token = _get_marketing_token()
        if not access_token:
            raise HTTPException(status_code=500, detail="META_ACCESS_TOKEN not configured")

        from meta_decision_engine import MetaAdsClient
        client = MetaAdsClient(access_token, "668790152408430")

        result = client.update_budget(req.adset_id, req.daily_budget)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", str(result["error"])))

        return {
            "success": True,
            "adset_id": req.adset_id,
            "new_daily_budget": req.daily_budget
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update budget: {str(e)}")


@app.get("/meta-ads/targeting-presets")
async def meta_ads_get_targeting_presets():
    """
    Get pre-built targeting presets for common use cases
    """
    from meta_decision_engine import MetaAdsClient

    return {
        "presets": [
            {
                "name": "Mirai Skincare - Women US",
                "description": "Women 21-45 in US interested in skincare/beauty",
                "targeting": MetaAdsClient.build_skincare_targeting_preset()
            },
            {
                "name": "Broad - Women US 25-45",
                "description": "Broad targeting for women in US",
                "targeting": MetaAdsClient.build_targeting(
                    age_min=25,
                    age_max=45,
                    genders=[1],
                    countries=["US"]
                )
            },
            {
                "name": "All Genders US 21-55",
                "description": "Wide audience in US",
                "targeting": MetaAdsClient.build_targeting(
                    age_min=21,
                    age_max=55,
                    genders=[1, 2],
                    countries=["US"]
                )
            }
        ]
    }


# ============================================================
# BLOG CONTENT GENERATION ENDPOINTS
# ============================================================

from pydantic import BaseModel as PydanticBaseModel


class BlogGenerateRequest(PydanticBaseModel):
    category: str
    topic: str
    keywords: List[str]
    word_count: int = 1000


class BlogRegenerateRequest(PydanticBaseModel):
    hints: str
    keep_keywords: bool = True


class BlogUpdateRequest(PydanticBaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    meta_description: Optional[str] = None
    excerpt: Optional[str] = None
    suggested_tags: Optional[List[str]] = None


class BlogApproveRequest(PydanticBaseModel):
    blog_id: str
    publish_immediately: bool = True


@app.get("/blog/categories")
async def blog_get_categories():
    """Get all blog categories with their style guides and example topics"""
    from blog_service import BLOG_CATEGORIES
    return {"categories": BLOG_CATEGORIES}


@app.get("/blog/seo-keywords/{category}")
async def blog_get_seo_keywords(category: str):
    """Get suggested SEO keywords for a category"""
    from blog_service import BlogGenerator
    keywords = BlogGenerator.get_seo_keywords(category)
    if not keywords:
        raise HTTPException(status_code=404, detail=f"Category not found: {category}")
    return {"category": category, "keywords": keywords}


@app.get("/blog/drafts")
async def blog_get_drafts(status: Optional[str] = None):
    """Get all draft articles, optionally filtered by status"""
    try:
        from blog_service import BlogStorage
        from dataclasses import asdict

        storage = BlogStorage()
        drafts = storage.get_all_drafts(status)

        return {
            "drafts": [asdict(d) for d in drafts],
            "count": len(drafts)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get drafts: {str(e)}")


@app.get("/blog/draft/{draft_id}")
async def blog_get_draft(draft_id: str):
    """Get a single draft by ID"""
    try:
        from blog_service import BlogStorage
        from dataclasses import asdict

        storage = BlogStorage()
        draft = storage.get_draft(draft_id)

        if not draft:
            raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")

        return asdict(draft)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get draft: {str(e)}")


@app.get("/blog/published")
async def blog_get_published():
    """Get all published articles"""
    try:
        from blog_service import BlogStorage
        from dataclasses import asdict

        storage = BlogStorage()
        published = storage.get_all_published()

        return {
            "articles": [asdict(p) for p in published],
            "count": len(published)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get published articles: {str(e)}")


@app.get("/blog/shopify-blogs")
async def blog_get_shopify_blogs():
    """Get list of blogs from Shopify store"""
    try:
        from shopify_client import fetch_blogs
        blogs = fetch_blogs()
        return {"blogs": blogs, "count": len(blogs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Shopify blogs: {str(e)}")


@app.get("/blog/shopify-articles")
async def blog_get_shopify_articles(limit: int = 50):
    """Get articles from Shopify store"""
    try:
        from shopify_client import fetch_all_articles
        articles = fetch_all_articles(limit=limit)
        return {"articles": articles, "count": len(articles)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Shopify articles: {str(e)}")


@app.post("/blog/generate")
async def blog_generate_article(req: BlogGenerateRequest):
    """Generate a new blog article using AI"""
    try:
        from blog_service import create_blog_generator

        generator = create_blog_generator()
        draft = generator.generate_article(
            category=req.category,
            topic=req.topic,
            keywords=req.keywords,
            word_count=req.word_count,
            user_email="dashboard"
        )

        return {
            "success": True,
            "draft_id": draft.id,
            "title": draft.title,
            "excerpt": draft.excerpt,
            "word_count": draft.word_count,
            "category": draft.category
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate article: {str(e)}")


@app.post("/blog/regenerate/{draft_id}")
async def blog_regenerate_article(draft_id: str, req: BlogRegenerateRequest):
    """Regenerate an article with user hints"""
    try:
        from blog_service import create_blog_generator

        generator = create_blog_generator()
        draft = generator.regenerate_article(
            draft_id=draft_id,
            hints=req.hints,
            keep_keywords=req.keep_keywords
        )

        return {
            "success": True,
            "draft_id": draft.id,
            "title": draft.title,
            "excerpt": draft.excerpt,
            "word_count": draft.word_count,
            "regeneration_count": draft.regeneration_count
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate article: {str(e)}")


@app.put("/blog/draft/{draft_id}")
async def blog_update_draft(draft_id: str, req: BlogUpdateRequest):
    """Update a draft's content manually"""
    try:
        from blog_service import create_blog_generator
        from dataclasses import asdict

        generator = create_blog_generator()
        draft = generator.update_draft(
            draft_id=draft_id,
            title=req.title,
            body=req.body,
            meta_description=req.meta_description,
            excerpt=req.excerpt,
            suggested_tags=req.suggested_tags
        )

        return {
            "success": True,
            "draft": asdict(draft)
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update draft: {str(e)}")


@app.post("/blog/approve/{draft_id}")
async def blog_approve_draft(draft_id: str, req: BlogApproveRequest):
    """Approve a draft and publish to Shopify"""
    try:
        from blog_service import create_blog_generator
        from shopify_client import create_article

        generator = create_blog_generator()
        draft = generator.get_draft(draft_id)

        if not draft:
            raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")

        # Create article in Shopify
        result = create_article(
            blog_id=req.blog_id,
            title=draft.title,
            body_html=draft.body,
            author="Mirai Skin Team",
            tags=draft.suggested_tags,
            published=req.publish_immediately,
            summary=draft.excerpt
        )

        # Record as published
        published = generator.record_published(
            draft_id=draft_id,
            shopify_article_id=result["article_id"],
            shopify_url=result["url"] or ""
        )

        return {
            "success": True,
            "shopify_article_id": result["article_id"],
            "url": result["url"],
            "title": draft.title
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish article: {str(e)}")


@app.post("/blog/reject/{draft_id}")
async def blog_reject_draft(draft_id: str):
    """Reject and delete a draft"""
    try:
        from blog_service import BlogStorage

        storage = BlogStorage()
        deleted = storage.delete_draft(draft_id)

        if not deleted:
            raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")

        return {"success": True, "draft_id": draft_id, "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject draft: {str(e)}")


# ---------- SEO Agent Endpoints ----------

@app.get("/blog/seo-agent/suggestions")
async def seo_agent_get_suggestions(force_refresh: bool = False, count: int = 5):
    """
    Get smart content suggestions from the SEO agent.

    The agent analyzes content gaps, trending topics, and seasonal
    opportunities to suggest high-value blog topics.
    """
    try:
        from blog_service import create_seo_agent

        agent = create_seo_agent()

        # If force_refresh or no existing suggestions, generate new ones
        if force_refresh:
            suggestions = agent.generate_smart_suggestions(count=count, force_refresh=True)
        else:
            suggestions = agent.get_suggestions()
            if len(suggestions) < count:
                suggestions = agent.generate_smart_suggestions(count=count)

        return {
            "suggestions": [
                {
                    "id": s.id,
                    "category": s.category,
                    "title": s.title,
                    "topic": s.topic,
                    "keywords": s.keywords,
                    "reason": s.reason,
                    "priority": s.priority,
                    "word_count": s.word_count,
                    "estimated_traffic": s.estimated_traffic,
                    "created_at": s.created_at,
                    "status": s.status
                }
                for s in suggestions
            ],
            "count": len(suggestions)
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get suggestions: {str(e)}")


@app.get("/blog/seo-agent/content-gaps")
async def seo_agent_analyze_gaps():
    """
    Analyze content gaps - identifies what topics are missing
    """
    try:
        from blog_service import SEOAgent

        agent = SEOAgent()
        gaps = agent.analyze_content_gaps()

        return {
            "gaps": gaps,
            "current_month": datetime.now().strftime("%B")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze gaps: {str(e)}")


@app.post("/blog/seo-agent/generate/{suggestion_id}")
async def seo_agent_generate_from_suggestion(suggestion_id: str, user_email: str = "system"):
    """
    Generate a full article draft from a suggestion.

    This creates a ready-to-review draft in the Drafts tab.
    """
    try:
        from blog_service import create_seo_agent
        from dataclasses import asdict

        agent = create_seo_agent()
        draft = agent.generate_from_suggestion(suggestion_id, user_email)

        return {
            "success": True,
            "draft_id": draft.id,
            "title": draft.title,
            "word_count": draft.word_count,
            "category": draft.category
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate article: {str(e)}")


@app.post("/blog/seo-agent/dismiss/{suggestion_id}")
async def seo_agent_dismiss_suggestion(suggestion_id: str):
    """Dismiss a suggestion (won't show again)"""
    try:
        from blog_service import SEOAgent

        agent = SEOAgent()
        dismissed = agent.dismiss_suggestion(suggestion_id)

        if not dismissed:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        return {"success": True, "suggestion_id": suggestion_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to dismiss: {str(e)}")


@app.get("/blog/seo-agent/ready-content")
async def seo_agent_get_ready_content():
    """Get suggestions that have been generated and are ready for review"""
    try:
        from blog_service import SEOAgent

        agent = SEOAgent()
        ready = agent.get_ready_content()

        return {
            "ready_content": ready,
            "count": len(ready)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get ready content: {str(e)}")


# ==================== SOCIAL MEDIA MANAGER ====================

from pydantic import BaseModel as _SMBaseModel

class SMStrategyGenerateRequest(_SMBaseModel):
    goals: List[str]
    date_range_start: str
    date_range_end: str
    product_focus: Optional[List[str]] = None

class SMPostGenerateRequest(_SMBaseModel):
    post_type: str  # photo, reel, carousel, product_feature
    strategy_id: Optional[str] = None
    product_ids: Optional[List[str]] = None
    topic_hint: Optional[str] = None

class SMPostUpdateRequest(_SMBaseModel):
    caption: Optional[str] = None
    visual_direction: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    scheduled_at: Optional[str] = None
    link_url: Optional[str] = None
    product_ids: Optional[List[str]] = None

class SMRejectRequest(_SMBaseModel):
    reason: str = ""

class SMRegenerateRequest(_SMBaseModel):
    hints: str


# ---------- Profile & Voice ----------

@app.get("/social-media/profile")
async def sm_get_profile(user: dict = Depends(require_auth)):
    """Get Instagram profile + cached brand voice analysis"""
    try:
        from social_media_service import create_social_media_storage
        storage = create_social_media_storage()
        cache = await storage.get_profile_cache_async()

        if cache:
            if cache.get("brand_voice_analysis"):
                try:
                    cache["brand_voice_analysis"] = json.loads(cache["brand_voice_analysis"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return {"profile": cache}

        # Try to fetch live from IG
        try:
            from social_media_service import create_instagram_publisher
            publisher = create_instagram_publisher()
            ig_id = await publisher.get_ig_account_id()
            profile = await publisher.get_profile_info(ig_id)
            return {"profile": {**profile, "ig_account_id": ig_id}}
        except Exception:
            return {"profile": None, "message": "No profile data cached. Run voice analysis first."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get profile: {str(e)}")


@app.post("/social-media/analyze-voice")
async def sm_analyze_voice(user: dict = Depends(require_auth)):
    """Trigger brand voice re-analysis from Instagram posts"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        result = await agent.analyze_brand_voice()
        return {"analysis": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze voice: {str(e)}")


# ---------- Strategy ----------

@app.post("/social-media/strategy/generate")
async def sm_generate_strategy(req: SMStrategyGenerateRequest, user: dict = Depends(require_auth)):
    """AI generates a content strategy"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        strategy = await agent.generate_strategy(
            goals=req.goals,
            date_range_start=req.date_range_start,
            date_range_end=req.date_range_end,
            product_focus=req.product_focus,
            user_email=user.get("email", "system")
        )
        return {"strategy": asdict(strategy)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate strategy: {str(e)}")


@app.get("/social-media/strategies")
async def sm_list_strategies(status: Optional[str] = None, user: dict = Depends(require_auth)):
    """List all strategies"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        strategies = await storage.get_all_strategies_async(status)
        return {"strategies": [asdict(s) for s in strategies]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list strategies: {str(e)}")


@app.get("/social-media/strategy/{uuid}")
async def sm_get_strategy(uuid: str, user: dict = Depends(require_auth)):
    """Get strategy detail"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        strategy = await storage.get_strategy_async(uuid)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return {"strategy": asdict(strategy)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get strategy: {str(e)}")


@app.post("/social-media/strategy/{uuid}/approve")
async def sm_approve_strategy(uuid: str, user: dict = Depends(require_auth)):
    """Approve a strategy"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        strategy = await storage.get_strategy_async(uuid)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        strategy.status = "approved"
        strategy.approved_at = datetime.utcnow().isoformat() + "Z"
        strategy.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_strategy_async(strategy)
        return {"strategy": asdict(strategy)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to approve strategy: {str(e)}")


@app.post("/social-media/strategy/{uuid}/reject")
async def sm_reject_strategy(uuid: str, req: SMRejectRequest, user: dict = Depends(require_auth)):
    """Reject a strategy with feedback"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        strategy = await storage.get_strategy_async(uuid)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        strategy.status = "rejected"
        strategy.rejection_reason = req.reason
        strategy.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_strategy_async(strategy)
        return {"strategy": asdict(strategy)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject strategy: {str(e)}")


# ---------- Content Calendar & Posts ----------

@app.get("/social-media/calendar")
async def sm_get_calendar(start_date: Optional[str] = None, end_date: Optional[str] = None,
                           user: dict = Depends(require_auth)):
    """Get posts in date range for calendar view"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        posts = await storage.get_all_posts_async(start_date=start_date, end_date=end_date)
        return {"posts": [asdict(p) for p in posts]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get calendar: {str(e)}")


@app.post("/social-media/post/generate")
async def sm_generate_post(req: SMPostGenerateRequest, user: dict = Depends(require_auth)):
    """AI generates a single post"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        post = await agent.generate_post_content(
            post_type=req.post_type,
            strategy_id=req.strategy_id,
            product_ids=req.product_ids,
            topic_hint=req.topic_hint,
            user_email=user.get("email", "system")
        )
        return {"post": asdict(post)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate post: {str(e)}")


@app.post("/social-media/post/generate-batch")
async def sm_generate_batch(strategy_id: str, user: dict = Depends(require_auth)):
    """AI generates multiple posts for a strategy"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        posts = await agent.generate_batch_posts(strategy_id, user_email=user.get("email", "system"))
        return {"posts": [asdict(p) for p in posts], "count": len(posts)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate batch: {str(e)}")


@app.get("/social-media/posts")
async def sm_list_posts(status: Optional[str] = None, post_type: Optional[str] = None,
                         strategy_id: Optional[str] = None, user: dict = Depends(require_auth)):
    """List posts with optional filters"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        posts = await storage.get_all_posts_async(status=status, post_type=post_type, strategy_id=strategy_id)
        return {"posts": [asdict(p) for p in posts]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list posts: {str(e)}")


@app.get("/social-media/post/{uuid}")
async def sm_get_post(uuid: str, user: dict = Depends(require_auth)):
    """Get post detail"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        return {"post": asdict(post)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get post: {str(e)}")


@app.put("/social-media/post/{uuid}")
async def sm_update_post(uuid: str, req: SMPostUpdateRequest, user: dict = Depends(require_auth)):
    """Edit post details"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        if req.caption is not None:
            post.caption = req.caption
        if req.visual_direction is not None:
            post.visual_direction = req.visual_direction
        if req.media_url is not None:
            post.media_url = req.media_url
        if req.media_type is not None:
            post.media_type = req.media_type
        if req.scheduled_at is not None:
            post.scheduled_at = req.scheduled_at
        if req.link_url is not None:
            post.link_url = req.link_url
        if req.product_ids is not None:
            post.product_ids = req.product_ids
        post.updated_at = datetime.utcnow().isoformat() + "Z"

        await storage.save_post_async(post)
        return {"post": asdict(post)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update post: {str(e)}")


@app.post("/social-media/post/{uuid}/approve")
async def sm_approve_post(uuid: str, user: dict = Depends(require_auth)):
    """Approve post for publishing"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.status = "approved"
        post.approved_at = datetime.utcnow().isoformat() + "Z"
        post.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_post_async(post)
        return {"post": asdict(post)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to approve post: {str(e)}")


@app.post("/social-media/post/{uuid}/reject")
async def sm_reject_post(uuid: str, req: SMRejectRequest, user: dict = Depends(require_auth)):
    """Reject post with correction notes"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        post = await storage.get_post_async(uuid)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.status = "rejected"
        post.rejection_reason = req.reason
        post.updated_at = datetime.utcnow().isoformat() + "Z"
        await storage.save_post_async(post)
        return {"post": asdict(post)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject post: {str(e)}")


@app.post("/social-media/post/{uuid}/regenerate")
async def sm_regenerate_post(uuid: str, req: SMRegenerateRequest, user: dict = Depends(require_auth)):
    """AI regenerate post with hints"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        post = await agent.regenerate_post(uuid, req.hints)
        return {"post": asdict(post)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate post: {str(e)}")


@app.post("/social-media/post/{uuid}/publish")
async def sm_publish_post(uuid: str, user: dict = Depends(require_auth)):
    """Publish approved post to Instagram + Facebook"""
    try:
        from social_media_service import create_social_media_agent
        from dataclasses import asdict
        agent = create_social_media_agent()
        post = await agent.publish_post(uuid)
        return {"post": asdict(post)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish post: {str(e)}")


@app.delete("/social-media/post/{uuid}")
async def sm_delete_post(uuid: str, user: dict = Depends(require_auth)):
    """Delete a draft post"""
    try:
        from social_media_service import create_social_media_storage
        storage = create_social_media_storage()
        deleted = await storage.delete_post_async(uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Post not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete post: {str(e)}")


# ---------- Product Integration ----------

@app.get("/social-media/products")
async def sm_get_products(user: dict = Depends(require_auth)):
    """Get Shopify products for featuring in posts"""
    try:
        if DB_SERVICE_AVAILABLE and db_service:
            products = await db_service.get_products()
            return {"products": products}

        from shopify_client import _gql_for
        return {"products": [], "message": "Product data requires database sync"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get products: {str(e)}")


# ---------- Insights & Analytics ----------

@app.get("/social-media/insights")
async def sm_get_insights(user: dict = Depends(require_auth)):
    """Overall social performance metrics"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        insights = await storage.get_insights_async()
        posts = await storage.get_all_posts_async(status="published")

        total_impressions = sum(i.impressions for i in insights)
        total_reach = sum(i.reach for i in insights)
        total_engagement = sum(i.engagement for i in insights)
        total_clicks = sum(i.website_clicks for i in insights)

        return {
            "summary": {
                "total_posts": len(posts),
                "total_impressions": total_impressions,
                "total_reach": total_reach,
                "total_engagement": total_engagement,
                "total_website_clicks": total_clicks,
                "avg_engagement_rate": round(total_engagement / total_reach * 100, 2) if total_reach else 0,
            },
            "posts": [asdict(i) for i in insights],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get insights: {str(e)}")


@app.get("/social-media/insights/post/{uuid}")
async def sm_get_post_insights(uuid: str, user: dict = Depends(require_auth)):
    """Single post performance"""
    try:
        from social_media_service import create_social_media_storage
        from dataclasses import asdict
        storage = create_social_media_storage()
        insights = await storage.get_insights_async(post_id=uuid)
        return {"insights": [asdict(i) for i in insights]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get post insights: {str(e)}")


@app.post("/social-media/insights/sync")
async def sm_sync_insights(user: dict = Depends(require_auth)):
    """Sync latest insights from Instagram API"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        synced = await agent.sync_insights()
        return {"synced": synced}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync insights: {str(e)}")


@app.get("/social-media/insights/best-times")
async def sm_best_times(user: dict = Depends(require_auth)):
    """Data-driven best posting times"""
    try:
        from social_media_service import create_social_media_agent
        agent = create_social_media_agent()
        result = await agent.suggest_optimal_times()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get best times: {str(e)}")


# ---------- Local dev entrypoint ----------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
