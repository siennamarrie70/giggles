"""
Draws a case's scenes in the Professor's art, for the drawn look (settings look.style: drawn, your
choice on 2026-10-27): Cloudflare Workers AI's FLUX.1 [schnell], on Cloudflare's free plan. The free plan gives
10,000 "neurons" a day; a 1024x1024 picture at 4 steps costs about 58 (4.8 per 512x512 tile and 9.6
per step, Cloudflare's pricing page, 2026-10-27), so about 170 pictures a day. Past the allocation
Cloudflare refuses (the free plan never charges); this stops itself at BUDGET first, counting today's
neurons in a database note (draw:budget, by UTC day: Cloudflare's count resets at 00:00 UTC).
After DrawingUnavailable the drawing rests (a note, draw:rest: until 00:00 UTC when the day's drawing is
used up). Meanwhile the Shorts are made in the real-footage look instead, so the day's ten still go up
(settings look.when_out: footage, your choice on 2026-10-27; style_now()): a new case is researched and
written for footage, and a case written for drawings is written again for footage (agents/animator.py).
look.when_out: wait brings back waiting for Cloudflare, like Gemini's voice. The real cost was about
twice this count on 2026-10-27 (the allocation ran out at 64 pictures, ~3,900 by this count), so in
practice it's Cloudflare's refusal that starts the rest, not BUDGET.

Every picture gets the same art description first (settings look.art, written from his character
sheet: FLUX can't be shown the sheet itself, so the words keep the style close), then the scene, then
what it must never have (lettering, logos). A picture is kept by its description, seed, model and
steps in the folder it's drawn for (.tmp/scenes/<case>/), so a re-render, or a Reviewer's fix to one
scene, only draws what changed. FLUX.1 [schnell] on Workers AI has no size setting: it draws squares,
which the video shows through a moving 9:16 window (tools/doc_render.py Scene). It takes no seed
either (a 400 when sent): every call is a new picture, so the seed only names the kept file, and a
Reviewer's redraw (a new seed) gets a new drawing.

Each picture is trimmed (trim()): a plain paper margin FLUX sometimes paints round it, and a thin
strip at every edge, where it sometimes signs a picture like a painter (a tiny scribble in a corner,
2026-10-27).

The sample of 2026-10-27 (#40's opening, six drawings): about 3 s a drawing, the style close to his
across all six. FLUX.2 [klein] (look.model "@cf/black-forest-labs/flux-2-klein-4b") followed the
descriptions better (it drew the second person schnell left out) at about 160 neurons a picture, too
many for 10 Shorts a day on the free plan; this client speaks schnell's JSON only.

Keys in .env: CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN (a Workers AI API token; see
workflows/setup_accounts.md). Neither is ever printed.

Usage:
    python tools/draw.py --check                                   # one test picture (about 58 neurons)
    python tools/draw.py --scene "a 1920s country road at dawn, an empty car" --out .tmp/out/scene.jpg
"""

import argparse
import base64
import hashlib
import io
import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

import db
from common import env, load_config, tmp_path

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
MODEL = "@cf/black-forest-labs/flux-1-schnell"
STEPS = 4                # FLUX.1 [schnell] takes up to 8; 4 is its usual
TILE, STEP = 4.8, 9.6    # neurons per 512x512 tile and per step (flux-1-schnell)
SIZE = 1024              # what it draws: 1024x1024
BUDGET = 9000            # neurons a day this stops at (Cloudflare's free plan: 10,000)
SHORT_PICTURES = 9       # a drawn case's most drawings (agents/writer.py MAX_SCENES): a new one is drawn only if it fits
TIMEOUT = 120
TRIES = 3
ART = ("anime-style 2D illustration in the look of a hand-painted animated film: clean dark ink outlines, soft "
       "painted cel shading, warm amber lamplight against deep navy shadows, a muted palette of rust, brown, cream "
       "and dark blue, a richly painted detailed background, cinematic composition")
# FLUX has no negative prompt: naming a thing ("no border") can draw it, so the picture's edges are asked for plainly
# (it drew a white paper edge round the first test) and trim() cuts any plain margin that still comes
NEVER = "full-bleed painting filling the whole picture edge to edge, no text, no lettering, no logos, no watermark"
MARGIN = 0.12            # trim() cuts a plain edge band up to this share of a side...
EDGE = 0.04              # ...and always this much more (a painter's signature sits in a corner)
CHECK_SCENE = "an old professor's study at night: shelves of books, a green-shaded desk lamp, a globe by the window"


