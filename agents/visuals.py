"""
Agent 3, Visuals (2026-11-24, your plan: an agent between the script writer and the Animator): each story's pictures.

  1. Its storyboard (agents/storyboard.py): its places, its people, a shot for every moment, the habit shown big, the
     thumbnail, all from the code-drawn library. Everything the library has is reused, never made again.
  2. What the script needed that the library lacks, made new: a thing (in the place that wanted it: on a table or a
     shelf, on the floor by the wall, or on the wall) or a picture (in the picture bubble that wished for it). Always a
     silhouette, your rule (tools/visual_recipes.py): Gemini designs it as a recipe (data, never code); code checks it,
     draws it and it must read as a silhouette; then Gemini compares it with three of the library's own and it must be
     the same silhouette style and clearly what it should be. One redesign with what was wrong; else the closest stays,
     as before. At most MOST_NEW a story; while Gemini is down or busy none is made: the story never waits for one.
  3. Each new visual joins the library (the database's `visuals`: every later story can use it), and the story keeps
     its own copies (story["visuals"]), so its film always draws them the same. You can remove one in the Studio.

Actions (how a body moves) aren't made: they're the rig's hand-built code. One the library lacks is shown by the closest
and stays listed in story["missing"].

Run it on a written script (the story as agents/story.py writes it):
    python -m agents.visuals script.json --out boarded.json
"""

import argparse
import importlib
import io
import json
import re
import sys
from pathlib import Path

import numpy as np

from agents import storyboard
from agents.base import act, lessons_for, log

import db  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402
import silhouette_words as W  # noqa: E402


class _Later:
    """A module loaded when first used. The drawing code needs OpenCV, which the website (Vercel) doesn't have: there
    the dashboard loads this agent only to list what it made, and nothing is drawn."""

    def __init__(self, name: str):
        self._name, self._mod = name, None

    def __getattr__(self, attr):
        if self._mod is None:
            self._mod = importlib.import_module(self._name)
        return getattr(self._mod, attr)


I = _Later("silhouette_icons")  # noqa: E741
VR = _Later("visual_recipes")

MOST_NEW = 3      # new visuals a story may get (the rest: the closest, as before)
TRIES = 2         # designs of one visual: the first and one redesign
WANTED = re.compile(r"^(?P<what>.+?) \((?:wanted )?in (?P<place>[a-z0-9_]+)\)$")   # the storyboard's missing things
NOT_THINGS = ("room on the wall", "a surface for")


def run(story: dict, progress=log) -> dict:
    """The story's pictures (its storyboard) and the visuals it needs that the library lacks, made: the story, ready for
    the Animator."""
    what = f"Pictures for “{story.get('title') or story.get('theme') or 'a story'}”"
    return act("visuals", what, _run, story, progress=progress)["story"]


def library() -> list[dict]:
    """The library's made visuals into this process (the removed ones out of it): the storyboard can pick them."""
    rows = db.visuals(removed=True)
    VR.forget([r["name"] for r in rows if r.get("removed_at")])
    VR.register([r for r in rows if not r.get("removed_at")])
    return rows


def _run(story: dict, progress=log) -> dict:
    library()
    boarded = storyboard.run(story, progress=progress)
    wants = wants_of(boarded)
    made, reused = [], []
    for want in wants[:MOST_NEW]:
        try:
            rec = make(want, boarded, progress)
        except Exception as e:
            if llm.down(e):
                progress("Gemini can't answer now: the library's closest visuals are used this time")
                break
            progress(f"Couldn't make {want['wish']} ({str(e)[:160]}): the closest is used")
            continue
        if rec:
            use(boarded, want, rec)
            (reused if rec.get("library") or rec.get("reused") else made).append(rec["name"])
    if len(wants) > MOST_NEW:
        progress(f"{len(wants) - MOST_NEW} more wished for: the closest are used (at most {MOST_NEW} new a story)")
    return {"story": boarded, "made": made, "reused": reused,
            "missing": [m for m in boarded.get("missing") or []][:12]}


def wants_of(story: dict) -> list[dict]:
    """What the script needed that the library lacks and can be made: a place's thing (the storyboard's missing list:
    "glue (wanted in shop_front)") or a picture a bubble wished for (bubble["wish"]); each once."""
    out, seen = [], set()
    places = {p.get("id") for p in story.get("places") or []}
    for m in story.get("missing") or []:
        g = WANTED.match(str(m))
        if not g or g["place"] not in places or g["what"].startswith(NOT_THINGS):
            continue
        key = ("thing", VR.name_of(g["what"]))
        if key[1] and key not in seen:
            seen.add(key)
            out.append({"kind": "thing", "wish": g["what"].strip(), "place": g["place"], "missing": m})
    for s in story.get("shots") or []:
        for b in s.get("bubbles") or []:
            wish = " ".join(str(b.get("wish") or "").split())[:40]
            key = ("picture", VR.name_of(wish))
            if wish and key[1] and key not in seen:
                seen.add(key)
                out.append({"kind": "picture", "wish": wish})
    return out


