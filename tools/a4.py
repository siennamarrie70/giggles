"""
Agent 4's rules in code, for the faceless look: your prompt (prompts/agent4.txt.enc, word for word) designs the scenes, and this
makes sure the design can be played and does what the prompt says.

  repair(raw, a3)      everything the prompt defines exactly is set in code: the format, the style preset, every time, each
                       scene's lines and beat, each callout's animation and position, the loop's last scene, the summary and
                       the AI flag; values outside the prompt's closed lists are replaced; camera, transition and sound
                       rules (no repeats, at most so many) are enforced. Nothing the model writes reaches a command or a
                       file name: only values from these closed lists do.
  problems(a4, a3)     what's still wrong: (must_fix, should_fix), in words the model can act on. must_fix: it can't be played
                       (the narration doesn't match the script); should_fix goes back to the model while tries remain.
  scene_words(a4)      how many of the script's words each scene covers, for timing it by his real voice.

Nothing here calls a service.
"""

import re

import prompts

SCHEMA_VERSION = "a4.v1"
FORMAT = {"aspect_ratio": "9:16", "width": 1080, "height": 1920, "fps": 30}
CAMERAS = ("ken_burns_zoom_in_slow", "ken_burns_zoom_in_fast", "ken_burns_zoom_out_slow", "ken_burns_zoom_out_fast",
           "slow_pan_left", "slow_pan_right", "slow_tilt_up", "slow_tilt_down", "2.5d_parallax_depth", "micro_drift")
REVERSE = {"ken_burns_zoom_in_slow": "ken_burns_zoom_out_slow", "ken_burns_zoom_out_slow": "ken_burns_zoom_in_slow",
           "ken_burns_zoom_in_fast": "ken_burns_zoom_out_fast", "ken_burns_zoom_out_fast": "ken_burns_zoom_in_fast",
           "slow_pan_left": "slow_pan_right", "slow_pan_right": "slow_pan_left", "slow_tilt_up": "slow_tilt_down",
           "slow_tilt_down": "slow_tilt_up", "2.5d_parallax_depth": "2.5d_parallax_depth", "micro_drift": "micro_drift"}
FX = ("screen_shake_impact", "zoom_punch", "rgb_glitch", "film_grain", "vignette_dark", "light_leak", "slow_motion_50")
GRADES = ("base", "color_grade_desaturate", "color_grade_bw_high_contrast", "color_grade_warm_gold", "color_grade_cold_blue",
          "color_grade_red_alert")
LAYOUTS = ("full_frame", "split_screen_comparison")
TRANSITIONS = ("hard_cut", "whip_pan", "flash_white", "glitch_cut", "zoom_through", "crossfade_fast")
BEAT_OPENERS = ("whip_pan", "flash_white", "glitch_cut", "zoom_through")
ANIMATIONS = ("count_up", "typewriter", "stamp", "slam_impact", "pop_in")
POSITIONS = ("center", "top_center")
SOURCES = ("ai_image_gen", "stock_video_api")
SFX_GROUPS = {
    "transition": ("whoosh_fast", "whoosh_soft", "glitch_burst", "camera_shutter", "page_flip", "paper_rip"),
    "big_impact": ("deep_sub_drop", "cinematic_boom", "bass_hit"),
    "impact": ("heartbeat_thump", "door_slam", "gavel_bang", "punch_hit", "metal_clank", "glass_shatter", "stamp_thud"),
    "tension": ("cinematic_riser", "tension_drone", "ticking_clock", "suspense_sting"),
    "ui_money": ("pop_click", "typewriter_keys", "notification_ding", "cash_register", "coin_drop", "keyboard_typing",
                 "error_buzzer"),
    "world": ("sword_clash", "thunder_crack", "fire_crackle", "crowd_gasp", "crowd_cheer", "crowd_murmur", "war_drums",
              "gunfire_burst", "distant_explosion", "wind_howl", "ocean_waves", "monster_roar", "magic_shimmer", "dark_choir",
              "earthquake_rumble", "bird_squawk"),
}
SFX_TAGS = tuple(tag for group in SFX_GROUPS.values() for tag in group)
BIG_IMPACTS = SFX_GROUPS["big_impact"]
MAX_BIG = 5
VOLUMES = {"low": -24.0, "medium": -16.0, "high": -10.0}
TRANSITION_SOUND = {"whip_pan": "whoosh_fast", "zoom_through": "whoosh_soft", "glitch_cut": "glitch_burst",
                    "crossfade_fast": "whoosh_soft", "flash_white": "bass_hit"}
