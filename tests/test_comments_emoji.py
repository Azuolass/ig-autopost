import json
import random
from pathlib import Path

from autopost.comments import Matcher, decide

DATA = json.loads((Path(__file__).resolve().parent.parent / "replies" / "templates.json").read_text())
EMOJI = DATA["emoji_only"]["replies"]


def test_emoji_only_comment_gets_one_emoji():
    m = Matcher(DATA)
    for text in ["🔥🔥🔥", "❤️", " 😍😍 ", "🌟❤️✌️❤️🌟", "💜💛🐍♾️"]:
        reply, ids, alert, reason = decide(text, m, random.Random(1))
        assert reason == "emoji" and reply in EMOJI and not alert


def test_text_with_emoji_is_not_emoji_only():
    m = Matcher(DATA)
    assert decide("I need this 🔥", m, random.Random(1))[3] == "template"
    assert decide("Facts 🔥", m, random.Random(1))[3] == "agreement"
    assert decide("so beautiful 🔥", m, random.Random(1))[3] == "praise"


def test_never_thinking_or_shush_emoji():
    for pool in (EMOJI, DATA["praise"]["replies"], DATA["agreement"]["replies"]):
        assert not any("🤔" in r or "🤫" in r for r in pool)


def test_mention_of_our_account_is_ignored():
    m = Matcher(DATA)
    # the real case: "respect 🫡" got 🤔
    assert decide("@successhunters.prints respect 🫡", m, random.Random(1))[3] == "praise"
    assert decide("@successhunters.prints 🫡💵💯", m, random.Random(1))[3] == "emoji"


def test_friend_tags_are_skipped():
    m = Matcher(DATA)
    assert decide("@some_friend", m, random.Random(1))[0] is None
    assert decide("@some_friend look at this one", m, random.Random(1))[0] is None
    assert decide("@some_friend where can i buy this?", m, random.Random(1))[3] == "template"


def test_criticism_gets_no_emoji_and_goes_to_a_person():
    m = Matcher(DATA)
    for text in ["It's supposed to be a black sheep not a wolf", "This looks wrong. Those aren't his shoes.",
                 "🔥 but this is AI", "ugly"]:
        reply, _, alert, reason = decide(text, m, random.Random(1))
        assert reply is None and alert and reason == "criticism", text


def test_order_issue_inside_praise_still_goes_to_support():
    m = Matcher(DATA)
    reply, ids, alert, _ = decide("🔥 but where is my order?", m, random.Random(1))
    assert ids == ["where_is_my_order"] and alert and "🔥" not in reply


def test_worldwide_asks_for_the_country():
    m = Matcher(DATA)
    assert decide("Do you ship worldwide?", m, random.Random(1))[0] == "which country are you ordering from?"
