# Workflow: Produce a Short

## Objective
Turn today's trends into finished YouTube Shorts on a fixed timetable: concept → stock clips → safety check →
captions and metadata → rendered 1080×1920 video → uploaded so it goes public on the minute of its slot.
The **autopilot** does this by itself: 10 Shorts a day, one every 2 hours from 08:00 India time (set in
`config/channel.yaml` → `schedule`). Use this workflow to run it by hand, test changes, or debug a failed slot.

## Required Inputs
- Keys in `.env` (see `workflows/setup_accounts.md`): `GEMINI_API_KEY`, `PEXELS_API_KEY`, the YouTube values
- Settings in `config/channel.yaml` (schedule, voice, formats, animals) and `config/calendar.yaml`
- Music tracks in `assets/music/` (optional; silent without them)

## Tools
| Step | Tool | Command |
|---|---|---|
| Timetable | `tools/slots.py` | `.venv/Scripts/python tools/slots.py` (today's and tomorrow's slots) |
| Trends | `tools/trends_fetch.py` | `.venv/Scripts/python tools/trends_fetch.py` |
| Concept | `tools/concept_write.py` | `.venv/Scripts/python tools/concept_write.py concept --trends .tmp/trends.json --format punchline` |
| Find clips | `tools/clips_search.py` | `.venv/Scripts/python tools/clips_search.py --query "kitten yawning" --query "sleepy cat"` |
| Check clips | `tools/clip_check.py` | `.venv/Scripts/python tools/clip_check.py --candidates .tmp/candidates.json --theme "<theme>"` |
| Text + edit | `tools/concept_write.py` | `.venv/Scripts/python tools/concept_write.py metadata --concept .tmp/concept.json --clips .tmp/checked.json` |
| Render | `tools/short_render.py` | `.venv/Scripts/python tools/short_render.py --edit .tmp/plan.json` |
| Upload | `tools/youtube_upload.py` | `.venv/Scripts/python tools/youtube_upload.py --file .tmp/out/short.mp4 --title "..." --description "..."` |
| All of it | `tools/jobs.py` | `.venv/Scripts/python tools/jobs.py autopilot [--now]` (or `prepare`, then `publish`) |

## How the autopilot works
- Each slot is **due** from 150 minutes before it until 60 minutes after. A check finds the earliest due slot,
  takes the oldest **planned** Short (or plans a new one), renders it and uploads it as private with the slot as its
  publish time, so YouTube makes it public on the minute. If the slot is less than 3 minutes away, or already passed,
  the Short goes up public straight away. Slots more than an hour gone are left empty ("No post").
- **Who runs the check:** in the cloud, Vercel Cron calls `/api/cron/autopilot` every hour (24 daily entries in
  `vercel.json`; Hobby fires each one at a random minute of its hour). On your computer, the dashboard server checks
  every minute while it runs, but only while the database is on this computer (no `DATABASE_URL` in `.env`).
- **One Short per slot:** a Short being made or scheduled holds its slot (a unique index in the database), so a
  duplicate cron call or a second runner can't post the same slot twice.
- **Header switch = `PAUSED`:** off stops all automatic posting. Planning, previews and uploads you start yourself
  still work.

## Steps
0. **Easiest: the dashboard.** Start it with `.venv/Scripts/python -m uvicorn app:app --port 8000` and open
   http://localhost:8000. The line-up shows today's slots (posted, ready, making, up next, no post). "Plan a new
   Short" adds one to the planned queue (preview and edit it before its turn); "Make the HH:MM Short now" runs the
   autopilot for the next free slot right away; each card has Render preview, editable captions/title, Upload &
   schedule (into the next free slot) and Discard.
1. **Quick path:** `tools/jobs.py prepare` plans a Short into the queue, `tools/jobs.py publish --dry-run` renders it
   without uploading (watch it in `.tmp/out/`), and `tools/jobs.py autopilot --now` makes and uploads the next slot's
   Short for real.
2. **Step by step** (when tuning prompts or debugging): run the tools in the table's order. Each one writes JSON to
   `.tmp/` that the next one reads. Copy the theme from `.tmp/concept.json` into the clip check.
3. Check the result in the YouTube Studio app: scheduled time (or public), Pets & Animals, "Not made for kids",
   title, hashtags and the credit line in the description.
4. `tools/db.py recent` shows what's planned, being made, scheduled, skipped or failed, and the latest job runs.

## Expected Outputs
- A Short in YouTube Studio for each slot: private and scheduled for its slot time, or public if it was made late
  (until it goes public you can edit or delete it: that's your veto)
- A database row per Short with its slot, the full plan (concept, clips, captions, edit), and its clips marked used
- Locally: `.tmp/trends.json`, `concept.json`, `candidates.json`, `checked.json`, `plan.json`, `out/*.mp4`

## Edge Cases & Known Issues
- **Formats:** `punchline` and `pov` need 1 approved clip, `top3` needs 3. If not enough clips pass the check,
  the job retries with broader searches ("cute <animal>"), then gives up on that try rather than posting something
  weak: the attempt is saved as "skipped" with the reason, and the next hourly check tries the slot again.
- **Clip check is strict on purpose:** any child, people in frame (unless `allow_people: true`), watermarks or
  text, distress, or a score under `min_check_score` rejects the clip. These rules are enforced in code.
- **Gemini speed and quota:** on the free tier gemini-3.8-flash took ~100 s per request (2026-10-24), so
  `tools/llm.py` uses gemini-3.5-flash-lite first (2–5 s), then gemini-2.5-flash, then gemini-3.8-flash. Each
  request times out after 60 s and quota errors (429) fall through to the next model. If all fail, the slot's run
  errors and Telegram tells you. 10 Shorts a day is about 40 requests.
- **top3 needs three matching clips:** a specific colour or breed ("black cat") often can't fill three, so the
  planner is told to use plain animals for that format.
- **Pexels:** 200 requests/hour, 20,000/month; 10 Shorts a day use about 50 requests. Portrait searches ask for 40
  results so popular searches still have unused clips after weeks of posting (no clip is ever used twice).
- **Pixabay** asks API users to cache results for 24 h and not to bulk-download; it's only a fallback here.
- **YouTube:** uploads have their own quota (100/day by default). Titles and descriptions can't contain `<` or `>`;
  the tools strip them.
- **Vercel: 300 s per run and 4 CPU-hours a month (Hobby).** One autopilot run plans, renders and uploads one Short
  in about 1–2 minutes. Rendering is the CPU cost (measured 2026-10-24 on one core: 10 s for a 14 s portrait Short,
  19 s for a 21 s Top 3), so `short_render.py` uses x264 "superfast" and a quarter-size background blur; 10 a day
  comes to roughly 2.5 CPU-hours a month. More than 12 a day won't fit the free plan.
- **Interrupted run:** if a run is cut off (300 s limit, crash), its Short stays "making"; after 15 minutes the next
  check puts it back in the queue (or marks it skipped if it had no plan yet).
- **Failed upload:** the Short goes back to "planned" and the next check retries it; after 2 failures it's marked
  "failed" with the error saved (`tools/db.py recent`), and the slot gets a fresh Short on the next try.
- **Two autopilots, two databases = double posts.** Once the cloud runs the autopilot, put the same `DATABASE_URL`
  in your local `.env` (the dashboard then shows the cloud's queue and stops its own loop).
