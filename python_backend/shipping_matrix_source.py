"""
Live Korealy shipping matrix, sourced from the Google Sheet that Korealy's
shipping calculator is mirrored into.

    https://docs.google.com/spreadsheets/d/1wvASH50UAwJNmA0dEXLYH6nSSKhBPzZxc9QPGp9Xbvc/edit#gid=1947558449

Sheet columns: country, country_id, weight_kg, shipping_speed
(Standard/Economy/Express), estimate_delivery_time, shipping_charge_usd, notes.

This module keeps `shipping_matrix_all.csv` (the file every loader in this
repo already reads) in sync with the sheet:

  * `STANDARD` (and legacy `PRICE`) = cheapest service Korealy offers for that
    country + weight tier: Standard where offered, else Economy, else Express.
    That is exactly what the old hand-made CSV meant by "STANDARD" (Albania's
    old 43 was an Express-only price), so every existing lookup keeps working.
  * `ECONOMY` / `EXPRESS` = raw prices for those speeds (blank when not offered).
  * `SERVICE` = which speed `STANDARD` came from.
  * Alias rows are emitted for Shopify country spellings the sheet lacks
    (e.g. "Czechia" -> "Czech Republic") so those orders stop falling back to
    the 80%-of-charged estimate.

Loaders call `refresh_if_stale(path)` before reading. It hits the sheet at
most once per SHIPPING_MATRIX_REFRESH_HOURS (default 6) per process, in a
background thread (blocking only when no file exists yet), and returns True
once after a successful refresh so the caller reloads. Any failure keeps the
committed CSV — the sheet being down never zeroes shipping costs.

CLI (also prints an old-vs-new diff):
    python shipping_matrix_source.py            # refresh the CSV next to this file
    python shipping_matrix_source.py --out X    # write elsewhere
    python shipping_matrix_source.py --dry-run  # only show the diff

Env: SHIPPING_MATRIX_SHEET_ID, SHIPPING_MATRIX_SHEET_GID, SHIPPING_MATRIX_URL
(overrides both), SHIPPING_MATRIX_REFRESH_HOURS, SHIPPING_MATRIX_AUTO_REFRESH
(=0 disables all network access), SHIPPING_MATRIX_MAX_WEIGHT_KG (default 10).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

DEFAULT_SHEET_ID = "1wvASH50UAwJNmA0dEXLYH6nSSKhBPzZxc9QPGp9Xbvc"
DEFAULT_SHEET_GID = "1947558449"

SPEED_PREFERENCE = ("Standard", "Economy", "Express")
REQUIRED_COLUMNS = ("country", "weight_kg", "shipping_speed", "shipping_charge_usd")
OUTPUT_COLUMNS = ("geo", "PRICE", "WEIGHT", "STANDARD", "ECONOMY", "EXPRESS", "SERVICE")

# Shopify country names -> the sheet's spelling. Loaders match on title-cased
# names (or on a small ISO2 map that yields e.g. "Czechia"), so each alias is
# written as an extra row under the Shopify spelling.
COUNTRY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "Czech Republic": ("Czechia",),
    "Hong Kong": ("Hong Kong SAR",),
    "Macau": ("Macao SAR", "Macao"),
    "Turkey": ("Türkiye", "Turkiye"),
    "Russia": ("Russian Federation",),
    "Vietnam": ("Viet Nam",),
    "South Korea": ("Korea, Republic of", "Republic of Korea", "Korea"),
    "United States": ("United States of America", "USA"),
    "United Kingdom": ("UK", "Great Britain"),
    "Cote D Ivoire": ("Côte d’Ivoire", "Côte d'Ivoire", "Ivory Coast"),
    "Curacao": ("Curaçao",),
    "Reunion": ("Réunion",),
    "The Bahamas": ("Bahamas",),
    "Swaziland": ("Eswatini",),
    "East Timor": ("Timor-Leste",),
    "Myanmar": ("Myanmar (Burma)",),
    "Saint Lucia": ("St. Lucia",),
    "Saint Kitts And Nevis": ("St. Kitts & Nevis",),
    "Saint Vincent And The Grenadines": ("St. Vincent & Grenadines",),
    "Saint Helena": ("St. Helena",),
    "Saint Pierre and Miquelon": ("St. Pierre & Miquelon",),
    "Turks And Caicos Islands": ("Turks & Caicos Islands",),
    "British Guyana": ("Guyana",),
    "French Guyana": ("French Guiana",),
    "Cape Verde": ("Cabo Verde",),
    "Congo": ("Congo - Brazzaville", "Congo - Kinshasa"),
    "Micronesia": ("Micronesia (Federated States of)",),
    "Brunei": ("Brunei Darussalam",),
    "Laos": ("Lao People's Democratic Republic",),
    "Moldova": ("Moldova, Republic of",),
    "Bolivia": ("Bolivia, Plurinational State of",),
    "Iran": ("Iran, Islamic Republic of",),
    "Syria": ("Syrian Arab Republic",),
    "Taiwan": ("Taiwan, Province of China",),
    "Tanzania": ("Tanzania, United Republic of",),
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except Exception:
        return default


def sheet_csv_url() -> str:
    explicit = (os.getenv("SHIPPING_MATRIX_URL") or "").strip()
    if explicit:
        return explicit
    sid = (os.getenv("SHIPPING_MATRIX_SHEET_ID") or DEFAULT_SHEET_ID).strip()
    gid = (os.getenv("SHIPPING_MATRIX_SHEET_GID") or DEFAULT_SHEET_GID).strip()
    return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"


def auto_refresh_enabled() -> bool:
    return (os.getenv("SHIPPING_MATRIX_AUTO_REFRESH", "1") or "1").strip().lower() not in ("0", "false", "no", "off")


def refresh_hours() -> float:
    return max(0.25, _env_float("SHIPPING_MATRIX_REFRESH_HOURS", 6.0))


def max_weight_kg() -> float:
    return max(1.0, _env_float("SHIPPING_MATRIX_MAX_WEIGHT_KG", 10.0))


def stamp_path(path: str) -> str:
    return f"{path}.stamp.json"


# ------------------------------------------------------------------------------
# fetch + transform
# ------------------------------------------------------------------------------

def fetch_sheet_rows(url: Optional[str] = None, timeout: float = 25.0) -> List[Dict[str, str]]:
    """Download the sheet tab as CSV and return its rows. Raises on any problem."""
    import requests  # already a dependency of both repos

    url = url or sheet_csv_url()
    resp = requests.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    ctype = (resp.headers.get("content-type") or "").lower()
    text = resp.content.decode("utf-8-sig", errors="replace")
    if "text/csv" not in ctype and not text.lstrip().lower().startswith("country"):
        raise RuntimeError(f"sheet export did not return CSV (content-type={ctype!r}); is the sheet still shared?")
    reader = csv.DictReader(io.StringIO(text))
    cols = [c.strip().lower() for c in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise RuntimeError(f"sheet is missing columns {missing}; got {reader.fieldnames}")
    rows = []
    for raw in reader:
        rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()})
    if len(rows) < 1000:
        raise RuntimeError(f"sheet returned only {len(rows)} rows — refusing to overwrite the matrix")
    return rows


def build_matrix_rows(sheet_rows: List[Dict[str, str]], max_kg: Optional[float] = None) -> List[Dict[str, str]]:
    """Collapse (country, weight, speed) rows into the legacy one-row-per-tier layout."""
    max_kg = max_kg or max_weight_kg()
    by_geo: Dict[str, Dict[float, Dict[str, float]]] = {}
    for r in sheet_rows:
        geo = r.get("country", "")
        speed = (r.get("shipping_speed", "") or "").strip().title()
        if not geo or speed not in SPEED_PREFERENCE:
            continue
        try:
            w = round(float(r.get("weight_kg", "")), 3)
            p = float(str(r.get("shipping_charge_usd", "")).replace("$", "").replace(",", ""))
        except Exception:
            continue
        if w <= 0 or w > max_kg + 1e-9 or p <= 0:
            continue
        by_geo.setdefault(geo, {}).setdefault(w, {})[speed] = p

    out: List[Dict[str, str]] = []

    def _fmt(v: Optional[float]) -> str:
        if v is None:
            return ""
        return str(int(v)) if float(v).is_integer() else f"{v:g}"

    def _emit(name: str, tiers: Dict[float, Dict[str, float]]) -> None:
        for w in sorted(tiers):
            speeds = tiers[w]
            service = next((s for s in SPEED_PREFERENCE if s in speeds), None)
            if service is None:
                continue
            price = speeds[service]
            out.append({
                "geo": name,
                "PRICE": _fmt(price),
                "WEIGHT": _fmt(w),
                "STANDARD": _fmt(price),
                "ECONOMY": _fmt(speeds.get("Economy")),
                "EXPRESS": _fmt(speeds.get("Express")),
                "SERVICE": service,
            })

    for geo in sorted(by_geo):
        _emit(geo, by_geo[geo])
    for src, aliases in COUNTRY_ALIASES.items():
        tiers = by_geo.get(src)
        if not tiers:
            continue
        for alias in aliases:
            if alias not in by_geo:
                _emit(alias, tiers)
    if not out:
        raise RuntimeError("sheet produced zero usable matrix rows")
    return out


def write_matrix_csv(rows: List[Dict[str, str]], path: str, source: str) -> None:
    """Atomically replace `path` and write the fetched-at stamp beside it."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".shipping_matrix_", suffix=".csv", dir=d)
    try:
        with os.fdopen(fd, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(OUTPUT_COLUMNS))
            wr.writeheader()
            wr.writerows(rows)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise
    stamp = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "rows": len(rows),
        "countries": len({r["geo"] for r in rows}),
        "max_weight_kg": max_weight_kg(),
    }
    with open(stamp_path(path), "w") as f:
        json.dump(stamp, f, indent=2)
        f.write("\n")


