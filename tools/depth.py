"""
How near each part of a photo is, so a still photo can move like a camera gliding past it (near
parts slide more than far ones: the "2.5D" look of documentaries). Depth Anything V2 Small
(Apache 2.0, onnx-community's ONNX export, pinned to one revision) runs on this computer's CPU
through onnxruntime; the model (~100 MB) downloads once into .tmp/models/depth. A photo's depth is
cached next to it as <photo>.depth.png (0 = far, 255 = near), so each photo is measured once.

Usage:
    python tools/depth.py --image photo.jpg [--out depth.png]
"""

import argparse
import sys
import threading
from pathlib import Path

import requests

from common import tmp_path

REVISION = "4472b7362082ad9968fee890ca0f1e5aca36b93d"
MODEL_URL = f"https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/{REVISION}/onnx/model.onnx"
SHORT_SIDE = 518  # the model sees the photo this big (sides multiples of 14)
MAX_LONG = 924
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)

_session = None
_lock = threading.Lock()


def model_path(progress=print) -> Path:
    path = tmp_path("models", "depth", "depth-anything-v2-small.onnx")
    if not path.exists():
        progress("Downloading the depth model (~100 MB), once")
        partial = path.with_suffix(".part")
        with requests.get(MODEL_URL, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(partial, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    f.write(chunk)
        partial.replace(path)
    return path


def _model():
    global _session
    if _session is None:
        import onnxruntime as ort

        _session = ort.InferenceSession(str(model_path()), providers=["CPUExecutionProvider"])
    return _session


def cache_path(image: Path) -> Path:
    return image.with_name(image.name + ".depth.png")


def depth_map(image: Path):
    """The photo's depth as floats 0 (far) to 1 (near), the photo's size; measured once, then read from the cache."""
    import numpy as np
    from PIL import Image, ImageFilter

    image = Path(image)
    cached = cache_path(image)
    photo = Image.open(image)
    if cached.exists():
        depth = Image.open(cached)
        if depth.size == photo.size:
            return np.asarray(depth, dtype=np.float32) / 255.0
    rgb = photo.convert("RGB")
    w, h = rgb.size
    scale = SHORT_SIDE / min(w, h)
    if max(w, h) * scale > MAX_LONG:
        scale = MAX_LONG / max(w, h)
    mw, mh = max(14, round(w * scale / 14) * 14), max(14, round(h * scale / 14) * 14)
    x = np.asarray(rgb.resize((mw, mh), Image.BICUBIC), dtype=np.float32) / 255.0
    x = ((x - np.array(MEAN, dtype=np.float32)) / np.array(STD, dtype=np.float32)).transpose(2, 0, 1)[None]
    with _lock:
        session = _model()
        out = session.run(None, {session.get_inputs()[0].name: x})[0]
    d = np.squeeze(out).astype(np.float32)
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    d = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
    img = Image.fromarray((d * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(max(2, w // 300)))  # soft edges: no tearing when it moves
    try:
        img.save(cached)
    except OSError:
        pass
    return np.asarray(img, dtype=np.float32) / 255.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--image", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    try:
        import numpy as np
        from PIL import Image

        d = depth_map(Path(args.image))
        out = Path(args.out) if args.out else cache_path(Path(args.image))
        Image.fromarray((d * 255).astype(np.uint8)).save(out)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