class DrawingUnavailable(RuntimeError):
    """Cloudflare can't draw now (today's free allocation is used up, the key is missing or refused, or it's down):
    the case waits, nothing counted against it. `until`: when it can draw again, if that's known (00:00 UTC for the
    day's allocation)."""

    def __init__(self, message: str, until: str | None = None):
        super().__init__(message)
        self.until = until


def style() -> str:
    """The look set for new cases: "drawn" (scenes in his art) or "footage" (stock video, archive film, photos)."""
    return "drawn" if str((load_config().get("look") or {}).get("style") or "").strip().lower() == "drawn" else "footage"


def fallback() -> bool:
    """While Cloudflare can't draw, are Shorts made in the real-footage look (look.when_out: footage, the default)
    rather than waiting for it (look.when_out: wait)?"""
    return str((load_config().get("look") or {}).get("when_out") or "footage").strip().lower() != "wait"


def resting() -> dict | None:
    """The note saying Cloudflare's drawing rests (today's free drawing is used up, or it failed), if it does."""
    note = db.latest_note("draw:rest")
    return note if note and (note.get("until") or "") > db.now_iso() else None


def can_draw() -> bool:
    """Can a whole case be drawn now: Cloudflare connected, not resting, and today's count leaves room for it."""
    return (is_configured() and not resting()
            and spent_today()["neurons"] + SHORT_PICTURES * cost(settings()["steps"]) <= BUDGET)


def style_now() -> str:
    """The look a case made now gets: the setting's, but the real-footage look while Cloudflare can't draw (unless
    look.when_out says wait)."""
    look = style()
    return "footage" if look == "drawn" and fallback() and not can_draw() else look


def is_configured() -> bool:
    return bool(env("CLOUDFLARE_ACCOUNT_ID") and env("CLOUDFLARE_API_TOKEN"))


def settings() -> dict:
    look = load_config().get("look") or {}
    return {"model": look.get("model") or MODEL, "steps": int(look.get("steps") or STEPS), "art": look.get("art") or ART}


