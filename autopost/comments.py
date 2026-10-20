"""Reply to comments under the account's own posts, using the templates in replies/templates.json.

Runs every 15 minutes. For each recent post it reads the top-level comments and,
for comments not handled yet:

  * skips our own comments, spam, and comments we (or a person on the team)
    already replied to;
  * matches the text against the templates (first two matches, in file order)
    and replies "@username <template>";
  * if nothing matches but it is praise, replies with a short thank-you;
  * customer-issue templates (damaged, order status, returns...) and questions
    nothing matched are also sent to Discord for a person to follow up.

The first run only records existing comments, so old comments get no replies.

    python -m autopost.comments            # live
    python -m autopost.comments --dry-run  # print what it would reply, change nothing
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .instagram import Instagram, InstagramError
from .notify import notify

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
STATE_FILE = ROOT / "state" / "comments.json"
TEMPLATES_FILE = ROOT / "replies" / "templates.json"
SITE = "successhuntersprints.com"


# ---- matching (pure, unit-tested) -------------------------------------------------

def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]


class Matcher:
    def __init__(self, data: dict):
        self.templates = [(t, _compile(t["triggers"])) for t in data["templates"]]
        praise = data.get("praise", {})
        self.praise_on = praise.get("enabled", False)
        self.praise = _compile(praise.get("triggers", []))
        self.praise_replies = praise.get("replies", [])
        self.spam = _compile(data.get("spam", []))

    def is_spam(self, text: str) -> bool:
        return any(p.search(text) for p in self.spam)

    def templates_for(self, text: str, limit: int = 2) -> list[dict]:
        hits = [t for t, pats in self.templates if any(p.search(text) for p in pats)]
        excluded = {x for t in hits for x in t.get("excludes", [])}
        hits = [t for t in hits if t["id"] not in excluded]
        if hits and hits[0].get("alert"):
            return hits[:1]  # a customer issue gets its own focused answer
        return hits[:limit]

    def is_praise(self, text: str) -> bool:
        return self.praise_on and any(p.search(text) for p in self.praise)


def combine(templates: list[dict]) -> str:
    """Join template replies; the shop link appears only once."""
    parts: list[str] = []
    site_seen = False
    for t in templates:
        lines = []
        for para in t["reply"].split("\n\n"):
            if SITE in para and site_seen and para.strip().lower().startswith(
                ("explore", "check", "shop", "you can find", "successhuntersprints")
            ):
                continue
            lines.append(para)
        text = "\n\n".join(lines)
        site_seen = site_seen or SITE in text
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def decide(text: str, matcher: Matcher, rng: random.Random) -> tuple[str | None, list[str], bool, str]:
    """Return (reply or None, template ids, alert, reason)."""
    if matcher.is_spam(text):
        return None, [], False, "spam"
    hits = matcher.templates_for(text)
    if hits:
        return combine(hits), [t["id"] for t in hits], any(t.get("alert") for t in hits), "template"
    if matcher.is_praise(text):
        return rng.choice(matcher.praise_replies), ["praise"], False, "praise"
    if "?" in text:
        return None, [], True, "unanswered question"
    return None, [], False, "no match"


# ---- state ------------------------------------------------------------------------

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        return {"initialized": False, "seen": {}}


def save_state(state: dict) -> None:
    # forget comments older than 45 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v.get("ts", "9") >= cutoff}
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False))


# ---- main -------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not os.environ.get("IG_ACCESS_TOKEN"):
        print("IG_ACCESS_TOKEN not set; skipping")
        return 0
    cfg = CONFIG.get("comments", {})
    if not cfg.get("enabled", True) and not args.dry_run:
        print("comment replies disabled in config.json")
        return 0

    matcher = Matcher(json.loads(TEMPLATES_FILE.read_text()))
    ig = Instagram(os.environ["IG_ACCESS_TOKEN"], os.environ.get("IG_USER_ID") or "me", CONFIG["graph_api_base"])
    me = ig.me()
    ig.user_id = str(me["user_id"])
    my_name = (me.get("username") or "").lower()

    now = datetime.now(timezone.utc)
    max_age = timedelta(days=cfg.get("max_comment_age_days", 7))
    media = ig._call("GET", f"{ig.user_id}/media", fields="id,caption,permalink,timestamp,comments_count",
                     limit=cfg.get("watch_posts", 15)).get("data", [])

    state = load_state()
    # a dry run shows decisions for existing comments too, and saves nothing
    first_run = not state.get("initialized") and not args.dry_run
    rng = random.Random()
    budget = cfg.get("max_replies_per_run", 20)
    alerts: list[str] = []
    replied = 0

    for m in media:
        try:
            comments = ig._call(
                "GET", f"{m['id']}/comments",
                fields="id,text,username,timestamp,replies{username}", limit=50,
            ).get("data", [])
        except InstagramError as e:
            print(f"cannot read comments of {m['id']}: {e}")
            alerts.append(f"• Nepavyko perskaityti komentarų: {e}")
            continue
        print(f"post {m.get('timestamp', '')[:10]} {m.get('permalink', '')}: "
              f"{len(comments)} comments readable, comments_count={m.get('comments_count')}")
        for c in comments:
            cid = c["id"]
            if cid in state["seen"]:
                continue
            record = {"ts": c.get("timestamp", now.isoformat())}
            state["seen"][cid] = record
            user = (c.get("username") or "").lower()
            text = c.get("text") or ""
            if first_run or user == my_name:
                record["action"] = "baseline" if first_run else "own"
                continue
            ts = c.get("timestamp")
            if ts and now - datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z") > max_age:
                record["action"] = "too old"
                if args.dry_run:
                    print(f"  (too old) @{c.get('username')}: {text[:80]}")
                continue
            if any((r.get("username") or "").lower() == my_name for r in (c.get("replies") or {}).get("data", [])):
                record["action"] = "already answered"
                continue

            reply, ids, alert, reason = decide(text, matcher, rng)
            record.update({"action": reason, "templates": ids})
            if reply and budget > 0:
                message = f"@{c.get('username')} {reply}" if c.get("username") else reply
                if args.dry_run:
                    print(f"\n[{reason}: {', '.join(ids)}] @{c.get('username')}: {text}\n--> {message}")
                else:
                    try:
                        ig._call("POST", f"{cid}/replies", message=message)
                        replied += 1
                        budget -= 1
                        time.sleep(cfg.get("seconds_between_replies", 4))
                    except InstagramError as e:
                        record["action"] = f"reply failed: {e}"
                        alert = True
            elif reply:
                record["action"] = "deferred (reply budget used)"
                del state["seen"][cid]  # try again next run
            elif args.dry_run:
                print(f"\n[{reason}] @{c.get('username')}: {text}\n--> (no reply)")
            if alert:
                what = "atsakyta šablonu, bet reikia žmogaus DM'e" if reply else "neatsakytas klausimas"
                alerts.append(f"• @{c.get('username')}: „{text[:200]}\"\n  ({what}) {m.get('permalink', '')}")

    if first_run:
        state["initialized"] = True
        print(f"first run: recorded {len(state['seen'])} existing comments, no replies sent")
    if alerts and not args.dry_run:
        notify("💬 Komentarai, kuriems reikia žmogaus:\n" + "\n".join(alerts[:15]))
    elif alerts:
        print("\nWOULD ALERT:\n" + "\n".join(alerts))
    if not args.dry_run:
        save_state(state)
    print(f"\nreplied: {replied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
