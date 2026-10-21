"""Full publish flow with fake Drive, fake Instagram and fake hosting."""
import io
import json

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from autopost import publish
from autopost.drive import FOLDER_MIME, DriveFile
from autopost.instagram import InstagramError

from .test_autopost import PDF_B


def _png(w=1086, h=1448):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (40, 40, 40)).save(b, "PNG")
    return b.getvalue()


def _pdf(text):
    b = io.BytesIO()
    c = canvas.Canvas(b)
    y = 800
    for line in text.splitlines():
        c.drawString(40, y, line)
        y -= 16
    c.save()
    return b.getvalue()


TREE = {
    "ROOT": [DriveFile("M", "2026.10", FOLDER_MIME)],
    "M": [DriveFile("D21", "21.10.2026", FOLDER_MIME), DriveFile("D20", "20.10.2026", FOLDER_MIME)],
    "D21": [DriveFile(f"P{i}", n, FOLDER_MIME) for i, n in
            [(1, "01_Fear_Of_God"), (2, "02_You_Vs_You"), (3, "03_Lock_In_Mike_Tyson")]],
    "P3": [DriveFile(f"img{i}", f"{i:02d}_shot.png", "image/png") for i in (3, 1, 12, 2, 10)]
          + [DriveFile("cap", "instagram_caption.pdf", "application/pdf")],
}
BLOBS = {"cap": _pdf(PDF_B), **{f"img{i}": _png() for i in (1, 2, 3, 10, 12)}}


class FakeDrive:
    def __init__(self):
        pass

    def list_children(self, fid):
        return TREE.get(fid, [])

    def download(self, fid):
        return BLOBS[fid]


class FakeIG:
    instances = []

    def __init__(self, token, user_id, base, reject_ratio=False):
        self.calls = []
        self.user_id = user_id
        self.reject_ratio = FakeIG.reject_ratio_next
        self.published = []
        FakeIG.instances.append(self)

    reject_ratio_next = False
    existing = []

    def me(self):
        return {"user_id": 42, "username": "test"}

    def recent_media(self, n):
        return FakeIG.existing

    def create_carousel_item(self, url):
        if self.reject_ratio and "_padded" not in url:
            raise InstagramError("The aspect ratio is not supported.", 36003, 2207009)
        self.calls.append(("item", url))
        return f"c{len(self.calls)}"

    def wait_ready(self, cid):
        pass

    def create_carousel(self, children, caption):
        self.calls.append(("carousel", children, caption))
        return "CAR"

    def publish(self, cid):
        self.published.append(cid)
        return "MEDIA1"

    def permalink(self, mid):
        return "https://instagram.com/p/abc"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "CONFIG", {**publish.CONFIG, "drive_root_folder_id": "ROOT"})
    monkeypatch.setattr(publish.drive, "Drive", FakeDrive)
    monkeypatch.setattr(publish, "Instagram", FakeIG)
    monkeypatch.setattr(publish, "STATE_FILE", tmp_path / "state.json")
    hosted = []
    monkeypatch.setattr(publish, "host_images",
                        lambda files, sub: hosted.append(sub) or [f"https://h/{sub}/{p.name}" for p in files])
    notes = []
    monkeypatch.setattr(publish, "notify", notes.append)
    monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setenv("IG_USER_ID", "1")
    FakeIG.instances.clear()
    FakeIG.reject_ratio_next = False
    FakeIG.existing = []
    return tmp_path, hosted, notes


def test_dry_run_publishes_nothing(env):
    tmp, hosted, notes = env
    assert publish.main(["--date", "2026-10-21", "--slot", "3", "--dry-run", "--preview-dir", str(tmp)]) == 0
    s = json.loads((tmp / "2026-10-21_slot3" / "summary.json").read_text())
    assert s["images"] == ["01_shot.jpg", "02_shot.jpg", "03_shot.jpg", "10_shot.jpg", "12_shot.jpg"]
    assert s["caption"].startswith("focus looks quiet.")
    assert not hosted and not FakeIG.instances


