"""
Makes the Professor's drawings for the videos, once, from the user's own character sheet
(assets/host/sheet.png), so he always looks exactly like it. His "Headshot" drawing is upscaled 2x
by waifu2x (an anime-art upscaler, MIT licence: its author's ONNX model, run on this computer and
checked against its SHA-256), cut out of the paper, and given the few extra drawings he needs to
talk and blink, all made from that same drawing:
  base.png                        him, cut out: eyes open, mouth closed
  mouth_1.png .. mouth_3.png      his jaw and beard dropped a little, more, and wide, with his mouth
                                  open under the moustache in the colours of the open mouth on the
                                  sheet's "Narrating / Speaking" drawing (patches)
  eyes_half.png, eyes_closed.png  his eyelids half and fully closed (patches)
  rig.json                        where the patches go, his face and the point he tilts around
tools/host.py reads these for every video; this only runs again if the drawing changes. The places
below (mouth, eyes, jaw) were measured on the upscaled drawing, 2026-10-26.

Usage:
    python tools/host_prep.py       # remakes assets/host/* and shows them all in .tmp/out/host_check.png
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter

from common import ASSETS_DIR, tmp_path

HOST_DIR = ASSETS_DIR / "host"
SHEET = HOST_DIR / "sheet.png"
HEADSHOT = (930, 0, 1225, 352)  # the sheet's "Headshot" drawing, in sheet pixels
MODEL_URL = "https://unlimited.waifu2x.net/models/swin_unet/art/scale2x.onnx"
MODEL_SHA256 = "f5de9edfbc4ef273c962502ccd949e6d4e3b2a93db2c2f9cba5c795d19554342"
SCALE, OFFSET = 2, 16           # the model doubles the size and trims OFFSET output pixels off each side
PAPER_TOLERANCE = 14            # how far from the paper's colour (Lab, colour counted double) is still paper
SS = 4                          # drawn this much bigger, then shrunk: smooth edges

# His face, in the upscaled drawing's pixels.
MOUTH_LINE = ((270, 463.5), (380, 473.5))  # the moustache's lower edge, where the mouth opens
MOUTH_X = 330                              # the middle of the mouth, under the parting of the moustache
MOUTHS = [(8, 33), (14, 42), (19, 50)]     # (how far the lips part, half the mouth's width): slight, open, wide
LIPS_EASE = 34                             # the chin drops fully this far below the lips (more than 1.5x the widest
                                           # opening, so the beard stretches smoothly and never folds)
JAW = [(236, 462), (214, 474), (200, 500), (212, 530), (240, 558), (272, 580), (304, 596), (322, 600),
       (345, 590), (372, 560), (398, 522), (414, 486), (404, 470)]  # lower lip and beard: what drops
MOUTH_COLOURS = {"dark": (38, 16, 14), "inside": (108, 44, 36), "tongue": (164, 86, 70), "lip": (84, 40, 32)}
EYES = {  # the open eye (white and iris, up to the top of the lid line); where the lid sits half and fully closed
    "right": {"open": [(240, 312), (248, 306), (262, 303), (280, 303), (296, 306), (305, 312), (306, 320), (300, 326),
                       (288, 331), (272, 333), (256, 331), (246, 327), (240, 320)],
              "half": [(240, 316), (256, 314), (272, 314), (290, 315), (305, 318)],
              "closed": [(241, 318), (256, 326), (272, 329), (290, 326), (304, 319)]},
    "left": {"open": [(377, 330), (385, 322), (398, 318), (414, 319), (428, 325), (440, 333), (441, 340), (432, 344),
                      (418, 348), (402, 350), (388, 347), (379, 342), (376, 336)],
             "half": [(377, 333), (392, 330), (408, 330), (424, 332), (440, 336)],
             "closed": [(378, 336), (392, 344), (408, 347), (424, 344), (440, 337)]},
}
LID_COLOUR = (28, 18, 16)
PIVOT = (300, 690)  # he tilts around the base of his neck


# --- the drawing ---------------------------------------------------------------

def model_path(progress=print) -> Path:
    path = tmp_path("models", "waifu2x", "swin_unet_art_scale2x.onnx")
    if not path.exists():
        progress("Downloading waifu2x's anime-art model (19 MB), once")
        resp = requests.get(MODEL_URL, timeout=120)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        path.unlink()
        raise RuntimeError(f"waifu2x's model isn't the file checked on 2026-10-26 (SHA-256 {digest[:12]}...)")
    return path


def upscale(img: Image.Image) -> Image.Image:
    """2x with waifu2x (swin_unet, art): the picture padded by repeating its edges, as the web version does."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(model_path()), providers=["CPUExecutionProvider"])
    a = np.asarray(img.convert("RGB"))
    h, w = a.shape[:2]
    pad = OFFSET // SCALE

    def size(v):  # the model's windows need (side - 16) to be a multiple of 48
        while (v - 16) % 48:
            v += 1
        return v

    ph, pw = size(h + 2 * pad), size(w + 2 * pad)
    x = np.pad(a, ((pad, ph - h - pad), (pad, pw - w - pad), (0, 0)), mode="edge")
    y = session.run(None, {"x": x.transpose(2, 0, 1)[None].astype(np.float32) / 255})[0][0]
    y = np.clip(y.transpose(1, 2, 0) * 255 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(y[:h * SCALE, :w * SCALE])


def cut_out(img: Image.Image) -> Image.Image:
    """Him without the paper: paper reachable from the edges goes (his ink lines stop it), then only the biggest
    piece stays (no label or stray marks), and paper-coloured specks enclosed near the bottom edge go too."""
    import cv2

    rgb = np.asarray(img.convert("RGB"))
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    edge = np.concatenate([lab[:6].reshape(-1, 3), lab[-6:].reshape(-1, 3), lab[:, :6].reshape(-1, 3),
                           lab[:, -6:].reshape(-1, 3)])
    paper = np.median(edge, axis=0)
    near = np.sqrt(((lab - paper) ** 2 * np.array([1.0, 2.0, 2.0], dtype=np.float32)).sum(-1)) < PAPER_TOLERANCE
    _, labels = cv2.connectedComponents(near.astype(np.uint8), connectivity=4)
    outside = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    figure = ~(np.isin(labels, list(outside)) & near)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(figure.astype(np.uint8), connectivity=8)
    mask = labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    h = mask.shape[0]
    mask[int(h * 0.82):] &= ~near[int(h * 0.82):]
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 0.8)
    return Image.fromarray(np.dstack([rgb, (alpha * 255 + 0.5).astype(np.uint8)]), "RGBA")


