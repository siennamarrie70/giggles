"""
Uploads a rendered Short to YouTube (resumable upload) as private, optionally
scheduled to go public at a set time. Until then you can watch, edit or delete it
in the YouTube Studio app: that's the veto window. With public=True it goes live at once
(the autopilot does that when a Short is ready only minutes before, or after, its slot).

set_thumbnail() gives a video its custom thumbnail (tools/thumbnail.py). YouTube allows that only on
channels verified by phone (youtube.com/verify); on others it refuses, and the Short keeps a frame
YouTube picks. Where Shorts show a custom thumbnail varies (the Shorts feed plays the video itself).

publish_now() makes a scheduled video public at once, unschedule() keeps it from going public (it
stays private), and delete() removes it, public or not: the dashboard's Post now, Stop and Delete
beside each Short on the Schedule page. They need the sign-in's permission to manage videos
(youtube_auth.MANAGE). statuses() asks how videos stand on YouTube (one request for up to 50, 1 unit
of the 10,000 a day), so the Schedule page notices what was changed in YouTube Studio.

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
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
VIDEOS_URL = f"{youtube_auth.API_BASE}/videos"
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
RETRYABLE = {500, 502, 503, 504}
# The parts of a video's status that can be written back (the rest, like uploadStatus, YouTube sets itself)
WRITABLE_STATUS = ("privacyStatus", "embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids",
                   "containsSyntheticMedia")


class NotAllowed(RuntimeError):
    """The YouTube sign-in can't change or delete videos (one from before it was asked to): allowed once on Google's
    page."""


class UploadLimit(RuntimeError):
    """YouTube takes no more uploads from the channel for now: its daily upload limit (400 uploadLimitExceeded, "The user
    has exceeded the number of videos they may upload"; hit on 2026-10-27 after 11 uploads in 24 hours, counting the
    ones deleted or stopped). Not the video's fault: it waits (tools/jobs.py), nothing else is made meanwhile."""


def _refused(resp: requests.Response, what: str) -> RuntimeError:
    if resp.status_code == 403 and "insufficient" in resp.text.lower():
        return NotAllowed("YouTube hasn't let this app change or delete videos yet. Allow it once from the dashboard on "
                          "your computer: press Stop or Delete there and, on Google's page, tick “See, edit, and "
                          "permanently delete your YouTube videos…”")
    return RuntimeError(f"{what} failed ({resp.status_code}): {youtube_auth.error_message(resp)}")


def _set_privacy(video_id: str, privacy: str, what: str) -> bool:
    """Gives a video this privacy and takes its publish time away. False if it isn't on YouTube any more."""
    items = youtube_auth.yt_get("videos", {"part": "status", "id": video_id}).get("items") or []
    if not items:
        return False
    # Writing the status replaces all of it: keep what's there, minus the publish time.
    status = {k: v for k, v in items[0]["status"].items() if k in WRITABLE_STATUS}
    status.update(privacyStatus=privacy, selfDeclaredMadeForKids=bool(status.get("selfDeclaredMadeForKids", False)))
    resp = requests.put(VIDEOS_URL, params={"part": "status"}, json={"id": video_id, "status": status}, timeout=30,
                        headers={"Authorization": f"Bearer {youtube_auth.get_access_token()}"})
    if resp.status_code != 200:
        raise _refused(resp, what)
    return True


def unschedule(video_id: str) -> dict:
    """Takes a scheduled video's publish time away: it stays on YouTube as private (only you can see it) and never
    goes public by itself. {"stopped": True}, or {"gone": True} if it isn't on YouTube any more."""
    return {"stopped": True} if _set_privacy(video_id, "private", "Stopping the schedule") else {"gone": True}


def publish_now(video_id: str) -> dict:
    """Makes a scheduled video public right away instead of at its publish time. {"public": True}, or {"gone": True}
    if it isn't on YouTube any more."""
    return {"public": True} if _set_privacy(video_id, "public", "Publishing it now") else {"gone": True}


def statuses(video_ids: list[str]) -> dict[str, dict]:
    """How each video stands on YouTube now, by its id: its privacy, publish time and upload state (uploaded, i.e.
    still processing; processed; rejected or failed, with YouTube's reason). A video that isn't returned was deleted."""
    found = {}
    for start in range(0, len(video_ids), 50):
        chunk = ",".join(video_ids[start:start + 50])
        for item in youtube_auth.yt_get("videos", {"part": "status", "id": chunk}).get("items") or []:
            status = item.get("status") or {}
            found[item["id"]] = {"privacy": status.get("privacyStatus"), "publish_at": status.get("publishAt"),
                                 "upload": status.get("uploadStatus"),
                                 "why": status.get("rejectionReason") or status.get("failureReason")}
    return found


def delete(video_id: str) -> dict:
    """Deletes a video from YouTube for good, public or not. {"deleted": True}, or {"gone": True} if it was gone
    already."""
    resp = requests.delete(VIDEOS_URL, params={"id": video_id}, timeout=30,
                           headers={"Authorization": f"Bearer {youtube_auth.get_access_token()}"})
    if resp.status_code == 404:
        return {"gone": True}
    if resp.status_code != 204:
        raise _refused(resp, "Deleting the video")
    return {"deleted": True}


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
        why = youtube_auth.error_message(start)
        if "uploadLimitExceeded" in start.text or "exceeded the number of videos" in why:
            raise UploadLimit(f"YouTube takes no more uploads for now (the channel's daily upload limit): {why}")
        raise RuntimeError(f"Upload start failed ({start.status_code}): {why}")
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


def set_thumbnail(video_id: str, image: Path | str) -> dict:
    """Sets the video's custom thumbnail (a JPEG under 2 MB). Returns {"set": True}, or {"set": False, "why": ...}
    when YouTube refuses (an unverified channel); other failures raise."""
    data = Path(image).read_bytes()
    if len(data) > MAX_THUMBNAIL_BYTES:
        raise ValueError(f"the thumbnail is {len(data) // 1024} KB; YouTube takes up to 2 MB")
    resp = requests.post(THUMBNAIL_URL, params={"videoId": video_id, "uploadType": "media"}, data=data, timeout=60,
                         headers={"Authorization": f"Bearer {youtube_auth.get_access_token()}",
                                  "Content-Type": "image/jpeg"})
    if resp.status_code == 200:
        return {"set": True}
    if resp.status_code in (403, 429):  # custom thumbnails not allowed for this channel (yet), or too many today
        return {"set": False, "why": youtube_auth.error_message(resp)}
    raise RuntimeError(f"Thumbnail failed ({resp.status_code}): {youtube_auth.error_message(resp)}")


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
