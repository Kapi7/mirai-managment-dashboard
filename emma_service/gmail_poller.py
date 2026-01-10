# gmail_poller.py
# Runs an IMAP poller in a background thread. Exposes start/stop/status/force/reset.
# Now also pushes emails to Mirai Dashboard for AI classification and draft generation.

from __future__ import annotations
import os, time, imaplib, email, requests, re, sys, threading
from html import unescape
from email.header import decode_header
from typing import Optional

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

# ---- Config (prefer INBOUND_*; fallback to IMAP_*) ----
IMAP_HOST     = os.getenv("INBOUND_IMAP_HOST")     or os.getenv("IMAP_HOST")     or "imap.gmail.com"
IMAP_PORT     = int(os.getenv("INBOUND_IMAP_PORT") or os.getenv("IMAP_PORT")     or "993")
IMAP_MAILBOX  = os.getenv("INBOUND_IMAP_MAILBOX")  or os.getenv("IMAP_MAILBOX")  or "INBOX"
IMAP_USER     = os.getenv("INBOUND_EMAIL_USER")    or os.getenv("IMAP_USER")
IMAP_PASS     = os.getenv("INBOUND_EMAIL_PASS")    or os.getenv("IMAP_PASS")
POLL_SECONDS  = int(os.getenv("INBOUND_POLL_SECONDS") or os.getenv("IMAP_POLL_SECONDS") or "20")
WEBHOOK_URL   = os.getenv("INBOUND_WEBHOOK_URL", "http://localhost:5001/webhook/inbound-reply")

_state = {
    "running": False,
    "last_cycle": None,
    "last_error": None,
    "seen_set": set(),   # simple dedupe for this process
}
_thread: Optional[threading.Thread] = None

def _fatal_if_missing_creds():
    if not IMAP_USER or not IMAP_PASS:
        raise SystemExit("[gmail-poller] Missing INBOUND_EMAIL_USER/INBOUND_EMAIL_PASS (or IMAP_USER/IMAP_PASS). Use a 16-char Gmail App Password and enable IMAP in Gmail settings.")

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

def _cycle():
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        M.login(IMAP_USER, IMAP_PASS)
        M.select(IMAP_MAILBOX)
    except imaplib.IMAP4.error as e:
        _state["last_error"] = f"auth/conn error: {e}"
        print(f"[gmail-poller] ERROR: {e}")
        time.sleep(POLL_SECONDS)
        return

    try:
        typ, data = M.search(None, 'UNSEEN')
        if typ != 'OK':
            return
        for num in data[0].split():
            if num in _state["seen_set"]:
                continue
            _state["seen_set"].add(num)

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
                    payload = part.get_payload(decode=True)
                    try:
                        text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore") if payload else ""
                    except Exception:
                        text = ""
                    if ctype == "text/plain" and not body_text:
                        body_text = text
                    elif ctype == "text/html" and not body_html:
                        body_html = text
            else:
                ctype = msg.get_content_type()
                payload = msg.get_payload(decode=True)
                text = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore") if payload else ""
                if ctype == "text/plain":
                    body_text = text
                elif ctype == "text/html":
                    body_html = text

            if not (body_text or "").strip() and body_html:
                body_text = _html_to_text(body_html)

            payload = {
                "email": from_addr,
                "from_header": from_header,  # Full From header for name extraction
                "subject": subj,
                "body_text": (body_text or "").strip() or "[customer replied with an empty body or image]",
                "body_html": (body_html or "").strip(),
                "thread_id": thread_ref,
                "in_reply_to": msg.get("In-Reply-To") or "",
                "message_id": message_id,
                "cart_items": [],
            }
            _post_webhook(payload)
            _push_to_dashboard(payload)  # Also push to Mirai Dashboard
    finally:
        try:
            M.close()
            M.logout()
        except Exception:
            pass

def _loop():
    print(f"[gmail-poller] starting on {IMAP_HOST}:{IMAP_PORT} mailbox={IMAP_MAILBOX} user={IMAP_USER}")
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
    return {
        "running": _state["running"],
        "last_cycle": _state["last_cycle"],
        "last_error": _state["last_error"],
    }

def force_cycle():
    # Run one immediate cycle in the current thread
    _cycle()
    _state["last_cycle"] = time.time()

def reset_cursor():
    _state["seen_set"].clear()
