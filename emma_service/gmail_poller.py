# gmail_poller.py
# Runs an IMAP poller in a background thread. Exposes start/stop/status/force/reset.
# Now also pushes emails to Mirai Dashboard for AI classification and draft generation.
# Supports MULTIPLE email accounts (emma@ and support@)

from __future__ import annotations
import os, time, imaplib, email, requests, re, sys, threading
from html import unescape
from email.header import decode_header
from typing import Optional, List, Dict, Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Dashboard bridge for pushing emails to Mirai Dashboard
try:
    from dashboard_bridge import process_incoming_email, MIRAI_DASHBOARD_URL
    DASHBOARD_ENABLED = bool(MIRAI_DASHBOARD_URL)
except ImportError:
    DASHBOARD_ENABLED = False
    def process_incoming_email(*args, **kwargs):
        return {"success": False, "error": "dashboard_bridge not available"}

# ---- Multi-Account Config ----
# Account 1: Emma (sales/abandoned cart)
EMMA_ACCOUNT = {
    "name": "emma",
    "user": os.getenv("EMMA_EMAIL_USER") or os.getenv("INBOUND_EMAIL_USER") or os.getenv("IMAP_USER"),
    "pass": os.getenv("EMMA_EMAIL_PASS") or os.getenv("INBOUND_EMAIL_PASS") or os.getenv("IMAP_PASS"),
    "host": os.getenv("EMMA_IMAP_HOST") or os.getenv("INBOUND_IMAP_HOST") or "imap.gmail.com",
    "port": int(os.getenv("EMMA_IMAP_PORT") or os.getenv("INBOUND_IMAP_PORT") or "993"),
    "mailbox": os.getenv("EMMA_IMAP_MAILBOX") or "INBOX",
    "type": "sales"  # For classification context
}

# Account 2: Support
SUPPORT_ACCOUNT = {
    "name": "support",
    "user": os.getenv("SUPPORT_EMAIL_USER"),
    "pass": os.getenv("SUPPORT_EMAIL_PASS"),
    "host": os.getenv("SUPPORT_IMAP_HOST") or "imap.gmail.com",
    "port": int(os.getenv("SUPPORT_IMAP_PORT") or "993"),
    "mailbox": os.getenv("SUPPORT_IMAP_MAILBOX") or "INBOX",
    "type": "support"  # For classification context
}

# Build list of active accounts
def _get_active_accounts() -> List[Dict[str, Any]]:
    accounts = []
    if EMMA_ACCOUNT["user"] and EMMA_ACCOUNT["pass"]:
        accounts.append(EMMA_ACCOUNT)
    if SUPPORT_ACCOUNT["user"] and SUPPORT_ACCOUNT["pass"]:
        accounts.append(SUPPORT_ACCOUNT)
    return accounts

POLL_SECONDS  = int(os.getenv("INBOUND_POLL_SECONDS") or os.getenv("IMAP_POLL_SECONDS") or "20")
# Legacy webhook - disabled by default, only enable if explicitly set
WEBHOOK_URL   = os.getenv("INBOUND_WEBHOOK_URL", "")

_state = {
    "running": False,
    "last_cycle": None,
    "last_error": None,
    "seen_sets": {},   # per-account dedupe: {"emma": set(), "support": set()}
    "accounts_status": {}  # per-account status
}
_thread: Optional[threading.Thread] = None

def _fatal_if_missing_creds():
    accounts = _get_active_accounts()
    if not accounts:
        raise SystemExit("[gmail-poller] No email accounts configured. Set EMMA_EMAIL_USER/PASS or SUPPORT_EMAIL_USER/PASS.")

def _html_to_text(html: str) -> str:
    x = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html or "")
    x = re.sub(r"(?is)<br\s*/?>", "\n", x)
    x = re.sub(r"(?is)</p\s*>", "\n\n", x)
    x = re.sub(r"(?is)<.*?>", "", x)
    return unescape(x).strip()

def _clean_subject(s):
    parts = decode_header(s or "")
    out = ""
    for txt, enc in parts:
        if isinstance(txt, bytes):
            out += txt.decode(enc or "utf-8", errors="ignore")
        else:
            out += txt
    return out

def _post_webhook(payload: dict):
    """Legacy webhook - only posts if INBOUND_WEBHOOK_URL is explicitly set"""
    if not WEBHOOK_URL:
        return  # Skip legacy webhook, use dashboard_bridge instead
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        print(f"[gmail-poller] → posted {r.status_code} {payload.get('email','')} subj='{(payload.get('subject') or '')[:60]}'")
    except Exception as e:
        print("[gmail-poller] post error:", e)


def _push_to_dashboard(payload: dict):
    """Push email to Mirai Dashboard for AI processing and human review"""
    if not DASHBOARD_ENABLED:
        return

    try:
        # Extract customer name from email if available
        customer_name = None
        from_header = payload.get("from_header", "")
        if from_header and "<" in from_header:
            customer_name = from_header.split("<")[0].strip().strip('"')

        result = process_incoming_email(
            thread_id=payload.get("thread_id") or payload.get("message_id") or "",
            customer_email=payload.get("email", ""),
            subject=payload.get("subject", ""),
            content=payload.get("body_text", ""),
            customer_name=customer_name,
            content_html=payload.get("body_html"),
            message_id=payload.get("message_id"),
            generate_draft=True  # Have Emma generate a draft response
        )

        if result.get("success"):
            print(f"[gmail-poller] → dashboard: email_id={result.get('email_id')}, "
                  f"classification={result.get('classification', {}).get('classification')}")
        else:
            print(f"[gmail-poller] → dashboard failed: {result.get('error')}")
    except Exception as e:
        print(f"[gmail-poller] dashboard error: {e}")

