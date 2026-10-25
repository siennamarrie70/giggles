# Workflow: Produce a Short

## Objective
Turn today's trends into finished animated comedy Shorts on a fixed timetable, made by five agents in order:
Agent 1 casts the characters, Agent 2 writes the sketch, Agent 3 voices and animates it, Agent 4 uploads it so it goes
public on the minute of its slot, and Agent 5 learns from the numbers. The **autopilot** does all of it by itself:
3 Shorts a day at 08:00, 14:00 and 20:00 India time (set in `config/channel.yaml` → `schedule`). Use this workflow
to run it by hand, test changes, or debug a failed slot.

## Required Inputs
- Keys in `.env` (see `workflows/setup_accounts.md`): `GEMINI_API_KEY` and the YouTube values
- Settings in `config/channel.yaml` (schedule, voice, `episodes`: settings, cast size, length, queue) and
  `config/calendar.yaml`
- This computer: the voices (Kokoro) and lip-sync (Rhubarb) run here; both download themselves into
  `.tmp/models/` the first time (~120 MB and ~90 MB)
- Music tracks in `assets/music/` (optional; Shorts are made without music otherwise). `assets/music/tracks.yaml`
  gives each track's `mood` (the Writer picks one, the Animator a track in it) and its `credit:` line, which the
  Publisher adds to the description. Kevin MacLeod's tracks (CC BY 4.0, in YouTube's Content ID) must always carry it.

## Tools
| Step | Who | Command |
|---|---|---|
| Timetable | | `.venv/Scripts/python tools/slots.py` (today's and tomorrow's slots) |
| Trends | | `.venv/Scripts/python tools/trends_fetch.py` |
| Cast | Agent 1 | `.venv/Scripts/python -m agents.casting` (saves the characters, prints them) |
| Script | Agent 2 | `.venv/Scripts/python -m agents.writer` (casts and writes one, prints it without saving the episode) |
| Animate | Agent 3 | `.venv/Scripts/python -m agents.animator --id <episode>` (renders `.tmp/out/short_<id>.mp4`) |
| One voice | | `.venv/Scripts/python tools/voice_tts.py --voice af_heart --text "Hello"` |
| One rig | | `.venv/Scripts/python tools/puppet.py --spec cast.json --out .tmp/out/cast.png` (character cards) |
| One set | | `.venv/Scripts/python tools/scene_draw.py --setting office --out .tmp/out/office.png` |
| Upload | Agent 4 | `.venv/Scripts/python tools/jobs.py publish` (the oldest episode into the next open slot) |
| Numbers | Agent 5 | `.venv/Scripts/python -m agents.analyst [--learn]` |
| All of it | | `.venv/Scripts/python tools/jobs.py autopilot [--now]` (or `prepare`, then `publish --dry-run`, then `publish`) |

## How the autopilot works
- Each slot is **due** from 150 minutes before it until 60 minutes after. The check finds the earliest due slot, takes
  the oldest **written** episode (or has Agents 1 and 2 write one on the spot), has Agent 3 animate it unless its
  preview already exists, and Agent 4 uploads it as private with the slot as its publish time, so YouTube makes it
  public on the minute. If the slot is less than 3 minutes away, or already passed, it goes up public straight away.
  Slots more than an hour gone are left empty ("No post").
- **Between slots, on this computer:** the dashboard's loop keeps `episodes.queue` episodes written ahead, renders
  their previews (so you can watch and edit them in the Studio before they go up), and has Agent 5 read the numbers
  once a day (`jobs.next_chore`). All of it stops while the autopilot is paused.
- **Where it runs:** on this computer only. The voices, lip-sync and frame drawing need more than Vercel's free plan
  allows (4 CPU-hours a month, 250 MB per function), so the cloud setup isn't used for the cartoons yet.
- **One Short per slot:** a Short being made or scheduled holds its slot (a unique index in the database), so a
  second runner can't post the same slot twice.