def cost(steps: int) -> float:
    """Neurons for one picture."""
    return (SIZE // 512) ** 2 * TILE + steps * STEP


def prompt_for(scene: str, art: str | None = None) -> str:
    return f"{(art or ART).strip().rstrip('.')}. {' '.join(scene.split()).rstrip('.')}. {NEVER}."


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def renews_at() -> str:
    """When Cloudflare's daily allocation (and this budget) starts again: the next 00:00 UTC."""
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    return f"{tomorrow.isoformat()}T00:00:00Z"


def spent_today() -> dict:
    """Today's drawing: {"neurons", "pictures"} (UTC day, as Cloudflare counts)."""
    note = db.latest_note("draw:budget") or {}
    if note.get("day") != _today():
        return {"neurons": 0.0, "pictures": 0}
    return {"neurons": float(note.get("neurons") or 0), "pictures": int(note.get("pictures") or 0)}


def _spend(neurons: float) -> None:
    now = spent_today()
    db.keep_note("draw:budget", {"day": _today(), "neurons": round(now["neurons"] + neurons, 1),
                                 "pictures": now["pictures"] + 1})


def picture_path(folder: Path, scene: str, seed: int, how: dict) -> Path:
    """Where a picture of this scene is kept: named by everything that changes it."""
    key = json.dumps([prompt_for(scene, how["art"]), int(seed), how["model"], how["steps"]])
    return Path(folder) / f"scene_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:14]}.jpg"


def trim(picture: Image.Image) -> Image.Image:
    """The picture without a plain (near-white or near-black, flat) band round its edges, nor a thin strip at every
    edge (EDGE), at its size again."""
    grey = np.asarray(picture.convert("L"), dtype=np.float32)
    h, w = grey.shape
    most = int(min(h, w) * MARGIN)

    def plain(strip):
        return strip.std() < 9 and (strip.mean() > 215 or strip.mean() < 22)

    top = next((i for i in range(most) if not plain(grey[i])), most)
    bottom = next((i for i in range(most) if not plain(grey[h - 1 - i])), most)
    left = next((i for i in range(most) if not plain(grey[:, i])), most)
    right = next((i for i in range(most) if not plain(grey[:, w - 1 - i])), most)
    margin = max(top, bottom, left, right)
    cut = margin + (6 if margin else 0) + round(min(h, w) * EDGE)  # the same from every side keeps it square (a little
    return picture.crop((cut, cut, w - cut, h - cut)).resize((w, h), Image.LANCZOS)  # more for a margin's ragged edge)


def _error(resp: requests.Response) -> str:
    try:
        errors = resp.json().get("errors") or []
        return "; ".join(str(e.get("message", e)) for e in errors)[:300] or resp.text[:300]
    except ValueError:
        return resp.text[:300]


def draw(scene: str, folder: Path | str | None = None, seed: int = 0, progress=print) -> Path:
    """The scene drawn in his art (a 1024x1024 JPEG in `folder`): the kept picture if it's been drawn before."""
    how = settings()
    folder = Path(folder or tmp_path("scenes", "misc", "x").parent)
    out = picture_path(folder, scene, seed, how)
    if out.exists() and out.stat().st_size > 1000:
        return out
    if not is_configured():
        raise DrawingUnavailable("Cloudflare isn't connected: add CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN to .env "
                                 "(workflows/setup_accounts.md)")
    need = cost(how["steps"])
    used = spent_today()["neurons"]
    if used + need > BUDGET:
        raise DrawingUnavailable(f"today's free drawing is used up ({used:.0f} of {BUDGET} neurons); it renews at "
                                 "00:00 UTC (05:30 in India)", until=renews_at())
    url = API.format(account=env("CLOUDFLARE_ACCOUNT_ID"), model=how["model"])
    # Workers AI's schnell takes no seed (a 400 "unevaluated properties '/seed'", 2026-10-27): every call draws a new
    # picture, so the seed only names the kept file, and a new seed (a Reviewer's redraw) gets a new drawing
    body = {"prompt": prompt_for(scene, how["art"]), "steps": how["steps"]}
    last = ""
    for attempt in range(TRIES):
        try:
            resp = requests.post(url, json=body, timeout=TIMEOUT,
                                 headers={"Authorization": f"Bearer {env('CLOUDFLARE_API_TOKEN')}"})
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {str(e)[:160]}"
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code == 200:
            image = (resp.json().get("result") or {}).get("image")
            if not image:
                raise RuntimeError("Cloudflare answered without a picture")
            picture = trim(Image.open(io.BytesIO(base64.b64decode(image))).convert("RGB"))
            folder.mkdir(parents=True, exist_ok=True)
            partial = out.with_suffix(".part")
            picture.save(partial, "JPEG", quality=93)
            partial.replace(out)
            _spend(need)
            return out
        why = _error(resp)
        if resp.status_code in (401, 403):
            raise DrawingUnavailable(f"Cloudflare refused the key ({resp.status_code}): {why}")
        if any(w in why.lower() for w in ("neuron", "allocation", "quota")):
            raise DrawingUnavailable(f"Cloudflare won't draw more today ({resp.status_code}): {why}", until=renews_at())
        if resp.status_code == 429 or "rate limit" in why.lower():
            raise DrawingUnavailable(f"Cloudflare asked to slow down ({resp.status_code}): {why}")
        if resp.status_code < 500:  # e.g. a scene its safety filter refused: this scene's problem, not Cloudflare's
            raise RuntimeError(f"Cloudflare couldn't draw “{scene[:80]}” ({resp.status_code}): {why}")
        last = f"{resp.status_code}: {why}"
        time.sleep(3 * (attempt + 1))
    raise DrawingUnavailable(f"Cloudflare didn't draw it after {TRIES} tries ({last})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--check", action="store_true", help="draw one test picture")
    parser.add_argument("--scene", help="what to draw")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", help="where to save it (default: .tmp/out/draw_check.jpg)")
    args = parser.parse_args()
    scene = CHECK_SCENE if args.check or not args.scene else args.scene
    out = Path(args.out or tmp_path("out", "draw_check.jpg"))
    try:
        started = time.monotonic()
        made = draw(scene, out.parent / "draw_cache", args.seed)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(made, out)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    today = spent_today()
    print(f"Drew {out} in {time.monotonic() - started:.1f} s; today: {today['pictures']} pictures, "
          f"{today['neurons']:.0f} of {BUDGET} neurons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
