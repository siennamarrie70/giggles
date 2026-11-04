"""
People cut out of photographs, for the Constructivist Montage look's photomontage: a person-segmentation model (u2net_human_seg, Apache
2.0, from the rembg project's release, checked against SHA256 below) runs on this computer's CPU through onnxruntime; the model (about
170 MB) downloads once into .tmp/models/cutout. The result has a 7 px paper border, the look's scissor edge, which also hides the
model's edge errors (the method is the Lemo-Opuscar kino-montage style's prep.py, MIT).

Group photographs rarely segment cleanly, and a poor cut-out looks worse than none, so cut() checks the shape and answers None for a
poor one: that photograph is then shown whole, in a window. Nothing here reads anything from outside but a photograph's pixels.

Usage:
    python tools/cutout.py --image photo.jpg --out person.png
"""

import argparse
import hashlib
import sys
import threading
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from common import tmp_path

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx"
SHA256 = "01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c"  # (read from the file itself, 2026-11-04: 175,997,641 bytes)
MAX_MODEL = 220 * 1024 * 1024
SIZE = 320                # the model sees the photograph this big
THRESHOLD = 0.5
BORDER = 7                # px of paper round the cut-out, at the height it's made at
HEIGHT = 900              # px tall: the cut-out is made at most this big
MIN_SHARE, MAX_SHARE = 0.03, 0.60   # of the photograph: smaller than this isn't a person you can see, bigger is usually the wrong thing
MIN_SOLID = 0.45          # of the shape's outline that it fills: lower is a tangle of people and things
MIN_TALL = 0.30           # of the photograph's height
TOP_MARGIN = 0.01         # of the photograph's height: a shape reaching this near the top has lost its head
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
PAPER = 228               # the border's grey (printed: near paper)

_session = None
_lock = threading.Lock()


def model_path(progress=print) -> Path:
    """The model's file, downloaded once and checked against its pinned checksum; a file that doesn't match is thrown away."""
    path = tmp_path("models", "cutout", "u2net_human_seg.onnx")
    if not path.exists():
        progress("Downloading the cut-out model (about 170 MB), once")
        partial = path.with_suffix(".part")
        digest, got = hashlib.sha256(), 0
        with requests.get(MODEL_URL, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(partial, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    got += len(chunk)
                    if got > MAX_MODEL:
                        raise RuntimeError("the cut-out model is bigger than it should be")
                    digest.update(chunk)
                    f.write(chunk)
        if digest.hexdigest() != SHA256:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"the cut-out model's checksum doesn't match: {digest.hexdigest()}")
        partial.replace(path)
    return path


def _model():
    global _session
    if _session is None:
        import onnxruntime as ort

        with _lock:
            if _session is None:
                _session = ort.InferenceSession(str(model_path()), providers=["CPUExecutionProvider"])
    return _session


def person_mask(img: Image.Image) -> np.ndarray:
    """The model's answer for a photograph: floats 0 to 1, the photograph's size."""
    model = _model()
    x = np.asarray(img.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS), dtype=np.float32) / 255
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
    m = model.run(None, {model.get_inputs()[0].name: x})[0][0, 0]
    m = (m - m.min()) / max(1e-6, float(m.max() - m.min()))
    small = Image.fromarray((m * 255).astype(np.uint8))
    return np.asarray(small.resize(img.size, Image.BICUBIC), dtype=np.float32) / 255


def good_shape(mask: np.ndarray) -> np.ndarray | None:
    """A yes/no mask of the biggest shape, if it looks like one person: a fair size, mostly solid, tall enough. None if it doesn't."""
    import cv2

    hard = ((mask > THRESHOLD) * 255).astype(np.uint8)
    hard = cv2.medianBlur(hard, 5)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(hard, connectivity=8)
    if count < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = int(stats[best, cv2.CC_STAT_AREA])
    h, w = hard.shape
    share = area / (h * w)
    if not MIN_SHARE <= share <= MAX_SHARE:
        return None
    if stats[best, cv2.CC_STAT_HEIGHT] / h < MIN_TALL:
        return None
    if stats[best, cv2.CC_STAT_TOP] <= h * TOP_MARGIN:  # it runs off the top: a head cut off by the picture's edge
        return None
    left, wide = stats[best, cv2.CC_STAT_LEFT], stats[best, cv2.CC_STAT_WIDTH]
    if left <= 1 and left + wide >= w - 1:  # edge to edge across the picture: not one person
        return None
    if int(stats[1:, cv2.CC_STAT_AREA].sum()) > area * 1.6:  # as much again in other shapes: a group
        return None
    shape = ((labels == best) * 255).astype(np.uint8)
    contours, _ = cv2.findContours(shape, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = cv2.contourArea(cv2.convexHull(np.vstack(contours)))
    if hull <= 0 or area / hull < MIN_SOLID:
        return None
    return shape


def cut(photo: Path | str, dest: Path | str, grey=None) -> Path | None:
    """The person in a photograph as a PNG with a paper border and a clear background, or None if there's no clean cut-out. The grey
    picture inside it is the plain photograph's: it's printed by the renderer's own table (grey: a table of 256 values to print it)."""
    import cv2

    with Image.open(photo) as im:
        img = im.convert("RGB")
    img.thumbnail((1600, 1600), Image.LANCZOS)
    shape = good_shape(person_mask(img))
    if shape is None:
        return None
    ys, xs = np.nonzero(shape)
    top, bottom, left, right = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    margin = BORDER + 4
    top, left = max(0, top - margin), max(0, left - margin)
    bottom, right = min(shape.shape[0], bottom + margin), min(shape.shape[1], right + margin)
    g = np.asarray(img.convert("L"))[top:bottom, left:right]
    shape = shape[top:bottom, left:right]
    if grey is not None:
        g = cv2.LUT(g, grey)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * BORDER + 1, 2 * BORDER + 1))
    outer = cv2.GaussianBlur(cv2.dilate(shape, kernel), (0, 0), 0.8)
    inner = cv2.GaussianBlur(shape, (0, 0), 1.0).astype(np.float32) / 255
    out_g = (g * inner + 255 * (1 - inner)).astype(np.uint8)  # (the border: full paper)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.merge("LA", (Image.fromarray(out_g), Image.fromarray(outer))).save(dest)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--image", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        made = cut(args.image, args.out)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(made if made else "No clean cut-out in that photograph.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
