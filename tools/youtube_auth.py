"""
YouTube sign-in: a one-time consent on your computer, then silent token refresh.

Run once locally (needs credentials.json, the Desktop OAuth client from Google Cloud):
    python tools/youtube_auth.py
A browser opens, you pick the channel, and YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET
and YOUTUBE_REFRESH_TOKEN are written to .env. Copy the same three into Vercel.

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

from common import ROOT, env

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/youtube/v3"
ENV_KEYS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")

_token_cache = {"token": None, "expires": 0.0}


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
                "YouTube sign-in expired or was revoked. Run `python tools/youtube_auth.py` again "
                "and update YOUTUBE_REFRESH_TOKEN in .env and in Vercel."
            )
        raise YouTubeAuthError(f"Token refresh failed ({resp.status_code}): {detail}")
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = time.time() + int(data.get("expires_in", 3600))
    return _token_cache["token"]


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
    """Interactive consent; saves the tokens to .env and returns the channel they belong to."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets = ROOT / "credentials.json"
    if not secrets.exists():
        raise FileNotFoundError(
            f"{secrets} not found. In Google Cloud create an OAuth client (type: Desktop app), "
            "download its JSON and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline", timeout_seconds=timeout_seconds)
    if not creds.refresh_token:
        raise RuntimeError(
            "Google didn't return a refresh token. Remove the app at "
            "https://myaccount.google.com/permissions and run this again."
        )

    values = dict(zip(ENV_KEYS, (creds.client_id, creds.client_secret, creds.refresh_token)))
    for key, value in values.items():
        set_key(str(ROOT / ".env"), key, value)
        os.environ[key] = value
    return {"channel": channel_title(), "saved_to": str(ROOT / ".env")}


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
    print("Add the same three values to Vercel: Project > Settings > Environment Variables.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
