"""Minimal client for the Instagram API with Instagram Login (content publishing)."""
from __future__ import annotations

import time

import requests


class InstagramError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, subcode: int | None = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode

    @property
    def is_aspect_ratio(self) -> bool:
        msg = str(self).lower()
        return self.subcode == 2207009 or "aspect ratio" in msg


class Instagram:
    def __init__(self, token: str, user_id: str, base: str, session: requests.Session | None = None):
        self.token = token
        self.user_id = user_id
        self.base = base.rstrip("/")
        self.s = session or requests.Session()

    def _call(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        url = f"{self.base}/{path.lstrip('/')}"
        if method == "GET":
            r = self.s.get(url, params=params, timeout=60)
        else:
            r = self.s.post(url, data=params, timeout=60)
        try:
            data = r.json()
        except ValueError:
            r.raise_for_status()
            raise InstagramError(f"non-JSON response from {path}: {r.text[:200]}")
        if "error" in data:
            e = data["error"]
            raise InstagramError(
                f"{path}: {e.get('message')} (code {e.get('code')}, subcode {e.get('error_subcode')})",
                e.get("code"),
                e.get("error_subcode"),
            )
        return data

    # -- account ------------------------------------------------------------
    def edge(self, path: str, *, max_items: int | None = None, **params):
        """Walk cursor pages without following token-bearing URLs to other hosts."""
        after = None
        cursors = set()
        seen = set()
        count = 0
        while True:
            page = self._call("GET", path, **params, **({"after": after} if after else {}))
            for item in page.get("data", []):
                identity = item.get("id")
                if identity is not None and identity in seen:
                    continue
                seen.add(identity)
                yield item
                count += 1
                if max_items is not None and count >= max_items:
                    return
            paging = page.get("paging") or {}
            if not paging.get("next"):
                return
            after = (paging.get("cursors") or {}).get("after")
            if not after or after in cursors:
                raise InstagramError(f"pagination cursor missing or repeated: {path}")
            cursors.add(after)

    def me(self) -> dict:
        return self._call("GET", "me", fields="user_id,username,account_type,media_count")

    def recent_media(self, limit: int = 10) -> list[dict]:
        return self._call("GET", f"{self.user_id}/media", fields="id,caption,timestamp,permalink", limit=limit).get(
            "data", []
        )

    def publishing_limit(self) -> dict:
        return self._call("GET", f"{self.user_id}/content_publishing_limit", fields="quota_usage,config")

    # -- publishing -----------------------------------------------------------
    def create_carousel_item(self, image_url: str) -> str:
        return self._call("POST", f"{self.user_id}/media", image_url=image_url, is_carousel_item="true")["id"]

    def create_carousel(self, children: list[str], caption: str) -> str:
        return self._call(
            "POST", f"{self.user_id}/media", media_type="CAROUSEL", children=",".join(children), caption=caption
        )["id"]

    def wait_ready(self, container_id: str, timeout: int = 300) -> None:
        deadline = time.time() + timeout
        while True:
            st = self._call("GET", container_id, fields="status_code,status")
            code = st.get("status_code")
            if code in ("FINISHED", "PUBLISHED"):
                return
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError(f"container {container_id} {code}: {st.get('status')}")
            if time.time() > deadline:
                raise InstagramError(f"container {container_id} not ready after {timeout}s (last: {code})")
            time.sleep(5)

    def publish(self, container_id: str) -> str:
        return self._call("POST", f"{self.user_id}/media_publish", creation_id=container_id)["id"]

    def permalink(self, media_id: str) -> str:
        return self._call("GET", media_id, fields="permalink").get("permalink", "")

    # -- token ----------------------------------------------------------------
    @staticmethod
    def refresh_token(token: str) -> dict:
        r = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
            timeout=30,
        )
        data = r.json()
        if "error" in data:
            raise InstagramError(f"token refresh failed: {data['error'].get('message')}")
        return data  # {access_token, token_type, expires_in}
