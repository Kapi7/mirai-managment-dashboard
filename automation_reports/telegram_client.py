# telegram_client.py — Robust Telegram alerts + persistent daily summary (Render-safe)
from __future__ import annotations

import os
import json
import re
import time
import threading
import requests
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import asdict, is_dataclass
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

try:
    import fcntl  # POSIX only (Render + macOS dev) — used for cross-process dedup
except Exception:  # pragma: no cover
    fcntl = None

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

# Render persistent disk mounted at /app/outputs
SUMMARY_STATE_FILE = Path(os.getenv("SUMMARY_STATE_FILE", "/app/outputs/.telegram_summary_state.json"))
SEEN_ORDERS_FILE = Path(
    os.getenv("TELEGRAM_SEEN_ORDERS_FILE")
    or os.getenv("TELEGRAM_SEEN_FILE")
    or "/app/outputs/.telegram_seen_orders.json"
)

SUMMARY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
SEEN_ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)

# Serialize summary upserts and order alerts within the process so concurrent
# background tasks (summary sync + order monitor) can't race into duplicate
# messages or duplicate seen-file writes.
_SUMMARY_LOCK = threading.Lock()
_ORDER_LOCK = threading.Lock()


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
    except requests.exceptions.ReadTimeout as e:
        # The request reached Telegram but the response never came back.
        # For sendMessage this very likely means the message WAS delivered —
        # callers must NOT blindly retry (that's how orders got alerted twice).
        print(f"[Telegram] READ-timeout on {method} (message may have been delivered): {e}")
        return {"_transport_error": "read", "_exc": str(e)}
    except requests.exceptions.RequestException as e:
        # Connect-level failure: the request never reached Telegram → safe to retry.
        print(f"[Telegram] Transport error on {method} (safe to retry): {e}")
        return {"_transport_error": "connect", "_exc": str(e)}
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


def _edit_error_means_message_gone(res: Dict[str, Any]) -> bool:
    """
    Decide whether a failed editMessageText means the target message no longer
    exists (so we SHOULD post a fresh one) vs. a benign/transient failure
    (so we must NOT post a duplicate).

    Returns True ONLY for errors that prove the saved message_id is unusable.
    """
    desc = ((res or {}).get("description") or "").lower()
    if not desc:
        # Empty dict / network error / no description → transient. Do NOT resend.
        return False
    # "not modified" = identical content → the message is fine, this is success.
    if "not modified" in desc:
        return False
    gone_markers = (
        "message to edit not found",
        "message can't be edited",
        "message_id_invalid",
        "message to delete not found",
        "chat not found",
    )
    return any(m in desc for m in gone_markers)


def _load_summary_state() -> Dict[str, Any]:
    return _load_json(SUMMARY_STATE_FILE, {})


def _save_summary_state(state: Dict[str, Any]) -> None:
    _save_json(SUMMARY_STATE_FILE, state)


# ---- seen-orders store (v2: dict of records; legacy format was a bare list) ----
#
# Record shape:
#   {"message_id": int|None, "chat_id": str, "channel": str, "sent_at": float,
#    "final": bool}
# `final` means "stop re-checking the channel for this alert" — either the
# channel is already a resolved/paid one, the alert is too old, or the record
# predates message-id tracking (legacy) so the message can't be edited.

_SEEN_LOCK_PATH = SEEN_ORDERS_FILE.with_suffix(SEEN_ORDERS_FILE.suffix + ".lock")


