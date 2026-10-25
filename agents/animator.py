"""
Agent 3, Animator: makes the video. For each line it makes the character's voice (Kokoro, on this
computer), works out the mouth shapes (Rhubarb), picks a music track in the script's mood, and
has tools/cartoon_render.py draw and encode the episode, with a cover frame for the dashboard.
No Gemini calls: everything here is deterministic and free.

The track is remembered on the plan, so the Publisher can add the credit line its licence asks for.

Usage:
    python -m agents.animator --id 12      # renders Short #12's preview into .tmp/out/short_12.mp4
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import cartoon_render
import db
import lipsync
import short_render
import voice_tts
from agents.base import act, log
from common import load_config, tmp_path


def preview_path(video_id: int) -> Path:
    return tmp_path("out", f"short_{video_id}.mp4")


def cover_path(video_id: int) -> Path:
    return tmp_path("out", f"cover_{video_id}.jpg")


def animate(row: dict, out: Path, progress=log) -> dict:
    """Voices, mouth shapes, music and the render for one Short; returns its updated plan."""
    cfg = load_config()
    plan = row["plan"]
    if not plan.get("script"):
        raise RuntimeError(f"Short #{row['id']} is from the cute-animal version: it has no script to animate")
    cast, script = plan["cast"], plan["script"]
    work = tmp_path("voices", str(row["id"]), "x").parent
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        progress(f"Recording {len(script['beats'])} lines in the characters' voices")
        beats = []
        for k, beat in enumerate(script["beats"]):
            spec = cast[beat["speaker"]]
            wav = work / f"line_{k}.wav"
            seconds = voice_tts.speak(beat["line"], spec["voice"], spec["speed"], wav)
            beats.append({**beat, "wav": str(wav), "seconds": round(seconds, 3)})
        progress("Working out the mouth shapes")
        for beat, cues in zip(beats, lipsync.cues_for([(Path(b["wav"]), b["line"]) for b in beats])):
            beat["cues"] = cues
        track = short_render.pick_music(script.get("music_mood")) if cfg["music"]["volume"] > 0 else None
        progress("Animating" + (f" with {track.stem}" if track else " (no music)"))
        episode = {"setting": plan["setting"], "seed": plan.get("seed", 0), "hook": script.get("hook", ""),
                   "cast": cast, "beats": beats}
        made = cartoon_render.render(episode, out, track, cfg["music"]["volume"], cover_path=cover_path(row["id"]),
                                     progress=progress)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    plan = {**plan, "music": track.name if track else None,
            "render": {"seconds": made["seconds"], "render_seconds": made["render_seconds"]}}
    db.update_video(row["id"], plan=plan)
    progress(f"Video ready: {made['seconds']:.0f} s, made in {made['render_seconds']:.0f} s")
    return {"plan": plan, "video_id": row["id"], "length": made["seconds"], "render_seconds": made["render_seconds"],
            "music": plan["music"]}


def run(row: dict, out: Path | None = None, progress=log) -> dict:
    return act("animator", f"Animate Short #{row['id']}", animate, row, out or preview_path(row["id"]), progress=progress)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--id", type=int, required=True)
    args = parser.parse_args()
    try:
        row = db.get_video(args.id)
        if not row or not row["plan"].get("script"):
            raise RuntimeError(f"Short #{args.id} has no script")
        result = run(row)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "plan"}, indent=2))
    print(f"Wrote {preview_path(args.id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
