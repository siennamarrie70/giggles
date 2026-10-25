# Workflow: Produce a Short

## Objective
Turn a question worth answering into a finished 60-second case study on a fixed timetable, made by six agents in
order: Agent 1 (Editor) picks the case, Agent 2 (Researcher) gathers and checks the facts, Agent 3 (Writer) writes the
two hosts' script and fact-checks it, Agent 4 (Animator) voices and animates it, Agent 5 (Publisher) uploads it so it
goes public on the minute of its slot, and Agent 6 (Analyst) learns from the numbers. The **autopilot** does all of it
by itself: 3 Shorts a day at 08:00, 14:00 and 20:00 India time (set in `config/channel.yaml` → `schedule`). Use this
workflow to run it by hand, test changes, or debug a failed slot.

## Required Inputs
- Keys in `.env` (see `workflows/setup_accounts.md`): `GEMINI_API_KEY` and the YouTube values
- Settings in `config/channel.yaml` (schedule, voice and rules, `cases`: types, approvals, length, queue) and
  `config/calendar.yaml` (holidays and anniversaries the Editor can tie a case to)
- This computer: the voices (Kokoro) and lip-sync (Rhubarb) run here; both download themselves into
  `.tmp/models/` the first time (~120 MB and ~90 MB)
- The internet, for research: Wikipedia, Wikimedia Commons, the IMF and World Bank data APIs, news sites' RSS feeds
  and GDELT. None needs a key.
- Music tracks in `assets/music/` (optional). `assets/music/tracks.yaml` gives each track's `mood` (the Writer picks
  one, the Animator a track in it) and its `credit:` line, which the Publisher adds to the description. Kevin
  MacLeod's tracks (CC BY 4.0, in YouTube's Content ID) must always carry it.

## Tools
| Step | Who | Command |
|---|---|---|
| Timetable | | `.venv/Scripts/python tools/slots.py` (today's and tomorrow's slots) |
| Trends | | `.venv/Scripts/python tools/trends_fetch.py` |
| The hosts | | `.venv/Scripts/python -m agents.hosts [--redesign]` |
| Pick a case | Agent 1 | `.venv/Scripts/python -m agents.editor` (prints a brief, saves nothing) |
| Sources | Agent 2 | `.venv/Scripts/python tools/research_fetch.py wiki Nokia` (also `search`, `events`, `onthisday`, `news`, `data`, `images`) |
| Research | Agent 2 | `.venv/Scripts/python -m agents.researcher --topic "..." --angle "..." --wiki Nokia` (prints a pack) |
| Script | Agent 3 | `.venv/Scripts/python -m agents.writer --brief brief.json --pack pack.json` (prints a script) |
| Animate | Agent 4 | `.venv/Scripts/python -m agents.animator --id <case>` (renders `.tmp/out/short_<id>.mp4`) |
| One visual | | `.venv/Scripts/python tools/infographics.py --spec visual.json --out .tmp/out/v.png` |
| The studio | | `.venv/Scripts/python tools/scene_draw.py --category business --out .tmp/out/studio.png` |
| One voice | | `.venv/Scripts/python tools/voice_tts.py --voice af_heart --text "Hello"` |
| Upload | Agent 5 | `.venv/Scripts/python tools/jobs.py publish` (the oldest ready case into the next open slot) |
| Numbers | Agent 6 | `.venv/Scripts/python -m agents.analyst [--learn]` |
| All of it | | `.venv/Scripts/python tools/jobs.py autopilot [--now]` (or `prepare`, then `publish --dry-run`, then `publish`) |

## How the autopilot works
- Each slot is **due** from 150 minutes before it until 60 minutes after. The check finds the earliest due slot, takes
  the oldest case that's **ready** (approved, or never needing approval), has Agent 4 animate it unless its preview
  already exists, and Agent 5 uploads it as private with the slot as its publish time, so YouTube makes it public on
  the minute. If the slot is less than 3 minutes away, or already passed, it goes up public straight away. Slots more
  than an hour gone are left empty ("No post").
- **No case ready:** Agents 1-3 make one on the spot, steering clear of news and politics (they'd need your OK). If it
  still turns out to need approval, it waits in the Studio and that slot stays empty.
- **Your OK first:** cases about this week's news (`cases.approval.trending`) or touching politics
  (`cases.approval.politics`) are saved as "waiting". They show in the Studio with Approve and Discard, and Telegram
  tells you. A case still waiting after `cases.approval_expires_days` is discarded: news goes stale.
- **Between slots, on this computer:** the dashboard's loop keeps `cases.queue` cases ready, renders previews (also
  for cases waiting for your OK, so you can watch them first) and has Agent 6 read the numbers and comments once a day
  (`jobs.next_chore`). All of it stops while the autopilot is paused.
