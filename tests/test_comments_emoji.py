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
    assert decide("Facts 🔥", m, random.Random(1))[3] == "praise"
