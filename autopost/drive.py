"""Read the day folders from Google Drive (Drive API v3, read-only).

Folder layout:
    <root>/<YYYY.MM>/<D.MM.YYYY>/<NN_Post_Name>/{01_*.png, 02_*.png, ..., instagram_caption*.pdf}

Auth, in order of preference:
    GOOGLE_SERVICE_ACCOUNT_JSON  full JSON of a service account the root folder is shared with
    GOOGLE_API_KEY               works only while the folders are shared "anyone with the link"
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date

import requests

API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"

_DAY_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")
_MONTH_RE = re.compile(r"^\s*(\d{4})\.(\d{1,2})\s*$")
_LEADING_NUM = re.compile(r"^\s*(\d+)")


@dataclass
class DriveFile:
    id: str
    name: str
    mime: str
    modified: str = ""


@dataclass
class PostAssets:
    folder_name: str
    title: str
    images: list[DriveFile]
    caption_pdf: DriveFile
    warnings: list[str] = field(default_factory=list)


class Drive:
    def __init__(self, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self._params: dict[str, str] = {}
        sa = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        key = os.environ.get("GOOGLE_API_KEY")
        if sa:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(
                json.loads(sa), scopes=["https://www.googleapis.com/auth/drive.readonly"]
            )
            creds.refresh(Request())
            self.s.headers["Authorization"] = f"Bearer {creds.token}"
        elif key:
            self._params["key"] = key
        else:
            raise RuntimeError("Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_API_KEY")

    def list_children(self, folder_id: str) -> list[DriveFile]:
        out: list[DriveFile] = []
        token = None
        while True:
            params = {
                **self._params,
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": "nextPageToken, files(id, name, mimeType, modifiedTime)",
                "pageSize": "1000",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if token:
                params["pageToken"] = token
            r = self.s.get(f"{API}/files", params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            out += [
                DriveFile(f["id"], f["name"], f["mimeType"], f.get("modifiedTime", ""))
                for f in data.get("files", [])
            ]
            token = data.get("nextPageToken")
            if not token:
                return out

    def download(self, file_id: str) -> bytes:
        r = self.s.get(
            f"{API}/files/{file_id}",
            params={**self._params, "alt": "media", "supportsAllDrives": "true"},
            timeout=120,
        )
        r.raise_for_status()
        return r.content


def root_folder_id() -> str:
    """DRIVE_ROOT_FOLDER_ID secret, falling back to config.json while that still holds it."""
    fid = os.environ.get("DRIVE_ROOT_FOLDER_ID")
    if fid:
        return fid.strip()
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text())
    if cfg.get("drive_root_folder_id"):
        return cfg["drive_root_folder_id"]
    raise RuntimeError("DRIVE_ROOT_FOLDER_ID secret is not set")


# ---- pure helpers (unit-tested) -------------------------------------------

def find_month_folder(children: list[DriveFile], day: date) -> DriveFile | None:
    for f in children:
        m = _MONTH_RE.match(f.name)
        if f.mime == FOLDER_MIME and m and int(m[1]) == day.year and int(m[2]) == day.month:
            return f
    return None


def find_day_folder(children: list[DriveFile], day: date) -> tuple[DriveFile | None, list[str]]:
    """Exact 'D.MM.YYYY' match. Variants like '8.10.2026 vol. 2' are reported, not used."""
    exact, variants = None, []
    for f in children:
        if f.mime != FOLDER_MIME:
            continue
        m = _DAY_RE.match(f.name)
        if m and (int(m[3]), int(m[2]), int(m[1])) == (day.year, day.month, day.day):
            exact = f
        elif f.name.strip().startswith(f"{day.day}.{day.month:02d}.{day.year}") or f.name.strip().startswith(
            f"{day.day}.{day.month}.{day.year}"
        ):
            variants.append(f.name)
    warnings = [f"extra folder for this day ignored: '{v}'" for v in variants]
    return exact, warnings


def leading_number(name: str) -> int | None:
    m = _LEADING_NUM.match(name)
    return int(m[1]) if m else None


def find_post_folder(children: list[DriveFile], slot: int) -> DriveFile | None:
    matches = [f for f in children if f.mime == FOLDER_MIME and leading_number(f.name) == slot]
    if len(matches) > 1:
        raise RuntimeError(f"more than one post folder numbered {slot:02d}: {[m.name for m in matches]}")
    return matches[0] if matches else None


def title_from_folder(name: str) -> str:
    return re.sub(r"^\s*\d+[_\-\s]*", "", name).replace("_", " ").strip()


def pick_assets(post_folder: DriveFile, children: list[DriveFile], max_items: int) -> PostAssets:
    warnings: list[str] = []
    images = [f for f in children if f.mime.startswith("image/")]
    numbered = [f for f in images if leading_number(f.name) is not None]
    unnumbered = [f for f in images if leading_number(f.name) is None]
    if unnumbered:
        warnings.append(f"images without a leading number skipped: {[f.name for f in unnumbered]}")
    numbered.sort(key=lambda f: (leading_number(f.name), f.name.lower()))
    nums = [leading_number(f.name) for f in numbered]
    if len(set(nums)) != len(nums):
        warnings.append(f"duplicate image numbers: {nums}")
    if len(numbered) < 2:
        raise RuntimeError(f"{post_folder.name}: a carousel needs at least 2 images, found {len(numbered)}")
    if len(numbered) > max_items:
        warnings.append(f"{len(numbered)} images, Instagram allows {max_items}; extra ones dropped")
        numbered = numbered[:max_items]

    pdfs = [f for f in children if f.mime == "application/pdf" and "caption" in f.name.lower()]
    if not pdfs:
        raise RuntimeError(f"{post_folder.name}: no instagram_caption*.pdf found")
    # Prefer an "updated" caption, then the most recently modified one.
    pdfs.sort(key=lambda f: ("updated" in f.name.lower(), f.modified), reverse=True)
    if len(pdfs) > 1:
        warnings.append(f"several caption PDFs, using '{pdfs[0].name}'")

    return PostAssets(
        folder_name=post_folder.name,
        title=title_from_folder(post_folder.name),
        images=numbered,
        caption_pdf=pdfs[0],
        warnings=warnings,
    )
