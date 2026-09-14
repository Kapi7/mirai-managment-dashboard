# utils/date_range.py
from __future__ import annotations
from datetime import datetime, timedelta
import pytz

def local_day_window(tz_name: str, day_str: str | None = None):
    """
    Returns (start_local_dt, end_local_dt, start_utc_iso, end_utc_iso, label_YYYY_MM_DD)
    Day is inclusive at 00:00 and exclusive at next 00:00.
    """
    tz = pytz.timezone(tz_name)
    if day_str:
        base = datetime.strptime(day_str, "%Y-%m-%d").date()
    else:
        base = datetime.now(tz).date()
    # if no given day, we default to TODAY (you can pass yesterday to get yesterday)
    start_local = tz.localize(datetime.combine(base, datetime.min.time()))
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc   = end_local.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return start_local, end_local, start_utc, end_utc, start_local.strftime("%Y-%m-%d")

def month_to_date_local(tz_name: str, up_to_day_str: str | None = None):
    """
    Returns MTD window [first_of_month, next_day_of_up_to) in local tz AND UTC ISO pair.
    """
    tz = pytz.timezone(tz_name)
    if up_to_day_str:
        up_to_day = datetime.strptime(up_to_day_str, "%Y-%m-%d").date()
    else:
        up_to_day = datetime.now(tz).date()
    first = up_to_day.replace(day=1)
    start_local = tz.localize(datetime.combine(first, datetime.min.time()))
    end_local = tz.localize(datetime.combine(up_to_day + timedelta(days=1), datetime.min.time()))
    return (
        start_local,
        end_local,
        start_local.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_local.astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
