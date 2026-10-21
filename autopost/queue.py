"""Publish posts listed in trigger/queue.json once their time has come.

    [{"date": "2026-10-22", "slot": 1, "at": "2026-10-22 04:00"}, ...]

"at" is Vilnius time. Run every minute by the always-on loop workflow.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import music, publish

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "trigger" / "queue.json"
TZ = ZoneInfo("Europe/Vilnius")
LATE_LIMIT = timedelta(hours=3)  # a post more than 3 h late is reported, not published


def due(items: list[dict], state: dict, now: datetime) -> list[dict]:
    out = []
    for it in items:
        key = f"{it['date']}#{it['slot']}"
        at = datetime.strptime(it["at"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        if key not in state and at <= now and not it.get("skip"):
            out.append({**it, "key": key, "late": now - at})
    return sorted(out, key=lambda x: x["at"])


def main() -> int:
    items = music.load_json(QUEUE, [])
    state = music.load_json(publish.STATE_FILE, {})
    now = datetime.now(TZ)
    for it in due(items, state, now):
        if it["late"] > LATE_LIMIT and not it.get("allow_late"):
            print(f"{it['key']} is {it['late']} late; not publishing automatically")
            publish.notify(f"⚠️ {it['key']} ({it['at']} LT) praleistas – vėluoja daugiau nei 3 val. Neįkeltas.")
            it["skip"] = True
            QUEUE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n")
            continue
        print(f"publishing {it['key']} planned for {it['at']} LT")
        try:
            publish.main(["--date", it["date"], "--slot", str(it["slot"])])
        except Exception as e:  # publish already notified; try the others
            print(f"{it['key']} failed: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