@contextmanager
def _seen_file_lock():
    """Cross-PROCESS lock. The threading lock only serializes one process —
    start.sh historically ran a second monitor process, and any overlap
    (deploy, manual backfill) must still never double-send."""
    if fcntl is None:
        yield
        return
    _SEEN_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    f = open(_SEEN_LOCK_PATH, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            pass
        f.close()


def _load_seen_records() -> Dict[str, dict]:
    data = _load_json(SEEN_ORDERS_FILE, {})
    if isinstance(data, list):
        # Legacy list of ids → records without message ids (not editable).
        return {str(x): {"legacy": True, "final": True} for x in data}
    if isinstance(data, dict):
        return {str(k): (v if isinstance(v, dict) else {"legacy": True, "final": True})
                for k, v in data.items()}
    return {}


def _save_seen_records(records: Dict[str, dict]) -> None:
    _save_json(SEEN_ORDERS_FILE, records)


def _is_order_seen(order_id: str) -> bool:
    return str(order_id) in _load_seen_records()


def _mark_order_seen(order_id: str, record: Optional[dict] = None) -> None:
    records = _load_seen_records()
    key = str(order_id)
    rec = dict(records.get(key) or {})
    rec.update(record or {})
    rec.setdefault("sent_at", time.time())
    records[key] = rec
    _save_seen_records(records)


def get_order_alert_record(order_id: str) -> Optional[dict]:
    """Public: record for a previously-sent order alert (or None)."""
    return _load_seen_records().get(str(order_id))


def mark_order_final(order_id: str) -> None:
    """Public: stop channel re-checks for this alert."""
    with _ORDER_LOCK:
        with _seen_file_lock():
            records = _load_seen_records()
            key = str(order_id)
            if key in records:
                records[key]["final"] = True
                _save_seen_records(records)


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

    # Shop Campaigns carry no UTMs; the campaign name arrives as an order tag
    # (e.g. "New campaign 01") alongside audience tags like "New customers".
    for t in (order.get("tags") or []):
        if isinstance(t, str) and "campaign" in t.lower():
            return _clean_campaign_name(t)

    return ""


# ---------------- summary render ----------------
def _render_summary(today_kpi: Dict[str, Any], yday_kpi: Dict[str, Any], mtd_kpi: Optional[Dict[str, Any]] = None) -> str:
    title_label = f"{SHOP_LABEL} Daily Report"
    title = f"🧾 *{title_label}*"  # No escaping needed for simple text

    # Extract values for each period
    _ALL_KEYS = ["orders", "net", "ship_chg", "cogs", "ship_est", "ship_pp", "psp", "op",
                 "g_spend", "g_pur", "g_cpa", "m_spend", "m_pur", "m_cpa",
                 "s_spend", "s_pur", "s_cpa", "total_spend", "margin", "gen_cpa"]

    def get_vals(k: Dict[str, Any]) -> dict:
        if not k:
            # Every key the template uses must exist, or an empty period
            # (e.g. yesterday on the 1st of the month) crashes the render.
            return {key: "—" for key in _ALL_KEYS}
        return {
            "orders": _fmt_int(k.get("orders", 0)),
            "net": _fmt_money(k.get("net", 0)),
            "ship_chg": _fmt_money(k.get("shipping_charged", 0)),
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
            "s_spend": _fmt_money(k.get("shop_spend", 0)),
            "s_pur": _fmt_opt_int(k.get("shop_pur")),
            "s_cpa": _fmt_opt_cpa(k.get("shop_cpa")),
            "total_spend": _fmt_money(k.get("total_spend", 0)),
            "margin": _fmt_money(k.get("margin", 0)),
            "gen_cpa": _fmt_opt_cpa(k.get("general_cpa")),
        }

    t = get_vals(today_kpi)
    y = get_vals(yday_kpi)
    m = get_vals(mtd_kpi) if mtd_kpi else {key: "—" for key in _ALL_KEYS}

    # One period block. Ordered so the math is checkable line-by-line:
    #   Operational = Net + Shipping Charged − COGS − PSP − Est Shipping
    #   NET MARGIN  = Operational − Total Spend
    # (PayPal Shipping is the real cash paid — informational, not in Op.)
    def block(header: str, v: dict) -> list:
        return [
            header,
            f"🛍️ Orders: *{v['orders']}* | Net: *{v['net']}*",
            f"➕ Shipping Charged: {v['ship_chg']}",
            f"💰 COGS: {v['cogs']}",
            f"💳 PSP Fee: {v['psp']}",
            f"📦 Est Shipping (Op): {v['ship_est']}",
            f"📊 Operational: *{v['op']}*",
            f"📣 Google: {v['g_spend']} ({v['g_pur']} ord, CPA {v['g_cpa']})",
            f"📣 Meta: {v['m_spend']} ({v['m_pur']} ord, CPA {v['m_cpa']})",
            f"🛒 Shop: {v['s_spend']} ({v['s_pur']} ord, CPA {v['s_cpa']})",
            f"💸 Total Spend: *{v['total_spend']}* | Gen CPA: {v['gen_cpa']}",
            f"💎 *NET MARGIN: {v['margin']}*",
            f"🚚 PayPal Shipping (Cash, not in Op): {v['ship_pp']}",
        ]

    lines = [title, ""]
    lines += block("📅 *TODAY*", t) + [""]
    lines += block("📅 *YESTERDAY*", y) + [""]
    lines += block("📊 *MONTH TO DATE*", m) + [
        "",
        "_Op = Net + Ship Charged − COGS − PSP − Est Ship · Margin = Op − Spend_",
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

    text = _render_summary(today_kpi, yday_kpi, mtd_kpi)
    key = str(summary_key).strip() or "DAILY"

    # Hold the lock for the whole read-edit/send-write cycle so two concurrent
    # callers can't both decide the message is gone and each post a new one.
    with _SUMMARY_LOCK:
        state = _load_summary_state()
        record = state.get(key)

        # ── Try to edit the existing pinned summary ──
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

            # Edit succeeded — done.
            if res.get("ok"):
                return

            # Content identical ("not modified") = the message is already correct.
            # Treat as success and keep the same message_id. This is the case
            # that used to spam a brand-new message every cycle.
            if not _edit_error_means_message_gone(res):
                desc = (res or {}).get("description")
                print(f"[Telegram] Edit non-fatal ({desc!r}) — keeping msg {msg_id}, "
                      f"NOT sending a new summary.")
                return

            # Message is genuinely gone → drop the dead id and fall through to send.
            print(f"[Telegram] Saved summary message {msg_id} is gone; will repost "
                  f"(allow_send_fallback={allow_send_fallback}).")
            state.pop(key, None)
            _save_summary_state(state)

            if not allow_send_fallback:
                return

        # ── Send a NEW summary (first ever, or the old one was deleted) ──
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


# ---------------- order alert rendering (shared by send + edit) ----------------

# Channels whose attribution may still be on its way from Shopify
# (customerJourneySummary typically lands ~5 min after the order).
PENDING_CHANNELS = {"", "unknown", "direct", "other / organic"}


def _render_order_alert(
    *,
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
    store_label: Optional[str] = None,
    shop_cost_order: Optional[float] = None,
) -> str:
    store_label = store_label or SHOP_LABEL
    emoji, store_name = _store_emoji_and_name(store_label)
    flag = _flag_from_country_code(country_code)

    # Simple text - no escaping needed for basic Markdown
    lines = [
        f"{emoji} *{store_name} Report*",
        f"🛒 New Order *{order_name}* | {flag}",
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

    # Shop orders ALWAYS show the ad-cost line — even when the CAC lookup
    # failed (shows —) or the cost is 0. Hiding it made Shop orders look free.
    if (marketing or "").strip().lower() == "shop":
        cost_txt = _fmt_money(shop_cost_order) if shop_cost_order is not None else "—"
        lines.append(f"🛒 Shop Ad Cost: *{cost_txt}*")
    elif shop_cost_order:
        lines.append(f"🛒 Shop Ad Cost: *{_fmt_money(shop_cost_order)}*")

    if approx_sale_profit is not None:
        lines.append(f"📈 Approx. Profit: *{_fmt_money(approx_sale_profit)}*")

    if is_returning:
        lines.append("🔁 *Returning customer*")

    return "\n".join(lines)


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
    shop_cost_order: Optional[float] = None,
):
    _, default_chat = _require_env(for_summary=False)
    chat_id = (chat_id or default_chat).strip()

    text = _render_order_alert(
        order_name=order_name, gross=gross, net=net, cogs=cogs,
        shipping_charged=shipping_charged, country_code=country_code,
        marketing=marketing, is_returning=is_returning,
        approx_shipping=approx_shipping, weight_kg=weight_kg,
        psp_usd_order=psp_usd_order, approx_sale_profit=approx_sale_profit,
        order=order, store_label=store_label, shop_cost_order=shop_cost_order,
    )

    # Atomic dedup: the thread lock serializes THIS process; the file lock
    # serializes ACROSS processes (two pollers / deploy overlap / manual
    # backfill). The seen file is the authoritative dedup record, re-checked
    # under both locks.
    with _ORDER_LOCK:
        with _seen_file_lock():
            if _is_order_seen(order_id):
                print(f"[Telegram] Skipping duplicate order alert: {order_id}")
                return

            res = _api("sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })

            if res.get("ok"):
                # Mark seen immediately after a confirmed send, before releasing
                # the lock, so the order can't be picked up again by any path.
                channel_final = (marketing or "").strip().lower() not in PENDING_CHANNELS
                _mark_order_seen(order_id, {
                    "message_id": (res.get("result") or {}).get("message_id"),
                    "chat_id": chat_id,
                    "channel": marketing or "",
                    "sent_at": time.time(),
                    "final": channel_final,
                })
                return

            if res.get("_transport_error") == "read":
                # Response lost but the message very likely went out. Mark seen
                # WITHOUT a message_id (not editable) — a duplicate alert is
                # worse than a missed channel-update. /force-backfill-today
                # exists for the rare genuinely-lost alert.
                print(f"[Telegram] Marking {order_id} seen after read-timeout "
                      f"(assume delivered; NOT retrying).")
                _mark_order_seen(order_id, {
                    "message_id": None,
                    "chat_id": chat_id,
                    "channel": marketing or "",
                    "sent_at": time.time(),
                    "final": True,
                    "read_timeout": True,
                })
                return

            # Genuine failure (connect error / Telegram rejection): raise so the
            # caller doesn't add this order to its own seen-set — it will be
            # retried next poll.
            desc = res.get("description") if isinstance(res, dict) else None
            raise RuntimeError(
                f"Telegram sendMessage failed for order_id={order_id}: {desc or res!r}"
            )


# ---------------- public: edit a sent Order Alert (late attribution) ----------------
def update_order_alert(
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
    store_label: Optional[str] = None,
    shop_cost_order: Optional[float] = None,
) -> bool:
    """
    Re-render a previously-sent order alert with corrected attribution and
    edit the original Telegram message in place. Returns True when the edit
    landed (or the message already had this content).
    """
    with _ORDER_LOCK:
        with _seen_file_lock():
            rec = get_order_alert_record(order_id)
            if not rec or not rec.get("message_id") or not rec.get("chat_id"):
                return False

            text = _render_order_alert(
                order_name=order_name, gross=gross, net=net, cogs=cogs,
                shipping_charged=shipping_charged, country_code=country_code,
                marketing=marketing, is_returning=is_returning,
                approx_shipping=approx_shipping, weight_kg=weight_kg,
                psp_usd_order=psp_usd_order, approx_sale_profit=approx_sale_profit,
                order=order, store_label=store_label, shop_cost_order=shop_cost_order,
            )

            res = _api("editMessageText", {
                "chat_id": rec["chat_id"],
                "message_id": rec["message_id"],
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })

            desc = ((res or {}).get("description") or "").lower()
            ok = bool(res.get("ok")) or "not modified" in desc
            if ok or _edit_error_means_message_gone(res):
                # Record the corrected channel; mark final so we stop rechecking.
                records = _load_seen_records()
                key = str(order_id)
                if key in records:
                    records[key]["channel"] = marketing or ""
                    records[key]["final"] = True
                    _save_seen_records(records)
            if not ok:
                print(f"[Telegram] update_order_alert failed for {order_id}: {res}")
            return ok


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
