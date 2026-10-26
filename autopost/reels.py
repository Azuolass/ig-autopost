"""Separate Trial Reels pipeline. Never changes the carousel queue or music rotation.

The JSON journal must be persisted remotely before any ambiguous publish or move.
TikTok publication is performed in Studio; this module accepts verified receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from .drive import Drive, API
from .instagram import Instagram

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc


def read_json(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        temp = f.name
    os.replace(temp, path)


def now_iso():
    return datetime.now(UTC).isoformat(timespec="seconds")


def captions_from_text(raw):
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    match = re.fullmatch(r"\s*INSTAGRAM TRIAL\n+(.*?)\n+TIKTOK\n+(.*?)\s*", text, re.S)
    if not match:
        raise ValueError("caption needs INSTAGRAM TRIAL and TIKTOK sections")
    result = dict(zip(("instagram", "tiktok"), (s.strip() for s in match.groups())))
    if any(not s or len(s.encode("utf-16-le")) // 2 > 2200 for s in result.values()):
        raise ValueError("empty or overlong caption")
    return result


def plan(manifest, config):
    tz = ZoneInfo(config["audience_timezone"])
    times = config["audience_times"]
    if len(times) != 5 or len(set(times)) != 5:
        raise ValueError("exactly five distinct daily times required")
    grouped = {}
    identities = set()
    for item in manifest:
        for key in ("folder_id", "video_id", "caption_id"):
            value = item[key]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", value) or value in identities:
                raise ValueError("invalid or repeated Drive identity")
            identities.add(value)
        grouped.setdefault(item["date"], []).append(item)
    result = []
    for day, items in sorted(grouped.items()):
        if len(items) != 5:
            raise ValueError(f"{day}: expected 5 reels")
        for item, clock in zip(sorted(items, key=lambda x: x["filename"].casefold()), sorted(times)):
            at = datetime.combine(date.fromisoformat(day), datetime.strptime(clock, "%H:%M").time(), tz)
            result.append({**item, "key": item["folder_id"], "at": at.astimezone(UTC).isoformat(),
                           "vilnius": at.astimezone(ZoneInfo("Europe/Vilnius")).isoformat(),
                           "audience_at": at.isoformat()})
    return result


def fingerprint(video, captions):
    h = hashlib.sha256()
    h.update(video)
    h.update(json.dumps(captions, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def prepare(item, d, output):
    children = d.list_children(item["folder_id"])
    ids = {x.id: x for x in children}
    if set(ids) != {item["video_id"], item["caption_id"]}:
        raise ValueError("reel folder must contain exactly its declared video and caption")
    if ids[item["video_id"]].name != item["filename"]:
        raise ValueError("video identity changed")
    if ids[item["caption_id"]].name != item["filename"] + ".captions.txt":
        raise ValueError("caption identity changed")
    captions = captions_from_text(d.download(item["caption_id"]))
    video = d.download(item["video_id"])
    if not 12 <= len(video) <= 90 * 1024 * 1024 or video[4:8] != b"ftyp":
        raise ValueError("video must be an MP4 under 90 MiB")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "video.mp4"
    path.write_bytes(video)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                           capture_output=True, text=True, check=True)
    meta = json.loads(probe.stdout)
    streams = meta.get("streams", [])
    vids = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if len(vids) != 1 or vids[0].get("codec_name") not in {"h264", "hevc"}:
        raise ValueError("unsupported video stream")
    if not audio or any(s.get("codec_name") != "aac" for s in audio):
        raise ValueError("expected embedded AAC audio")
    duration = float(meta["format"]["duration"])
    if not 3 <= duration <= 900:
        raise ValueError("unsupported reel duration")
    digest = fingerprint(video, captions)
    atomic_json(output / "prepared.json", {"key": item["key"], "fingerprint": digest,
                "captions": captions, "duration": duration, "video_id": item["video_id"]})
    for platform, caption in captions.items():
        (output / f"{platform}.txt").write_text(caption + "\n")
    return path, captions, digest


def host_video(path, key, config):
    """Dedicated branch; never overwrites the existing carousel media branch."""
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("invalid repository")
    branch = config["media_branch"]
    if branch != "reels-media":
        raise ValueError("dedicated reels-media branch required")
    with tempfile.TemporaryDirectory(prefix="reel-media-") as work:
        def git(*args):
            # Never log command arguments, credentials or subprocess output.
            p = subprocess.run(["git", *args], cwd=work, capture_output=True)
            if p.returncode:
                raise RuntimeError("reels media git operation failed")
        git("init", "-q")
        git("checkout", "-q", "--orphan", branch)
        git("config", "user.name", "autopost")
        git("config", "user.email", "autopost@users.noreply.github.com")
        target = Path(work) / key
        target.mkdir()
        shutil.copyfile(path, target / "video.mp4")
        git("add", ".")
        git("commit", "-q", "-m", "temporary reel media")
        git("push", "-q", "--force", f"https://x-access-token:{token}@github.com/{repo}.git", f"HEAD:{branch}")
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{key}/video.mp4"
    import time
    for attempt in range(20):
        r = requests.head(url, timeout=20)
        if r.status_code == 200:
            return url
        time.sleep(3)
    raise RuntimeError("reel video hosting not ready")


class Journal:
    def __init__(self, path, persist):
        self.path = Path(path)
        self.data = read_json(path, {})
        self.persist = persist

    def save(self):
        atomic_json(self.path, self.data)
        self.persist()  # Must succeed before the next external side effect.

    def bind(self, key, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("a validated SHA-256 fingerprint is required")
        row = self.data.setdefault(key, {"fingerprint": digest})
        if row["fingerprint"] != digest:
            raise ValueError("content changed after preparation; review required")
        return row


def instagram_trial(ig, journal, item, digest, video_url, caption, validate=False):
    row = journal.bind(item["key"], digest)
    rec = row.setdefault("instagram", {})
    if rec.get("status") == "verified":
        return rec
    if rec.get("status") in {"published", "publishing", "pending"}:
        raise RuntimeError("Instagram result needs review; refusing duplicate publication")
    if not rec.get("container_id"):
        rec.update(status="creating", started_at=now_iso())
        journal.save()
        # An uncertain container creation is harmless: containers are not public posts.
        container = ig._call("POST", f"{ig.user_id}/media", media_type="REELS", video_url=video_url,
                             caption=caption, trial_params=json.dumps({"graduation_strategy": "MANUAL"}))
        rec.update(container_id=container["id"], status="processing")
        journal.save()
    ig.wait_ready(rec["container_id"])
    rec["status"] = "ready"
    journal.save()
    if validate:
        return rec
    rec.update(status="publishing", attempted_at=now_iso())
    journal.save()
    media_id = ig.publish(rec["container_id"])
    # Persist the ID before requesting optional metadata.
    rec.update(media_id=media_id, status="published", published_at=now_iso())
    journal.save()
    rec["permalink"] = ig.permalink(media_id)
    if not re.fullmatch(r"https://www\.instagram\.com/(?:p|reel)/[A-Za-z0-9_-]+/?", rec["permalink"]):
        raise RuntimeError("published media missing valid permalink; do not republish")
    rec["status"] = "verified"
    journal.save()
    return rec


def reconcile_instagram(ig, journal, key):
    """Recover metadata for an already known media ID; never publishes anything."""
    rec = journal.data.get(key, {}).get("instagram", {})
    if not rec.get("media_id") or rec.get("status") not in {"published", "verified"}:
        raise RuntimeError("no known published media ID; manual review required")
    permalink = ig.permalink(rec["media_id"])
    if not re.fullmatch(r"https://www\.instagram\.com/(?:p|reel)/[A-Za-z0-9_-]+/?", permalink):
        raise RuntimeError("published media permalink not verified")
    rec.update(permalink=permalink, status="verified")
    journal.save()
    return rec


def record_tiktok(journal, key, digest, permalink, published_at):
    if not re.fullmatch(r"https://www\.tiktok\.com/@successhunters\.prints/video/\d+/?", permalink):
        raise ValueError("a published video URL on the correct TikTok account is required")
    stamp = datetime.fromisoformat(published_at)
    if stamp.tzinfo is None or stamp > datetime.now(UTC):
        raise ValueError("publication time must be timezone-aware and in the past")
    row = journal.bind(key, digest)
    old = row.get("tiktok", {})
    if old.get("status") == "verified" and old.get("permalink") != permalink:
        raise ValueError("conflicting TikTok publication receipt")
    row["tiktok"] = {"status": "verified", "permalink": permalink,
                     "published_at": stamp.isoformat(), "verified_via": "studio_visual_check"}
    journal.save()


def archive(item, journal, d):
    row = journal.data.get(item["key"], {})
    if any(row.get(p, {}).get("status") != "verified" or not row[p].get("permalink")
           for p in ("instagram", "tiktok")):
        raise RuntimeError("both platforms must be verified before archiving")
    rec = row.setdefault("archive", {})
    if rec.get("status") == "verified":
        return
    # Reconcile a previous move by actual Drive parent; never blindly repeat a move.
    parents = d.parents(item["folder_id"])
    if parents == [item["posted_day_id"]]:
        rec.update(status="verified", verified_at=now_iso())
        journal.save()
        return
    if parents != [item["ready_day_id"]]:
        raise RuntimeError("unexpected Drive parent; archive needs review")
    rec.update(status="pending", source=parents[0], destination=item["posted_day_id"])
    journal.save()
    d.move(item["folder_id"], parents[0], item["posted_day_id"])
    if d.parents(item["folder_id"]) != [item["posted_day_id"]]:
        raise RuntimeError("archive move not verified")
    rec.update(status="verified", verified_at=now_iso())
    journal.save()


class ArchiveDrive(Drive):
    def __init__(self):
        # Only used by the explicitly enabled archive command, never carousel jobs.
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(
            json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
            scopes=["https://www.googleapis.com/auth/drive"])
        creds.refresh(Request())
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {creds.token}"
        self._params = {}

    def parents(self, fid):
        r = self.s.get(f"{API}/files/{fid}", params={"fields": "parents", "supportsAllDrives": "true"}, timeout=30)
        r.raise_for_status()
        return r.json().get("parents", [])

    def move(self, fid, source, destination):
        r = self.s.patch(f"{API}/files/{fid}", params={"addParents": destination, "removeParents": source,
                         "supportsAllDrives": "true", "fields": "id,parents"}, json={}, timeout=30)
        r.raise_for_status()


def git_persist():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("live state persistence requires the dedicated GitHub Actions workflow")
    relative = "state/reels.json"
    subprocess.run(["git", "add", relative], cwd=ROOT, check=True, capture_output=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    for args in (["git", "commit", "-qm", "reels: durable state"],
                 ["git", "pull", "--rebase", "-q"], ["git", "push", "-q"]):
        result = subprocess.run(args, cwd=ROOT, capture_output=True)
        if result.returncode:
            raise RuntimeError("could not persist reels state; external action stopped")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["plan", "check-drive", "prepare", "validate-instagram",
                                      "publish-instagram", "reconcile-instagram", "record-tiktok", "archive"])
    ap.add_argument("--key")
    ap.add_argument("--output", default="reels-preview")
    ap.add_argument("--url")
    ap.add_argument("--published-at")
    ap.add_argument("--fingerprint")
    args = ap.parse_args(argv)
    config = read_json(ROOT / "reels/config.json")
    items = plan(read_json(ROOT / "reels/manifest.json"), config)
    if args.action == "plan":
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    found = [x for x in items if x["key"] == args.key]
    if len(found) != 1:
        ap.error("--key must identify exactly one reel folder")
    item = found[0]
    if args.action == "check-drive":
        d = Drive()
        children = d.list_children(item["folder_id"])
        if {x.id for x in children} != {item["video_id"], item["caption_id"]}:
            raise RuntimeError("Drive read access or folder identity check failed")
        captions_from_text(d.download(item["caption_id"]))
        print("Drive read and caption checks OK; no publishing or moves")
        return 0
    if args.action in {"record-tiktok", "archive"}:
        if not config.get("enabled"):
            raise RuntimeError("reels live mode is disabled")
        journal = Journal(ROOT / "state/reels.json", git_persist)
        if args.action == "record-tiktok":
            record_tiktok(journal, item["key"], args.fingerprint, args.url or "", args.published_at or "")
        else:
            if not config.get("archive_enabled"):
                raise RuntimeError("automatic archiving disabled")
            archive(item, journal, ArchiveDrive())
        return 0
    if args.action == "reconcile-instagram":
        ig = Instagram(os.environ["IG_ACCESS_TOKEN"], os.environ.get("IG_USER_ID", "me"), config["graph_api_base"])
        if ig.me().get("username") != "successhunters.prints":
            raise RuntimeError("unexpected Instagram account")
        print(json.dumps(reconcile_instagram(ig, Journal(ROOT / "state/reels.json", git_persist), item["key"])))
        return 0
    if args.action == "publish-instagram":
        if not config.get("enabled"):
            raise RuntimeError("reels live mode is disabled")
        now = datetime.now(UTC)
        planned = datetime.fromisoformat(item["at"])
        if not planned <= now <= planned + timedelta(minutes=30):
            raise RuntimeError("outside this reel's 30-minute publishing window")
    path, captions, digest = prepare(item, Drive(), Path(args.output) / item["key"])
    if args.action == "prepare":
        print(f"Prepared {item['key']}; no upload or publication")
        return 0
    ig = Instagram(os.environ["IG_ACCESS_TOKEN"], os.environ.get("IG_USER_ID", "me"), config["graph_api_base"])
    account = ig.me()
    if account.get("username") != "successhunters.prints":
        raise RuntimeError("unexpected Instagram account")
    ig.user_id = str(account["user_id"])
    journal = Journal(ROOT / "state/reels.json", git_persist)
    rec = journal.bind(item["key"], digest).get("instagram", {})
    if rec.get("status") in {"verified", "published", "publishing", "pending"}:
        if rec.get("status") == "verified":
            print("Already verified; no upload or publication")
            return 0
        raise RuntimeError("existing publication needs reconciliation; refusing duplicate")
    url = host_video(path, item["key"], config)
    result = instagram_trial(ig, journal, item, digest, url, captions["instagram"],
                             validate=args.action == "validate-instagram")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
