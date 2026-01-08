# sheets_client.py — Month tab writer + header/MTD auto-bootstrap + robust retries
import os, calendar, time, random
from typing import List, Tuple, Dict, Any, Callable, Type, Optional

# Make gspread optional to avoid import errors when not installed
try:
    import gspread
    from requests import exceptions as req_exc
    HAS_GSPREAD = True
    # Store WorksheetNotFound for use in except clauses
    WorksheetNotFound = gspread.WorksheetNotFound
except ImportError:
    gspread = None
    req_exc = None
    HAS_GSPREAD = False
    # Fallback exception class that will never match (since HAS_GSPREAD is False)
    WorksheetNotFound = type('WorksheetNotFound', (Exception,), {})
    print("⚠️ gspread not installed - Google Sheets integration disabled")

try:
    from gspread_formatting import (
        CellFormat, NumberFormat, TextFormat, Color,
        format_cell_range, set_frozen, set_column_width,
        ConditionalFormatRule, BooleanRule, BooleanCondition,
        get_conditional_format_rules,
    )
    HAS_FMT = True
except Exception:
    HAS_FMT = False

SHEET_ID_ENV = "GOOGLE_SHEET_ID_MASTER"
OAUTH_DIR_ENV = "GOOGLE_OAUTH_DIR"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ---------------- retries ----------------
def _with_retries(
    fn: Callable, *args, _tries: int = 6, _base: float = 0.8, _max_sleep: float = 8.0,
    _retry_on: Tuple[Type[BaseException], ...] = None,
    **kwargs,
):
    # Build default retry exceptions only if gspread is available
    if _retry_on is None:
        if HAS_GSPREAD and gspread and req_exc:
            _retry_on = (
                gspread.exceptions.APIError,
                req_exc.ConnectionError,
                req_exc.Timeout,
                req_exc.ChunkedEncodingError,
            )
        else:
            _retry_on = (Exception,)  # Fallback to generic exception

    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except _retry_on as e:
            if HAS_GSPREAD and gspread and isinstance(e, gspread.exceptions.APIError):
                resp = getattr(e, "response", None)
                status = getattr(resp, "status_code", None)
                if status not in (500, 502, 503, 504, 429, None):
                    raise
            attempt += 1
            if attempt >= _tries:
                raise
            sleep = min(_max_sleep, _base * (2 ** (attempt - 1)))
            sleep *= random.uniform(0.5, 1.5)
            time.sleep(sleep)


# ---------------- gspread client ----------------
def _client():
    if not HAS_GSPREAD:
        raise RuntimeError("gspread not installed")
    from pathlib import Path
    oauth_dir = Path(os.getenv(OAUTH_DIR_ENV, ".google_oauth"))
    oauth_dir.mkdir(parents=True, exist_ok=True)
    cs = oauth_dir / "client_secret.json"
    tk = oauth_dir / "token.json"
    if not cs.exists():
        raise RuntimeError(f"Missing OAuth client at {cs}")
    return gspread.oauth(
        credentials_filename=str(cs),
        authorized_user_filename=str(tk),
        scopes=SCOPES,
    )

def _open_sheet():
    if not HAS_GSPREAD:
        raise RuntimeError("gspread not installed")
    sheet_id = (os.getenv(SHEET_ID_ENV) or "").strip()
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID_MASTER not set in env")
    client = _with_retries(_client)
    return _with_retries(client.open_by_key, sheet_id)


# ---------------- worksheet helpers ----------------
def ensure_month_tab(month_label: str) -> Tuple[Any, Any]:
    if not HAS_GSPREAD:
        raise RuntimeError("gspread not installed - Google Sheets integration unavailable")
    sh = _open_sheet()
    try:
        ws = _with_retries(sh.worksheet, month_label)
    except WorksheetNotFound:
        ws = _with_retries(sh.add_worksheet, title=month_label, rows=2000, cols=30)
    return sh, ws


def _header_matches(existing: List[str], expected: List[str]) -> bool:
    ex = [str(x).strip() for x in existing if str(x).strip() != ""]
    exp = [str(x).strip() for x in expected]
    return ex == exp


