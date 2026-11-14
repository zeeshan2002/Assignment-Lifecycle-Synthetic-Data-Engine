"""
Timestamp helpers and a self-contained time-zone engine.

Due dates are authored in a *local* wall-clock time and converted to UTC using explicit DST rules
(US, EU, fixed-offset). Implementing the rules here (instead of relying on the OS tz database)
keeps the generated data identical on every machine, which the reproducibility check requires.
"""

from datetime import datetime, timedelta, timezone

TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
LOCAL_FMT = "%Y-%m-%dT%H:%M:%S"


def fmt(dt: datetime) -> str:
    """Aware or naive-UTC datetime -> 'YYYY-MM-DDTHH:MM:SSZ'."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(TS_FMT)


def parse(s: str) -> datetime:
    return datetime.strptime(s, TS_FMT).replace(tzinfo=timezone.utc)


def fmt_local(dt: datetime) -> str:
    return dt.strftime(LOCAL_FMT)


def parse_local(s: str) -> datetime:
    return datetime.strptime(s, LOCAL_FMT)


# zone -> (dst_rule, standard_offset_minutes)
ZONES = {
    "UTC": ("none", 0),
    "Asia/Kolkata": ("none", 330),
    "America/New_York": ("us", -300),
    "America/Los_Angeles": ("us", -480),
    "Europe/London": ("eu", 0),
}


def _nth_sunday(year: int, month: int, n: int) -> int:
    first = datetime(year, month, 1)
    return 1 + (6 - first.weekday()) % 7 + 7 * (n - 1)


def _last_sunday(year: int, month: int) -> int:
    last = datetime(year, month, 31)          # March and October both have 31 days
    return 31 - (last.weekday() + 1) % 7


def _dst_bounds(rule: str, std: int, year: int):
    """DST interval [start, end) expressed in naive UTC."""
    if rule == "us":   # 2nd Sunday of March 02:00 standard -> 1st Sunday of November 02:00 daylight
        start = datetime(year, 3, _nth_sunday(year, 3, 2), 2, 0) - timedelta(minutes=std)
        end = datetime(year, 11, _nth_sunday(year, 11, 1), 2, 0) - timedelta(minutes=std + 60)
    else:              # EU: last Sunday of March 01:00 UTC -> last Sunday of October 01:00 UTC
        start = datetime(year, 3, _last_sunday(year, 3), 1, 0)
        end = datetime(year, 10, _last_sunday(year, 10), 1, 0)
    return start, end


def utc_offset_minutes(tz: str, utc_dt: datetime) -> int:
    rule, std = ZONES[tz]
    if rule == "none":
        return std
    naive = utc_dt.replace(tzinfo=None)
    start, end = _dst_bounds(rule, std, naive.year)
    return std + 60 if start <= naive < end else std


def utc_to_local(tz: str, utc_dt: datetime) -> datetime:
    return (utc_dt + timedelta(minutes=utc_offset_minutes(tz, utc_dt))).replace(tzinfo=None)


def local_to_utc(tz: str, local_naive: datetime) -> datetime:
    """Local wall-clock -> aware UTC. Ambiguous (fall-back) times resolve to the first occurrence;
    non-existent (spring-forward) times are interpreted with the standard offset."""
    rule, std = ZONES[tz]
    offsets = [std] if rule == "none" else [std + 60, std]
    for off in offsets:
        cand = (local_naive - timedelta(minutes=off)).replace(tzinfo=timezone.utc)
        if utc_offset_minutes(tz, cand) == off:
            return cand
    return (local_naive - timedelta(minutes=std)).replace(tzinfo=timezone.utc)
