import json
import pathlib
import random

import pytest

from autopost.comments import Matcher, combine, decide

DATA = json.loads((pathlib.Path(__file__).resolve().parent.parent / "replies" / "templates.json").read_text())
M = Matcher(DATA)
RNG = random.Random(1)


def ids(text):
    return decide(text, M, RNG)[1]


@pytest.mark.parametrize("text, expected", [
    ("how much is this?", ["price"]),
    ("Price?", ["price"]),
    ("what sizes do you have", ["sizes"]),
    ("do you ship to Canada?", ["worldwide"]),
    ("do you ship to the US?", ["usa", "worldwide"]),
    ("Is this canvas or a poster", ["canvas_or_poster"]),
    ("framed?", ["framed"]),
    ("where can I buy this", ["where_to_buy"]),
    ("I need this for my gym 🔥", ["where_to_buy"]),
    ("link?", ["where_to_buy"]),
    ("can I get a custom size 72x48?", ["custom_size"]),
    ("my canvas arrived damaged", ["damaged"]),
    ("where is my order??", ["where_is_my_order"]),
    ("how long does shipping take to USA", ["usa", "shipping_time"]),
    ("how long does it take to ship to Canada", ["shipping_time", "worldwide"]),
    ("any discount code?", ["discount"]),
    ("how much and how long to ship?", ["price", "shipping_time"]),
])
def test_template_matching(text, expected):
    assert ids(text) == expected


def test_praise_and_noise():
    assert ids("🔥🔥🔥") == ["emoji"]
    assert ids("this goes hard") == ["praise"]
    assert decide("ok", M, RNG)[0] is None
    reply, _, alert, reason = decide("who is the guy in the picture?", M, RNG)
    assert reply is None and alert and reason == "unanswered question"


def test_spam_is_ignored_even_with_trigger_words():
    assert decide("Promote it on @bestpage for a low price", M, RNG)[3] == "spam"
    assert decide("nice! check https://spam.example", M, RNG)[3] == "spam"


def test_issue_templates_alert_people():
    reply, _, alert, _ = decide("I want a refund", M, RNG)
    assert reply and alert
    assert decide("how much?", M, RNG)[2] is False


def test_combined_reply_has_shop_link_once():
    text = decide("how much and what sizes?", M, RNG)[0]
    assert text.count("successhuntersprints.com") == 1
    assert "18x12" in text and "Prices depend" in text


def test_all_replies_fit_in_a_comment():
    for t in DATA["templates"]:
        assert len(t["reply"]) < 400
        assert "Send us your" not in t["reply"]  # public comment: always 'send us a DM'
