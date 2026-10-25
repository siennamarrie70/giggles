"""
Agent 4, Animator: makes the video. It records every line in its host's voice (Kokoro, on this
computer), works out the mouth shapes (Rhubarb), turns each line's visual into something to draw
(the research pack's photos and data become photos, charts, maps, timelines, big numbers...), picks
a music track in the script's mood, and has tools/case_render.py draw and encode the case, with a
cover frame for the dashboard. No Gemini calls: everything here is deterministic and free.

The track is remembered on the plan, so the Publisher can add the credit line its licence asks for.

Usage:
    python -m agents.animator --id 12      # renders Short #12's preview into .tmp/out/short_12.mp4
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import case_render
import db
import lipsync
import short_render
import voice_tts
from agents.base import act, log
from agents.writer import visual_spec
from common import load_config, tmp_path


def preview_path(video_id: int) -> Path:
    return tmp_path("out", f"short_{video_id}.mp4")


def cover_path(video_id: int) -> Path:
    return tmp_path("out", f"cover_{video_id}.jpg")


def case_number(video_id: int) -> int:
    """The case's number on screen ("Case file 12"): its place among the cases made so far."""
    with db.connect() as conn:
        return conn.query("SELECT COUNT(*) AS n FROM videos WHERE format = %s AND id <= %s "
                          "AND status NOT IN ('discarded', 'skipped')", (db.FORMAT, video_id))[0]["n"]


def end_text(cfg: dict) -> str:
    ch = cfg["channel"]
    return f"Follow {ch['name']} for a new case every day" if ch.get("show_name") else "A new case every day"


def animate(row: dict, out: Path, progress=log) -> dict:
    """Voices, mouth shapes, visuals, music and the render for one case; returns its updated plan."""
    cfg = load_config()
    plan = row["plan"]
    if row["format"] != db.FORMAT or not plan.get("script"):
        raise RuntimeError(f"Short #{row['id']} is from an earlier version of the channel: it has no case to animate")
    hosts, script = plan["hosts"], plan["script"]
    work = tmp_path("voices", str(row["id"]), "x").parent
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        progress(f"Recording {len(script['lines'])} lines in the hosts' voices")
        lines = []
        for k, line in enumerate(script["lines"]):
            host = hosts[line["speaker"]]
            wav = work / f"line_{k}.wav"
            seconds = voice_tts.speak(line["text"], host["voice"], host["speed"], wav)
            lines.append({**line, "visual": visual_spec(line["visual"], plan), "wav": str(wav), "seconds": round(seconds, 3)})
        progress("Working out the mouth shapes")
        for line, cues in zip(lines, lipsync.cues_for([(Path(l["wav"]), l["text"]) for l in lines])):
            line["cues"] = cues
        track = short_render.pick_music(script.get("music_mood")) if cfg["music"]["volume"] > 0 else None
        progress("Animating" + (f" with {track.stem}" if track else " (no music)"))
        case = {"category": plan["brief"]["category"], "case_no": case_number(row["id"]),
                "case_title": script["case_title"], "end_text": end_text(cfg), "hosts": hosts, "lines": lines}
        made = case_render.render(case, out, track, cfg["music"]["volume"], cover_path=cover_path(row["id"]),
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
        if not row:
            raise RuntimeError(f"there's no Short #{args.id}")
        result = run(row)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "plan"}, indent=2))
    print(f"Wrote {preview_path(args.id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