def ensure_month_layout(ws, headers: List[str], year: int, month: int) -> None:
    """
    Guarantees:
      - Row 1 has headers (A1:S1)
      - Worksheet has enough rows for day rows + MTD row
      - MTD row exists (formulas)
      - Formatting applied (optional)
    """
    days_in_month = calendar.monthrange(year, month)[1]

    # We use:
    # Row 1 = headers
    # Row 2..(days_in_month+1) = daily rows
    # Row (days_in_month+2) = MTD
    mtd_row_idx = days_in_month + 2

    # 1) Ensure headers
    existing = _with_retries(ws.row_values, 1) or []
    if not _header_matches(existing, headers):
        print(f"[Sheets] Writing headers on '{ws.title}'...")
        _with_retries(ws.update, "A1", [headers], value_input_option="USER_ENTERED")

    # 2) Ensure size
    need_rows = mtd_row_idx
    if ws.row_count < need_rows:
        _with_retries(ws.resize, rows=need_rows)

        # 3) Ensure MTD formulas row
    # Columns A..T (20 columns) matching MONTH_HEADERS in master_report_mirai.py
    A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T = list("ABCDEFGHIJKLMNOPQRST")
    start = 2
    end = 1 + days_in_month

    orders_total    = f"=SUM({B}{start}:{B}{end})"
    gross_total     = f"=SUM({C}{start}:{C}{end})"
    disc_total      = f"=SUM({D}{start}:{D}{end})"
    refunds_total   = f"=SUM({E}{start}:{E}{end})"
    net_total       = f"=SUM({F}{start}:{F}{end})"
    cogs_total      = f"=SUM({G}{start}:{G}{end})"
    shipchg_total   = f"=SUM({H}{start}:{H}{end})"

    # IMPORTANT: Est Shipping (Matrix) is I; PayPal shipping is J (info only)
    ship_est_total  = f"=SUM({I}{start}:{I}{end})"
    ship_pp_total   = f"=SUM({J}{start}:{J}{end})"

    g_spend_total   = f"=SUM({K}{start}:{K}{end})"
    m_spend_total   = f"=SUM({L}{start}:{L}{end})"
    tot_spend_total = f"=SUM({M}{start}:{M}{end})"
    psp_total       = f"=SUM({N}{start}:{N}{end})"

    returning_total = f"=SUM({S}{start}:{S}{end})"

    # Operational Profit must match Telegram / master_report:
    # operational = (net + ship_charged) - est_ship_matrix - cogs - psp
    oper_total   = f"=({F}{mtd_row_idx}+{H}{mtd_row_idx})-{I}{mtd_row_idx}-{G}{mtd_row_idx}-{N}{mtd_row_idx}"

    # Net Margin = operational - total spend
    margin_total = f"={O}{mtd_row_idx}-{M}{mtd_row_idx}"

    # Margin % = margin / (net + ship_charged)
    margin_pct   = f"=IFERROR({P}{mtd_row_idx}/({F}{mtd_row_idx}+{H}{mtd_row_idx}),0)"

    aov_total     = f"=IFERROR({C}{mtd_row_idx}/{B}{mtd_row_idx},0)"
    gen_cpa_total = f"=IFERROR({M}{mtd_row_idx}/{B}{mtd_row_idx},0)"

    mtd_row = [
        "MTD",
        orders_total, gross_total, disc_total, refunds_total, net_total,
        cogs_total, shipchg_total,
        ship_est_total, ship_pp_total,
        g_spend_total, m_spend_total, tot_spend_total,
        psp_total,
        oper_total, margin_total, margin_pct,
        aov_total, returning_total, gen_cpa_total
    ]

    _with_retries(ws.update, f"A{mtd_row_idx}", [mtd_row], value_input_option="USER_ENTERED")


    # 4) Formatting (optional)
    if not HAS_FMT:
        return

    end_row = mtd_row_idx
    _with_retries(set_frozen, ws, rows=1)

    header_fmt = CellFormat(
        backgroundColor=Color(0.10, 0.44, 0.78),
        textFormat=TextFormat(bold=True, foregroundColor=Color(1, 1, 1)),
    )
    _with_retries(format_cell_range, ws, "A1:S1", header_fmt)

    widths = {
        "A":110,"B":85,"C":120,"D":120,"E":120,"F":120,"G":120,
        "H":150,"I":140,"J":120,"K":120,"L":130,"M":120,
        "N":150,"O":120,"P":90,"Q":110,"R":160,"S":120
    }
    for c, w in widths.items():
        _with_retries(set_column_width, ws, c, w)

    money_fmt = CellFormat(numberFormat=NumberFormat(type="NUMBER", pattern="$#,##0.00"))
    pct_fmt   = CellFormat(numberFormat=NumberFormat(type="PERCENT", pattern="0.00%"))
    int_fmt   = CellFormat(numberFormat=NumberFormat(type="NUMBER", pattern="0"))

    # Money columns
    _with_retries(format_cell_range, ws, f"C2:O{end_row}", money_fmt)
    _with_retries(format_cell_range, ws, f"Q2:Q{end_row}", money_fmt)
    _with_retries(format_cell_range, ws, f"S2:S{end_row}", money_fmt)
    _with_retries(format_cell_range, ws, f"P2:P{end_row}", pct_fmt)
    _with_retries(format_cell_range, ws, f"B2:B{end_row}", int_fmt)
    _with_retries(format_cell_range, ws, f"R2:R{end_row}", int_fmt)

    # Conditional formatting on Margin (O)
    rules = _with_retries(get_conditional_format_rules, ws)
    del rules[:]

    rules.append(ConditionalFormatRule(
        ranges=[{"sheetId": ws.id,"startRowIndex": 1,"endRowIndex": end_row,
                 "startColumnIndex": 14, "endColumnIndex": 15}],  # O
        booleanRule=BooleanRule(
            condition=BooleanCondition("NUMBER_GREATER_THAN_EQ", ["0"]),
            format=CellFormat(backgroundColor=Color(0.85, 0.95, 0.85)),
        ),
    ))
    rules.append(ConditionalFormatRule(
        ranges=[{"sheetId": ws.id,"startRowIndex": 1,"endRowIndex": end_row,
                 "startColumnIndex": 14, "endColumnIndex": 15}],
        booleanRule=BooleanRule(
            condition=BooleanCondition("NUMBER_LESS", ["0"]),
            format=CellFormat(backgroundColor=Color(0.97, 0.85, 0.85)),
        ),
    ))
    _with_retries(rules.save)


def update_single_day_row(ws, day_int: int, row_data: List[Any], *, year: int, month: int, headers: List[str]) -> None:
    """
    Updates ONLY the row corresponding to the specific day number.
    Day 1 is row 2 (row 1 is header), so day X is row X + 1.

    Also ensures headers + MTD row exist (bootstrap).
    """
    ensure_month_layout(ws, headers=headers, year=year, month=month)

    row_idx = day_int + 1
    range_name = f"A{row_idx}"

    print(f"[Sheets] Patching single day: Row {row_idx} (Day {day_int}) on '{ws.title}'")
    _with_retries(ws.update, range_name, [row_data], value_input_option="USER_ENTERED")
