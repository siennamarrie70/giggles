"""
Posts a finished Short to Instagram as a Reel through Instagram's Graph API (free), from your own
Instagram professional account linked to a Facebook Page ("Instagram API with Facebook Login"). The
video gets to Instagram one of two ways (settings instagram.send): "upload", sent from this computer
(a resumable upload to rupload.facebook.com), or "link", fetched by Instagram itself from a temporary
public link to it (video_url, tools/tunnel.py: the way Instagram's API is meant to get a video; it
falls back to sending when no link can be made, or Instagram won't take it). Instagram processes it,
and then it's published with its caption, shared to the feed too, with its cover frame chosen by
thumb_offset. Instagram's API
can't schedule Reels, so the Publisher posts each one when its slot comes. Instagram allows 100 posts
a day by API; the channel posts 10.

Reels want AAC sound at up to 128 kbps and an MP4 with no edit lists (Meta's docs, checked 2026-10-26).
Our renders have an edit list on each track (ffmpeg writes one for the picture's B-frames and one for
AAC's start). So what's uploaded is a copy made for Reels: the picture encoded again without B-frames (so
it still starts with the sound: without the edit list a copied picture came 0.083 s late, enough to see on
his lips) at up to 8 Mbps and small enough to send in time (below; Instagram encodes Reels again, smaller),
the sound at 128 kbps, no edit lists. About a minute a Short.

The upload goes in 4 MB pieces (CHUNK), each continuing at the byte offset where the last one ended
(Instagram answers 206 "Partial request" until the last piece, then 200), all on one kept-open
connection, and it must be sent within about a minute. Instagram drops one that takes longer: its last
piece fails about 30 s after it's sent, ProcessingFailedError "Request processing failed", and the
container says bytes_transferred 0, "File not found" (error 1363008). Measured on 2026-10-27 (this
connection sends about 1 MB/s): sent whole (47-95 MB, 1-2 minutes) every real Short failed; in pieces,
47 MB in 53 s went through, 59 MB in 61-66 s failed three times, 30 MB in 33 s went through and the same
30 MB spread over 70 s failed. One kept-open connection makes each piece faster (3.7 s instead of 4.5,
no new handshake): #45's 59 MB then went in 55 s, but #46's 67 MB (about 60 s) failed three times. So the
Reel copy is also made small enough to send in well under a minute: at most REEL_MB (its picture's
bitrate capped by its length). Even so Instagram drops uploads, in spells: its answer to the last piece
came in 24-31 s when it worked and at 33-34 s when it didn't, whatever the size (59 MB worked, 28 MB
failed); #46's 28 MB copy went through three times in tests that afternoon, then was dropped ten times
in a row over the next 90 minutes, and a 14 MB copy sent whole was dropped three times out of three
(43.5 s each). A drop is sent again at once with a new container (UPLOAD_TRIES), and the Publisher
tries again later, over hours (agents/publisher.py REEL_WAITS). A dropped container is never published
and expires by itself; it can even say FINISHED ("ready to be published") with its upload phase
"error" and no video, so a container counts as ready only with its upload complete (_processed). The
"link" way has none of this: Instagram fetches the file at its own pace.

Connecting (once; workflows/setup_accounts.md has the steps): an Instagram professional account
linked to a Facebook Page you manage, a Meta app of your own (Facebook Login for Business) and an
access token from it with instagram_basic, instagram_content_publish, pages_show_list and
pages_read_engagement. connect() exchanges that token for a long-lived one (with the app's id and
secret), finds the Page your Instagram account is linked to, and keeps the Page's token (which
doesn't expire when it comes from a long-lived token) in .env: INSTAGRAM_ACCESS_TOKEN,
INSTAGRAM_USER_ID and INSTAGRAM_USERNAME, plus FACEBOOK_APP_ID and FACEBOOK_APP_SECRET. Nothing
about the account is kept anywhere else.

When Meta refuses the connection itself, not one video, the error is Disconnected: the token, its
permissions, the Meta app or the account (BROKEN codes). Then no Reel can go up until it's fixed, and
the Publisher keeps them all waiting without counting tries (agents/publisher.py). Seen 2026-10-29:
Meta blocked the app (its own key got "API access blocked", code 200), and from then on the Page's
token got "Any of the pages_read_engagement, ... permission(s) must be granted before impersonating
a user's page" (code 190), on this computer and on GitHub alike. check() asks with one harmless read.

delete() deletes a posted Reel (the Schedule page's Delete). Meta's reference documents it for
"Instagram API with Facebook Login" (DELETE /<IG_MEDIA_ID>, checked 2026-10-27), and the token needs
one more permission for it, instagram_manage_contents; without it Instagram refuses and the error
says so (the Reel can always be deleted in the Instagram app). Not yet tried on a real account.

Usage:
    python tools/instagram.py --status
    python tools/instagram.py --connect TOKEN [--app-id ID --app-secret SECRET]
    python tools/instagram.py --file .tmp/out/short_12.mp4 --caption "..." [--cover-at 2.5]
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import set_key, unset_key

import short_render
import tunnel
from common import ROOT, env, load_config, tmp_path

VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"
UPLOAD = f"https://rupload.facebook.com/ig-api-upload/{VERSION}"
ACCOUNT_KEYS = ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID", "INSTAGRAM_USERNAME")
APP_KEYS = ("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET")
CAPTION_CHARS, MAX_HASHTAGS = 2200, 30
WAIT_EVERY, WAIT_FOR = 10, 600  # seconds: how often to ask whether Instagram has processed the video, and how long
AUDIO_RATE = "128k"
CHUNK = 4 * 1024 * 1024         # bytes sent to Instagram a request (a whole Short in one request was dropped)
CHUNK_TRIES = 3                 # a piece that hits a network error is sent again this many times
REEL_MB = 30                    # the Reel copy's most size (MB): an upload has about a minute (30 MB: about 27 s here)
UPLOAD_TRIES = 2                # sent again at once when Instagram drops it at its last piece (the Publisher tries
                                # again later, over hours: drops come in spells)
MOST_KBPS = 8000                # the Reel copy's picture never above this
SEND_WAYS = ("upload", "link")  # settings instagram.send: this computer sends the video, or Instagram fetches it
BROKEN = {10, 102, 190, 368, *range(200, 300)}  # Meta's error codes for the token, its permissions, the app or the
                                                # account (not one video): Disconnected


class InstagramError(RuntimeError):
    pass


class Disconnected(InstagramError):
    """Meta refused the connection itself, not one video (BROKEN): no Reel can go up until it's fixed."""


