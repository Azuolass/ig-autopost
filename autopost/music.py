"""Suggest a song from the account's Saved audio for each post.

The Instagram API cannot attach music to carousels or read Saved audio, so
the song is added by hand after publishing (post ⋯ → Edit → Add music).
This module only picks which one.

music/library.json  the Saved songs:   [{"title": "...", "artist": "...", "tags": ["calm", "dark"]}]
music/plan.json     manual overrides:  {"2026-10-21#1": "Song title"}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# words in a post's title/caption -> moods that suit it
KEYWORD_MOODS: dict[str, list[str]] = {
    r"lock in|focus|quiet|silence|calm|patience": ["calm", "focus", "dark"],
    r"fear|god|faith|pray|believe": ["epic", "cinematic", "spiritual"],
    r"tyson|box|fight|war|warrior|beast|savage": ["intense", "aggressive", "dark"],
    r"curry|kobe|jordan|lebron|ball|court|basketball": ["hype", "confident", "hip-hop"],
    r"you vs you|version|discipline|reps|standard|work|grind": ["motivational", "focus", "confident"],
    r"all in|win|champion|legend|king|greatness": ["epic", "hype", "motivational"],
}


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def moods_for(text: str) -> list[str]:
    text = text.lower()
    moods: list[str] = []
    for pattern, ms in KEYWORD_MOODS.items():
        if re.search(pattern, text):
            moods += [m for m in ms if m not in moods]
    return moods


def pick_song(
    key: str, title: str, caption: str, library: list[dict], plan: dict, recent: list[str]
) -> tuple[str | None, str]:
    """Return (song label, why)."""
    if key in plan:
        return plan[key], "chosen in music/plan.json"
    if not library:
        return None, "music/library.json is empty: add your Saved songs"
    wanted = moods_for(f"{title} {caption}")

    def label(s: dict) -> str:
        return f"{s['title']} – {s['artist']}" if s.get("artist") else s["title"]

    def score(s: dict) -> tuple[int, int]:
        tags = [t.lower() for t in s.get("tags", [])]
        match = sum(len(wanted) - i for i, m in enumerate(wanted) if m in tags)
        fresh = 0 if label(s) in recent else 1
        return (fresh, match)

    best = max(library, key=score)
    hit = [m for m in wanted if m in [t.lower() for t in best.get("tags", [])]]
    why = f"matches {', '.join(hit)}" if hit else "no tag match, least recently used"
    return label(best), why