- **Header switch = `PAUSED`:** off stops all automatic work. Writing, previews and uploads you start yourself still
  work.

## Steps
0. **Easiest: the dashboard.** Start it with `.venv/Scripts/python -m uvicorn app:app --port 8000` and open
   http://localhost:8000. Overview shows the five agents and today's slots; **Write a new episode** runs Agents 1
   and 2; **Scripts** lets you edit the hook, every line (who says it, emotion, action, camera, how the others react),
   the title and the description; **Studio** has Animate, the preview, Upload & schedule and Discard; **Cast** shows
   every character with their voice.
1. **Quick path:** `tools/jobs.py prepare` writes an episode, `tools/jobs.py publish --dry-run` animates it without
   uploading (watch `.tmp/out/short_<id>.mp4`), and `tools/jobs.py autopilot --now` makes and uploads the next slot's
   Short for real.
2. **Check the result** in the YouTube Studio app: scheduled time (or public), Comedy, "Not made for kids", title,
   hashtags and the music's credit line in the description.
3. `tools/db.py recent` shows what's written, being made, scheduled, skipped or failed, and the latest runs.

## Expected Outputs
- A Short in YouTube Studio for each slot: private and scheduled for its slot time, or public if it was made late
  (until it goes public you can edit or delete it: that's your veto)
- A database row per Short with its slot and its plan (setting, cast, script, title, music), and its characters in the
  `characters` table
- Locally: `.tmp/out/short_<id>.mp4` (deleted after upload) and `cover_<id>.jpg` (kept for the dashboard)

## Edge Cases & Known Issues
- **Measured 2026-10-25 on this PC (20 cores):** Kokoro speaks ~3x faster than real time (a 3 s line in ~1 s, plus
  ~1.5 s to load once); Rhubarb takes ~0.75 s per second of speech (lines run in parallel); drawing and encoding a
  16 s episode took 12 s. A whole episode (voices, lip-sync, animation) takes about a minute or less.
- **Gemini copies examples.** A prompt that shows an example hook got that exact hook back (2026-10-25). Describe what
  a good line does instead of giving one to copy.
- **Everything Gemini returns is checked in code before it's used:** characters are snapped to parts the rig can draw
  (`tools/character_spec.py`; ages 25-75, no two voices alike), beats to known speakers, emotions, actions and cameras
  (`agents/writer.py`); the first shot is always wide, a walk-in only on a character's first line, and a sketch longer
  than `max_seconds` loses a middle line. Edits from the dashboard go through the same checks.
- **Adults only:** the rig has no child proportions and every age is clamped to 25+. The upload always says
  "not made for kids". Keep topics adult so YouTube doesn't decide otherwise; check the audience in YouTube Studio.
- **Shorts from the cute-animal version** (the same database) show in the Studio as "Cute-animal version": they can
  still be uploaded as they are (if their video was kept) or discarded. The agents never pick them, and the Analyst
  only learns from cartoons.
- **Rhubarb missing or failing** falls back to mouth shapes from the loudness of the voice: rougher, but the mouth
  still moves. Kokoro has no fallback: if its model can't download, Agent 3 fails and says why.
- **Gemini speed and quota:** `tools/llm.py` tries gemini-3.5-flash-lite first (2-6 s), then gemini-3.1-flash-lite,
  gemini-3.5-flash and finally gemini-3.8-flash (slow). Quota errors (429) fall through to the next model. An episode
  takes two requests (casting, writing); the weekly lessons one more.
- **YouTube:** uploads have their own quota (100/day by default). Titles and descriptions can't contain `<` or `>`;
  the tools strip them.
- **Interrupted run:** if a run is cut off (crash, PC asleep), its Short stays "making"; after 15 minutes the next
  check puts it back in the queue (or marks it skipped if it had no plan yet).
- **Failed upload:** the Short goes back to the queue and the next check retries it; after 2 failures it's marked
  "failed" with the error saved, and the slot gets a fresh Short on the next try.
