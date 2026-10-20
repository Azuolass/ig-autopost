import io
from datetime import date, datetime, timezone

import pytest
from PIL import Image

from autopost import captions, drive, images, music, schedule
from autopost.drive import FOLDER_MIME, DriveFile
from autopost.instagram import InstagramError

SLOTS = {"1": "13:00", "2": "17:00", "3": "21:00"}
TZ = "America/New_York"

# Real text from the Drive PDFs (as pypdf extracts it).
PDF_A = """1 puslapis iš 1

20 October 2026 Post 2

You Vs You Stephen Curry

Instagram caption

your last version is the one to beat.

keep showing up for the reps. fix what needs fixing. give yourself something

better to measure against tomorrow.

put the standard on your wall. this wall art belongs where you do the work.

shop now. "You Vs You Stephen Curry". link in bio.
"""

PDF_B = """SUCCESS HUNTERS / 20.10.2026 / POST 3

Lock In Mike Tyson

focus looks quiet.

the work tells the rest.

let your room hold the standard.

shop now. "Lock In Mike Tyson". link in bio.

instagram caption
"""


# ---- captions -----------------------------------------------------------------

def test_caption_layout_a():
    assert captions.clean_caption(PDF_A, "You Vs You Stephen Curry") == (
        "your last version is the one to beat.\n"
        "keep showing up for the reps. fix what needs fixing. give yourself something better to measure against tomorrow.\n"
        "put the standard on your wall. this wall art belongs where you do the work.\n"
        'shop now. "You Vs You Stephen Curry". link in bio.'
    )


def test_caption_layout_b():
    assert captions.clean_caption(PDF_B, "Lock In Mike Tyson") == (
        "focus looks quiet.\n"
        "the work tells the rest.\n"
        "let your room hold the standard.\n"
        'shop now. "Lock In Mike Tyson". link in bio.'
    )


def test_caption_keeps_title_inside_cta():
    out = captions.clean_caption(PDF_B, "Lock In Mike Tyson")
    assert '"Lock In Mike Tyson"' in out


def test_caption_empty_raises():
    with pytest.raises(ValueError):
        captions.clean_caption("SUCCESS HUNTERS / 1.1.2026 / POST 1\ninstagram caption", None)


def test_caption_from_real_pdf_bytes(tmp_path):
    # Build a PDF with the same text and make sure extraction + cleaning works.
    from reportlab.pdfgen import canvas  # noqa: available in test env only if installed

    p = tmp_path / "c.pdf"
    c = canvas.Canvas(str(p))
    y = 800
    for line in PDF_B.splitlines():
        c.drawString(40, y, line)
        y -= 16
    c.save()
    text = captions.pdf_to_text(p.read_bytes())
    assert captions.clean_caption(text, "Lock In Mike Tyson").startswith("focus looks quiet.")


# ---- drive selection ------------------------------------------------------------

def f(name, mime="image/png", modified=""):
    return DriveFile(id=name, name=name, mime=mime, modified=modified)


def folder(name):
    return f(name, FOLDER_MIME)


def test_month_and_day_folders():
    root = [folder("2026.10"), folder("2026.11")]
    assert drive.find_month_folder(root, date(2026, 10, 21)).name == "2026.10"
    days = [folder("4.10.2026"), folder("8.10.2026"), folder("8.10.2026 vol. 2"), folder("21.10.2026")]
    got, warns = drive.find_day_folder(days, date(2026, 10, 8))
    assert got.name == "8.10.2026"
    assert any("vol. 2" in w for w in warns)
    assert drive.find_day_folder(days, date(2026, 10, 21))[0].name == "21.10.2026"
    assert drive.find_day_folder(days, date(2026, 10, 22))[0] is None


def test_post_folder_by_slot():
    posts = [folder("01_Fear_Of_God"), folder("02_You_Vs_You_Stephen_Curry"), folder("03_Lock_In_Mike_Tyson"),
             f("20-10-2026_inventory.json", "application/json")]
    assert drive.find_post_folder(posts, 3).name == "03_Lock_In_Mike_Tyson"
    assert drive.title_from_folder("02_You_Vs_You_Stephen_Curry") == "You Vs You Stephen Curry"


