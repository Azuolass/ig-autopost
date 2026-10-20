"""Publish one day's post (date + slot) from Google Drive to Instagram as a carousel.

    python -m autopost.publish --cron "2 17 * * *"            # what the schedule runs
    python -m autopost.publish --date 2026-10-21 --slot 1      # a specific post
    python -m autopost.publish --date 2026-10-21 --slot 1 --dry-run --preview-dir out/

--dry-run does everything except upload and publish: it downloads the images,
converts them, cleans the caption, picks the song and writes a preview.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from . import captions, drive, images, music, schedule
from .instagram import Instagram, InstagramError
from .notify import notify

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
STATE_FILE = ROOT / "state" / "published.json"


def post_key(day: date, slot: int) -> str:
    return f"{day.isoformat()}#{slot}"


# ---- media hosting: an orphan git branch served by raw.githubusercontent ----

def host_images(files: list[Path], subdir: str) -> list[str]:
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = CONFIG["media_branch"]
    work = Path(tempfile.mkdtemp(prefix="media-"))
    token = os.environ["GITHUB_TOKEN"]
    remote = f"https://x-access-token:{token}@github.com/{repo}.git"

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)

    git("init", "-q")
    git("checkout", "-q", "--orphan", branch)
    git("config", "user.name", "autopost")
    git("config", "user.email", "autopost@users.noreply.github.com")
    (work / subdir).mkdir(parents=True)
    for f in files:
        shutil.copy(f, work / subdir / f.name)
    git("add", ".")
    git("commit", "-q", "-m", f"media for {subdir}")
    # Only the current post lives on this branch; older media is not needed
    # once Instagram has copied it.
    git("push", "-q", "--force", remote, f"{branch}:{branch}")

    urls = [f"https://raw.githubusercontent.com/{repo}/{branch}/{subdir}/{f.name}" for f in files]
    deadline = time.time() + 90
    for u in urls:
        while True:
            r = requests.head(u, timeout=20)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/jpeg"):
                break
            if time.time() > deadline:
                raise RuntimeError(f"hosted image not reachable: {u} ({r.status_code})")
            time.sleep(3)
    return urls


# ---- main -------------------------------------------------------------------

def resolve_target(args) -> tuple[date, int] | None:
    if args.date:
        if not args.slot:
            sys.exit("--date needs --slot")
        return date.fromisoformat(args.date), int(args.slot)
    if args.cron:
        when = schedule.intended_utc(args.cron, datetime.now(timezone.utc))
        return schedule.slot_for(when, CONFIG["slots"], CONFIG["timezone"])
    sys.exit("give --cron or --date/--slot")


def fetch_post(day: date, slot: int):
    d = drive.Drive()
    warnings: list[str] = []
    month = drive.find_month_folder(d.list_children(CONFIG["drive_root_folder_id"]), day)
    if not month:
        raise RuntimeError(f"no month folder '{day.year}.{day.month:02d}' in the Instagram folder")
    day_folder, w = drive.find_day_folder(d.list_children(month.id), day)
    warnings += w
    if not day_folder:
        raise RuntimeError(f"no day folder '{day.day}.{day.month:02d}.{day.year}' in {month.name}")
    post_folder = drive.find_post_folder(d.list_children(day_folder.id), slot)
    if not post_folder:
        raise RuntimeError(f"no post folder starting with '{slot:02d}_' in {day_folder.name}")
    assets = drive.pick_assets(post_folder, d.list_children(post_folder.id), CONFIG["max_carousel_items"])
    assets.warnings = warnings + assets.warnings
    raw = captions.pdf_to_text(d.download(assets.caption_pdf.id))
    caption = captions.clean_caption(raw, assets.title)
    originals = [(f.name, d.download(f.id)) for f in assets.images]
    return assets, caption, originals


def convert_all(originals, out_dir: Path, pad_to: str | None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in originals:
        jpg, _ = images.to_instagram_jpeg(
            data, CONFIG["image_max_width"], CONFIG["jpeg_quality"], pad_to=pad_to
        )
        p = out_dir / (Path(name).stem + ".jpg")
        p.write_bytes(jpg)
        paths.append(p)
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cron")
    ap.add_argument("--date")
    ap.add_argument("--slot")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="publish even if state says it is done")
    ap.add_argument("--preview-dir", default="preview")
    args = ap.parse_args(argv)

    if args.cron and not os.environ.get("IG_ACCESS_TOKEN"):
        print("IG_ACCESS_TOKEN is not set yet: setup not finished, skipping scheduled run")
        return 0

    target = resolve_target(args)
    if not target:
        print("this run does not fall on a posting slot; nothing to do")
        return 0
    day, slot = target
    key = post_key(day, slot)
    state = music.load_json(STATE_FILE, {})
    if key in state and not args.force and not args.dry_run:
        print(f"{key} already published: {state[key].get('permalink')}")
        return 0

    try:
        assets, caption, originals = fetch_post(day, slot)
    except Exception as e:
        notify(f"⚠️ Instagram {key}: could not read the post from Drive.\n{e}")
        raise

    library = music.load_json(ROOT / "music" / "library.json", [])
    plan = music.load_json(ROOT / "music" / "plan.json", {})
    recent = [v.get("song") for k, v in sorted(state.items())[-6:] if v.get("song")]
    song, why = music.pick_song(key, assets.title, caption, library, plan, recent)

    work = Path(args.preview_dir) / key.replace("#", "_slot")
    jpgs = convert_all(originals, work, pad_to=None)

    summary = {
        "post": key,
        "folder": assets.folder_name,
        "title": assets.title,
        "images": [p.name for p in jpgs],
        "caption": caption,
        "song": song,
        "song_reason": why,
        "warnings": assets.warnings,
    }
    (work / "caption.txt").write_text(caption + "\n", encoding="utf-8")
    (work / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.dry_run:
        print(f"\nDRY RUN: nothing published. Preview in {work}")
        return 0

    ig = Instagram(os.environ["IG_ACCESS_TOKEN"], os.environ.get("IG_USER_ID") or "me", CONFIG["graph_api_base"])
    if ig.user_id == "me":
        ig.user_id = str(ig.me()["user_id"])

    # Safety net if a previous run published but could not save state.
    for m in ig.recent_media(10):
        if (m.get("caption") or "").strip() == caption.strip():
            print(f"identical caption already on the account: {m.get('permalink')}; not posting again")
            state[key] = {"media_id": m["id"], "permalink": m.get("permalink"), "song": song, "recovered": True}
            STATE_FILE.parent.mkdir(exist_ok=True)
            STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
            return 0

    subdir = f"{key.replace('#', '_slot')}_{int(time.time())}"
    try:
        urls = host_images(jpgs, subdir)
        try:
            children = [ig.create_carousel_item(u) for u in urls]
        except InstagramError as e:
            if not e.is_aspect_ratio:
                raise
            print(f"aspect ratio rejected ({e}); retrying padded to {CONFIG['fallback_aspect']}")
            jpgs = convert_all(originals, work / "padded", pad_to=CONFIG["fallback_aspect"])
            urls = host_images(jpgs, subdir + "_padded")
            children = [ig.create_carousel_item(u) for u in urls]
        for c in children:
            ig.wait_ready(c)
        carousel = ig.create_carousel(children, caption)
        ig.wait_ready(carousel)
        media_id = ig.publish(carousel)
        link = ig.permalink(media_id)
    except Exception as e:
        notify(f"❌ Instagram {key} ({assets.title}) FAILED to publish.\n{e}")
        raise

    state[key] = {
        "media_id": media_id,
        "permalink": link,
        "title": assets.title,
        "images": len(jpgs),
        "song": song,
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    msg = f"✅ Išėjo: {assets.title} ({len(jpgs)} nuotr.)\n{link}"
    if song:
        msg += f"\n\n🎵 Pridėk dainą: {song}\n(⋯ → Edit → Add music)"
    else:
        msg += f"\n\n🎵 {why}"
    if assets.warnings:
        msg += "\n\n⚠️ " + "\n⚠️ ".join(assets.warnings)
    notify(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
