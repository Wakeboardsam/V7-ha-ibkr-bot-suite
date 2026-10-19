"""
The weekend bot pause: from a Friday time to a Sunday time, in the add-on's
time zone, the bot and its Gateway are off.

The engine uses pause_end() to stop on Friday. run.sh calls this file as a
script before it starts the Gateway, and waits out the pause when one is
active. This file uses only the standard library.
"""
import argparse
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

FRIDAY = 4
SUNDAY = 6


def parse_hhmm(value: str) -> time:
    hour, minute = value.strip().split(":")
    return time(int(hour), int(minute))


def pause_end(now: datetime, start_friday: str, end_sunday: str) -> Optional[datetime]:
    """
    The Sunday time the pause ends at, when `now` is inside the pause; otherwise
    None. `now` must be aware and in the add-on's time zone.
    """
    start = parse_hhmm(start_friday)
    end = parse_hhmm(end_sunday)
    days_to_sunday = (SUNDAY - now.weekday()) % 7
    sunday: date = (now + timedelta(days=days_to_sunday)).date()
    friday = sunday - timedelta(days=2)
    start_dt = datetime.combine(friday, start, tzinfo=now.tzinfo)
    end_dt = datetime.combine(sunday, end, tzinfo=now.tzinfo)
    if start_dt <= now < end_dt:
        return end_dt
    return None


def seconds_until(now: datetime, later: datetime) -> int:
    """Real seconds between two aware times, correct across a daylight-saving change."""
    return max(0, int((later.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prints the seconds left in the weekend pause (0 when not paused).")
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--start", required=True, help="Friday HH:MM")
    parser.add_argument("--end", required=True, help="Sunday HH:MM")
    args = parser.parse_args(argv)

    now = datetime.now(ZoneInfo(args.timezone))
    end = pause_end(now, args.start, args.end)
    print(seconds_until(now, end) if end else 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