- **Your requests come first:** a topic you type on the Topics page (or the Overview) is the Editor's next case,
  unless it breaks the channel's rules; then it's marked "Not made" with the reason.
- **Where it runs:** on this computer only. The voices, lip-sync and drawing need more than Vercel's free plan allows.
- **One Short per slot:** a Short being made or scheduled holds its slot (a unique index in the database), so a
  second runner can't post the same slot twice.
- **Header switch = `PAUSED`:** off stops all automatic work. Making cases, previews and uploads you start yourself
  still work.

## Steps
0. **Easiest: the dashboard.** Start it with `.venv/Scripts/python -m uvicorn app:app --port 8000` and open
   http://localhost:8000. Overview shows the six agents and today's slots; **Make a new case** runs Agents 1-3;
   **Topics** takes your requests; **Research** shows every source, checked fact, data series and photo; **Scripts**
   lets you edit every line (who says it, what's on screen, the shot, emotions), the case title, key points, title and
   description; **Studio** has the preview, Approve, Animate, Upload & schedule and Discard; **Hosts** shows the two
   hosts with their voices.
1. **Quick path:** `tools/jobs.py prepare` makes a case, `tools/jobs.py publish --dry-run` animates the oldest ready
   one without uploading (watch `.tmp/out/short_<id>.mp4`), and `tools/jobs.py autopilot --now` makes and uploads the
   next slot's Short for real.
2. **Check the result** in the YouTube Studio app: scheduled time (or public), Education, "Not made for kids", title,
   the sources, photo credits and music credit in the description.
3. `tools/db.py recent` shows what's written, being made, scheduled, skipped or failed, and the latest runs.

## Expected Outputs
- A Short in YouTube Studio for each slot: private and scheduled for its slot time, or public if it was made late
  (until it goes public you can edit or delete it: that's your veto)
- A database row per Short with its slot and its plan (brief, research pack, hosts, script, title, music)
- Locally: `.tmp/out/short_<id>.mp4` (deleted after upload), `cover_<id>.jpg` (kept for the dashboard) and the case's
  photos in `.tmp/research/<date>-<topic>/` (downloaded again from Commons if `.tmp` is cleared)

## Edge Cases & Known Issues
- **Measured 2026-10-25 on this PC (20 cores):** research 20-80 s (more with news and data); Gemini about 5 calls
  (~20-40 s); voices ~20 s and lip-sync ~5 s for 60 s of speech; drawing and encoding a 60 s case at 24 fps 70-110 s
  (100-125 s with the 2026-10-26 look). A whole case takes 3-4 minutes. Drawing is kept fast by drawing the hosts 12
  times a second (studio and close-ups whole, the screen shot's desk) and cards' animations on twos too; drawing
  everything 24 times a second took 194 s for a 61 s case.
- **No Google Search on the free tier:** Gemini's free tier doesn't include Grounding with Google Search (2026-10-25:
  "Not available"; its 5,000 free searches a month are a paid-tier perk). So `tools/research_fetch.py` fetches the
  sources itself and Gemini only reads what it's given.
- **Every fact is checked in code** (`agents/researcher.py`): its quote must be in its source (accents, quotes and
  citation marks ignored: "Karṇa" = "Karna"; long quotes may differ slightly), and every digit in the claim must be in
  the quote. Spelled-out numbers count in quotes only, and never "one" ("one of the largest"). Facts the code
  calculates from the data (change over a decade, the IMF's expected growth, doubling time) are marked as such.
  Fewer than 6 checked facts and the Editor picks another topic.
- **The Writer uses the bigger Flash model** (`llm.generate_json(careful=True)`: gemini-3.6-flash first, a little
  thinking). Flash-Lite read the facts out word for word and put a quote card on every line (2026-10-25).
- **The fact-checker** reads every line against its facts' quotes. It fixes an overstated line, cuts an unsupported
  one (never the co-host's questions, unless they bring numbers), and asks for one rewrite if it cuts more than 3
  lines or the hook. Edited lines are marked "edited by you" and aren't re-checked: keep their numbers to the facts.
- **Gemini copies examples.** A prompt that shows an example got that exact text back (2026-10-25). Prompts describe
  what a good line does instead of giving one to copy.
- **News:** GDELT answers 429 often, even to the first request of the day from some IPs (2026-10-25), so the news
  sites' RSS feeds (`research_fetch.FEEDS`: BBC, the Guardian, Al Jazeera, NPR, CNBC, France 24, Economic Times,
  Mint) are searched first and GDELT is a best-effort extra. Feeds only hold the last few days, so news research works
  best for this week's topics. Wikipedia's Current events portal adds links to the outlets for big stories.
- **User-Agents:** Wikimedia refuses bare library agents ("python-requests/x") with 403; the IMF's firewall refuses
  anything else (even browser-like ones). `research_fetch` sends each its own.
- **Rate limits:** Wikimedia answers 429 when asked quickly; `_get_json` waits (Retry-After, up to 10 s) and tries
  again, and a failed photo search only skips that subject. Answers are cached in `.tmp/research/cache` (a day for
  news, a week for the rest).
- **Photos:** only public domain, CC0 and CC BY (share-alike off by default, `research.share_alike_images`), no SVGs,
  logos, emblems or screenshots, at least 800 px; then Gemini looks at each and drops ones with children, violence,
  mostly text or logos, or poor quality. If that check fails, no photo is used (drawn visuals instead). Credits go in
  the description; the photo shows its author and licence in the corner.
- **The look (2026-10-26):** most lines are screen shots: the visual big under the band, both hosts at their desk
  under it (a light behind whoever is talking; the other glances up at each new visual and nods at the numbers), the
  captions between. Before, the speaker talked from a small round bubble and the co-host vanished for most of a case.
  Cards keep zooming in slowly and follow the words: a big number counts up and lands in gold as it's said, a
  timeline's years turn gold as they're said, lists and timelines fill in while the line is spoken. A close-up never
  changes the card (it isn't on screen). The look before is kept in `backups/v4-look-before-2026-10-26/`.
- **When each word is said:** Kokoro gives no word timings, so `case_render.word_times` estimates them from each
  word's spoken length (numbers count as said: "33%" is "thirty-three percent") and, when Rhubarb's resting mouths
  (0.12 s or longer) match the line's commas and full stops, fits each phrase between those pauses.
- **Spoken money:** Kokoro would read "$5.4 billion" oddly; `voice_tts._spoken` says "5.4 billion dollars".
  Case scripts are read at about 2.3 words a second at speed 1.0 (numbers take longer): the Writer estimates with that.
- **Settings file:** edits keep quotes (`common.update_config`, ruamel `preserve_quotes`): an unquoted 14:00 would
  load as a number (YAML 1.1), and lines up to 130 characters aren't re-wrapped.
- **Adults only, never "made for kids":** the hosts are adults (the rig has no child proportions), photos with
  children are dropped, and the upload always says "not made for kids". Topics about children are off-limits.
- **Off-limits topics** (the Editor's and Writer's rules): elections and voting; wars, attacks, disasters and crimes
  from the last 25 years; health or investment advice; anything sexual; mocking a faith, nation or group.
  Politics only as policy and economics, both sides, and after your OK.
- **Shorts from earlier versions** (the same database) show in the Studio as "Cartoon version" or "Cute-animal
  version": they can still be uploaded as they are (if their video was kept) or discarded. The agents never pick them,
  and the Analyst only learns from cases.
- **Rhubarb missing or failing** falls back to mouth shapes from the loudness of the voice. Kokoro has no fallback: if
  its model can't download, Agent 4 fails and says why.
- **Gemini speed and quota:** Flash-Lite models first for lists and checks, Flash for writing; quota errors (429)
  fall through to the next model. A case takes about 5 requests (Editor 1, Researcher 2, Writer 2); the weekly lessons
  one more; designing the hosts one.
- **YouTube:** uploads have their own quota (100/day by default); comments cost 1 unit per Short a day. Titles and
  descriptions can't contain `<` or `>`; the tools strip them.
- **Interrupted run:** if a run is cut off (crash, PC asleep), its Short stays "making"; after 15 minutes the next
  check puts it back in the queue (or marks it skipped if it had no plan yet).
- **Failed upload:** the Short goes back to the queue and the next check retries it; after 2 failures it's marked
  "failed" with the error saved, and the slot gets a fresh Short on the next try.
