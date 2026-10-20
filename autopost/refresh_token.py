"""Refresh the long-lived Instagram token (valid 60 days) and store it back as a repo secret.

Needs IG_ACCESS_TOKEN, and GH_PAT (a fine-grained token with "Secrets: read and
write" on this repo) to save the new value. Runs every Monday, so the token
never gets close to its 60-day expiry. Any failure is sent to Discord.

Instagram only refreshes tokens that are at least 24 hours old.
"""
from __future__ import annotations

import os
import subprocess

from .instagram import Instagram
from .notify import notify


def main() -> int:
    try:
        data = Instagram.refresh_token(os.environ["IG_ACCESS_TOKEN"])
    except Exception as e:
        notify(f"⚠️ Instagram tokeno atnaujinti nepavyko: {e}\n"
               "Jei tai kartojasi, tokeną reikės sugeneruoti iš naujo Meta developer puslapyje.")
        return 1
    days = int(data.get("expires_in", 0)) // 86400
    new = data["access_token"]
    if not os.environ.get("GH_PAT"):
        notify(f"⚠️ Instagram tokenas atnaujintas ({days} d.), bet GH_PAT nenustatytas, todėl naujas tokenas "
               "neišsaugotas. Pridėk GH_PAT secret.")
        return 1
    try:
        subprocess.run(
            ["gh", "secret", "set", "IG_ACCESS_TOKEN", "--repo", os.environ["GITHUB_REPOSITORY"]],
            input=new.encode(), check=True, capture_output=True,
            env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]},
        )
    except subprocess.CalledProcessError as e:
        notify(f"⚠️ Naujo Instagram tokeno išsaugoti nepavyko (GH_PAT teisės?): "
               f"{e.stderr.decode(errors='ignore')[:300]}")
        return 1
    print(f"token refreshed and saved, valid {days} more days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
