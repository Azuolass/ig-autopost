"""Tell the owner when a post reaches the like threshold, so the like count can be un-hidden.

The Instagram API cannot hide or un-hide like counts, it can only read them.
This runs every hour, looks at the account's most recent posts (automatic and
manual ones) and sends one Discord message per post when it crosses
`likes_threshold`. Already-notified posts are remembered in state/likes.json.

    python -m autopost.likes
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .instagram import Instagram
from .notify import notify

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
STATE_FILE = ROOT / "state" / "likes.json"


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        return {"notified": {}, "warned_missing": False, "initialized": False}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def title_of(caption: str | None) -> str:
    """The product name from the CTA line, else the first line of the caption."""
    caption = caption or ""
    import re

    m = re.search(r'"([^"]+)"', caption)
    if m:
        return m.group(1)
    first = caption.strip().split("\n")[0]
    return (first[:40] + "…") if len(first) > 40 else first or "postas"


def check(media: list[dict], state: dict, threshold: int, now: datetime, max_age_days: int) -> list[str]:
    """Return messages to send; updates state in place."""
    messages: list[str] = []
    missing = 0
    for m in media:
        mid = m["id"]
        if mid in state["notified"]:
            continue
        ts = m.get("timestamp")
        if ts:
            posted = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
            if now - posted > timedelta(days=max_age_days):
                continue
        likes = m.get("like_count")
        if likes is None:
            missing += 1
            continue
        if likes >= threshold:
            state["notified"][mid] = {"likes": likes, "at": now.isoformat(timespec="seconds")}
            messages.append(
                f"🎉 „{title_of(m.get('caption'))}\" pasiekė {likes} like'ų.\n"
                f"Atslėpk like'us: ⋯ → Unhide like count\n{m.get('permalink', '')}"
            )
    if missing and not state.get("warned_missing"):
        state["warned_missing"] = True
        messages.append(
            f"⚠️ Instagram negrąžina like'ų skaičiaus {missing} postams su paslėptais like'ais, "
            "todėl 500 like'ų stebėjimas jiems neveikia. Reikės kito sprendimo."
        )
    return messages


def main() -> int:
    if not os.environ.get("IG_ACCESS_TOKEN"):
        print("IG_ACCESS_TOKEN not set; skipping")
        return 0
    ig = Instagram(os.environ["IG_ACCESS_TOKEN"], os.environ.get("IG_USER_ID") or "me", CONFIG["graph_api_base"])
    if ig.user_id == "me":
        ig.user_id = str(ig.me()["user_id"])
    media = ig._call(
        "GET", f"{ig.user_id}/media", fields="id,caption,like_count,timestamp,permalink",
        limit=CONFIG.get("likes_watch_posts", 25),
    ).get("data", [])
    # The /media edge may hide like_count when the owner hides likes; a direct
    # query on each post by its owner returns the real number.
    for m in media:
        if m.get("like_count") is None or m.get("like_count") == 0:
            try:
                m["like_count"] = ig._call("GET", m["id"], fields="like_count").get("like_count")
            except Exception as e:
                print(f"could not read likes of {m['id']}: {e}")
    state = load_state()
    if not state.get("initialized"):
        # first run: posts already over the threshold are remembered silently
        threshold = CONFIG.get("likes_threshold", 500)
        for m in media:
            if (m.get("like_count") or 0) >= threshold:
                state["notified"][m["id"]] = {"likes": m["like_count"], "baseline": True}
        state["initialized"] = True
    msgs = check(media, state, CONFIG.get("likes_threshold", 500), datetime.now(timezone.utc),
                 CONFIG.get("likes_watch_days", 30))
    for msg in msgs:
        notify(msg)
    for m in media[:6]:
        print(f"{m.get('timestamp', '')[:16]}  likes={m.get('like_count')}  {title_of(m.get('caption'))}")
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
