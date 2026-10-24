"""
Uploads a rendered Short to YouTube (resumable upload) as private, optionally
scheduled to go public at a set time. Until then you can watch, edit or delete it
in the YouTube Studio app: that's the veto window. With public=True it goes live at once
(the autopilot does that when a Short is ready only minutes before, or after, its slot).

Usage:
    python tools/youtube_upload.py --file .tmp/out/short.mp4 --title "..." --description "..." \
        [--tag cats --tag funny] [--publish-at 2026-10-25T23:00:00Z | --public]
Without --publish-at or --public the video stays private until you publish it yourself.
"""

import argparse
import sys
import time
from pathlib import Path

import requests

import youtube_auth
from common import load_config

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
RETRYABLE = {500, 502, 503, 504}


def _strip(text: str, limit: int) -> str:
    return text.replace("<", "").replace(">", "")[:limit]  # YouTube rejects < and > in metadata


def _uploaded_bytes(session_url: str, size: int) -> int:
    """Ask YouTube how much of an interrupted upload arrived, to resume from there."""
    resp = requests.put(session_url, timeout=30, headers={
        "Authorization": f"Bearer {youtube_auth.get_access_token()}",
        "Content-Range": f"bytes */{size}", "Content-Length": "0",
    })
    if resp.status_code == 308 and resp.headers.get("Range"):
        return int(resp.headers["Range"].split("-")[-1]) + 1
    return 0


def run(file: Path | str, title: str, description: str, tags: list[str] | None = None,
        publish_at: str | None = None, category_id: str = "15", language: str = "en",
        made_for_kids: bool = False, synthetic_media: bool = False, public: bool = False) -> dict:
    if public and publish_at:
        raise ValueError("a public upload can't also have a publish time")
    path = Path(file)
    size = path.stat().st_size
    status = {"privacyStatus": "public" if public else "private", "selfDeclaredMadeForKids": made_for_kids,
              "containsSyntheticMedia": synthetic_media, "embeddable": True}
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {"title": _strip(title, 100), "description": _strip(description, 4900), "tags": tags or [],
                    "categoryId": category_id, "defaultLanguage": language},
        "status": status,
    }

    start = requests.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, json=body,
                          timeout=30, headers={"Authorization": f"Bearer {youtube_auth.get_access_token()}",
                                               "X-Upload-Content-Length": str(size),
                                               "X-Upload-Content-Type": "video/mp4"})
    if start.status_code != 200:
        raise RuntimeError(f"Upload start failed ({start.status_code}): {youtube_auth.error_message(start)}")
    session_url = start.headers["Location"]

    offset = 0
    for attempt in range(5):
        headers = {"Authorization": f"Bearer {youtube_auth.get_access_token()}", "Content-Type": "video/mp4",
                   "Content-Length": str(size - offset)}
        if offset:
            headers["Content-Range"] = f"bytes {offset}-{size - 1}/{size}"
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                resp = requests.put(session_url, data=f, headers=headers, timeout=180)
            if resp.status_code in (200, 201):
                video_id = resp.json()["id"]
                return {"id": video_id, "url": f"https://youtube.com/shorts/{video_id}",
                        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit", "publish_at": publish_at}
            if resp.status_code not in RETRYABLE:
                raise RuntimeError(f"Upload failed ({resp.status_code}): {youtube_auth.error_message(resp)}")
        except requests.RequestException:
            pass  # network hiccup: resume below
        time.sleep(2 ** attempt)
        offset = _uploaded_bytes(session_url, size)
    raise RuntimeError("Upload failed after 5 attempts")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--file", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--publish-at", help="UTC time to go public, e.g. 2026-10-25T23:00:00Z")
    parser.add_argument("--public", action="store_true", help="go live straight away")
    args = parser.parse_args()

    meta = load_config()["metadata"]
    try:
        result = run(args.file, args.title, args.description, args.tag, args.publish_at,
                     meta["category_id"], meta["language"], public=args.public)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    when = ("public now" if args.public else f"goes public {result['publish_at']}" if result["publish_at"]
            else "private until you publish it")
    print(f"Uploaded {result['id']} ({when})")
    print(f"Review or veto: {result['studio_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