MOODS = ("epic_orchestral", "tense_cinematic", "dark_ambient", "suspense_electronic", "mysterious_ethereal")
DEFAULT_MOOD = {"business": "suspense_electronic", "history": "epic_orchestral", "mythology": "dark_ambient"}
STOCK_SHARE = {"business": (50, 70), "history": (25, 50), "mythology": (0, 30)}
SHOT_TYPES = ("extreme close-up", "close-up", "medium close-up", "medium shot", "wide shot", "aerial wide shot", "low-angle",
              "high-angle", "top-down shot", "over-the-shoulder shot", "tracking shot", "silhouette shot")
VERDICTS = {"NO", "DENIED", "FAILED", "BANNED", "BANKRUPT", "DEAD", "WON", "LOST"}
MONTHS = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER")
SLAM_ROLES = ("hook", "close_loop_1", "close_loop_2", "climax")
OPEN_LOOPS = ("open_loop_1", "open_loop_2")
FEWEST_SCENES, MOST_SCENES = 18, 22
FEWEST_CALLOUTS, MOST_CALLOUTS = 10, 18
MAX_GRADED, MAX_SPLITS, MAX_OTHER_MOVES = 6, 2, 6
CALLOUT_CHARS = 18
PROMPT_WORDS = (25, 60)
HAS_NUMBER = re.compile(r"\d")
CALLOUT_ALLOWED = re.compile(r"[^A-Z0-9 ,.$%/&'\-]")
QUERY_ALLOWED = re.compile(r"[^a-z ]")
NUMBER_LEAD = re.compile(r"^\$?(\d[\d,]*(?:\.\d+)?)")
YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
WORDY_NUMBER = re.compile(r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
                          r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
                          r"thousand|million|billion|trillion|percent|tenth|twentieth|thirtieth|january|february|march|april|"
                          r"june|july|august|september|october|november|december)\b", re.IGNORECASE)


def _one_line(value) -> str:
    return " ".join(str(value or "").split())


def _script_words(a3: dict) -> list[tuple[str, dict]]:
    """Every word of the script with its line, in order."""
    return [(word, line) for beat in a3["beats"] for line in beat["lines"] for word in line["text"].split()]


def _at(a3_line: dict, words_in: int) -> float:
    """The prompt's estimate of when so many of a line's words have been said."""
    if words_in >= a3_line["word_count"]:
        return a3_line["est_end_sec"]
    return round(a3_line["est_start_sec"] + round(words_in / 3, 1), 1)


def _clean_query(value) -> str:
    return " ".join(QUERY_ALLOWED.sub(" ", str(value or "").lower()).split()[:3])


def _visual(raw: dict) -> dict:
    source = raw.get("source_primary") if raw.get("source_primary") in SOURCES else "ai_image_gen"
    return {"source_primary": source, "ai_image_prompt": _one_line(raw.get("ai_image_prompt")),
            "stock_query": _clean_query(raw.get("stock_query"))}


def _callout_text(value) -> str:
    text = CALLOUT_ALLOWED.sub("", _one_line(value).upper())
    return " ".join(text.split())


def animation_for(text: str, role: str) -> str:
    """The prompt's rule for a callout's animation: the first that matches."""
    number = NUMBER_LEAD.match(text)
    if number:
        digits = number[1].replace(",", "")
        is_year = "," not in number[1] and bool(YEAR.fullmatch(number[1])) and not text.startswith("$")
        try:
            if float(digits) >= 10 and not is_year:
                return "count_up"
        except ValueError:
            pass
    if YEAR.search(text) or any(month in text for month in MONTHS) or role in OPEN_LOOPS:
        return "typewriter"
    if set(re.findall(r"[A-Z]+", text)) & VERDICTS:
        return "stamp"
    if role in SLAM_ROLES:
        return "slam_impact"
    return "pop_in"


def position_for(animation: str) -> str:
    return "center" if animation in ("count_up", "stamp") else "top_center"


def _change_camera(camera: str, avoid: set[str], ai: bool) -> str:
    return next(c for c in CAMERAS if c not in avoid and c != camera and (ai or c != "2.5d_parallax_depth")
                and c != "micro_drift")


