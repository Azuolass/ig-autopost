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
        "your last version is the one to beat.\n\n"
        "keep showing up for the reps. fix what needs fixing. give yourself something better to measure against tomorrow.\n\n"
        "put the standard on your wall. this wall art belongs where you do the work.\n\n"
        'shop now. "You Vs You Stephen Curry". link in bio.'
    )


def test_caption_layout_b():
    assert captions.clean_caption(PDF_B, "Lock In Mike Tyson") == (
        "focus looks quiet.\n\n"
        "the work tells the rest.\n\n"
        "let your room hold the standard.\n\n"
        'shop now. "Lock In Mike Tyson". link in bio.'
    )


def test_caption_keeps_title_inside_cta():
    out = captions.clean_caption(PDF_B, "Lock In Mike Tyson")
    assert '"Lock In Mike Tyson"' in out


def test_caption_title_with_ampersand_matches_folder_name():
    raw = """SUCCESS HUNTERS / 21.10.2026 / POST 1

911 & Blackbird

some machines make you look twice.

a classic silhouette on the road. another above it.

shop now. "911 & Blackbird". link in bio.

instagram caption
"""
    out = captions.clean_caption(raw, "911 And Blackbird")
    assert out.startswith("some machines make you look twice.\n\n")
    assert out.endswith('shop now. "911 & Blackbird". link in bio.')


def _layout_pdf(path, rows):
    """rows: (y, size, text) like the real caption documents."""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    for y, size, text in rows:
        c.setFont("Helvetica", size)
        c.drawString(90, y, text)
    c.save()
    return path.read_bytes()


def test_caption_pdf_layout_keeps_paragraphs_exactly(tmp_path):
    # Same layout as the real "Fear Of God" PDF: 16pt line steps inside a
    # paragraph, ~31pt between paragraphs. Expected text = the live post.
    data = _layout_pdf(tmp_path / "fear.pdf", [
        (770, 18, "20 October 2026 Post 1"),
        (735, 11, "Fear Of God"),
        (719, 11, "Instagram caption"),
        (688, 11, "faith stays when the noise gets loud."),
        (657, 11, "stay grounded in what you believe. keep your discipline when the room is empty"),
        (641, 11, "and the work gets heavy."),
        (610, 11, "wall art for the space where you come back to your purpose."),
        (579, 11, 'shop now. "Fear Of God". link in bio.'),
    ])
    assert captions.clean_caption(captions.pdf_to_text(data), "Fear Of God") == (
        "faith stays when the noise gets loud.\n\n"
        "stay grounded in what you believe. keep your discipline when the room is empty and the work gets heavy.\n\n"
        "wall art for the space where you come back to your purpose.\n\n"
        'shop now. "Fear Of God". link in bio.'
    )


def test_caption_pdf_multi_sentence_lines_in_one_paragraph_stay_together(tmp_path):
    data = _layout_pdf(tmp_path / "x.pdf", [
        (770, 11, "SUCCESS HUNTERS / 21.10.2026 / POST 2"),
        (740, 11, "Make Money Trading"),
        (709, 11, "give your ambition a place on the wall."),
        (678, 11, "the chart moves."),
        (662, 11, "the discipline stays."),
        (631, 11, 'shop now. "Make Money Trading". link in bio.'),
        (600, 11, "instagram caption"),
    ])
    assert captions.clean_caption(captions.pdf_to_text(data), "Make Money Trading") == (
        "give your ambition a place on the wall.\n\n"
        "the chart moves.\nthe discipline stays.\n\n"
        'shop now. "Make Money Trading". link in bio.'
    )


def test_caption_tyson_layout_keeps_line_break_inside_paragraph(tmp_path):
    data = _layout_pdf(tmp_path / "t.pdf", [
        (780, 9, "SUCCESS HUNTERS / 20.10.2026 / POST 3"),
        (745, 16, "Lock In Mike Tyson"),
        (700, 11, "focus looks quiet."),
        (684, 11, "the work tells the rest."),
        (653, 11, "let your room hold the standard."),
        (622, 11, 'shop now. "Lock In Mike Tyson". link in bio.'),
    ])
    assert captions.clean_caption(captions.pdf_to_text(data), "Lock In Mike Tyson") == (
        "focus looks quiet.\nthe work tells the rest.\n\n"
        "let your room hold the standard.\n\n"
        'shop now. "Lock In Mike Tyson". link in bio.'
    )


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
    {"title": "Song A", "artist": "X", "reels": "10K"},
    {"title": "Song B", "artist": "Y"},
    {"title": "Song C", "artist": "Z"},
]