def read_stamp(path: str) -> Optional[dict]:
    try:
        with open(stamp_path(path)) as f:
            return json.load(f)
    except Exception:
        return None


def stamp_age_hours(path: str) -> float:
    st = read_stamp(path)
    if not st:
        return float("inf")
    try:
        fetched = datetime.fromisoformat(st["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0)
    except Exception:
        return float("inf")


def refresh(path: str, url: Optional[str] = None) -> bool:
    """Fetch the sheet and rewrite `path`. Returns True on success, False (logged) on failure."""
    url = url or sheet_csv_url()
    try:
        rows = build_matrix_rows(fetch_sheet_rows(url))
        write_matrix_csv(rows, path, url)
        print(f"[matrix] refreshed {path}: {len({r['geo'] for r in rows})} GEOs, {len(rows)} rows from Google Sheet")
        return True
    except Exception as e:
        print(f"[matrix] WARN sheet refresh failed, keeping existing file ({e})")
        return False


# ------------------------------------------------------------------------------
# freshness gate used by the loaders
# ------------------------------------------------------------------------------

_lock = threading.Lock()
_last_check: Dict[str, float] = {}     # path -> monotonic time of last decision
_pending_reload: Dict[str, bool] = {}  # path -> a background refresh landed
_in_flight: Dict[str, bool] = {}


def _background_refresh(path: str) -> None:
    ok = False
    try:
        ok = refresh(path)
    finally:
        with _lock:
            _in_flight.pop(path, None)
            if ok:
                _pending_reload[path] = True
            else:
                # retry sooner than a full interval after a failure
                _last_check[path] = time.monotonic() - refresh_hours() * 3600 + 1800


def refresh_if_stale(path: str, max_age_hours: Optional[float] = None) -> bool:
    """
    Keep `path` within `max_age_hours` of the sheet. Returns True when the
    caller must reload the file (a refresh just landed). Never raises.
    """
    if not auto_refresh_enabled():
        return False
    max_age = max_age_hours or refresh_hours()
    now = time.monotonic()
    with _lock:
        if _pending_reload.pop(path, False):
            return True
        if _in_flight.get(path):
            return False
        last = _last_check.get(path)
        if last is not None and now - last < max_age * 3600:
            return False
        _last_check[path] = now
        if stamp_age_hours(path) < max_age and os.path.exists(path):
            return False
        _in_flight[path] = True

    if not os.path.exists(path):
        # nothing to serve yet: block so the first lookup has data
        ok = refresh(path)
        with _lock:
            _in_flight.pop(path, None)
        return ok

    t = threading.Thread(target=_background_refresh, args=(path,), name="shipping-matrix-refresh", daemon=True)
    t.start()
    return False


# ------------------------------------------------------------------------------
# CLI: refresh + diff report
# ------------------------------------------------------------------------------

def _read_matrix(path: str) -> Dict[str, Dict[float, float]]:
    out: Dict[str, Dict[float, float]] = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            cols = {k.strip().upper(): (v or "").strip() for k, v in r.items() if k}
            geo = cols.get("GEO", "")
            try:
                w = float(cols.get("WEIGHT", ""))
                p = float(cols.get("STANDARD") or cols.get("PRICE") or 0)
            except Exception:
                continue
            if geo:
                out.setdefault(geo, {})[w] = p
    return out


def diff_report(old: Dict[str, Dict[float, float]], new: Dict[str, Dict[float, float]],
                spotlight=("United States", "Australia", "United Kingdom", "Canada", "Germany",
                           "France", "Israel", "Japan", "Singapore", "United Arab Emirates")) -> str:
    lines = []
    og, ng = set(old), set(new)
    lines.append(f"countries: old {len(og)} -> new {len(ng)} (+{len(ng - og)} added, -{len(og - ng)} removed)")
    added = sorted(ng - og)
    if added:
        lines.append(f"  added: {', '.join(added[:40])}{' ...' if len(added) > 40 else ''}")
    removed = sorted(og - ng)
    if removed:
        lines.append(f"  removed: {', '.join(removed[:40])}{' ...' if len(removed) > 40 else ''}")
    ups = downs = same = 0
    deltas = []
    for g in og & ng:
        for w, p in old[g].items():
            q = new[g].get(w)
            if q is None:
                continue
            if abs(q - p) < 0.005:
                same += 1
            elif q > p:
                ups += 1
                deltas.append((q - p, g, w, p, q))
            else:
                downs += 1
                deltas.append((q - p, g, w, p, q))
    tot = ups + downs + same
    if tot:
        lines.append(f"tiers compared: {tot}: {ups} higher, {downs} lower, {same} unchanged")
        avg = sum(d[0] for d in deltas) / len(deltas) if deltas else 0.0
        lines.append(f"  average change on changed tiers: {avg:+.2f} USD")
    lines.append("spotlight (0.5 kg / 1 kg, old -> new):")
    for g in spotlight:
        if g in new:
            parts = []
            for w in (0.5, 1.0):
                o = old.get(g, {}).get(w)
                n = new[g].get(w)
                parts.append(f"{w:g}kg {('$%g' % o) if o is not None else '-'} -> ${n:g}" if n is not None else f"{w:g}kg -")
            lines.append(f"  {g:22s} " + " | ".join(parts))
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Refresh shipping_matrix_all.csv from the Korealy Google Sheet")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "shipping_matrix_all.csv"))
    ap.add_argument("--dry-run", action="store_true", help="only print the diff, do not write")
    a = ap.parse_args(argv)

    old = _read_matrix(a.out)
    url = sheet_csv_url()
    rows = build_matrix_rows(fetch_sheet_rows(url))
    new: Dict[str, Dict[float, float]] = {}
    for r in rows:
        new.setdefault(r["geo"], {})[float(r["WEIGHT"])] = float(r["STANDARD"])
    print(f"source: {url}")
    print(diff_report(old, new))
    if a.dry_run:
        print("(dry run — nothing written)")
        return 0
    write_matrix_csv(rows, a.out, url)
    print(f"wrote {a.out} ({len(rows)} rows) + {stamp_path(a.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