# --- talking ---------------------------------------------------------------

def _mouth_line(x):
    (x0, y0), (x1, y1) = MOUTH_LINE
    return y0 + (y1 - y0) / (x1 - x0) * (x - x0)


def _lens(x, half_width: float):
    """How far apart the lips are along the mouth (0 at the corners, 1 in the middle)."""
    u = np.clip((np.asarray(x, dtype=np.float32) - MOUTH_X) / half_width, -1, 1)
    return np.maximum(np.cos(np.pi / 2 * u), 0) ** 0.8


def _soft_polygon(size: tuple[int, int], points: list, blur: float = 0.0) -> np.ndarray:
    """A polygon as a 0-1 mask with smooth edges (drawn SS times bigger, then shrunk)."""
    w, h = size
    big = Image.new("L", (w * SS, h * SS), 0)
    ImageDraw.Draw(big).polygon([(x * SS, y * SS) for x, y in points], fill=255)
    small = big.resize((w, h), Image.LANCZOS)
    if blur:
        small = small.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(small, dtype=np.float32) / 255


def mouth(base: Image.Image, opening: float, half_width: float) -> Image.Image:
    """Him with his mouth open: everything under the moustache's edge (lower lip, chin, beard) drops by up to
    `opening` px (the mouth's corners stay put), and the gap is his open mouth."""
    import cv2

    a = np.asarray(base, dtype=np.float32)
    h, w = a.shape[:2]
    X, Y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    below = Y - _mouth_line(X)
    jaw = cv2.GaussianBlur(_soft_polygon((w, h), JAW), (0, 0), 10)
    ease = np.clip(below / LIPS_EASE, 0, 1)
    ease = ease * ease * (3 - 2 * ease)
    profile = _lens(X, half_width) * (np.abs(X - MOUTH_X) < half_width) * (1 - ease) + jaw * ease
    drop = np.where(below > 0, opening * profile, 0).astype(np.float32)
    moved = cv2.remap(a, X, Y - drop, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    out = Image.fromarray(np.clip(moved, 0, 255).astype(np.uint8), "RGBA")

    # The open mouth, between the moustache's edge and the dropped lower lip, drawn big then shrunk.
    xs = np.arange(MOUTH_X - half_width, MOUTH_X + half_width + 0.5, 0.5)
    gap = opening * _lens(xs, half_width)
    top = [(x, _mouth_line(x) - 1.0) for x in xs]
    bottom = [(x, _mouth_line(x) + g) for x, g in zip(xs, gap)]
    x0, y0 = int(xs[0]) - 2, int(min(y for _, y in top)) - 2
    x1, y1 = int(xs[-1]) + 3, int(max(y for _, y in bottom)) + 4
    bw, bh = (x1 - x0) * SS, (y1 - y0) * SS
    shape = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(shape).polygon([((x - x0) * SS, (y - y0) * SS) for x, y in top + bottom[::-1]], fill=255)
    colour = Image.new("RGB", (bw, bh), MOUTH_COLOURS["dark"])
    d = ImageDraw.Draw(colour)
    for x, g in zip(xs, gap):  # down each column: dark at the top, the inside, then the tongue if it's wide open
        line = _mouth_line(x) - y0
        for frac, name in ((0.45, "inside"), (0.75, "tongue" if opening >= 11 else "inside")):
            d.rectangle(((x - x0) * SS, (line + g * frac) * SS, (x - x0 + 0.5) * SS + 1, (line + g + 2) * SS),
                        fill=MOUTH_COLOURS[name])
    colour = colour.filter(ImageFilter.GaussianBlur(SS * 0.7))
    lip = Image.new("L", (bw, bh), 0)  # a thin line along the lower lip
    ImageDraw.Draw(lip).line([((x - x0) * SS, (y - y0) * SS) for x, y in bottom[len(bottom) // 10: -len(bottom) // 10]],
                             fill=255, width=int(1.5 * SS))
    colour.paste(Image.new("RGB", (bw, bh), MOUTH_COLOURS["lip"]), (0, 0), lip)
    piece = colour.resize((x1 - x0, y1 - y0), Image.LANCZOS).convert("RGBA")
    piece.putalpha(shape.resize((x1 - x0, y1 - y0), Image.LANCZOS))
    out.alpha_composite(piece, (x0, y0))
    return out


# --- blinking ---------------------------------------------------------------

def _smooth(points: list, steps: int = 8) -> list:
    """A smooth curve through the points (Catmull-Rom)."""
    p = [points[0]] + list(points) + [points[-1]]
    out = []
    for k in range(1, len(p) - 2):
        p0, p1, p2, p3 = (np.asarray(v, dtype=np.float32) for v in p[k - 1:k + 3])
        for t in np.linspace(0, 1, steps, endpoint=False):
            out.append(tuple(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                                    + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3)))
    return out + [tuple(points[-1])]


def _skin_fill(rgb: np.ndarray, cover: np.ndarray) -> np.ndarray:
    """The skin a lid would show: a smooth gradient fitted to the clean skin around the eye (not its lines,
    lashes or glasses), so the lid keeps the drawing's shading."""
    import cv2

    hole = (cover > 0.02).astype(np.uint8)
    ring = (cv2.dilate(hole, np.ones((13, 13), np.uint8)) > 0) & ~(cv2.dilate(hole, np.ones((5, 5), np.uint8)) > 0)
    f = rgb.astype(np.float32)
    skin = ring & (f.mean(axis=2) > 140) & (f.max(axis=2) - f.min(axis=2) > 45)
    ys, xs = np.nonzero(skin)
    design = np.stack([np.ones_like(xs), xs, ys], axis=1).astype(np.float32)
    coef, *_ = np.linalg.lstsq(design, f[ys, xs], rcond=None)
    Y, X = np.mgrid[0:rgb.shape[0], 0:rgb.shape[1]].astype(np.float32)
    return np.clip(coef[0] + X[:, :, None] * coef[1] + Y[:, :, None] * coef[2], 0, 255)


def _stroke(points: list, widths: tuple[float, float, float]) -> list:
    """A brush stroke along `points` as one polygon: widths at the start, middle and end."""
    pts = np.asarray(_smooth(points), dtype=np.float32)
    seg = np.diff(pts, axis=0)
    t = np.concatenate([[0], np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))])
    t /= t[-1]
    left, right = [], []
    for k, (p, s) in enumerate(zip(pts, t)):
        d = pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]
        n = np.array([-d[1], d[0]]) / (np.hypot(*d) or 1)
        width = np.interp(s, [0, 0.5, 1], widths)
        left.append(tuple(p + n * width / 2))
        right.append(tuple(p - n * width / 2))
    return left + right[::-1]