def _taken(kind: str, name: str) -> bool:
    return name in (W.PROPS if kind == "thing" else I.ICONS)


def _png(rgb) -> bytes:
    """A drawn preview as PNG bytes."""
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(buf, "PNG")
    return buf.getvalue()


def make(want: dict, story: dict, progress=log) -> dict | None:
    """One visual the story wished for: the library's own if it has it by that name, else designed as a silhouette,
    checked by code and by Gemini's eyes against the library, saved and registered. None: not good enough twice."""
    kind, name = want["kind"], VR.name_of(want["wish"])
    if _taken(kind, name):   # (the library has it by that name: reused; a made one's copy kept in the story)
        made = VR.MADE.get((kind, name))
        return {**made, "reused": True} if made else {"kind": kind, "name": name, "library": True}
    note = ""
    for attempt in range(TRIES):
        progress(f"Designing {want['wish']} as a silhouette" + (" again" if attempt else ""))
        raw = llm.generate_json([design_prompt(want, story, note)], recipe_schema(kind), design_system(),
                                careful=True)
        try:
            rec = VR.validate({**(raw or {}), "kind": kind, "name": name})
        except ValueError as e:
            note = f"Your last recipe was refused: {e}. Keep to the format and the silhouette tones."
            continue
        rgb, mask = VR.preview(rec)
        ok, why = VR.silhouette_ok(rgb, mask, kind)
        if not ok:
            note = f"Your last recipe didn't draw a silhouette: {why}."
            continue
        seen = look(rec, rgb, want)
        if seen.get("same_style") and seen.get("is_it"):
            db.add_visual(rec, made_for=str(story.get("title") or ""))
            db.set_visual_preview(rec["name"], _png(rgb))   # (shown online, where nothing is drawn)
            VR.register([rec])
            progress(f"New silhouette in the library: {rec['says']} ({rec['name']})")
            return rec
        note = ("Seen next to the film's own silhouettes: " + (seen.get("fix") or "it doesn't match them") + ".")
    progress(f"{want['wish']}: no silhouette good enough after {TRIES} designs; the closest is used")
    return None


def use(story: dict, want: dict, rec: dict) -> None:
    """The visual put where the story wanted it (a thing into its place's things on a surface or on the wall; a picture
    into every bubble that wished for it) and, if new, a copy kept in the story (story["visuals"])."""
    name = rec["name"]
    if want["kind"] == "thing":
        place = next(p for p in story["places"] if p.get("id") == want["place"])
        key = "wall_things" if W.PROPS[name][3] == "wall" else "small"
        things = place.setdefault("spec", {}).setdefault(key, [])
        if name not in things:
            things.append(name)
        story["missing"] = [m for m in story.get("missing") or [] if m != want["missing"]]
    else:
        for s in story.get("shots") or []:
            for b in s.get("bubbles") or []:
                if VR.name_of(b.get("wish")) == VR.name_of(want["wish"]):
                    b["picture"] = name
    if not rec.get("library"):
        kept = story.setdefault("visuals", [])
        if all(v.get("name") != name for v in kept):
            kept.append({k: v for k, v in rec.items() if k not in ("made_for", "made_at", "removed_at", "reused")})


# --- Gemini: the design and its look ---------------------------------------------------------------------------------------
def design_system() -> str:
    advice = (lessons_for("visuals") or {}).get("advice") or []
    sizes = ", ".join(f"{n.replace('_', ' ')} {W.PROPS[n][2]:g}" for n in ("mug", "bottle", "books", "laptop", "clock",
                                                                             "poster") if n in W.PROPS)
    return f"""You design one new visual for the code-drawn library of an animated short film. Every picture in the film is
a silhouette, and so is yours: solid, filled, flat shapes in dark silhouette tones, like a cut-out shadow with a thin lit
edge. NEVER a detailed drawing, an outline, a gradient, a texture, a pattern, text, letters, numbers, a logo, a face, or
anything photographic. Simple and readable at a glance, the way a shadow is.

A THING (kind thing) is drawn in world units: x across it (0 its middle, -width/2 to width/2), y up from where it stands
(0 its base, up to its height). For scale, the library's widths: {sizes}.
  layer: small (stands on a table, desk or shelf), floor_small (on the floor by the wall) or wall (hangs on the wall;
  hang: its bottom's height above the floor, 220-640, a clock hangs at 560).
  tones: wood, dark, ink, metal, steel, fabric1-fabric6 (all dark silhouette tones); paper and glow (a screen's light)
  only for a small part. lit: true on a box gives it the thin lit edge along its top, as the film's things have.
A PICTURE (kind picture) is a pictogram in a thought bubble: solid ink shapes on the bubble's cream, x across and y up,
-1 to 1, centred and filling most of it; accent: none, or one colour (red, pink, gold, green, blue, grey, brown, teal)
for a small part only (tone accent).
SHAPES, drawn in order (back to front), usually 3-14, at most 24: box (x0, x1, y0, y1, round, lit), shape (points: the
corners of a filled polygon, in order), bar (points along it, width: a thick stroke), circle (x, y, r), oval (x, y, rx,
ry). Every shape inside the size. Pieces that make one object overlap or touch, so it reads as one solid shape.
says: what it is, in a few plain words (the storyboard's words for it).

The film's look, in its maker's own words:
{prompts.load("look_silhouette")}""" + ("\nLearned so far:\n- " + "\n- ".join(advice) if advice else "")


