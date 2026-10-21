from datetime import datetime
from zoneinfo import ZoneInfo

from autopost.queue import due

ITEMS = [{"date": "2026-10-22", "slot": 1, "at": "2026-10-22 04:00"},
         {"date": "2026-10-22", "slot": 2, "at": "2026-10-22 07:00"}]


def test_only_due_and_unpublished():
    now = datetime(2026, 10, 22, 4, 1, tzinfo=ZoneInfo("Europe/Vilnius"))
    assert [d["key"] for d in due(ITEMS, {}, now)] == ["2026-10-22#1"]
    assert due(ITEMS, {"2026-10-22#1": {}}, now) == []
    early = datetime(2026, 10, 22, 3, 59, tzinfo=ZoneInfo("Europe/Vilnius"))
    assert due(ITEMS, {}, early) == []