def eyes(base: Image.Image, state: str) -> Image.Image:
    """Him with his eyelids half or fully closed: the lid in the colours of the skin around the eye, and the
    lid's line where it now sits."""
    out = base.copy()
    w, h = base.size
    for eye in EYES.values():
        xs, ys = zip(*eye["open"])
        top = min(ys) - 1
        if state == "closed":
            cover = _soft_polygon((w, h), eye["open"], 0.5)
        else:  # the eye's upper part, down to where the lid now sits
            curve = eye["half"]
            region = [(curve[0][0] - 2, top - 2), (curve[-1][0] + 2, top - 2)] + curve[::-1]
            cover = np.minimum(_soft_polygon((w, h), eye["open"], 0.5), _soft_polygon((w, h), region, 0.5))
        a = np.asarray(out, dtype=np.float32)
        skin = _skin_fill(a[:, :, :3], cover)
        a[:, :, :3] = a[:, :, :3] * (1 - cover[:, :, None]) + skin * cover[:, :, None]
        out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
        widths = (1.6, 4.2, 1.6) if state == "closed" else (4.0, 6.0, 4.0)
        line = eye["closed"] if state == "closed" else eye["half"]
        if line[0][0] > line[-1][0]:
            line = line[::-1]
        big = Image.new("L", (w * SS, h * SS), 0)
        ImageDraw.Draw(big).polygon([(x * SS, y * SS) for x, y in _stroke(line, widths)], fill=255)
        stroke = big.resize((w, h), Image.LANCZOS)
        out.paste(Image.new("RGBA", (w, h), (*LID_COLOUR, 255)), (0, 0), stroke)
    return out