def refused_connection(text: str | None) -> bool:
    """Whether an error saved earlier (its "(code N" part) was Meta refusing the connection (Disconnected)."""
    found = re.search(r"\(code (\d+)", text or "")
    return bool(found) and int(found[1]) in BROKEN


def is_configured() -> bool:
    return bool(env("INSTAGRAM_ACCESS_TOKEN") and env("INSTAGRAM_USER_ID"))


def _check(resp: requests.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400 or (isinstance(body, dict) and "error" in body):
        err = body.get("error") if isinstance(body, dict) else None
        err = err if isinstance(err, dict) else {}
        code = ", ".join(f"{name} {err[key]}" for name, key in (("code", "code"), ("subcode", "error_subcode"))
                         if err.get(key))
        why = err.get("error_user_msg") or err.get("error_user_title")  # (Instagram's own words for what was wrong)
        raise (Disconnected if err.get("code") in BROKEN else InstagramError)(
            f"Instagram answered {resp.status_code}: {err.get('message') or resp.text[:300]}"
            + (f" ({code})" if code else "") + (f": {why}" if why else ""))
    return body


def _http(method: str, url: str, **kwargs) -> requests.Response:
    """A request to Meta. A network failure is told without its web address, which carries the token (and without
    the original error, which names it too)."""
    try:
        return requests.request(method, url, **kwargs)
    except requests.RequestException as e:
        raise InstagramError(f"Instagram couldn't be reached ({type(e).__name__})") from None


def _get(path: str, token: str, **params) -> dict:
    return _check(_http("GET", f"{GRAPH}/{path}", params={**params, "access_token": token}, timeout=30))


def _post(path: str, token: str, **params) -> dict:
    return _check(_http("POST", f"{GRAPH}/{path}", data={**params, "access_token": token}, timeout=60))


def _save(values: dict) -> None:
    for key, value in values.items():
        set_key(str(ROOT / ".env"), key, value)
        os.environ[key] = value


def _business_pages(token: str, fields: str) -> list[dict]:
    """The Pages of the Business portfolios this token can manage (their owned and client Pages)."""
    pages = []
    try:
        for business in _get("me/businesses", token, fields="id").get("data") or []:
            for edge in ("owned_pages", "client_pages"):
                try:
                    pages += _get(f"{business['id']}/{edge}", token, fields=f"name,access_token,{fields}").get("data") or []
                except InstagramError:
                    continue
    except InstagramError:  # no business_management: nothing more to find
        pass
    return pages


def _granted(token: str) -> set[str] | None:
    """The permissions the token was granted, or None if Facebook won't say."""
    try:
        return {p["permission"] for p in _get("me/permissions", token).get("data") or [] if p.get("status") == "granted"}
    except InstagramError:
        return None


def connect(token: str, app_id: str | None = None, app_secret: str | None = None) -> dict:
    """Finds your Instagram account from an access token and keeps what's needed to post in .env."""
    token = token.strip()
    app_id = (app_id or env("FACEBOOK_APP_ID") or "").strip()
    app_secret = (app_secret or env("FACEBOOK_APP_SECRET") or "").strip()
    if not token:
        raise InstagramError("paste an access token first")
    long_lived = False
    if app_id and app_secret:  # a long-lived token (about 60 days), whose Page tokens don't expire
        token = _check(_http("GET", f"{GRAPH}/oauth/access_token", timeout=30, params={
            "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret,
            "fb_exchange_token": token}))["access_token"]
        long_lived = True
    fields = "instagram_business_account{id,username}"
    try:
        pages = _get("me/accounts", token, fields=f"name,access_token,{fields}").get("data") or []
    except InstagramError:  # a Page's own token: it is the Page
        me = _get("me", token, fields=f"name,{fields}")
        pages = [{**me, "access_token": token}]
    page = next((p for p in pages if p.get("instagram_business_account")), None)
    if not page:  # a Page in a Business portfolio isn't always in me/accounts (needs business_management): look there
        pages += _business_pages(token, fields)
        page = next((p for p in pages if p.get("instagram_business_account")), None)
    if not page:
        granted = _granted(token)
        missing = [p for p in ("instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement")
                   if granted is not None and p not in granted]
        try:
            who = _get("me", token, fields="name").get("name")
        except InstagramError:
            who = None
        seen = ", ".join(sorted({p.get("name") or "?" for p in pages})) or "none"
        raise InstagramError(
            "none of the Facebook Pages this token can see has an Instagram professional account linked to it. "
            + (f"The token is {who}'s. " if who else "") + f"Pages it can see: {seen}."
            + (f" The token is missing these permissions: {', '.join(missing)}: add them in the Graph API Explorer "
               "and generate a new token." if missing else "")
            + (" No Page at all: either the Page wasn't ticked in Facebook's window when the token was made, or the Page "
               "belongs to your Business portfolio without being assigned to you (Business settings > Accounts > Pages "
               "> your Page > Assign people > you, full control), or there's no Page yet."
               + ("" if granted is None or "business_management" in granted else
                  " (With the business_management permission too, this also looks inside your Business portfolio.)")
               if not pages else " Link your Instagram (a Creator or Business account) to one of these Pages: the "
                                 "Page's settings > Linked accounts > Instagram."))
    account = page["instagram_business_account"]
    page_token = page.get("access_token") or token  # (a portfolio's Page not assigned to you comes without its own)
    _save({"INSTAGRAM_ACCESS_TOKEN": page_token, "INSTAGRAM_USER_ID": str(account["id"]),
           "INSTAGRAM_USERNAME": str(account.get("username") or "")})
    if app_id and app_secret:
        _save({"FACEBOOK_APP_ID": app_id, "FACEBOOK_APP_SECRET": app_secret})
    return {"username": account.get("username"), "page": page.get("name"), "long_lived": long_lived,
            **expiry(page_token)}


def disconnect() -> None:
    for key in ACCOUNT_KEYS:
        unset_key(str(ROOT / ".env"), key)
        os.environ.pop(key, None)


def expiry(token: str | None = None) -> dict:
    """When the token stops working (never, for a Page token from a long-lived one), and whether it may delete Reels,
    if the app's id and secret are known to ask; else nothing."""
    token = token or env("INSTAGRAM_ACCESS_TOKEN")
    app_id, app_secret = env("FACEBOOK_APP_ID"), env("FACEBOOK_APP_SECRET")
    if not (token and app_id and app_secret):
        return {}
    try:
        data = _get("debug_token", f"{app_id}|{app_secret}", input_token=token).get("data") or {}
    except (InstagramError, requests.RequestException):
        return {}
    scopes = data.get("scopes")
    return {"expires_at": int(data.get("expires_at") or 0), "valid": bool(data.get("is_valid")),
            **({"can_delete": "instagram_manage_contents" in scopes} if isinstance(scopes, list) else {})}


def status() -> dict:
    """Whether posting would work now: the account it posts to, and how many of today's 100 posts are used."""
    if not is_configured():
        return {"connected": False}
    token, user = env("INSTAGRAM_ACCESS_TOKEN"), env("INSTAGRAM_USER_ID")
    try:
        me = _get(user, token, fields="username,name,media_count")
        limit = (_get(f"{user}/content_publishing_limit", token, fields="quota_usage,config").get("data") or [{}])[0]
    except (InstagramError, requests.RequestException) as e:
        return {"connected": False, "error": str(e)[:300], "username": env("INSTAGRAM_USERNAME"),
                "refused": isinstance(e, Disconnected)}
    return {"connected": True, "username": me.get("username"), "name": me.get("name"), "posts": me.get("media_count"),
            "used_today": limit.get("quota_usage"), "daily_limit": (limit.get("config") or {}).get("quota_total"),
            **expiry(token)}


def check() -> str | None:
    """Whether Meta takes the connection now, with one harmless read (the account's name): None if it does, else why
    not, in Meta's words. InstagramError when that can't be told (Meta unreachable, or another answer)."""
    if not is_configured():
        return "Instagram isn't connected (the dashboard's Channels page)"
    try:
        _get(env("INSTAGRAM_USER_ID"), env("INSTAGRAM_ACCESS_TOKEN"), fields="username")
    except Disconnected as e:
        return str(e)
    return None


def _seconds(video: Path) -> float:
    err = subprocess.run([short_render.ffmpeg_exe(), "-hide_banner", "-i", str(video)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=60).stderr
    found = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return int(found[1]) * 3600 + int(found[2]) * 60 + float(found[3]) if found else 90.0


def picture_kbps(seconds: float, mb: float) -> int:
    """The Reel copy's picture bitrate for a video this long to come to at most `mb` MB with its sound (a little
    under, for the MP4's own bytes), never above MOST_KBPS."""
    return int(min(MOST_KBPS, mb * 8000 * 0.92 / max(seconds, 1.0) - int(AUDIO_RATE.rstrip("k"))))


def _for_reels(video: Path, mb: float = REEL_MB) -> Path:
    """A copy of the video as Reels take it: the picture without B-frames, the sound at 128 kbps, no edit lists, at
    most `mb` MB."""
    out = tmp_path("out", f"reel_{video.stem}.mp4")
    kbps = picture_kbps(_seconds(video), mb)
    subprocess.run([short_render.ffmpeg_exe(), "-y", "-v", "error", "-i", str(video), "-map", "0:v", "-map", "0:a",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-bf", "0", "-pix_fmt", "yuv420p",
                    "-maxrate", f"{kbps}k", "-bufsize", f"{2 * kbps}k", "-c:a", "aac", "-b:a", AUDIO_RATE, "-ar", "44100",
                    "-use_editlist", "0", "-movflags", "+faststart", str(out)],
                   check=True, capture_output=True, timeout=900)
    return out


def _send(uri: str, file: Path, token: str) -> None:
    """The file to Instagram's upload address in CHUNK pieces, each at the offset where the last one ended, all on one
    kept-open connection (pieces on separate connections were often lost)."""
    size, offset = file.stat().st_size, 0
    with open(file, "rb") as f, requests.Session() as session:
        while offset < size:
            f.seek(offset)
            body = f.read(CHUNK)
            for attempt in range(CHUNK_TRIES):
                try:
                    resp = session.post(uri, data=body, timeout=300, headers={
                        "Authorization": f"OAuth {token}", "offset": str(offset), "file_size": str(size)})
                except requests.RequestException:
                    if attempt == CHUNK_TRIES - 1:
                        raise
                    time.sleep(5 * (attempt + 1))
                    continue
                if resp.status_code < 500 or attempt == CHUNK_TRIES - 1:
                    break
                time.sleep(5 * (attempt + 1))
            if resp.status_code not in (200, 206):  # 206: "Partial request", the next piece continues it
                _check(resp)
                raise InstagramError(f"Instagram answered {resp.status_code}: {resp.text[:300]}")
            offset += len(body)


def _processed(container: str, token: str, progress=print, uploaded: bool = True) -> None:
    """Waits until Instagram has the container's video processed: FINISHED, with its upload complete (a dropped upload
    can say FINISHED too, with no video: seen 2026-10-27). video_status exists only for a video sent to Instagram
    (`uploaded`): for one it fetched from a link, asking for it is refused (400, subcode 2207065, 2026-10-28)."""
    progress("Instagram is processing the video")
    deadline = time.monotonic() + WAIT_FOR
    while True:
        state = _get(container, token, fields="status_code,status,video_status" if uploaded else "status_code,status")
        code = state.get("status_code")
        if code == "FINISHED":
            if uploaded and ((state.get("video_status") or {}).get("uploading_phase") or {}).get("status") == "error":
                raise InstagramError("Instagram says the video is ready, but its upload failed (no video arrived)")
            return
        if code in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Instagram couldn't process the video: {state.get('status') or code}")
        if time.monotonic() > deadline:
            raise InstagramError(f"Instagram was still processing the video after {WAIT_FOR // 60} minutes")
        time.sleep(WAIT_EVERY)


def _by_upload(upload: Path, token: str, user: str, how: dict, progress=print) -> str:
    """The Reel copy sent to Instagram (pieces on one connection); its container, processed. Dropped at its last piece,
    it's sent again at once with a new container, UPLOAD_TRIES in all (a dropped container expires by itself)."""
    for attempt in range(UPLOAD_TRIES):
        made = _post(f"{user}/media", token, upload_type="resumable", **how)
        progress(f"Sending the video to Instagram ({upload.stat().st_size / 1e6:.0f} MB)")
        started = time.monotonic()
        try:
            _send(made.get("uri") or f"{UPLOAD}/{made['id']}", upload, token)
        except InstagramError as e:
            if "ProcessingFailedError" not in str(e) or attempt + 1 == UPLOAD_TRIES:
                raise
            progress(f"Instagram dropped the upload at its last piece ({time.monotonic() - started:.0f} s); trying again")
            continue
        _processed(made["id"], token, progress)
        return made["id"]


def _by_link(upload: Path, token: str, user: str, how: dict, progress=print, refused: list | None = None) -> str | None:
    """Instagram fetches the Reel copy itself, from a temporary public link to it (tools/tunnel.py), while it
    processes it; the container, processed. None if no link could be made, or Instagram didn't take the video
    from it (why is added to `refused`): the copy is sent instead."""
    try:
        with tunnel.link(upload, progress) as url:
            progress("Instagram is fetching the video from a temporary link")
            container = _post(f"{user}/media", token, video_url=url, **how)["id"]
            _processed(container, token, progress, uploaded=False)
            return container
    except tunnel.TunnelError as e:
        progress(f"No temporary link could be made ({e}); sending the video to Instagram instead")
        return None
    except Disconnected:  # (sending it would be refused the same way)
        raise
    except InstagramError as e:  # (refused at the first real try, 2026-10-28: "Invalid parameter (code 100)")
        progress(f"Instagram didn't take the video from the temporary link ({e}); sending it instead")
        if refused is not None:
            refused.append(str(e))
        return None


def send_way() -> str:
    """How the video gets to Instagram (settings instagram.send): "upload", or "link" (Instagram fetches it)."""
    way = str((load_config().get("instagram") or {}).get("send") or "upload").strip().lower()
    return way if way in SEND_WAYS else "upload"


def publish(video: Path | str, caption: str, cover_at: float = 0.0, progress=print) -> dict:
    """Posts the video as a Reel (also shown in the feed); returns its id and link, and why Instagram refused the
    temporary link if it did ("link_refused"; on an InstagramError, as its .link_refused)."""
    if not is_configured():
        raise InstagramError("Instagram isn't connected (the dashboard's Channels page)")
    token, user = env("INSTAGRAM_ACCESS_TOKEN"), env("INSTAGRAM_USER_ID")
    how = {"media_type": "REELS", "caption": caption[:CAPTION_CHARS], "share_to_feed": "true",
           "thumb_offset": str(max(0, int(cover_at * 1000)))}
    upload, refused = _for_reels(Path(video), REEL_MB), []
    try:
        container = (_by_link(upload, token, user, how, progress, refused) if send_way() == "link" else None) \
            or _by_upload(upload, token, user, how, progress)
        media = _post(f"{user}/media_publish", token, creation_id=container)["id"]
        try:
            link = _get(media, token, fields="permalink").get("permalink")
        except InstagramError:
            link = None
        return {"id": media, "url": link, **({"link_refused": refused[0]} if refused else {})}
    except InstagramError as e:
        if refused:
            e.link_refused = refused[0]
        raise
    finally:
        upload.unlink(missing_ok=True)


def delete(media_id: str) -> dict:
    """Deletes a posted Reel from Instagram. {"deleted": True}, or {"gone": True} if it isn't there any more."""
    if not is_configured():
        raise InstagramError("Instagram isn't connected (the dashboard's Channels page)")
    resp = _http("DELETE", f"{GRAPH}/{media_id}", params={"access_token": env("INSTAGRAM_ACCESS_TOKEN")}, timeout=30)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    err = body.get("error") if isinstance(body, dict) else None
    if resp.status_code < 400 and not err:
        return {"deleted": True}
    err = err if isinstance(err, dict) else {}
    message = err.get("message") or resp.text[:300]
    if "permission" in message.lower() or err.get("code") in (10, 200) or err.get("error_subcode") == 33:
        raise InstagramError(f"Instagram didn't delete it ({message}). Deleting needs the instagram_manage_contents "
                             "permission: make a new token with it in the Graph API Explorer and connect again (the "
                             "Channels page), or delete the Reel in the Instagram app.")
    if err.get("code") == 100 and "does not exist" in message.lower():
        return {"gone": True}
    raise InstagramError(f"Instagram answered {resp.status_code}: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--connect", metavar="TOKEN")
    parser.add_argument("--app-id")
    parser.add_argument("--app-secret")
    parser.add_argument("--file")
    parser.add_argument("--caption", default="")
    parser.add_argument("--cover-at", type=float, default=0.0, help="seconds into the video for the cover frame")
    args = parser.parse_args()
    try:
        if args.connect:
            result = connect(args.connect, args.app_id, args.app_secret)
        elif args.file:
            result = publish(args.file, args.caption, args.cover_at)
        else:
            result = status()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print({k: v for k, v in result.items() if "token" not in k})
    return 0


if __name__ == "__main__":
    sys.exit(main())