def design_prompt(want: dict, story: dict, note: str = "") -> str:
    if want["kind"] == "thing":
        place = next((p for p in story.get("places") or [] if p.get("id") == want.get("place")), {})
        where = (f"a thing in “{place.get('name') or want.get('place')}” "
                 f"({(place.get('spec') or {}).get('kind') or 'a place'}) in a story about {story.get('theme') or 'a habit'}")
    else:
        where = f"a picture in a thought bubble, in a story about {story.get('theme') or 'a habit'}"
    return f"Design: {want['wish']}\nFor: {where}\n" + (f"{note}\n" if note else "") + "Answer with its recipe."


def recipe_schema(kind: str) -> dict:
    num = {"type": "number"}
    tones = (list(VR.THING_TONES) + list(VR.THING_ACCENTS)) if kind == "thing" else ["ink", "accent"]
    shape = {"type": "object", "properties": {
        "shape": {"type": "string", "enum": list(VR.SHAPES)}, "tone": {"type": "string", "enum": tones},
        "x0": num, "x1": num, "y0": num, "y1": num, "round": num, "lit": {"type": "boolean"},
        "points": {"type": "array", "items": {"type": "object", "properties": {"x": num, "y": num},
                                              "required": ["x", "y"]}},
        "width": num, "x": num, "y": num, "r": num, "rx": num, "ry": num},
        "required": ["shape", "tone"]}
    props = {"says": {"type": "string"}, "shapes": {"type": "array", "items": shape}}
    if kind == "thing":
        props.update(layer={"type": "string", "enum": list(VR.LAYERS)}, width=num, height=num, hang=num)
        need = ["says", "layer", "width", "height", "shapes"]
    else:
        props["accent"] = {"type": "string", "enum": ["none"] + list(VR.PICTURE_ACCENTS)}
        need = ["says", "accent", "shapes"]
    return {"type": "object", "properties": props, "required": need}


LOOK_SYSTEM = """You check one new visual for the code-drawn library of an animated short film, all in silhouettes. You see
the film's own visuals first, then the new one, marked NEW. Answer with JSON:
  same_style: is NEW the same silhouette style as the film's own (solid, flat, dark shapes; no outlines, fine detail,
              gradients, text or faces)?
  is_it: would a viewer see at a glance what NEW is meant to be?
  fix: when either is no, what to change, in a few words (else empty)."""


def look(rec: dict, rgb: np.ndarray, want: dict) -> dict:
    """Gemini's eyes on the new visual beside three of the library's own silhouettes of the same kind."""
    tiles = [(f"film's own: {n.replace('_', ' ')}", img) for n, img in VR.examples(rec["kind"], rec.get("layer", "small"))]
    tiles.append((f"NEW: {want['wish']}", rgb))
    png = sheet(tiles)
    answer = llm.generate_json([f"NEW is meant to be: {rec['says']} ({want['wish']}).", ("image/png", png)],
                               {"type": "object", "properties": {"same_style": {"type": "boolean"},
                                                                 "is_it": {"type": "boolean"},
                                                                 "fix": {"type": "string"}},
                                "required": ["same_style", "is_it", "fix"]}, LOOK_SYSTEM)
    return answer or {}


def sheet(tiles: list[tuple[str, np.ndarray]], cell: int = 240) -> bytes:
    """The visuals side by side, each fitted in a square cell with its label above (PNG)."""
    from PIL import Image, ImageDraw

    out = Image.new("RGB", (len(tiles) * (cell + 12) + 12, cell + 48), (236, 236, 232))
    d = ImageDraw.Draw(out)
    for i, (label, img) in enumerate(tiles):
        im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
        im.thumbnail((cell, cell))
        x = 12 + i * (cell + 12)
        out.paste(im, (x + (cell - im.width) // 2, 36 + (cell - im.height) // 2))
        d.text((x, 10), label[:34], fill=(20, 20, 18))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("story", help="the written story (JSON: the story, or {\"story\": ...})")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.story).read_text(encoding="utf-8"))
    boarded = run(data.get("story") or data, progress=print)
    Path(args.out).write_text(json.dumps(boarded, indent=1, ensure_ascii=False), encoding="utf-8")
    print("made:", [v["name"] for v in boarded.get("visuals") or []], "| still missing:", boarded.get("missing"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