# --- saving ---------------------------------------------------------------

def _patch(base: Image.Image, changed: Image.Image) -> tuple[Image.Image, list[int]]:
    """The part of `changed` that differs from `base`, and where it goes."""
    diff = np.abs(np.asarray(changed, dtype=np.int16) - np.asarray(base, dtype=np.int16)).max(axis=2) > 0
    ys, xs = np.nonzero(diff)
    box = (max(0, xs.min() - 2), max(0, ys.min() - 2), min(base.width, xs.max() + 3), min(base.height, ys.max() + 3))
    return changed.crop(box), [int(box[0]), int(box[1])]


def prepare(progress=print) -> dict:
    sheet = Image.open(SHEET).convert("RGB")
    progress("Upscaling the Headshot 2x (waifu2x)")
    big = upscale(sheet.crop(HEADSHOT))
    progress("Cutting him out of the paper")
    base = cut_out(big)
    HOST_DIR.mkdir(parents=True, exist_ok=True)
    base.save(HOST_DIR / "base.png", optimize=True)
    rig = {"source": f"sheet.png, Headshot {list(HEADSHOT)}, upscaled {SCALE}x", "size": list(base.size),
           "pivot": list(PIVOT), "face": [180, 60, 460, 600], "mouth": [MOUTH_X, round(_mouth_line(MOUTH_X), 1)],
           "mouths": [], "eyes": {}}
    for n, (opening, half_width) in enumerate(MOUTHS, start=1):
        piece, at = _patch(base, mouth(base, opening, half_width))
        piece.save(HOST_DIR / f"mouth_{n}.png", optimize=True)
        rig["mouths"].append({"file": f"mouth_{n}.png", "at": at})
    for state in ("half", "closed"):
        piece, at = _patch(base, eyes(base, state))
        piece.save(HOST_DIR / f"eyes_{state}.png", optimize=True)
        rig["eyes"][state] = {"file": f"eyes_{state}.png", "at": at}
    (HOST_DIR / "rig.json").write_text(json.dumps(rig, indent=1), encoding="utf-8")
    progress(f"Saved {HOST_DIR}")
    return rig


def check_sheet(dest: Path) -> Path:
    """Every mouth with every eye state, over dark and light backgrounds, and the face close up."""
    rig = json.loads((HOST_DIR / "rig.json").read_text(encoding="utf-8"))
    base = Image.open(HOST_DIR / "base.png")
    mouths = [None] + [(Image.open(HOST_DIR / m["file"]), tuple(m["at"])) for m in rig["mouths"]]
    lids = [None] + [(Image.open(HOST_DIR / e["file"]), tuple(e["at"])) for e in rig["eyes"].values()]
    w, h = base.size
    s = 0.5
    tw, th = int(w * s), int(h * s)
    board = Image.new("RGB", (tw * 4, th * 3 * 2 + 400 * 2), (60, 60, 60))
    face_box = (200, 280, 460, 620)
    for row, eye in enumerate(lids):
        for col, m in enumerate(mouths):
            img = base.copy()
            for part in (m, eye):
                if part:
                    img.alpha_composite(part[0], part[1])
            for k, bg in enumerate([(14, 22, 38), (196, 210, 224)]):
                tile = Image.new("RGB", (w, h), bg)
                tile.paste(img, (0, 0), img)
                board.paste(tile.resize((tw, th), Image.LANCZOS), (col * tw, (k * 3 + row) * th))
            if row == 0 or col == 0:  # close-ups: the mouths (top) and the eyes (bottom)
                close = Image.new("RGB", (w, h), (14, 22, 38))
                close.paste(img, (0, 0), img)
                close = close.crop(face_box).resize((tw, 400 * tw // tw), Image.LANCZOS)
                y = th * 6 + (0 if row == 0 else 400)
                board.paste(close.resize((tw, 400)), ((col if row == 0 else row) * tw, y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    board.save(dest)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--check-only", action="store_true", help="only redraw the check sheet")
    args = parser.parse_args()
    try:
        if not args.check_only:
            prepare()
        print(f"Check: {check_sheet(tmp_path('out', 'host_check.png'))}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
