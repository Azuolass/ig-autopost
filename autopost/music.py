"""Pick the song for each post from the account's Saved audio, in order.

The Instagram API cannot attach music to carousels or read Saved audio, so
the song is added by hand after publishing (post ⋯ → Edit → Add music).
This module only decides which one.

music/library.json  Saved songs, in the order they should be used:
                    [{"title": "...", "artist": "...", "reels": "263K"}]
music/plan.json     optional manual override per post: {"2026-10-21#1": "Song – Artist"}

Rotation: each post takes the song after the one the previous post used.
After the last song it starts again from the first. Progress is kept in
state/published.json as "song_index" on each post.
"""
from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def label(song: dict) -> str:
    out = f"{song['title']} – {song['artist']}" if song.get("artist") else song["title"]
    if song.get("reels"):
        out += f" ({song['reels']} reels)"
    return out


def last_index(state: dict) -> int | None:
    """song_index of the most recent post that has one (posts ordered by key = date#slot)."""
    for key in sorted(state, reverse=True):
        idx = state[key].get("song_index")
        if isinstance(idx, int):
            return idx
    return None


def pick_song(key: str, library: list[dict], plan: dict, state: dict) -> tuple[str | None, int | None, str]:
    """Return (song label, song_index, why)."""
    if key in plan:
        return plan[key], None, "chosen in music/plan.json"
    if not library:
        return None, None, "music/library.json is empty: add your Saved songs"
    prev = last_index(state)
    idx = 0 if prev is None else (prev + 1) % len(library)
    why = f"song {idx + 1} of {len(library)}"
    if prev is not None and idx == 0:
        why += " (list finished, starting again)"
    return label(library[idx]), idx, why