def test_images_ordered_numerically_and_updated_caption_preferred():
    kids = [
        f("13_model_floor_support.png"), f("02_room_wide.png"), f("10_model_holding.png"),
        f("01_original_artwork.jpg", "image/jpeg"), f("09_model_considering.png"),
        f("instagram_caption.pdf", "application/pdf", "2026-10-12"),
        f("instagram_caption_updated.pdf", "application/pdf", "2026-10-10"),
        f("instagram_caption.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ]
    a = drive.pick_assets(folder("02_X"), kids, 20)
    assert [i.name for i in a.images] == [
        "01_original_artwork.jpg", "02_room_wide.png", "09_model_considering.png",
        "10_model_holding.png", "13_model_floor_support.png",
    ]
    assert a.caption_pdf.name == "instagram_caption_updated.pdf"


def test_too_many_images_trimmed_with_warning():
    kids = [f(f"{i:02d}_x.png") for i in range(1, 23)] + [f("instagram_caption.pdf", "application/pdf")]
    a = drive.pick_assets(folder("01_X"), kids, 20)
    assert len(a.images) == 20 and a.images[-1].name == "20_x.png"
    assert a.warnings


def test_missing_caption_raises():
    with pytest.raises(RuntimeError):
        drive.pick_assets(folder("01_X"), [f("01_a.png"), f("02_b.png")], 20)


# ---- schedule -----------------------------------------------------------------

@pytest.mark.parametrize(
    "cron, now, expected",
    [
        # October, daylight time (EDT, UTC-4)
        ("2 17 * * *", datetime(2026, 10, 21, 17, 9, tzinfo=timezone.utc), (date(2026, 10, 21), 1)),
        ("2 21 * * *", datetime(2026, 10, 21, 21, 40, tzinfo=timezone.utc), (date(2026, 10, 21), 2)),
        ("2 1 * * *", datetime(2026, 10, 22, 1, 5, tzinfo=timezone.utc), (date(2026, 10, 21), 3)),
        ("25 1 * * *", datetime(2026, 10, 22, 1, 50, tzinfo=timezone.utc), (date(2026, 10, 21), 3)),
        # the standard-time lines do nothing in October
        ("2 18 * * *", datetime(2026, 10, 21, 18, 3, tzinfo=timezone.utc), None),
        ("2 2 * * *", datetime(2026, 10, 22, 2, 3, tzinfo=timezone.utc), None),
        # December, standard time (EST, UTC-5)
        ("2 18 * * *", datetime(2026, 12, 3, 18, 4, tzinfo=timezone.utc), (date(2026, 12, 3), 1)),
        ("2 2 * * *", datetime(2026, 12, 4, 2, 4, tzinfo=timezone.utc), (date(2026, 12, 3), 3)),
        ("2 17 * * *", datetime(2026, 12, 3, 17, 4, tzinfo=timezone.utc), None),
    ],
)
def test_slot_resolution(cron, now, expected):
    when = schedule.intended_utc(cron, now)
    assert schedule.slot_for(when, SLOTS, TZ) == expected


def test_late_start_still_maps_to_intended_slot():
    # cron for 01:02 UTC starts 50 minutes late
    when = schedule.intended_utc("2 1 * * *", datetime(2026, 10, 22, 1, 52, tzinfo=timezone.utc))
    assert schedule.slot_for(when, SLOTS, TZ) == (date(2026, 10, 21), 3)


def test_workflow_lists_every_cron_line():
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    cfg = json.loads((root / "config.json").read_text())
    wf = (root / ".github/workflows/publish.yml").read_text()
    for line in schedule.utc_cron_lines(cfg["slots"], cfg["timezone"], 2026):
        assert f'cron: "{line}"' in wf


def test_lithuanian_times_match_request():
    # 13/17/21 NY must be 20:00 / 00:00 / 04:00 in Vilnius once both are on normal offsets
    from zoneinfo import ZoneInfo

    ny = ZoneInfo(TZ)
    for hh, lt in [(13, "20:00"), (17, "00:00"), (21, "04:00")]:
        t = datetime(2026, 10, 21, hh, 0, tzinfo=ny).astimezone(ZoneInfo("Europe/Vilnius"))
        assert t.strftime("%H:%M") == lt


# ---- images -------------------------------------------------------------------

def png(w, h, mode="RGBA"):
    buf = io.BytesIO()
    Image.new(mode, (w, h), (30, 30, 30, 255) if mode == "RGBA" else (30, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_png_becomes_jpeg_and_keeps_ratio():
    data, size = images.to_instagram_jpeg(png(1086, 1448))
    assert data[:3] == b"\xff\xd8\xff" and size == (1086, 1448)


def test_big_original_is_downscaled():
    data, size = images.to_instagram_jpeg(png(4500, 6000, "RGB"), max_width=1440)
    assert size == (1440, 1920)
    assert len(data) < 8 * 1024 * 1024


def test_pad_to_four_five():
    _, size = images.to_instagram_jpeg(png(1086, 1448), pad_to="4:5")
    assert abs(size[0] / size[1] - 0.8) < 0.002 and size[1] == 1448


def test_aspect_error_detection():
    assert InstagramError("x", 36003, 2207009).is_aspect_ratio
    assert InstagramError("The aspect ratio is not supported.").is_aspect_ratio
    assert not InstagramError("Invalid OAuth access token", 190).is_aspect_ratio


# ---- music --------------------------------------------------------------------

LIB = [
    {"title": "Calm Song", "artist": "A", "tags": ["calm", "focus"]},
    {"title": "Hype Song", "artist": "B", "tags": ["hype", "hip-hop"]},
    {"title": "Epic Song", "artist": "C", "tags": ["epic", "cinematic"]},
]


def test_music_matches_post_mood():
    assert music.pick_song("k", "Lock In Mike Tyson", "focus looks quiet.", LIB, {}, [])[0] == "Calm Song – A"
    assert music.pick_song("k", "Fear Of God", "", LIB, {}, [])[0] == "Epic Song – C"


def test_music_plan_overrides_and_recent_avoided():
    assert music.pick_song("2026-10-21#1", "x", "", LIB, {"2026-10-21#1": "Manual"}, [])[0] == "Manual"
    got = music.pick_song("k", "Lock In", "focus", LIB, {}, ["Calm Song – A"])[0]
    assert got != "Calm Song – A"


def test_music_empty_library():
    song, why = music.pick_song("k", "x", "", [], {}, [])
    assert song is None and "library.json" in why
