"""
YouTube sign-in: a one-time consent on your computer, then silent token refresh.

Run once locally (needs credentials.json, the Desktop OAuth client from Google Cloud):
    python tools/youtube_auth.py
A browser opens, you pick the channel, and YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET
and YOUTUBE_REFRESH_TOKEN are written to .env. Copy the same three into the GitHub
repository's secrets (the morning run) and Vercel (the dashboard there).

Check the saved sign-in still works:
    python tools/youtube_auth.py --check

Other tools import get_access_token() and yt_get() from here.
"""

import argparse
import os
import sys
import time

import requests
from dotenv import set_key

from common import ROOT, env, keep_secret

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    # Stopping or deleting a scheduled Short from the dashboard (videos.update, videos.delete); asked for since
    # 2026-10-26, so a sign-in from before is given it once (the first Stop or Delete opens Google's page for it).
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
NEEDED = SCOPES[:3]  # uploads, the channel's details and its numbers: without these the channel stops
MANAGE = ("https://www.googleapis.com/auth/youtube.force-ssl", "https://www.googleapis.com/auth/youtube")
# Google's page has a box for each permission, worded like this.
BOXES = {
    SCOPES[0]: "Manage your YouTube videos",
    SCOPES[1]: "View your YouTube account",
    SCOPES[2]: "View YouTube Analytics reports for your YouTube content",
    SCOPES[3]: "See, edit, and permanently delete your YouTube videos, ratings, comments and captions",
}
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/youtube/v3"
ENV_KEYS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")

_token_cache = {"token": None, "expires": 0.0, "scope": ""}


class YouTubeAuthError(RuntimeError):
    pass


def is_configured() -> bool:
    return all(env(k) for k in ENV_KEYS)


def error_message(resp: requests.Response) -> str:
    try:
        err = resp.json().get("error")
        return err.get("message", str(err)) if isinstance(err, dict) else str(err)
    except ValueError:
        return resp.text[:300]


def get_access_token() -> str:
    """Exchange the stored refresh token for a short-lived access token (cached)."""
    if _token_cache["token"] and time.time() < _token_cache["expires"] - 60:
        return _token_cache["token"]
    resp = requests.post(TOKEN_URL, timeout=30, data={
        "client_id": env("YOUTUBE_CLIENT_ID", required=True),
        "client_secret": env("YOUTUBE_CLIENT_SECRET", required=True),
        "refresh_token": env("YOUTUBE_REFRESH_TOKEN", required=True),
        "grant_type": "refresh_token",
    })
    if resp.status_code != 200:
        detail = error_message(resp)
        if "invalid_grant" in resp.text:
            raise YouTubeAuthError(
                "YouTube sign-in expired or was revoked. Reconnect on the dashboard's YouTube page (or run "
                "`python tools/youtube_auth.py`), then update YOUTUBE_REFRESH_TOKEN in the GitHub secrets and Vercel too."
            )
        raise YouTubeAuthError(f"Token refresh failed ({resp.status_code}): {detail}")
    data = resp.json()
    keep_secret(data["access_token"])
    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = time.time() + int(data.get("expires_in", 3600))
    _token_cache["scope"] = data.get("scope", "")  # what the sign-in allows
    return _token_cache["token"]


def can_manage() -> bool:
    """Whether the sign-in may stop or delete the channel's videos (a sign-in from before 2026-10-26 only uploads and
    reads; Reconnect once on the dashboard's YouTube page)."""
    get_access_token()
    return any(scope in _token_cache["scope"].split() for scope in MANAGE)


def yt_get(path_or_url: str, params: dict) -> dict:
    """GET a YouTube Data API path (e.g. "videos") or a full API URL; returns the JSON body."""
    url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}/{path_or_url}"
    resp = requests.get(url, params=params, timeout=30,
                        headers={"Authorization": f"Bearer {get_access_token()}"})
    if resp.status_code != 200:
        raise RuntimeError(f"YouTube API {path_or_url} failed ({resp.status_code}): {error_message(resp)}")
    return resp.json()


def channel_title() -> str | None:
    items = yt_get("channels", {"part": "snippet", "mine": "true"}).get("items", [])
    return items[0]["snippet"]["title"] if items else None


def run(timeout_seconds: int = 300) -> dict:
    """Interactive consent; saves the tokens to .env and returns the channel they belong to and whether the sign-in
    may stop or delete videos ("manage")."""
    from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError
    from oauthlib.oauth2 import AccessDeniedError

    secrets = ROOT / "credentials.json"
    if not secrets.exists():
        raise FileNotFoundError(
            f"{secrets} not found. In Google Cloud create an OAuth client (type: Desktop app), "
            "download its JSON and save it there."
        )
    # A box left unticked on Google's page comes back as a smaller grant (checked below), not oauthlib's
    # "Scope has changed" error.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    try:
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline", timeout_seconds=timeout_seconds)
    except WSGITimeoutError:
        raise RuntimeError(f"Google's page wasn't finished within {timeout_seconds // 60} minutes; nothing changed. "
                           "Try again when you're ready.")
    except AccessDeniedError:
        raise RuntimeError("You cancelled on Google's page; nothing changed.")
    if not creds.refresh_token:
        raise RuntimeError(
            "Google didn't return a refresh token. Remove the app at "
            "https://myaccount.google.com/permissions and run this again."
        )
    granted = creds.granted_scopes or SCOPES
    granted = granted.split() if isinstance(granted, str) else list(granted)
    unticked = [f"“{BOXES[scope]}”" for scope in NEEDED if scope not in granted]
    if unticked:
        one = len(unticked) == 1
        names = unticked[0] if one else ", ".join(unticked[:-1]) + " and " + unticked[-1]
        raise RuntimeError(f"Nothing changed: {names} {'was' if one else 'were'} left unticked on Google's page, and "
                           f"the channel needs {'it' if one else 'them'}. Try again and tick every box.")

    values = dict(zip(ENV_KEYS, (creds.client_id, creds.client_secret, creds.refresh_token)))
    for key, value in values.items():
        set_key(str(ROOT / ".env"), key, value)
        os.environ[key] = value
    _token_cache.update(token=None, expires=0.0, scope="")  # the old sign-in's token (and what it allowed) is done
    return {"channel": channel_title(), "saved_to": str(ROOT / ".env"),
            "manage": any(scope in granted for scope in MANAGE)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Only verify the saved sign-in works")
    args = parser.parse_args()

    try:
        if args.check:
            print(f"Signed in to channel: {channel_title()}")
            return 0
        result = run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Signed in to channel: {result['channel']}")
    print(f"Saved YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN to {result['saved_to']}")
    if not result["manage"]:
        print(f"Stop and Delete can't work: “{BOXES[SCOPES[3]]}” was left unticked.")
    print("Copy the same three values to the GitHub repository's secrets and Vercel too, if you use them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
