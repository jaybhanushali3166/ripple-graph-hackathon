"""Time conversion. Every stored time is an integer of UTC epoch milliseconds.

Date-only "YYYY-MM-DD" means the end of that day in Asia/Kolkata (next IST midnight
minus 1 ms). Instants are ISO 8601 with an explicit offset.
"""
import re
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def end_of_day_ms(day):
    next_midnight = datetime.combine(date.fromisoformat(day) + timedelta(days=1), time(0), tzinfo=IST)
    return round(next_midnight.timestamp() * 1000) - 1


def instant_ms(iso):
    parsed = datetime.fromisoformat(iso)
    if parsed.tzinfo is None:
        raise ValueError("instant needs a UTC offset: %r" % iso)
    return round(parsed.timestamp() * 1000)


def to_ms(value):
    """Date-only strings become end of IST day; ISO instants become their epoch ms."""
    return end_of_day_ms(value) if _DATE_RE.match(value) else instant_ms(value)


def ist_date(ms):
    """Epoch ms to the IST calendar date, for human-readable reasons."""
    return datetime.fromtimestamp(ms / 1000, IST).date().isoformat()