def test_music_starts_at_first_song():
    song, idx, why = music.pick_song("2026-10-21#1", LIB, {}, {})
    assert (song, idx) == ("Song A – X (10K reels)", 0)


def test_music_goes_in_order_and_wraps():
    state = {"2026-10-20#2": {"song_index": 0}, "2026-10-20#3": {"song_index": 1}}
    assert music.pick_song("2026-10-21#1", LIB, {}, state)[:2] == ("Song C – Z", 2)
    state["2026-10-21#1"] = {"song_index": 2}
    song, idx, why = music.pick_song("2026-10-21#2", LIB, {}, state)
    assert idx == 0 and "starting again" in why


def test_music_ignores_posts_without_index_and_plan_overrides():
    state = {"2026-10-20#1": {"note": "manual"}, "2026-10-20#2": {"song_index": 1}}
    assert music.pick_song("2026-10-20#3", LIB, {}, state)[1] == 2
    assert music.pick_song("k", LIB, {"k": "Manual"}, state)[0] == "Manual"


def test_music_empty_library():
    song, idx, why = music.pick_song("k", [], {}, {})
    assert song is None and "library.json" in why


def test_real_library_is_valid():
    import json
    import pathlib

    lib = json.loads((pathlib.Path(__file__).resolve().parent.parent / "music" / "library.json").read_text())
    assert len(lib) >= 100 and all(s["title"] and s["artist"] for s in lib)


def _jpeg_markers(data: bytes) -> set[int]:
    markers, i = set(), 2
    while i < len(data) - 4 and data[i] == 0xFF:
        m = data[i + 1]
        if m == 0xDA:  # start of scan
            break
        markers.add(m)
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return markers


def test_output_has_no_metadata():
    from PIL import PngImagePlugin

    meta = PngImagePlugin.PngInfo()
    meta.add_text("XML:com.adobe.xmp", '<x:xmpmeta><rdf:Description DigitalSourceType="trainedAlgorithmicMedia"/></x:xmpmeta>')
    meta.add_text("parameters", "prompt: canvas mockup, made with AI")
    meta.add_text("Software", "SomeGenerator")
    buf = io.BytesIO()
    Image.new("RGB", (400, 533), (50, 60, 70)).save(buf, "PNG", pnginfo=meta)
    out, _ = images.to_instagram_jpeg(buf.getvalue())
    # only quantisation/huffman/frame/restart markers; no APPn (EXIF, XMP, ICC, IPTC, JUMBF/C2PA) or comments
    assert not any(0xE1 <= m <= 0xEF for m in _jpeg_markers(out))
    assert 0xFE not in _jpeg_markers(out)
    for word in (b"xmp", b"trainedAlgorithmic", b"prompt", b"Generator", b"c2pa", b"jumb"):
        assert word.lower() not in out.lower()


def test_icc_profile_converted_not_kept():
    from PIL import ImageCms

    p3 = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (200, 10, 10)).save(buf, "PNG", icc_profile=p3)
    out, _ = images.to_instagram_jpeg(buf.getvalue())
    assert 0xE2 not in _jpeg_markers(out)  # APP2 = ICC
    assert Image.open(io.BytesIO(out)).getpixel((50, 50))[0] > 180


def test_new_pdf_header_is_removed():
    from autopost.captions import clean_caption
    raw = 'Pain Is Fuel Instagram caption SH IG DAILY 30 October 2026 use every setback.\n\nshop now. "Pain Is Fuel". link in bio.'
    assert clean_caption(raw).startswith("use every setback.")


def test_caption_house_style_lowercase_keeps_product_name():
    from autopost.captions import clean_caption
    raw = 'Focus Instagram caption SH IG DAILY 31 October 2026 Cut the noise.\n\nShop now. "Focus". Link in bio.'
    assert clean_caption(raw) == 'cut the noise.\n\nshop now. "Focus". link in bio.'
