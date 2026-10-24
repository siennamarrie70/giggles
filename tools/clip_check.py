"""
Checks candidate clips from their preview frames with Gemini and scores them.

All candidates go in one request (cheap on the free tier). Clips are rejected for a
visible child, people in frame (unless allowed in config), watermarks or burned-in
text, an animal in distress or danger, poor footage, or not fitting the theme.
The hard rules are applied in code after the model answers, so a lenient answer
can't let a child through.

Usage:
    python tools/clip_check.py --candidates .tmp/candidates.json --theme "cats vs Mondays" [--out .tmp/checked.json]
"""

import argparse
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

import llm
from common import load_config, tmp_path

FRAME_SIZE = 512  # px, long side; plenty for judging and keeps the request small

SYSTEM = """You review stock video clips for a family-friendly YouTube Shorts channel of cute, funny animals.
Each candidate comes with 1-3 frames taken from the same clip. Judge only what you can see in the frames.
Be strict about safety flags: if you are unsure whether a person or child is visible, flag it.
fits_theme is false when the main animal isn't the wanted animal, including its colour or breed when the
wanted animal names one (a grey cat doesn't fit 'black cat').
Score 0-10 for how cute, funny or eye-catching the clip would be as a Short, and how well it suits the theme."""

SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "animal": {"type": "string", "description": "main animal, e.g. 'orange kitten'"},
                    "what_happens": {"type": "string", "description": "one short sentence describing the action"},
                    "people_visible": {"type": "boolean", "description": "any person or body part (hands count)"},
                    "child_visible": {"type": "boolean"},
                    "watermark_or_text": {"type": "boolean", "description": "logo, watermark, captions or other text"},
                    "distress_or_danger": {"type": "boolean", "description": "animal scared, hurt, sick, trapped or at risk"},
                    "low_quality": {"type": "boolean", "description": "blurry, dark, shaky or the animal is hard to see"},
                    "fits_theme": {"type": "boolean"},
                    "score": {"type": "integer", "description": "0-10"},
                },
                "required": ["index", "animal", "what_happens", "people_visible", "child_visible",
                             "watermark_or_text", "distress_or_danger", "low_quality", "fits_theme", "score"],
            },
        },
    },
    "required": ["candidates"],
}


def fetch_frame(url: str) -> bytes | None:
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None
    img.thumbnail((FRAME_SIZE, FRAME_SIZE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def reject_reasons(verdict: dict | None, allow_people: bool, min_score: int) -> list[str]:
    if verdict is None:
        return ["not assessed"]
    reasons = []
    if verdict["child_visible"]:
        reasons.append("child visible")
    if verdict["people_visible"] and not allow_people:
        reasons.append("people visible")
    if verdict["watermark_or_text"]:
        reasons.append("watermark or text")
    if verdict["distress_or_danger"]:
        reasons.append("distress or danger")
    if verdict["low_quality"]:
        reasons.append("low quality")
    if not verdict["fits_theme"]:
        reasons.append("off theme")
    if verdict["score"] < min_score:
        reasons.append(f"score {verdict['score']} < {min_score}")
    return reasons


def run(candidates: list[dict], theme: str, allow_people: bool = False, min_score: int = 6,
        animal: str | None = None) -> list[dict]:
    """Returns the candidates with `check`, `ok` and `reject_reasons` added, best first."""
    wanted = f"\nWanted animal: {animal}" if animal else ""
    parts = [f"Theme of the Short: {theme}{wanted}\nThere are {len(candidates)} candidates, numbered from 0."]
    with ThreadPoolExecutor(max_workers=8) as pool:  # ~24 small images; fetching them in parallel saves ~30 s
        futures = [[pool.submit(fetch_frame, url) for url in clip["preview_urls"][:3]] for clip in candidates]
        frames_per_clip = [[f.result() for f in clip_futures] for clip_futures in futures]
    has_frames = set()
    for i, clip in enumerate(candidates):
        frames = [f for f in frames_per_clip[i] if f]
        if frames:
            has_frames.add(i)
            parts.append(f"Candidate {i}:")
            parts.extend(("image/jpeg", f) for f in frames)

    verdicts = {}
    if has_frames:
        answer = llm.generate_json(parts, SCHEMA, system=SYSTEM)
        for v in answer.get("candidates", []):
            if v.get("index") in has_frames:
                v["score"] = max(0, min(10, int(v.get("score", 0))))
                verdicts[v["index"]] = v

    checked = []
    for i, clip in enumerate(candidates):
        verdict = verdicts.get(i)
        reasons = reject_reasons(verdict, allow_people, min_score) if i in has_frames else ["no preview frames"]
        checked.append({**clip, "check": verdict, "ok": not reasons, "reject_reasons": reasons})
    return sorted(checked, key=lambda c: (c["ok"], (c["check"] or {}).get("score", -1)), reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--candidates", required=True, help="JSON file from clips_search.py")
    parser.add_argument("--theme", required=True)
    parser.add_argument("--animal", help="Wanted animal, e.g. 'black cat'")
    parser.add_argument("--out", default=str(tmp_path("checked.json")))
    args = parser.parse_args()

    content = load_config()["content"]
    try:
        with open(args.candidates, encoding="utf-8") as f:
            candidates = json.load(f)
        checked = run(candidates, args.theme, content["allow_people"], content["min_check_score"], args.animal)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(checked, f, indent=2, ensure_ascii=False)
    for c in checked:
        what = (c["check"] or {}).get("what_happens", "")
        status = "OK " if c["ok"] else "NO "
        print(f"{status}{c['key']:<18} score {(c['check'] or {}).get('score', '-'):>2}  {what}  {', '.join(c['reject_reasons'])}")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
