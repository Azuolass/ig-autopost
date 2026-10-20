"""Refresh the long-lived Instagram token (valid 60 days) and store it back as a repo secret.

Needs IG_ACCESS_TOKEN, and GH_PAT (a fine-grained token with "Secrets: read and
write" on this repo) to save the new value. Without GH_PAT it still refreshes
the expiry of the current token where Instagram allows it, and warns.
"""
from __future__ import annotations

import os
import subprocess

from .instagram import Instagram
from .notify import notify


def main() -> int:
    data = Instagram.refresh_token(os.environ["IG_ACCESS_TOKEN"])
    days = int(data.get("expires_in", 0)) // 86400
    new = data["access_token"]
    if os.environ.get("GH_PAT"):
        subprocess.run(
            ["gh", "secret", "set", "IG_ACCESS_TOKEN", "--repo", os.environ["GITHUB_REPOSITORY"]],
            input=new.encode(),
            check=True,
            env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]},
        )
        print(f"token refreshed and saved, valid {days} more days")
    else:
        notify(
            f"⚠️ Instagram token refreshed (valid {days} days) but GH_PAT is not set, "
            "so the new token was not saved. Add GH_PAT or update IG_ACCESS_TOKEN by hand."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
