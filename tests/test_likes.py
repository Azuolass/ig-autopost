from datetime import datetime, timezone

from autopost import likes

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def media(i, n, days_ago=1, caption='x\n\nshop now. "Fear Of God". link in bio.'):
    ts = NOW.replace(day=NOW.day - days_ago).strftime("%Y-%m-%dT%H:%M:%S+0000")
    m = {"id": str(i), "timestamp": ts, "permalink": f"https://instagram.com/p/{i}", "caption": caption}
    if n is not None:
        m["like_count"] = n
    return m


def test_notifies_once_when_threshold_reached():
    state = {"notified": {}, "warned_missing": False}
    msgs = likes.check([media(1, 499), media(2, 512)], state, 500, NOW, 30)
    assert len(msgs) == 1 and "Fear Of God" in msgs[0] and "512" in msgs[0]
    assert likes.check([media(1, 499), media(2, 600)], state, 500, NOW, 30) == []
    msgs = likes.check([media(1, 501)], state, 500, NOW, 30)
    assert len(msgs) == 1


def test_old_posts_ignored_and_missing_counts_warned_once():
    state = {"notified": {}, "warned_missing": False}
    assert likes.check([media(3, 9000, days_ago=20)], state, 500, NOW.replace(month=12), 30) == []
    msgs = likes.check([media(4, None)], state, 500, NOW, 30)
    assert len(msgs) == 1 and "paslėptais" in msgs[0]
    assert likes.check([media(4, None)], state, 500, NOW, 30) == []


def test_title_from_caption():
    assert likes.title_of('a\n\nshop now. "Lock In Mike Tyson". link in bio.') == "Lock In Mike Tyson"
    assert likes.title_of("no quotes here") == "no quotes here"
