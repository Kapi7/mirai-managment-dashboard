# channel_normalizer.py — classify channels using sourceName + UTMs + referrerUrl
from __future__ import annotations
from typing import Optional
from urllib.parse import urlparse

# treat self-referrals as direct
SELF_DOMAINS = ("mirai-skin.com",)

# google surfaces to check in referrerUrl
GOOGLE_HOST_HINTS = (
    "google.", "youtube.", "gmail.", "googleadservices.", "doubleclick.", "googlesyndication."
)

def _host(s: Optional[str]) -> str:
    if not s:
        return ""
    try:
        if "://" not in s:
            s = "http://" + s
        return (urlparse(s).netloc or "").lower()
    except Exception:
        return ""

def _is_google_host(h: str) -> bool:
    return bool(h) and any(tok in h for tok in GOOGLE_HOST_HINTS)

def normalize_channel(*, source_name: str = "", utm_source: str = "", utm_medium: str = "",
                      referrer_url: str = "", landing_page_url: str = "") -> str:
    """
    Output one of: 'Google Paid', 'Klaviyo', 'ChatGPT', 'Direct', 'Other / Organic'
    Rules:
      - If UTMs say google/cpc/product_sync → Google Paid
      - If gclid parameter present → Google Paid
      - Else if referrerUrl host looks like Google/YouTube/Gmail → Google Paid
      - Klaviyo from sourceName/UTMs/email medium
      - ChatGPT special case
      - Otherwise Direct when no UTMs and referrer is self/empty, else Other/Organic
    """
    sname = (source_name or "").strip().lower()
    usrc  = (utm_source or "").strip().lower()
    umed  = (utm_medium or "").strip().lower()
    ref_h = _host(referrer_url)

    # Check for gclid in referrer or landing page URLs
    has_gclid = False
    for url in (referrer_url, landing_page_url):
        if url and "gclid=" in url.lower():
            has_gclid = True
            break

    # Klaviyo
    if sname == "klaviyo" or usrc == "klaviyo" or umed == "email":
        return "Klaviyo"

    # Google Paid by gclid (definitive Google Ads indicator)
    if has_gclid:
        return "Google Paid"

    # Google Paid by UTMs/sourceName
    if usrc == "google" or umed in ("cpc", "product_sync") or sname == "google":
        return "Google Paid"

    # Google Paid by referrerUrl (covers PMax no-UTM cases)
    if _is_google_host(ref_h):
        return "Google Paid"

    # ChatGPT
    if usrc in ("chatgpt.com", "openai", "chatgpt") or ref_h == "chatgpt.com":
        return "ChatGPT"

    # Direct if no UTMs and referrer is self/empty
    if not usrc and not umed and not has_gclid and (not ref_h or any(dom in ref_h for dom in SELF_DOMAINS)):
        return "Direct"

    return "Other / Organic"

def attach_normalized_channel(df):
    if df is None or df.empty:
        return df

    def _row_norm(r):
        return normalize_channel(
            source_name = r.get("sourceName") or "",
            utm_source  = r.get("utm_source") or "",
            utm_medium  = r.get("utm_medium") or "",
            referrer_url= r.get("referrer_url") or "",   # <-- use referrerUrl from GraphQL
        )

    out = df.copy()
    out["channel_norm"] = out.apply(_row_norm, axis=1)
    return out