def _cycle_account(account: Dict[str, Any]):
    """Poll a single email account for new messages"""
    account_name = account["name"]

    # Initialize seen set for this account if not exists
    if account_name not in _state["seen_sets"]:
        _state["seen_sets"][account_name] = set()

    try:
        M = imaplib.IMAP4_SSL(account["host"], account["port"])
        M.login(account["user"], account["pass"])
        M.select(account["mailbox"])
        _state["accounts_status"][account_name] = {"connected": True, "last_check": time.time()}
    except imaplib.IMAP4.error as e:
        _state["accounts_status"][account_name] = {"connected": False, "error": str(e)}
        print(f"[gmail-poller:{account_name}] ERROR: {e}")
        return

    try:
        typ, data = M.search(None, 'UNSEEN')
        if typ != 'OK':
            return

        seen_set = _state["seen_sets"][account_name]

        for num in data[0].split():
            if num in seen_set:
                continue
            seen_set.add(num)

            typ, msg_data = M.fetch(num, '(RFC822)')
            if typ != 'OK' or not msg_data:
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            from_header = msg.get("From") or ""
            from_addr  = email.utils.parseaddr(from_header)[1]
            subj       = _clean_subject(msg.get("Subject",""))
            message_id = (msg.get("Message-ID") or "").strip()
            thread_ref = (msg.get("In-Reply-To") or msg.get("References") or "").strip()

            body_text, body_html = "", ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    ctype = part.get_content_type()
                    payload_data = part.get_payload(decode=True)
                    try:
                        text = payload_data.decode(part.get_content_charset() or "utf-8", errors="ignore") if payload_data else ""
                    except Exception:
                        text = ""
                    if ctype == "text/plain" and not body_text:
                        body_text = text
                    elif ctype == "text/html" and not body_html:
                        body_html = text
            else:
                ctype = msg.get_content_type()
                payload_data = msg.get_payload(decode=True)
                text = payload_data.decode(msg.get_content_charset() or "utf-8", errors="ignore") if payload_data else ""
                if ctype == "text/plain":
                    body_text = text
                elif ctype == "text/html":
                    body_html = text

            if not (body_text or "").strip() and body_html:
                body_text = _html_to_text(body_html)

            payload = {
                "email": from_addr,
                "from_header": from_header,
                "subject": subj,
                "body_text": (body_text or "").strip() or "[customer replied with an empty body or image]",
                "body_html": (body_html or "").strip(),
                "thread_id": thread_ref,
                "in_reply_to": msg.get("In-Reply-To") or "",
                "message_id": message_id,
                "cart_items": [],
                "inbox_type": account["type"],  # "sales" or "support"
                "inbox_name": account_name,
            }

            print(f"[gmail-poller:{account_name}] New email from {from_addr}: {subj[:50]}")
            _post_webhook(payload)
            _push_to_dashboard(payload)
    finally:
        try:
            M.close()
            M.logout()
        except Exception:
            pass


def _cycle():
    """Poll all configured email accounts"""
    accounts = _get_active_accounts()
    for account in accounts:
        try:
            _cycle_account(account)
        except Exception as e:
            print(f"[gmail-poller:{account['name']}] cycle error: {e}")

def _loop():
    accounts = _get_active_accounts()
    account_names = [a["name"] + ":" + a["user"] for a in accounts]
    print(f"[gmail-poller] starting with {len(accounts)} accounts: {', '.join(account_names)}")

    while _state["running"]:
        try:
            _cycle()
            _state["last_cycle"] = time.time()
            _state["last_error"] = None
        except Exception as e:
            _state["last_error"] = str(e)
            print("[gmail-poller] loop error:", e)
        time.sleep(POLL_SECONDS)
    print("[gmail-poller] stopped")

# ---- Public API for main.py ----
def start_gmail_poller() -> bool:
    global _thread
    _fatal_if_missing_creds()
    if _state["running"]:
        return True
    _state["running"] = True
    _thread = threading.Thread(target=_loop, name="gmail_poller", daemon=True)
    _thread.start()
    return True

def stop_gmail_poller():
    _state["running"] = False

def get_gmail_poller_status():
    accounts = _get_active_accounts()
    return {
        "running": _state["running"],
        "last_cycle": _state["last_cycle"],
        "last_error": _state["last_error"],
        "accounts": [{"name": a["name"], "user": a["user"], "type": a["type"]} for a in accounts],
        "accounts_status": _state.get("accounts_status", {}),
    }

def force_cycle():
    # Run one immediate cycle in the current thread
    _cycle()
    _state["last_cycle"] = time.time()

def reset_cursor():
    _state["seen_sets"].clear()
    print("[gmail-poller] All account cursors reset")
