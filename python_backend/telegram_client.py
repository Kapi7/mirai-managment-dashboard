# telegram_client.py — Robust Telegram alerts + persistent daily summary (Render-safe)
from __future__ import annotations

import os
import json
import re
import requests
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import asdict, is_dataclass
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

# NOTE: avoid crashing if config is missing
try:
    from config import SHOP_LABEL  # e.g. "Mirai Skin + Mirai Cosmetics"
except Exception:
    SHOP_LABEL = "Mirai Store"

load_dotenv()

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

# Fallback order: specific → generic
ALERT_CHAT_ID = (os.getenv("TELEGRAM_ALERT_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
SUMMARY_CHAT_ID = (os.getenv("TELEGRAM_SUMMARY_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()

_API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Use /tmp for state files (writable in all environments including Render dashboard)
# The live mirai-reports service uses /app/outputs which is mounted persistent disk
SUMMARY_STATE_FILE = Path(os.getenv("SUMMARY_STATE_FILE", "/tmp/.telegram_summary_state.json"))
SEEN_ORDERS_FILE = Path(
    os.getenv("TELEGRAM_SEEN_ORDERS_FILE")
    or os.getenv("TELEGRAM_SEEN_FILE")
    or "/tmp/.telegram_seen_orders.json"
)

# Safely create directories - won't fail if no permission (dashboard doesn't need these anyway)
try:
    SUMMARY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError):
    pass  # Ignore permission errors - Telegram features won't work but reports will


# ---------------- validation ----------------
def _require_env(for_summary: bool = False) -> tuple[str, str]:
    """
    Returns (bot_token, chat_id). Raises RuntimeError only when a function is called.
    """
    if not BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment.")
    chat_id = SUMMARY_CHAT_ID if for_summary else ALERT_CHAT_ID
    if not chat_id:
        raise RuntimeError(
            "Missing Telegram chat id. Set TELEGRAM_CHAT_ID or "
            "TELEGRAM_ALERT_CHAT_ID/TELEGRAM_SUMMARY_CHAT_ID."
        )
    return BOT_TOKEN, chat_id


# ---------------- low-level Telegram helper ----------------
def _api(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _API_BASE:
        print("[Telegram] ERROR: _API_BASE is empty (missing TELEGRAM_BOT_TOKEN).")
        return {}

    try:
        r = requests.post(f"{_API_BASE}/{method}", json=payload, timeout=25)
        data = r.json() if r is not None else {}
        if not data.get("ok"):
            # Print BOTH telegram error + payload summary
            desc = data.get("description")
            print(f"[Telegram] API error {method}: {data} | desc={desc} | chat_id={payload.get('chat_id')}")
        return data
    except Exception as e:
        print(f"[Telegram] Request error {method}: {e}")
        return {}


# ---------------- state management ----------------
def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def _save_json(path: Path, obj) -> None:
    try:
        path.write_text(json.dumps(obj, indent=2, sort_keys=True))
    except Exception as e:
        print(f"[Telegram] Failed to write state file {path}: {e}")


def _load_summary_state() -> Dict[str, Any]:
    return _load_json(SUMMARY_STATE_FILE, {})


def _save_summary_state(state: Dict[str, Any]) -> None:
    _save_json(SUMMARY_STATE_FILE, state)


def _is_order_seen(order_id: str) -> bool:
    seen = _load_json(SEEN_ORDERS_FILE, [])
    return str(order_id) in set(map(str, seen))


def _mark_order_seen(order_id: str) -> None:
    seen = _load_json(SEEN_ORDERS_FILE, [])
    s = set(map(str, seen))
    if str(order_id) in s:
        return
    seen.append(str(order_id))
    _save_json(SEEN_ORDERS_FILE, seen)


# ---------------- formatting helpers ----------------
def _bold(s: str) -> str:
    return f"*{s}*"


def _fmt_money(v) -> str:
    try:
        x = float(v if v not in (None, "") else 0.0)
    except Exception:
        x = 0.0
    return f"${x:,.2f}"


def _fmt_int(v) -> str:
    try:
        return f"{int(float(v or 0))}"
    except Exception:
        return "0"


def _fmt_opt_int(v) -> str:
    try:
        if v in (None, ""):
            return "—"
        return f"{int(float(v))}"
    except Exception:
        return "—"


def _fmt_opt_cpa(v) -> str:
    if v in (None, ""):
        return "—"
    return _fmt_money(v)


def _flag_from_country_code(cc: Optional[str]) -> str:
    if not cc:
        return "🌍"
    cc = cc.strip().upper()
    if len(cc) != 2 or not cc.isalpha():
        return "🌍"
    base = 0x1F1E6
    return chr(base + ord(cc[0]) - ord("A")) + chr(base + ord(cc[1]) - ord("A"))


def _store_emoji_and_name(store_label: str) -> tuple[str, str]:
    lbl = (store_label or "").strip() or SHOP_LABEL or "Mirai Store"
    low = lbl.lower()
    if "cosmetic" in low:
        return "💄", lbl
    if "skin" in low:
        return "🧴", lbl
    return "🛍️", lbl


# ---------------- Markdown escaping ----------------
_MD_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"

def _escape_md(s: str) -> str:
    """
    Telegram Markdown (classic) is brittle. Escape dynamic strings.
    """
    s = (s or "").strip()
    if not s:
        return ""
    # Escape all special chars used by Markdown
    return re.sub(r"([\\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])", r"\\\1", s)


# ---------------- UTM campaign extraction ----------------
def _clean_campaign_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _extract_utm_campaign(order: dict) -> str:
    if not isinstance(order, dict):
        return ""

    cjs = order.get("customerJourneySummary") or {}

    for edge in ("lastVisit", "firstVisit"):
        visit = cjs.get(edge) or {}
        if isinstance(visit, dict):
            utm = visit.get("utmParameters") or {}
            if isinstance(utm, dict):
                camp = utm.get("campaign")
                if isinstance(camp, str) and camp.strip():
                    return _clean_campaign_name(camp)

            for k in ("landingPageUrl", "referrerUrl"):
                u = visit.get(k)
                if isinstance(u, str) and u:
                    try:
                        q = parse_qs(urlparse(u).query)
                        camp = (q.get("utm_campaign") or [""])[0]
                        if camp:
                            return _clean_campaign_name(camp)
                    except Exception:
                        pass

    for k in ("landingPageUrl", "referrerUrl", "customerUrl"):
        u = order.get(k)
        if isinstance(u, str) and u:
            try:
                q = parse_qs(urlparse(u).query)
                camp = (q.get("utm_campaign") or [""])[0]
                if camp:
                    return _clean_campaign_name(camp)
            except Exception:
                pass

    return ""


# ---------------- summary render ----------------
def _render_summary(today_kpi: Dict[str, Any], yday_kpi: Dict[str, Any], mtd_kpi: Optional[Dict[str, Any]] = None) -> str:
    title_label = f"{SHOP_LABEL} Daily Report"
    title = f"🧾 *{title_label}*"  # No escaping needed for simple text

    # Extract values for each period
    def get_vals(k: Dict[str, Any]) -> dict:
        if not k:
            return {key: "—" for key in ["orders", "net", "cogs", "ship_est", "ship_pp", "psp", "op", "g_spend", "m_spend", "total_spend", "margin", "gen_cpa"]}
        return {
            "orders": _fmt_int(k.get("orders", 0)),
            "net": _fmt_money(k.get("net", 0)),
            "cogs": _fmt_money(k.get("cogs", 0)),
            "ship_est": _fmt_money(k.get("shipping_estimated", 0)),
            "ship_pp": _fmt_money(k.get("shipping_cost", 0)),
            "psp": _fmt_money(k.get("psp_usd", 0)),
            "op": _fmt_money(k.get("operational", 0)),
            "g_spend": _fmt_money(k.get("google_spend", 0)),
            "g_pur": _fmt_opt_int(k.get("google_pur")),
            "g_cpa": _fmt_opt_cpa(k.get("google_cpa")),
            "m_spend": _fmt_money(k.get("meta_spend", 0)),
            "m_pur": _fmt_opt_int(k.get("meta_pur")),
            "m_cpa": _fmt_opt_cpa(k.get("meta_cpa")),
            "total_spend": _fmt_money(k.get("total_spend", 0)),
            "margin": _fmt_money(k.get("margin", 0)),
            "gen_cpa": _fmt_opt_cpa(k.get("general_cpa")),
        }

    t = get_vals(today_kpi)
    y = get_vals(yday_kpi)
    m = get_vals(mtd_kpi) if mtd_kpi else {key: "—" for key in t.keys()}

    # Build compact, readable format with margin on separate line
    lines = [
        title,
        "",
        "📅 *TODAY*",
        f"🛍️ Orders: *{t['orders']}* | Net: *{t['net']}*",
        f"💰 COGS: {t['cogs']} | PSP: {t['psp']}",
        f"📦 Est Shipping (Op): {t['ship_est']}",
        f"🚚 PayPal Shipping (Cash): {t['ship_pp']}",
        f"📊 Operational: *{t['op']}*",
        f"📣 Google: {t['g_spend']} ({t['g_pur']} ord, CPA {t['g_cpa']})",
        f"📣 Meta: {t['m_spend']} ({t['m_pur']} ord, CPA {t['m_cpa']})",
        f"💸 Total Spend: *{t['total_spend']}* | Gen CPA: {t['gen_cpa']}",
        f"💎 *NET MARGIN: {t['margin']}*",
        "",
        "📅 *YESTERDAY*",
        f"🛍️ Orders: *{y['orders']}* | Net: *{y['net']}*",
        f"💰 COGS: {y['cogs']} | PSP: {y['psp']}",
        f"📦 Est Shipping (Op): {y['ship_est']}",
        f"🚚 PayPal Shipping (Cash): {y['ship_pp']}",
        f"📊 Operational: *{y['op']}*",
        f"📣 Google: {y['g_spend']} ({y['g_pur']} ord, CPA {y['g_cpa']})",
        f"📣 Meta: {y['m_spend']} ({y['m_pur']} ord, CPA {y['m_cpa']})",
        f"💸 Total Spend: *{y['total_spend']}* | Gen CPA: {y['gen_cpa']}",
        f"💎 *NET MARGIN: {y['margin']}*",
        "",
        "📊 *MONTH TO DATE*",
        f"🛍️ Orders: *{m['orders']}* | Net: *{m['net']}*",
        f"💰 COGS: {m['cogs']} | PSP: {m['psp']}",
        f"📦 Est Shipping (Op): {m['ship_est']}",
        f"🚚 PayPal Shipping (Cash): {m['ship_pp']}",
        f"📊 Operational: *{m['op']}*",
        f"📣 Google: {m['g_spend']} ({m['g_pur']} ord, CPA {m['g_cpa']})",
        f"📣 Meta: {m['m_spend']} ({m['m_pur']} ord, CPA {m['m_cpa']})",
        f"💸 Total Spend: *{m['total_spend']}* | Gen CPA: {m['gen_cpa']}",
        f"💎 *NET MARGIN: {m['margin']}*",
    ]

    return "\n".join(lines)


# ---------------- public: Upsert Single Summary Message ----------------
def upsert_daily_summary(
    *,
    today_kpi,
    yday_kpi,
    mtd_kpi=None,
    pin: bool = True,
    chat_id: Optional[str] = None,
    summary_key: str = "DAILY",
    allow_send_fallback: bool = True,   # ✅ CHANGED DEFAULT: never deadlock
) -> None:
    _, default_chat = _require_env(for_summary=True)
    chat_id = (chat_id or default_chat).strip()

    if is_dataclass(today_kpi):
        today_kpi = asdict(today_kpi)
    else:
        today_kpi = dict(today_kpi or {})

    if is_dataclass(yday_kpi):
        yday_kpi = asdict(yday_kpi)
    else:
        yday_kpi = dict(yday_kpi or {})

    if mtd_kpi:
        if is_dataclass(mtd_kpi):
            mtd_kpi = asdict(mtd_kpi)
        else:
            mtd_kpi = dict(mtd_kpi)

    state = _load_summary_state()
    key = str(summary_key).strip() or "DAILY"
    record = state.get(key)

    text = _render_summary(today_kpi, yday_kpi, mtd_kpi)

    # Try edit existing summary
    if record and record.get("message_id"):
        msg_id = record["message_id"]
        record_chat = (record.get("chat_id") or chat_id).strip()

        print(f"[Telegram] Editing summary (key={key}) chat={record_chat} msg={msg_id} ...")
        res = _api("editMessageText", {
            "chat_id": record_chat,
            "message_id": msg_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
        if res.get("ok"):
            return

        print(f"[Telegram] Edit failed. Will send new summary (allow_send_fallback={allow_send_fallback}).")
        # Clear record so we don't keep trying a dead message_id forever
        state.pop(key, None)
        _save_summary_state(state)

        if not allow_send_fallback:
            return

    # Send NEW summary
    print(f"[Telegram] Sending NEW summary (key={key}) chat={chat_id} ...")
    res = _api("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })

    if res.get("ok"):
        new_msg_id = res["result"]["message_id"]
        state[key] = {"message_id": new_msg_id, "chat_id": chat_id}
        _save_summary_state(state)

        if pin:
            _api("pinChatMessage", {"chat_id": chat_id, "message_id": new_msg_id})


# ---------------- public: Order Alert (Dedup) ----------------
def send_order_alert(
    *,
    order_id: str,
    order_name: str,
    gross: float,
    net: float,
    cogs: float,
    shipping_charged: float,
    country_code: Optional[str],
    marketing: str,
    is_returning: bool,
    approx_shipping: Optional[float] = None,
    weight_kg: Optional[float] = None,
    psp_usd_order: Optional[float] = None,
    approx_sale_profit: Optional[float] = None,
    order: Optional[dict] = None,
    chat_id: Optional[str] = None,
    store_label: Optional[str] = None,
):
    _, default_chat = _require_env(for_summary=False)
    chat_id = (chat_id or default_chat).strip()

    if _is_order_seen(order_id):
        print(f"[Telegram] Skipping duplicate order alert: {order_id}")
        return

    store_label = store_label or SHOP_LABEL
    emoji, store_name = _store_emoji_and_name(store_label)
    flag = _flag_from_country_code(country_code)

    # Simple text - no escaping needed for basic Markdown
    title_line = f"{emoji} *{store_name} Report*"
    order_line = f"🛒 New Order *{order_name}* | {flag}"

    lines = [
        title_line,
        order_line,
        f"💵 Gross: *{_fmt_money(gross)}*",
        f"🧾 Net: *{_fmt_money(net)}*",
        f"📦 Shipping Charged: *{_fmt_money(shipping_charged)}*",
        f"💰 COGS: *{_fmt_money(cogs)}*",
        f"📣 Channel: *{marketing or 'Unknown'}*",
    ]

    campaign = _extract_utm_campaign(order or {})
    if campaign:
        lines.append(f"🏷️ Campaign: *{campaign}*")

    if approx_shipping is not None:
        grams_txt = "—"
        if weight_kg is not None:
            try:
                grams_txt = f"{int(round(weight_kg * 1000))} g"
            except Exception:
                pass
        lines.append(f"🚚 Approx. Shipping: *{_fmt_money(approx_shipping)}* · *{grams_txt}*")

    if psp_usd_order is not None:
        lines.append(f"💳 PSP Fee: *{_fmt_money(psp_usd_order)}*")

    if approx_sale_profit is not None:
        lines.append(f"📈 Approx. Profit: *{_fmt_money(approx_sale_profit)}*")

    if is_returning:
        lines.append("🔁 *Returning customer*")

    text = "\n".join(lines)

    res = _api("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })

    if res.get("ok"):
        _mark_order_seen(order_id)
    else:
        print(f"[Telegram] Order alert NOT sent (won't mark seen). order_id={order_id}")


# ---------------- optional: quick test ----------------
def telegram_self_test() -> None:
    """
    Call this once on Render to verify bot+chat_id works.
    """
    try:
        _, chat_alert = _require_env(for_summary=False)
        _, chat_sum = _require_env(for_summary=True)
    except Exception as e:
        print("[Telegram] Self-test failed env validation:", e)
        return

    res1 = _api("sendMessage", {
        "chat_id": chat_alert,
        "text": "✅ Telegram self-test: order alerts channel OK",
        "disable_web_page_preview": True,
    })
    res2 = _api("sendMessage", {
        "chat_id": chat_sum,
        "text": "✅ Telegram self-test: summary channel OK",
        "disable_web_page_preview": True,
    })
    print("[Telegram] Self-test results:", {"alert_ok": res1.get("ok"), "summary_ok": res2.get("ok")})
