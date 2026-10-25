"""Download a range of days from Drive and build:

  out/ready/<date>_<slot>_<Title>/NN_name.jpg   clean upload-ready JPEGs (no metadata, sRGB),
                                                 review removals from review/skip.json applied
  out/ready/<...>/caption.txt                   caption with paragraph spacing
  out/ready/<...>/info.json                     title, time (Vilnius), song, image list
  out/review/<...>/sheet_NN.jpg                 two images side by side for visual QA
  out/review/<...>/original_tile_N.jpg          2x2 tiles of the original artwork at high resolution

    python -m autopost.prepare --from 2026-10-21 --to 2026-10-28 --out out
"""
from __future__ import annotations

import argparse
import io
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from . import captions, drive, images, music

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())


def safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def vilnius_time(day: date, slot: int) -> str:
    h, m = map(int, CONFIG["slots"][str(slot)].split(":"))
    ny = datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfo(CONFIG["timezone"]))
    return ny.astimezone(ZoneInfo("Europe/Vilnius")).strftime("%Y-%m-%d %H:%M")


def thumb(data: bytes, height: int) -> Image.Image:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    return im.resize((round(im.width * height / im.height), height), Image.LANCZOS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--out", default="out")
    args = ap.parse_args(argv)

    out = Path(args.out)
    d = drive.Drive()
    root = d.list_children(drive.root_folder_id())
    skip_all = music.load_json(ROOT / "review" / "skip.json", {})
    library = music.load_json(ROOT / "music" / "library.json", [])
    state = music.load_json(ROOT / "state" / "published.json", {})
    song_idx = music.last_index(state)
    summary = []

    day = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    while day <= end:
        month = drive.find_month_folder(root, day)
        folder, warns = drive.find_day_folder(d.list_children(month.id), day) if month else (None, [])
        if not folder:
            summary.append({"day": day.isoformat(), "error": "no day folder"})
            day += timedelta(days=1)
            continue
        posts = d.list_children(folder.id)
        for slot in (1, 2, 3):
            key = f"{day.isoformat()}#{slot}"
            pf = drive.find_post_folder(posts, slot)
            if not pf:
                summary.append({"post": key, "error": "missing post folder"})
                continue
            try:
                a = drive.pick_assets(pf, d.list_children(pf.id), CONFIG["max_carousel_items"])
                caption = captions.clean_caption(captions.pdf_to_text(d.download(a.caption_pdf.id)), a.title)
            except Exception as e:
                summary.append({"post": key, "folder": pf.name, "error": str(e)})
                print(f"{key}: ERROR {e}")
                continue
            name = f"{day.isoformat()}_{slot}_{safe(a.title)}"
            ready = out / "ready" / name
            review = out / "review" / name
            ready.mkdir(parents=True, exist_ok=True)
            review.mkdir(parents=True, exist_ok=True)

            skip = {str(s).zfill(2) for s in skip_all.get(key, [])}
            originals, broken = [], []
            for f in a.images:
                data = None
                for _ in range(3):  # Drive downloads occasionally arrive cut short
                    try:
                        data = d.download(f.id)
                        if images.check_decodable(data) == "end-cut":
                            a.warnings.append(f"{f.name}: file end missing in Drive, picture complete, used")
                        break
                    except Exception:
                        data = None
                if data is None:
                    broken.append(f.name)
                else:
                    originals.append((f.name, data))
            if broken:
                a.warnings.append(f"BROKEN FILES in Drive (cannot be opened, left out): {broken}")

            # review sheets: two images per sheet, labelled by file name
            thumbs = [(n, thumb(b, 900)) for n, b in originals]
            for i in range(0, len(thumbs), 2):
                pair = thumbs[i:i + 2]
                w = sum(t.width for _, t in pair) + 10 * (len(pair) - 1)
                sheet = Image.new("RGB", (w, 900), (30, 30, 30))
                x = 0
                for _, t in pair:
                    sheet.paste(t, (x, 0))
                    x += t.width + 10
                sheet.save(review / f"sheet_{i // 2 + 1:02d}__{'__'.join(Path(n).stem[:2] for n, _ in pair)}.jpg",
                           quality=88)

            # original artwork at high resolution, in four tiles
            orig = next((b for n, b in originals if drive.leading_number(n) == 1), None)
            if orig:
                im = Image.open(io.BytesIO(orig)).convert("RGB")
                im = im.resize((1800, round(im.height * 1800 / im.width)), Image.LANCZOS)
                hw, hh = im.width // 2, im.height // 2
                for t, (x0, y0) in enumerate([(0, 0), (hw, 0), (0, hh), (hw, hh)], 1):
                    im.crop((x0, y0, x0 + hw, y0 + hh)).save(review / f"original_tile_{t}.jpg", quality=90)

            # upload-ready files
            kept = []
            for n, b in originals:
                num = f"{drive.leading_number(n):02d}"
                if num in skip:
                    continue
                jpg, _ = images.to_instagram_jpeg(b, CONFIG["image_max_width"], CONFIG["jpeg_quality"])
                p = ready / f"{Path(n).stem}.jpg"
                p.write_bytes(jpg)
                kept.append(p.name)

            song_idx = 0 if song_idx is None else (song_idx + 1) % max(len(library), 1)
            song = music.label(library[song_idx]) if library else None
            (ready / "caption.txt").write_text(caption + "\n", encoding="utf-8")
            info = {"post": key, "title": a.title, "publish_vilnius": vilnius_time(day, slot),
                    "song": song, "song_index": song_idx, "images": kept,
                    "removed": sorted(skip), "warnings": a.warnings + warns}
            (ready / "info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
            summary.append(info)
            print(f"{key} {a.title}: {len(kept)} images, song {song}")
        day += timedelta(days=1)

    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