def test_publish_in_order_saves_state_and_notifies(env):
    tmp, hosted, notes = env
    assert publish.main(["--date", "2026-10-21", "--slot", "3", "--preview-dir", str(tmp)]) == 0
    ig = FakeIG.instances[0]
    items = [c[1].rsplit("/", 1)[1] for c in ig.calls if c[0] == "item"]
    assert items == ["01_shot.jpg", "02_shot.jpg", "03_shot.jpg", "10_shot.jpg", "12_shot.jpg"]
    car = [c for c in ig.calls if c[0] == "carousel"][0]
    assert car[2].endswith('shop now. "Lock In Mike Tyson". link in bio.')
    assert ig.published == ["CAR"]
    state = json.loads((tmp / "state.json").read_text())
    assert state["2026-10-21#3"]["permalink"] == "https://instagram.com/p/abc"
    assert "Lock In Mike Tyson" in notes[-1]

    # second run for the same slot (the backup cron) does nothing
    FakeIG.instances.clear()
    assert publish.main(["--date", "2026-10-21", "--slot", "3", "--preview-dir", str(tmp)]) == 0
    assert not FakeIG.instances


def test_aspect_ratio_fallback_pads(env):
    tmp, hosted, notes = env
    FakeIG.reject_ratio_next = True
    assert publish.main(["--date", "2026-10-21", "--slot", "3", "--preview-dir", str(tmp)]) == 0
    assert any(h.endswith("_padded") for h in hosted)
    padded = list((tmp / "2026-10-21_slot3" / "padded").glob("*.jpg"))
    w, h = Image.open(padded[0]).size
    assert abs(w / h - 0.8) < 0.002


def test_does_not_repost_if_caption_already_live(env):
    tmp, hosted, notes = env
    from autopost import captions
    FakeIG.existing = [{"id": "OLD", "caption": captions.clean_caption(PDF_B, "Lock In Mike Tyson"),
                        "permalink": "https://instagram.com/p/old"}]
    assert publish.main(["--date", "2026-10-21", "--slot", "3", "--preview-dir", str(tmp)]) == 0
    assert FakeIG.instances[0].published == []
    assert json.loads((tmp / "state.json").read_text())["2026-10-21#3"]["recovered"]


def test_missing_day_folder_notifies_and_fails(env):
    tmp, hosted, notes = env
    with pytest.raises(RuntimeError):
        publish.main(["--date", "2026-10-29", "--slot", "1", "--preview-dir", str(tmp)])
    assert "could not read" in notes[-1]



def test_user_id_read_from_token_when_secret_missing(env, monkeypatch):
    tmp, hosted, notes = env
    monkeypatch.delenv("IG_USER_ID")
    assert publish.main(["--date", "2026-10-21", "--slot", "3", "--preview-dir", str(tmp)]) == 0
    assert FakeIG.instances[0].user_id == "42"


def test_validate_builds_carousel_but_never_publishes(env):
    tmp, hosted, notes = env
    assert publish.main(["--date", "2026-10-21", "--slot", "3", "--validate", "--preview-dir", str(tmp)]) == 0
    ig = FakeIG.instances[0]
    assert any(c[0] == "carousel" for c in ig.calls)
    assert ig.published == []
    assert not (tmp / "state.json").exists()
    assert "NEpublikuotas" in notes[-1]


def test_review_skip_list_removes_images(env, monkeypatch, tmp_path):
    tmp, hosted, notes = env
    root = tmp_path / "root"
    (root / "review").mkdir(parents=True)
    (root / "review" / "skip.json").write_text('{"2026-10-21#3": ["01", "10"]}')
    (root / "music").mkdir()
    monkeypatch.setattr(publish, "ROOT", root)
    assert publish.main(["--date", "2026-10-21", "--slot", "3", "--preview-dir", str(tmp)]) == 0
    items = [c[1].rsplit("/", 1)[1] for c in FakeIG.instances[0].calls if c[0] == "item"]
    assert items == ["02_shot.jpg", "03_shot.jpg", "12_shot.jpg"]
    assert "removed by review" in notes[-1]


def test_auto_mode_outside_slot_does_nothing(env, monkeypatch):
    from datetime import datetime, timezone
    from autopost import schedule

    # 10:00 New York is not a posting slot
    assert schedule.slot_for(datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc),
                             publish.CONFIG["slots"], publish.CONFIG["timezone"]) is None
    # 13:05 New York (EDT) is slot 1
    assert schedule.slot_for(datetime(2026, 10, 21, 17, 5, tzinfo=timezone.utc),
                             publish.CONFIG["slots"], publish.CONFIG["timezone"]) == (
        datetime(2026, 10, 21).date(), 1)


def test_paused_scheduled_run_publishes_nothing(env, monkeypatch):
    monkeypatch.setattr(publish, "CONFIG", {**publish.CONFIG, "publishing_paused": True})
    assert publish.main(["--cron", "2 17 * * *"]) == 0
    assert publish.main(["--auto"]) == 0
    assert not FakeIG.instances
