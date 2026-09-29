"""The operator's timezone, read from config.

`operator_timezone` takes an IANA zone name ("Asia/Tokyo", "Europe/London", "America/New_York"), so
daylight-saving shifts are handled. If it is unset or unknown, `operator_tz_offset_hours` (a fixed
hour offset from UTC, default 0) is used instead. Brief dates, the weekly scrape calendar, the
Monday reset and the slot hours are all computed in this zone.
"""
from datetime import timezone, timedelta


def operator_tz(cfg):
    cfg = cfg or {}
    name = cfg.get("operator_timezone")
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(str(name))
        except Exception as e:
            print(f"  operator_timezone {name!r} not usable ({type(e).__name__}); "
                  f"using operator_tz_offset_hours. On Windows run: pip install tzdata")
    return timezone(timedelta(hours=float(cfg.get("operator_tz_offset_hours", 0))))