def repair(raw: dict, a3: dict) -> dict:
    """The design with everything the prompt defines exactly set in code. Scenes whose words don't follow the script keep
    their given words: problems() sends them back."""
    niche = a3["niche"]
    words = _script_words(a3)
    scenes, used = [], 0
    raw_scenes = [s for s in raw.get("scenes") or [] if isinstance(s, dict)]
    for k, item in enumerate(raw_scenes):
        text = _one_line(item.get("narration_text"))
        count = len(text.split())
        part = words[used:used + count]
        lines = list({id(line): line for _, line in part}.values())
        beat = next((b["beat_id"] for b in a3["beats"] if lines and lines[0] in b["lines"]), "B1")
        role = lines[-1]["role"] if lines else ""
        scene = {"scene_id": f"S{k + 1:02d}", "beat_id": beat, "line_ids": [line["line_id"] for line in lines],
                 "narration_text": text, "start_sec": 0.0, "end_sec": 0.0, "duration_sec": 0.0, **_visual(item),
                 "reuse_asset_from": None, "layout": item.get("layout") if item.get("layout") in LAYOUTS else "full_frame",
                 "secondary_visual": None, "camera": item.get("camera") if item.get("camera") in CAMERAS else "ken_burns_zoom_in_slow",
                 "fx": [f for f in dict.fromkeys(item.get("fx") or []) if f in FX][:2],
                 "color_grade": item.get("color_grade") if item.get("color_grade") in GRADES else "base",
                 "transition_in": item.get("transition_in") if item.get("transition_in") in TRANSITIONS else "hard_cut",
                 "on_screen_text": None, "sfx": [], "_role": role}
        if part:
            first, last = part[0][1], part[-1][1]
            before = sum(1 for w, line in words[:used] if line is first)
            after = sum(1 for w, line in words[:used + count] if line is last)
            scene["start_sec"], scene["end_sec"] = _at(first, before), _at(last, after)
        scene["duration_sec"] = round(scene["end_sec"] - scene["start_sec"], 1)
        callout = item.get("on_screen_text") if isinstance(item.get("on_screen_text"), dict) else None
        text_on = _callout_text((callout or {}).get("text"))
        if text_on and len(text_on) <= CALLOUT_CHARS and len(text_on.split()) <= 3:
            animation = animation_for(text_on, role)
            scene["on_screen_text"] = {"text": text_on, "animation": animation, "position": position_for(animation)}
        for sound in item.get("sfx") or []:
            if isinstance(sound, dict) and sound.get("tag") in SFX_TAGS:
                try:
                    at = max(0.0, round(float(sound.get("offset_sec") or 0), 1))
                except (TypeError, ValueError):
                    at = 0.0
                scene["sfx"].append({"tag": sound["tag"], "offset_sec": at,
                                     "volume": sound.get("volume") if sound.get("volume") in VOLUMES else "medium"})
        secondary = item.get("secondary_visual")
        if scene["layout"] == "split_screen_comparison" and isinstance(secondary, dict):
            scene["secondary_visual"] = _visual(secondary)
        else:
            scene["layout"] = "full_frame"
        scenes.append(scene)
        used += count
    _rules(scenes, niche)
    for scene in scenes:
        scene.pop("_role", None)
    preset = prompts.presets()[niche]
    stock = sum(1 for s in scenes if s["source_primary"] == "stock_video_api")
    total = a3["est_total_duration_sec"]
    music = raw.get("music") if isinstance(raw.get("music"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION, "status": "ok", "error": None, "video_id": a3["video_id"], "niche": niche,
        "format": dict(FORMAT), "est_total_duration_sec": total, "style_bible": preset,
        "character_sheet": [{"subject_id": re.sub(r"[^a-z0-9_]", "_", str(c.get("subject_id") or "subject").lower())[:40],
                             "descriptor": _one_line(c.get("descriptor"))}
                            for c in raw.get("character_sheet") or [] if isinstance(c, dict)][:4],
        "music": {"mood": music.get("mood") if music.get("mood") in MOODS else DEFAULT_MOOD[niche],
                  "search_query": _one_line(music.get("search_query"))[:60]},
        "scenes": scenes,
        "summary": {"scene_count": len(scenes), "ai_image_scenes": len(scenes) - stock, "stock_video_scenes": stock,
                    "callout_count": sum(1 for s in scenes if s["on_screen_text"]),
                    "split_screen_count": sum(1 for s in scenes if s["layout"] == "split_screen_comparison"),
                    "avg_scene_sec": round(total / max(len(scenes), 1), 2)},
        "ai_disclosure_flag": bool(preset["photoreal"]) and len(scenes) > stock,
        "warnings": [_one_line(w)[:200] for w in raw.get("warnings") or []][:10],
    }


def _rules(scenes: list[dict], niche: str) -> None:
    """The prompt's rules that can be enforced as they stand, in the order they affect each other."""
    if not scenes:
        return
    first, last = scenes[0], scenes[-1]
    # 9. the seamless loop: the last scene is S01's picture with the camera going back
    if len(scenes) > 1:
        last.update(source_primary=first["source_primary"], ai_image_prompt=first["ai_image_prompt"],
                    stock_query=first["stock_query"], reuse_asset_from="S01", layout="full_frame", secondary_visual=None,
                    fx=[], color_grade="base", on_screen_text=None)
    first["layout"], first["secondary_visual"] = "full_frame", None
    if first["camera"] == "micro_drift":
        first["camera"] = "ken_burns_zoom_in_fast"
    # 5. layouts, cameras, effects, grades
    splits = 0
    graded = 0
    was_split = False
    for scene in scenes:
        ai = scene["source_primary"] == "ai_image_gen"
        if scene["layout"] == "split_screen_comparison":
            splits += 1
            if splits > MAX_SPLITS or was_split:  # (two in a row would need the same camera twice in a row)
                scene["layout"], scene["secondary_visual"] = "full_frame", None
                if scene["camera"] == "micro_drift":
                    scene["camera"] = "ken_burns_zoom_in_slow"
            else:
                scene["camera"] = "micro_drift"
        was_split = scene["layout"] == "split_screen_comparison"
        if scene["camera"] == "2.5d_parallax_depth" and not ai:
            scene["camera"] = "ken_burns_zoom_in_slow"
        scene["fx"] = [f for f in scene["fx"] if f != "slow_motion_50" or not ai]
        if scene["color_grade"] != "base":
            graded += 1
            if graded > MAX_GRADED:
                scene["color_grade"] = "base"
    if len(scenes) > 1:
        last["camera"] = REVERSE[first["camera"]]
    for k in range(1, len(scenes)):
        before, scene = scenes[k - 1], scenes[k]
        if scene["camera"] == before["camera"]:
            after = scenes[k + 1]["camera"] if k + 1 < len(scenes) else ""
            fixed_here = scene is last or scene["layout"] == "split_screen_comparison"
            target = before if fixed_here and k > 1 else scene
            target["camera"] = _change_camera(target["camera"], {before["camera"], scene["camera"], after,
                                                                  scenes[k - 2]["camera"] if k > 1 else ""},
                                              target["source_primary"] == "ai_image_gen")
    # 6. transitions
    first["transition_in"] = "hard_cut"
    beats_seen, others = {first["beat_id"]}, 0
    for k, scene in enumerate(scenes[1:], start=1):
        opens_beat = scene["beat_id"] not in beats_seen
        beats_seen.add(scene["beat_id"])
        previous = scenes[k - 1]["transition_in"]
        move = scene["transition_in"]
        if opens_beat:
            if move not in BEAT_OPENERS:
                move = "whip_pan"
        elif move != "hard_cut":
            others += 1
            if others > MAX_OTHER_MOVES:
                move = "hard_cut"
            elif move == "crossfade_fast" and scene is not last and scene["_role"] not in ("twist", "stakes"):
                move = "hard_cut"
        if move != "hard_cut" and move == previous:
            move = next(m for m in BEAT_OPENERS if m != previous) if opens_beat else "hard_cut"
        scene["transition_in"] = move
    # 7. callouts: at most so many, none on the last scene, and at least 3 other scenes without one
    if len(scenes) > 1:
        last["on_screen_text"] = None
    shown = [s for s in scenes if s["on_screen_text"]]
    spare = sorted(shown, key=lambda s: (bool(HAS_NUMBER.search(s["on_screen_text"]["text"])),
                                         s["on_screen_text"]["animation"] != "pop_in"))
    while len(shown) > MOST_CALLOUTS or len(scenes) - len(shown) - 1 < 3 and len(shown) > FEWEST_CALLOUTS:
        victim = spare.pop(0)
        victim["on_screen_text"] = None
        shown = [s for s in scenes if s["on_screen_text"]]
    # 8. sound: the transition's sound first, then what the design chose; at most so many big hits, no tag twice in a row
    big = 0
    used_before: set[str] = set()
    for scene in scenes:
        chosen = [dict(s) for s in scene["sfx"]]
        move = scene["transition_in"]
        lead = None
        if move != "hard_cut":
            wanted = TRANSITION_SOUND[move]
            already = next((s for s in chosen if s["tag"] == wanted or (move == "flash_white" and s["tag"] in
                                                                        ("bass_hit", "deep_sub_drop"))), None)
            lead = {"tag": already["tag"] if already else wanted, "offset_sec": 0.0,
                    "volume": already["volume"] if already else ("high" if move == "flash_white" else "medium")}
            chosen = [lead] + [s for s in chosen if s is not already]
        kept = []
        for sound in chosen:
            if len(kept) == 2 or (sound["tag"] in used_before and sound is not lead):
                continue
            if sound["tag"] in BIG_IMPACTS:
                if big >= MAX_BIG:
                    continue
                big += 1
            sound["offset_sec"] = min(sound["offset_sec"], round(max(scene["duration_sec"] - 0.1, 0.0), 1))
            kept.append(sound)
        if not kept:  # every scene has a sound (1 or 2)
            fill = next(t for t in ("pop_click", "whoosh_soft", "camera_shutter", "page_flip") if t not in used_before)
            kept = [{"tag": fill, "offset_sec": 0.0, "volume": "low"}]
        scene["sfx"] = kept
        used_before = {s["tag"] for s in kept}
    del niche


def problems(a4: dict, a3: dict) -> tuple[list[str], list[str]]:
    """What's still wrong: (must_fix, should_fix)."""
    must, should = [], []
    scenes = a4.get("scenes") or []
    said = [word for word, _ in _script_words(a3)]
    given = [word for scene in scenes for word in scene["narration_text"].split()]
    if given != said:
        at = next((k for k, (a, b) in enumerate(zip(said, given)) if a != b), min(len(said), len(given)))
        must.append(f"The scenes' narration_text must follow the script word for word, with nothing added, changed or left "
                    f"out. They go wrong at word {at + 1}: the script says '{' '.join(said[at:at + 6])}', the scenes say "
                    f"'{' '.join(given[at:at + 6])}'.")
    if not FEWEST_SCENES <= len(scenes) <= MOST_SCENES:
        should.append(f"There are {len(scenes)} scenes; there must be {FEWEST_SCENES}-{MOST_SCENES} (section 3).")
    seen_queries = set()
    for k, scene in enumerate(scenes):
        name = scene["scene_id"]
        if not given == said:
            break
        if not 1.0 <= scene["duration_sec"] <= 3.5:
            should.append(f"{name} lasts {scene['duration_sec']:g} s; every scene must last 1.0-3.5 s (section 3).")
        visuals = [scene] + ([scene["secondary_visual"]] if scene["secondary_visual"] else [])
        for visual in visuals:
            prompt = visual["ai_image_prompt"]
            count = len(prompt.split())
            if not PROMPT_WORDS[0] <= count <= PROMPT_WORDS[1]:
                should.append(f"{name}'s ai_image_prompt has {count} words; it must have {PROMPT_WORDS[0]}-{PROMPT_WORDS[1]}.")
            if prompt and not prompt.lower().startswith(SHOT_TYPES):
                should.append(f"{name}'s ai_image_prompt must start with a shot type (wide shot, close-up, ...).")
            query = visual["stock_query"]
            if not 2 <= len(query.split()) <= 3:
                should.append(f"{name}'s stock_query must be 2-3 lowercase words (it's '{query}').")
            elif k < len(scenes) - 1 and query in seen_queries:
                should.append(f"{name}'s stock_query '{query}' repeats an earlier one; each must be unique.")
            seen_queries.add(query)
        text = scene["narration_text"]
        if (HAS_NUMBER.search(text) or WORDY_NUMBER.search(text)) and not scene["on_screen_text"] and k < len(scenes) - 1:
            if re.search(r"\b(thousand|million|billion|trillion|hundred|percent|nineteen|eighteen|seventeen|sixteen|"
                         r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\b", text, re.IGNORECASE):
                should.append(f"{name} says a number or a date, so it must have a callout.")
    summary = a4.get("summary") or {}
    if not FEWEST_CALLOUTS <= summary.get("callout_count", 0) <= MOST_CALLOUTS:
        should.append(f"There are {summary.get('callout_count', 0)} callouts; there must be {FEWEST_CALLOUTS}-{MOST_CALLOUTS}.")
    low, high = STOCK_SHARE[a4["niche"]]
    share = 100 * summary.get("stock_video_scenes", 0) / max(len(scenes), 1)
    if not low <= share <= high:
        should.append(f"{share:.0f}% of the scenes use stock_video_api; for {a4['niche']} it must be {low}-{high}%: switch the "
                      "closest-call scenes.")
    return must, should


def scene_words(a4: dict) -> list[int]:
    return [len(scene["narration_text"].split()) for scene in a4.get("scenes") or []]
