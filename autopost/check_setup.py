"""Check every connection before going live. Prints what works and what does not.

    python -m autopost.check_setup
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import captions, drive
from .instagram import Instagram

CONFIG = json.loads((__import__("pathlib").Path(__file__).resolve().parent.parent / "config.json").read_text())


def main() -> int:
    ok = True

    print("== Instagram ==")
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        print("  ✗ IG_ACCESS_TOKEN missing")
        ok = False
    else:
        try:
            ig = Instagram(token, os.environ.get("IG_USER_ID", "me"), CONFIG["graph_api_base"])
            me = ig.me()
            print(f"  ✓ @{me.get('username')}  type={me.get('account_type')}  posts={me.get('media_count')}")
            print(f"    user_id = {me.get('user_id')}   <- this is IG_USER_ID")
            if os.environ.get("IG_USER_ID") and os.environ["IG_USER_ID"] != str(me.get("user_id")):
                print("  ✗ IG_USER_ID secret does not match the token's account")
                ok = False
            ig.user_id = str(me.get("user_id"))
            print(f"    publishing quota: {ig.publishing_limit().get('data')}")
        except Exception as e:
            print(f"  ✗ {e}")
            ok = False

    print("== Google Drive ==")
    try:
        d = drive.Drive()
        today = datetime.now(ZoneInfo(CONFIG["timezone"])).date()
        how = "service account" if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") else "API key (public link)"
        print(f"  access via {how}")
        root = d.list_children(drive.root_folder_id())
        for offset in range(0, 3):
            day = today + timedelta(days=offset)
            month = drive.find_month_folder(root, day)
            if not month:
                print(f"  ✗ {day}: no month folder")
                continue
            folder, warns = drive.find_day_folder(d.list_children(month.id), day)
            if not folder:
                print(f"  ✗ {day}: no day folder")
                ok = False
                continue
            posts = d.list_children(folder.id)
            for slot in (1, 2, 3):
                pf = drive.find_post_folder(posts, slot)
                if not pf:
                    print(f"  ✗ {day} slot {slot}: missing")
                    ok = False
                    continue
                a = drive.pick_assets(pf, d.list_children(pf.id), CONFIG["max_carousel_items"])
                print(f"  ✓ {day} {CONFIG['slots'][str(slot)]} NY: {a.title} ({len(a.images)} img, {a.caption_pdf.name})")
                try:
                    cap = captions.clean_caption(captions.pdf_to_text(d.download(a.caption_pdf.id)), a.title)
                    lines = cap.split("\n")
                    for ln in lines:
                        print(f"      | {ln}")
                    if not lines[-1].lower().startswith("shop now"):
                        print("      ⚠ caption does not end with the shop now CTA")
                except Exception as e:
                    print(f"      ✗ caption: {e}")
                    ok = False
                for w in a.warnings + warns:
                    print(f"      ⚠ {w}")
    except Exception as e:
        print(f"  ✗ {e}")
        ok = False

    print("== Drive privacy ==")
    if os.environ.get("GOOGLE_API_KEY") and os.environ.get("DRIVE_ROOT_FOLDER_ID"):
        try:
            if drive.publicly_readable(drive.root_folder_id(), os.environ["GOOGLE_API_KEY"]):
                print("  ⚠ the Instagram folder is still shared 'anyone with the link' (public)")
            else:
                print("  ✓ the Instagram folder is private")
        except Exception as e:
            print(f"  - could not test: {e}")
    else:
        print("  - not tested")

    print("== Token auto-refresh (GH_PAT) ==")
    if os.environ.get("GH_PAT") and os.environ.get("GITHUB_REPOSITORY"):
        import subprocess
        import time as _time

        r = subprocess.run(
            ["gh", "secret", "set", "AUTOPOST_PAT_CHECK", "--repo", os.environ["GITHUB_REPOSITORY"]],
            input=str(int(_time.time())).encode(), capture_output=True,
            env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]},
        )
        if r.returncode == 0:
            print("  ✓ GH_PAT can write repo secrets (token refresh will be saved automatically)")
        else:
            print(f"  ✗ GH_PAT cannot write secrets: {r.stderr.decode(errors='ignore')[:200]}")
            ok = False
    else:
        print("  - GH_PAT not set: the Instagram token will expire after 60 days")

    print("== Notifications ==")
    if os.environ.get("DISCORD_WEBHOOK_URL") or os.environ.get("TELEGRAM_BOT_TOKEN"):
        from .notify import notify

        notify("🔔 Instagram autopilot: pranešimai veikia." + (" Viskas paruošta." if ok else " Dar kažką reikia sutvarkyti, žiūrėk GitHub log'ą."))
        print("  ✓ test message sent: check Discord")
    else:
        print("  - DISCORD_WEBHOOK_URL not set (no phone notifications)")

    print("\nALL GOOD" if ok else "\nSOMETHING NEEDS FIXING (see ✗ above)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
