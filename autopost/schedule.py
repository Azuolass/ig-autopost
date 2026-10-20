"""Work out which post (date + slot) a scheduled run is for.

GitHub cron runs in UTC, can start late, and occasionally skips a run. So the
workflow fires each slot twice (a few minutes after, then a backup ~25 min
after) for both US daylight and standard time. Each run takes the cron
expression that fired it, rebuilds the intended UTC moment, converts it to
New York time and keeps going only if that falls inside a slot's window.
The publisher's state file stops the backup from posting twice.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WINDOW_MIN = 45


def intended_utc(cron_expr: str, now_utc: datetime) -> datetime:
    minute, hour = cron_expr.split()[:2]
    t = now_utc.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if t > now_utc:  # a time later than "now" today means it was yesterday's run
        t -= timedelta(days=1)
    return t


def slot_for(when_utc: datetime, slots: dict[str, str], tz: str) -> tuple[date, int] | None:
    local = when_utc.astimezone(ZoneInfo(tz))
    for slot, at in slots.items():
        h, m = map(int, at.split(":"))
        start = local.replace(hour=h, minute=m, second=0, microsecond=0)
        if start <= local < start + timedelta(minutes=WINDOW_MIN):
            return start.date(), int(slot)
    return None


def utc_cron_lines(slots: dict[str, str], tz: str, year: int, offsets=(2, 25)) -> list[str]:
    """Every UTC cron line needed to hit every slot in both daylight and standard time."""
    lines = set()
    zone = ZoneInfo(tz)
    for probe in (date(year, 1, 15), date(year, 7, 15)):
        for at in slots.values():
            h, m = map(int, at.split(":"))
            for off in offsets:
                local = datetime(probe.year, probe.month, probe.day, h, m, tzinfo=zone) + timedelta(minutes=off)
                u = local.astimezone(timezone.utc)
                lines.add(f"{u.minute} {u.hour} * * *")
    return sorted(lines, key=lambda s: (int(s.split()[1]), int(s.split()[0])))
