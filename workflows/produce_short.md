# Workflow: Produce a Short

## Objective
Turn a mystery worth solving into a finished case study a minute or so long, hosted by **the Professor** (the user's
own character, floating in the lower-left corner) over real footage, on a fixed timetable. Seven agents in order:
Agent 1 (Editor) picks the case, its paradox and its question; Agent 2 (Researcher) gathers and checks the facts and
finds real photos, stock video and archive film; Agent 3 (Writer) writes the Professor's script in the five-part
format and fact-checks it; Agent 4 (Animator) has him read it and makes the video and its thumbnail; Agent 5
(Reviewer) watches and listens to every video and sends one that fails back to Agent 4 with notes; Agent 6
(Publisher) uploads what passed so it goes public on the minute of its slot, and posts it to Instagram as a Reel;
Agent 7 (Analyst) learns from the numbers and teaches every agent. The **autopilot** does all of it by itself on the
schedule in `config/channel.yaml` → `schedule` (10 a day, every 2 hours from 08:00 India time, as of 2026-10-26):
every morning at `make_at` (07:00) **the morning run** makes the whole day's Shorts, one after another, until all are
scheduled on YouTube, then rests until the next morning. It runs on GitHub Actions (`.github/workflows/morning.yml`),
or on this computer while the database is the local one, without waiting for anyone's OK (`cases.approval` is off:
the Publisher approves news and politics itself). Use this workflow to run it by hand, test changes, or debug a
failed slot.

## Required Inputs
- Keys in `.env` (see `workflows/setup_accounts.md`): `GEMINI_API_KEY`, `PEXELS_API_KEY` (and optionally
  `PIXABAY_API_KEY`), `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (the drawn look's scenes) and the YouTube values; for Reels, the `INSTAGRAM_*` and `FACEBOOK_APP_*` values (the dashboard's
  Channels page writes them) and `instagram.enabled: true` (its switch)
- Settings in `config/channel.yaml`: schedule (with `make_at`), `cases` (types, approvals, length), `look` (`style`:
  drawn or footage, his `art` in words, Cloudflare's `model` and `steps`), `host` (his name for the dashboard, his size)
  and `voice` (Gemini voice, model, persona style, `deeper`); and
  `config/calendar.yaml` (holidays and anniversaries the Editor can tie a case to)
- The Professor's drawings in `assets/host/` (made once from the user's sheet by `tools/host_prep.py`; committed)
- This computer: whisper (word timings), Rhubarb (his mouth), the depth model (photos that move) and waifu2x (only for `host_prep.py`) download themselves into `.tmp/models/` the first time
- The internet: Wikipedia, Wikimedia Commons, the IMF and World Bank data APIs, news sites' RSS feeds and GDELT, the
  Internet Archive and NASA's library (no keys), Pexels and Pixabay (keys)
- Music tracks in `assets/music/` (optional). `assets/music/tracks.yaml` gives each track's `mood` (the Writer picks
  one, the Animator a track in it) and its `credit:` line, which the Publisher adds to the description. Kevin
  MacLeod's tracks (CC BY 4.0, in YouTube's Content ID) must always carry it.

## Tools
| Step | Who | Command |
|---|---|---|
| Timetable | | `.venv/Scripts/python tools/slots.py` (today's and tomorrow's slots) |
| Trends | | `.venv/Scripts/python tools/trends_fetch.py` |
| Pick a case | Agent 1 | `.venv/Scripts/python -m agents.editor` (prints a brief, saves nothing) |
| Sources | Agent 2 | `.venv/Scripts/python tools/research_fetch.py wiki Nokia` (also `search`, `events`, `onthisday`, `news`, `data`, `images`) |
| Footage | Agent 2 | `.venv/Scripts/python tools/footage.py --query "old mobile phone" [--archive Tupperware] [--history] [--check] [--download]` |
| Research | Agent 2 | `.venv/Scripts/python -m agents.researcher --topic "..." --angle "..." --wiki Nokia --broll "stock market screen" [--archive "aircraft carrier"]` |
| Script | Agent 3 | `.venv/Scripts/python -m agents.writer --brief brief.json --pack pack.json` (prints a script) |
| His voice | Agent 4 | `.venv/Scripts/python tools/narration.py --text "In 2000..." --text "Fourteen years later..."` |
| A drawing | Agent 4 | `.venv/Scripts/python tools/draw.py --check` (one test picture, ~58 of the 10,000 free neurons) or `--scene "a 1920s country road at dawn" --out .tmp/out/scene.jpg` |
| Him alone | Agent 4 | `.venv/Scripts/python tools/host.py [--size L]` (a test clip: his line from the sheet) |
| Animate | Agent 4 | `.venv/Scripts/python -m agents.animator --id <case> [--now]` (renders `.tmp/out/short_<id>.mp4` and `thumb_<id>.jpg`; `--now`: ask Gemini's voice even while it rests) |
| Thumbnail | Agent 4 | `.venv/Scripts/python tools/thumbnail.py --image photo.jpg --text "One phone *sank* Nokia" --category business --out t.jpg` |
| Review | Agent 5 | `.venv/Scripts/python -m agents.reviewer --id <case> [--fix]` (`--fix`: the whole make-review-fix loop) |
| Render a case file | | `.venv/Scripts/python tools/doc_render.py --case case.json --out .tmp/out/doc.mp4` |
| His drawings | | `.venv/Scripts/python tools/host_prep.py` (only if the sheet changes; check `.tmp/out/host_check.png`) |
| Upload | Agent 6 | `.venv/Scripts/python tools/jobs.py publish` (the oldest ready case into the next open slot) |
| Reels | Agent 6 | `.venv/Scripts/python tools/jobs.py instagram` (the Reels whose slot has come); `tools/instagram.py --status` |
| Numbers | Agent 7 | `.venv/Scripts/python -m agents.analyst [--learn]` |
| The day's run | | `.venv/Scripts/python tools/jobs.py morning` (what GitHub runs at 06:55; it waits for 07:00) |
| One Short | | `.venv/Scripts/python tools/jobs.py autopilot [--now]` (or `prepare`, then `publish --dry-run`, then `publish`) |
| Move the data to the cloud | | `.venv/Scripts/python tools/db_copy.py` (once; needs `DATABASE_URL`) |

## How the autopilot works
- **The morning run** (`jobs.morning`): a posting day's slots (08:00 to 02:00 the next morning) are all **due** from
  `make_at` (07:00) that morning until an hour after each slot; before 07:00 nothing is made. The run takes the
  earliest due slot, the oldest case that's **ready** (approved or never needing approval, and not held by the
  Reviewer), or makes one on the spot, has Agent 4 make it and Agent 5 review it, and Agent 6 uploads it as private
  with the slot as its publish time, so YouTube makes it public on the minute, then sets its thumbnail. Then the next
  slot, with no pause, until every slot of the day is scheduled: one summary to your phone, then the day's numbers.
  A slot less than 3 minutes away, or already passed, goes up public straight away; slots more than an hour gone are
  left empty ("No post"). About 10-15 minutes a Short, so 10 take about 2 hours.
- **When a Short fails** the run carries on: the next try waits 2 minutes, twice as long after each failure in a row,
  up to 20 (`jobs.RETRY_FIRST`, `RETRY_MOST`), so Gemini's free per-minute limits recover. It stops early, as a failed
  run (GitHub emails you, Telegram says why), only when YouTube's sign-in is broken, after 25 Shorts tried
  (`jobs.MAX_TRIES`), or at 5 h 40 min (GitHub's jobs end at 6 hours); the pause switch stops it quietly.
- **Your veto, on the Schedule page:** beside each Short, a YouTube part and an Instagram part show where it stands
  there (`publisher.platforms`; the dashboard asks YouTube about the page's Shorts at most every 2 minutes,
  `youtube_upload.statuses`, so one deleted, made private or rejected in YouTube Studio shows as that), each with
  **Open**, **Post now** and **Delete** (2026-10-27). YouTube: **Post now** makes it public at once (`publish_now`;
  its slot stays its own, so no other Short is made for it, and its Reel still waits for the slot); **Stop** keeps it
  as private (it never goes public by itself; you can still publish it in YouTube Studio); **Delete** removes it,
  public or not (`unschedule`, `delete`; the case shows "Stopped" or "Deleted", and its Reel goes too unless it's
  posted). Stop and Delete free its slot: while the autopilot is on, the morning run makes a new Short for it (on this
  computer within a minute; in the cloud at the next catch-up run), unless the slot is more than an hour gone. They
  need the sign-in's permission to change and delete videos (`youtube.force-ssl`, asked for since 2026-10-26). A
  sign-in from before only uploads and reads, so the first press offers Google's page (the API answers 403 with
  `reconnect`); once it's allowed, the action finishes by itself. The Schedule page's "Allow it now" and the YouTube
  page's Reconnect do the same.
- **The Reviewer's loop** (`reviewer.reviewed`): a video that fails goes back to the Animator with notes
  (`animator.improve`: a colliding number or name comes off its line, the title leaves sooner, a dark, frozen or
  unsuitable shot is swapped, a rushed line is read again slower, a voice that isn't his read again, longer
  pauses, a line cut, or simply made again). It also checks the voice is **his**: read by one of his models and
  measured like the Host page's sample of his voice (`reviewer.his_voice`, `tools/voiceprint.py`; added 2026-10-27
  after you discarded three Shorts it had passed in a lighter, younger voice).
  At most 2 fixes (`reviewer.MAX_ROUNDS`); one that still fails is **turned down (held)**: never posted as it is,
  and the slot goes to the next case. **It's made again by itself, over and over until it passes** (the user's
  call, 2026-10-27: "make sure that the animator makes it again by itself without my approval"): the loop
  (`jobs.unmade`) has `animator.make_again` prepare it when its `review.remake_at` comes (at once the first time,
  then 30 min, 1 h, 2 h, then every 4 h: `reviewer.REMAKE_WAITS`), then it's made and reviewed again with a fresh
  2 rounds of fixes. Each time something real changes: every scene the last review turned down gets a drawing from
  a seed never used before (`line.seed_from`; redraws counted afresh), a voice problem gets a new reading (and a
  line Gemini still rushes after "slower" is slowed on its own, pitch kept: `narration.slow_rushed`, since Gemini
  read #52's line 5 at 3.7 words a second even when asked to go slowly), and from the third time
  (`animator.REWRITE_FROM`) the Writer writes the script again first. Once it passes it takes the next open slot.
  Telegram says so once, the first time. Nothing goes to YouTube meanwhile (until 2026-10-27 a held video went up
  as private for you to watch and decide: retired). The Studio still offers Post it anyway and Discard.
- **Instagram Reels** (when connected and `instagram.enabled`): once a Short's slot has come and it's public on
  YouTube, the same video goes up as a Reel (`publisher.post_reel`); Instagram's API can't schedule Reels. A Short you
  deleted on YouTube (the veto) isn't posted there. A failed try waits longer each time (8 tries over about nine
  hours: Instagram's upload server drops uploads in spells); a Reel not posted within
  2 days of its slot (this PC was off) is given up. The video file is kept until the Reel is up, or 2 days after the
  slot. On the Schedule page, Instagram's **Post now** posts it at once, even before it's public on YouTube (a task
  beside the morning run: the upload and Instagram's processing take a few minutes; if it fails, a Reel that was
  waiting still goes at its slot), and **Delete** deletes a posted Reel from Instagram, or takes one off that isn't
  posted yet (Post now still works while the video is kept). A Reel is claimed ("posting") before it goes, so the
  loop and your Post now never post it twice; one cut off mid-way (the dashboard stopped) shows as failed after 30
  minutes, ready for Post now. Deleting a Reel needs one more permission on the token, `instagram_manage_contents`;
  without it Instagram refuses and the dashboard says so (delete it in the Instagram app instead).
- **Reels go out beside the morning run (2026-10-27):** the loop on this computer posts due Reels as a task of their
  own every minute (`dashboard/api.py` `_post_due_reels`), not as one of `jobs.next_chore`'s chores: the morning run
  held the chores for hours (and on 2026-10-27 waited ~14 hours for Cloudflare), so Reels would have gone out hours
  late. The pause switch still stops them.
- **A Short that went up while Reels were off** has no video kept, so its Instagram side offers **Schedule**
  (`publisher.remake_reel`, the "remake" task): the video is made again as it was (`animator.animate(again=True)`: the
  same case, music and kept drawings, read again by the same voice since the first reading isn't kept either;
  footage that was cleared is fetched again; nothing in the plan changes, so it still describes the YouTube video),
  and its Reel then waits for its slot (or goes at once if the slot has passed). About 5-6 minutes a Short. Used
  first on 2026-10-27, when Instagram was connected after the day's Shorts were up. A drawn Short whose drawings
  were cleared can't be made again while Cloudflare rests.
- **No case ready:** Agents 1-3 make one on the spot, steering clear of news and politics (they'd need your OK). If it
  still turns out to need approval, it waits in the Studio and that slot stays empty.
- **Your OK first (off since 2026-10-26):** with `cases.approval.trending` or `cases.approval.politics` true, cases
  about this week's news or touching politics are saved as "waiting", shown in the Studio with Approve and Discard,
  and Telegram tells you; one still waiting after `cases.approval_expires_days` is discarded (news goes stale). With
  both false, as now, the Publisher approves them itself at every check (`publisher.auto_approve`).
- **Every agent learns** (`agents/base.py lessons_for`): a problem the Reviewer finds in 3 of the last 12 first looks
  becomes a standing fix (e.g. longer pauses from the start) or advice in the Writer's and Researcher's prompts
  (`review:lessons` note); the Analyst's weekly playbook adds lessons for each agent from the numbers. Every agent
  reads its own every time; the dashboard shows them on the Review and Results pages.
- **Between runs it rests (your choice, 2026-10-26):** no new cases are made ahead during the day; the dashboard's
  loop on this computer (`jobs.next_chore`, every minute) starts the morning run when a slot is due, posts Reels
  whose slot has come, makes the video of any case that's waiting without one, and has Agent 7 read the numbers
  once a day. The `cases.queue` setting is retired.
- **Nothing asks you to press "Make the video" (2026-10-27):** a waiting case without its video (made from the Topics
  page, sent back with "Make it again", or left from a run) is made and reviewed by the loop (`jobs.unmade`): not
  while Gemini's voice rests, a failed one again after 30 minutes (`PREVIEW_RETRY`), given up after 3 failures
  (`PREVIEW_TRIES`; the morning run makes a new case). A case the Reviewer turned down is made again the same way
  when its time comes (above). "Make it now" in the Studio is optional.
- **When an agent hits a snag (2026-10-27):** it's fixed where it happens, else the case is replaced at once.
  A topic the Researcher can't support, or a script the Writer can't get past the fact-check even rewritten, is
  swapped for another topic (`jobs.TOPIC_TRIES`, 3); a video the Reviewer fails goes back to the Animator with notes;
  a case whose making or upload fails is tried once more (it goes back to the queue). If that doesn't fix it, the
  whole process starts again with a new case for the same slot, with no waiting (`jobs.CASE_TRIES`, 3). Only what
  no other case would get past makes the run wait (`jobs._must_wait`): Gemini's voice out, Gemini out of quota or
  refusing the key, YouTube's sign-in. Short #37's script (2026-10-26, "too few lines survived the fact-check") used
  to end its try with a 2-minute wait; now another topic is written straight away.
- **Your requests come first:** a topic you type on the Topics page (or the Overview) is the Editor's next case,
  unless it breaks the channel's rules; then it's marked "Not made" with the reason. Topics you discarded in the
  last 90 days aren't chosen again by the Editor itself (`editor.discarded_topics`), but you can still ask for one.
- **Where it runs:** GitHub Actions, free for a public repository (4 cores, 16 GB, 6 hours a job): every day at 06:55
  India time, with catch-up runs at 13:00 and 19:00 that fill any slot the morning couldn't (and end within minutes
  otherwise); "Run workflow" on the Actions tab starts it by hand, and its **test** option makes and reviews one video
  without uploading. The keys are the repository's secrets and the data is in Neon's free Postgres (`DATABASE_URL`),
  which the dashboard reads too. With `DATABASE_URL` in `.env`, this computer's own loop stays off, so only the cloud
  posts; without it, the dashboard here runs the same morning run (it keeps the laptop awake while working: it
  sleeps after 5 idle minutes otherwise). Vercel can show the dashboard, but can't make the videos: one Short needs
  10-15 minutes and about 1.6 GB of models and packages; a Vercel function gets 5 minutes and 250 MB.
- **Settings live in the repository:** the cloud reads `config/channel.yaml` (and the music) from GitHub, so a change
  made in the dashboard on this computer reaches the cloud once it's committed and pushed.
- **One Short per slot:** a Short being made or scheduled holds its slot (a unique index in the database), so a
  second runner can't post the same slot twice.
- **Header switch:** off stops the morning run and all automatic work, here and in the cloud (it's kept in the
  database; `PAUSED=true` in `.env` or GitHub's variables does the same). Making cases, videos and uploads you start
  yourself still work.

## Steps
0. **Easiest: the dashboard.** Start it with `.venv/Scripts/python -m uvicorn app:app --port 8000` and open
   http://localhost:8000. Overview shows the seven agents and today's slots; **Make a new case** runs Agents 1-3;
   **Topics** takes your requests; **Research** shows the story, every source, checked fact, data series, photo, stock
   clip and archive film; **Scripts** lets you edit every line (its beat, what he says and how, what's on screen), the
   case title, title and description; **Studio** has the video, the Reviewer's verdict, the thumbnail (change its
   words or still), Make it now (optional) / Make it again (not for a turned-down case: that's made again by itself),
   Post it anyway (turned-down cases), Upload & schedule and Discard; **Review** lists the cases being made again (why,
   and when next), recent reviews and the lessons taught; **Results** shows what each agent has learned;
   **Host** shows the Professor, his voice (samples of Gemini's deep voices, Deeper, persona), his size and a
   test clip; **Channels** connects YouTube and Instagram.
1. **Quick path:** `tools/jobs.py prepare` makes a case, `tools/jobs.py publish --dry-run` animates the oldest ready
   one without uploading (watch `.tmp/out/short_<id>.mp4`), and `tools/jobs.py autopilot --now` makes and uploads the
   next slot's Short for real.
2. **Check the result** in the YouTube Studio app: scheduled time (or public), Education, "Not made for kids", title,
   and the sources, photo, footage and music credits in the description.
3. `tools/db.py recent` shows what's written, being made, scheduled, skipped or failed, and the latest runs.

## Expected Outputs
- A Short in YouTube Studio for each slot: private and scheduled for its slot time, or public if it was made late
  (until it goes public you can edit or delete it: that's your veto)
- A database row per Short (`format = 'doc'`) with its slot and its plan (brief, research pack, script, title, music,
  voice, credits)
- With Reels on, the same video on Instagram at its slot time, its caption made from the same description (sources
  named, not linked) and its cover frame at the thumbnail's shot
- Locally: `.tmp/out/short_<id>.mp4` (deleted after upload; with Reels on, once its Reel is up or 2 days after its
  slot), `cover_<id>.jpg` and
  `thumb_<id>.jpg` / `thumb_<id>_wide.jpg` (kept for the dashboard), the Professor's reading in `.tmp/voices/<id>`
  (until the Short is posted or discarded), the case's
  photos and depth maps in `.tmp/research/<date>-<topic>/`, and its clips in `.tmp/footage/` (deleted after upload;
  fetched again from their source if ever needed); in the drawn look its drawings and their depth maps in
  `.tmp/scenes/<id>/` (kept by description, so a re-render or a redraw only draws what changed)

## The look and the voice
- **The frame:** 1080x1920, 24 fps. Each line has one or two visuals, so the picture changes every few seconds:
  stock video (cropped to fill, pushing in), archive film (whole, full width, high in the frame, over a blurred copy),
  real photos with depth (near parts slide more than far ones), NASA's Blue Marble with the countries lit, charts and
  quote cards high in the frame. Numbers count up and land in gold, with an impact, the moment they're said. A
  person's photo gets their name top left (after the title fades). One grade, vignette and grain for all of it.
- **The Professor:** always in the lower-left corner, about 440 px wide (`host.size`: S/M/L), his chest fading out
  just above YouTube's title text, a soft shadow behind him. He bobs slowly, sways, tilts a degree, nods as each line
  starts, blinks every 2-6 s, and his mouth follows Rhubarb's shapes (held two frames, like hand-drawn animation).
  Every movement repeats a whole number of times over the video, so the loop is seamless. Captions sit in the middle,
  above him; the right side stays clear for YouTube's buttons.
- **His voice:** one Gemini text-to-speech call per case (`voice.model`, free tier), every line with the
  persona (`voice.style`) and its own direction; whisper (small.en) times every word; quiet pauses over 0.34 s are
  cut to 0.2 s; then `deeper` lowers it (ffmpeg's rubberband, formants kept, timing unchanged).
- **Sound:** a whoosh at each new beat, an impact under each number, a riser into the reveal, music in the script's
  mood ducked under his voice, loudness -14 LUFS. No end card: the video ends half a second after the last word.
- **The drawn look (`look.style: drawn`, the user's choice on 2026-10-27; `footage` brings the look above back):**
  every line plays over a scene painted in the Professor's own art. The Writer describes each drawing in the line's
  `scene` (6 to 9 a Short, at most `writer.MAX_SCENES`; "same" keeps the one before, with a new camera move), the
  Animator has Cloudflare's FLUX.1 [schnell] draw them (`tools/draw.py`: his `look.art` words first, then the scene),
  and each square drawing is seen through a 9:16 window travelling across it, with depth. Real photos are framed over
  the line's drawing (a print with a paper border, slightly turned, the person's name top left); maps, charts and
  quotes sit on the drawing, softened and darkened; maps are the drawn navy-and-gold map, never the satellite photo.
  A line under 8 words with a photo or card shows only that (`animator.SHORT_LINE`). The Researcher looks for no
  clips. A script keeps the look it was written in (`script.look`), so switching only changes the next cases.
- **When Cloudflare can't draw, the real-footage look takes over (`look.when_out: footage`, the user's choice on
  2026-10-27: "has to finish the daily 10 videos"):** while its drawing rests (its free allocation used up until
  05:30 in India, or it's down), new cases are researched and written for footage (`draw.style_now()`; the pack says
  which look it was researched for, `pack.look`), and a case written for drawings that can't be drawn is written
  again for footage before he reads it (`animator.as_footage`: the Researcher's `add_footage` finds its clips, the
  Writer writes it again from the same facts and photos; `plan.switched` records it, and the Reviewer's fixes for
  the old lines go). The day's slots all fill. A Short made again for its Reel (Schedule) never changes its look: it
  waits for Cloudflare. `look.when_out: wait` (Settings: "When Cloudflare can't draw") brings back waiting.
- **No "Case file N" on screen (the user's call, 2026-10-27):** the opening chip shows only the case type over the
  title, and the thumbnail's tab only the case type. The case number still seeds his blinks (`animator.case_number`).

## Edge Cases & Known Issues
- **YouTube's daily upload limit (found 2026-10-27):** after 11 uploads in 24 hours (deleted and stopped ones count
  too) YouTube answered every upload with 400 "The user has exceeded the number of videos they may upload"
  (uploadLimitExceeded), from about 08:30 UTC. The run took it for a bad case: gave each up and made a new one, 16
  cases (#49-#64) made in vain over 6 hours, wearing out Gemini's free voice. Now it's `youtube_upload.UploadLimit`:
  the case goes back to the queue untouched (no try counted, `publisher.upload`), no other case is made for it
  (`jobs._must_wait`), and the run waits an hour and tries the same case again (`jobs.UPLOAD_WAIT`). The limit
  seemed to count the last 24 hours, so every extra upload (a re-upload, a Short deleted and made again) can cost a
  slot later. That's also why held videos no longer go up as private.
- **The drawn look's limits (measured 2026-10-27):** Cloudflare's free plan gives 10,000 neurons a day (renewed at
  00:00 UTC, 05:30 in India); a 1024x1024 schnell picture at 4 steps costs ~58, so ~170 a day, and 10 Shorts of 6-9
  drawings use ~3,500-5,200. `draw.py` stops itself at 9,000 (a `draw:budget` note by UTC day): then, or when Cloudflare
  says its allocation is used up, the drawing rests until 00:00 UTC (a `draw:rest` note; the dashboard shows it), and
  when Cloudflare is down or refuses the key it rests 10 minutes, doubling up to an hour, like the voice. Meanwhile the
  Shorts are made with real footage (above), or with `look.when_out: wait` they wait (`DrawingResting`). The free plan
  never charges: past its allocation Cloudflare refuses. A picture takes ~3 s. **In practice the allocation ran out at
  64 pictures on 2026-10-27 (~3,900 by our count): Cloudflare's real cost is about twice the published rate, so about
  7-8 drawn Shorts fit a day and the rest are made with footage.**
- **Schnell on Workers AI takes no seed:** sending `seed` gives a 400 ("unevaluated properties '/seed'"). Each call is
  a new picture anyway, so the seed only names the kept file: a Reviewer's redraw (a new seed) gets a new drawing.
- **FLUX has no "negative prompt":** "no border, no frame" drew a white paper margin round the first test picture.
  The prompt now asks for "a full-bleed painting filling the whole picture edge to edge", and `draw.trim` cuts any
  plain margin plus a thin strip at every edge (`EDGE`, 4%), where it sometimes paints a fake signature (one tiny
  scribble in the hotel scene of the sample). Redraw hints are written as what to do, never as what to avoid.
- **Schnell sometimes drops the second subject:** asked for "a woman by the window, a man by the fireplace", it drew
  only the woman (the sample, 2026-10-27). Hence the Writer's rule: one main subject per drawing, the one that matters
  first. FLUX.2 [klein] (`@cf/black-forest-labs/flux-2-klein-4b`, multipart, 9:16, can take his sheet as a style
  reference) drew both, but costs ~160 neurons a picture: too many for 10 Shorts a day on the free plan, and `draw.py`
  speaks schnell's JSON only.
- **Scenes are checked in code before they're drawn** (`writer.clean_scene`): words in quotes and "a sign reading..."
  go (they come out as garbled letters), a real person's name becomes their role (never a likeness: their real photo
  shows their face), and a scene with anything graphic or a child stays on the drawing before. The Reviewer then
  looks for letters or a signature in a drawing, a photo-real or off-style drawing and twisted hands or faces
  (`garbled_text`, `off_style`, `bad_anatomy`, major), and a drawing it turns down (or one too dark to see) is drawn
  again with a word on what to change, at most twice (`animator.MAX_REDRAWS`).
- **waifu2x is too slow for scenes:** sharpening one 1024px drawing ran over 4 minutes on this PC and froze it
  (memory), so drawings are enlarged the plain way; waifu2x stays for `host_prep.py` only.
- **The laptop stays usable while it renders:** every job and the renders it starts run below normal priority
  (`common.background_priority`, from `jobs.py` and the dashboard). Measured with two renders at once: a stand-in
  program's worst stall fell from 0.31 to 0.21 s. One drawn render alone: ~2 GB of memory, a third of the processor on
  average, ~3 minutes for a 45-second Short, about the same as the footage look.
- **Measured 2026-10-26 on this PC:** research 2-5 minutes (archive film is the slow part: ~20 s per film to read
  three frames over the web); the Writer's three Gemini readings ~20-30 s; his voice 10-35 s; whisper ~5 s; mouth
  shapes 6-15 s; drawing and encoding a 71 s case ~2 minutes (his drawing ~15 ms a frame).
- **His voice gives 20 readings a day, and hangs when they're used (2026-10-27):** each of his two models gives 10
  free readings a day (Google's day: it renews at midnight Pacific time, 12:30 in India, 13:30 once the US clocks go
  back). When a model's 10 are used, the Interactions API doesn't say so: it never answers (both models, even a
  one-line read), while generate_content answers at once with 429 "generate_content_free_tier_requests, limit: 10 ...
  per day". (That's what "hung for over an hour" was on 2026-10-26 too.) So every reading is counted per model and day
  (`narration.used_today`, note `voice:used`, `DAILY`); a model with none left isn't asked; one that hangs is asked once
  through generate_content for one word (`narration._used_up`): "per day" marks it used up until the renewal. Ten Shorts
  need ten readings plus any the Reviewer asks for again; the Host page shows the readings left. `gemini_read` still
  gives up after 120 s by the clock (in a daemon thread, so a request that never answers can't keep a script from
  ending), and a model that failed for another reason is asked last for 30 minutes (`narration.ordered`).
- **Only his models read him (2026-10-27):** the legacy `gemini-3.1-flash-tts-preview` refuses a direction per line
  ("Speech metadata is not supported for this model", 400), so it read the plain words, sped up, slowed back down by
  software (0.78-0.98x) and lowered: a lighter, younger man, 4.6-5.9 semitones above his sample. It read every case
  once the 3.8 models' readings ran out that afternoon, the Reviewer passed them, and you discarded #62, #64 and #66
  (and deleted #42) for the voice. With his persona written into its text it still came out 3.6-4.0 semitones higher.
  It's gone (`narration.TTS_MODELS`), with its slowing down; a model chosen in the settings only reorders his two.
  Bare 16-bit samples with no WAV header (which ffmpeg can't read) still get one in `gemini_read`.
- **Every reading is measured against his voice (`tools/voiceprint.py`):** against the Host page's sample of the voice
  you chose, in his persona and depth (`narration.his_voice`; made once if it's missing). Pitch: the median of a YIN
  track; timbre: the distance of the mean MFCCs in units of the sample's spread. Measured 2026-10-27 against Alnilam,
  2 deeper (106.7 Hz): his 8 readings -2.3 to +1.3 semitones, timbre 0.15-0.21; the legacy model's 6 +4.6 to +5.9,
  0.24-0.30. Limits: -3 to +2 semitones (`voiceprint.PITCH`), timbre 0.26. A reading outside them isn't used (the next
  model reads it); a kept one isn't used again (`animator.is_his`); and the Reviewer measures every video's reading
  the same way (`reviewer.his_voice`: "not_his_voice", fixed by reading it again). A review from before this check
  (`reviewer.CHECKS`) is done again before the case is posted, so the legacy-voiced cases still queued (#49, #58,
  #61, #63) are read again in his voice first.
- **When his voice is out:** it rests (a `voice:rest` note; the dashboard says until when): until his readings renew
  when they're used up (the note's `used_up`), else 10 minutes, twice as long after each failure in a row, up to an
  hour (`animator.REST_FIRST`, `REST_MOST`); a voice that answers ends it. There's no other voice (your choice,
  2026-10-27: Kokoro's backup didn't sound like him and was removed, its files in
  `backups/kokoro-backup-voice-2026-10-27/`; the legacy model went the same day). The case waits: it goes back to
  the queue with no try counted (`animator.VoiceResting`), and the morning run sleeps until the rest is over and asks
  again (a Short due, or "Make it now", asks even while it rests, but never a model with no readings left). Slots can
  go empty on a day his readings run out. A fix waiting for his voice is applied once, not again at each try
  (`fixes.after`: the render its review was of). Waiting for the voice isn't sent to your phone as a failure.
- **A rushed line (2026-10-27):** a line the Reviewer found rushed is read again "slowly"; Gemini doesn't always hear it
  (#52 came back at 3.7 words a second), so a line still faster than 3.0 is slowed on its own, pitch kept
  (`narration.slow_rushed`, `stretch`: rubberband with smooth transients, which kept a steady tone's pitch where the
  default lowered it), never below 0.85x: gently, as a stronger stretch smears his voice.
- **Whisper skips speech when given the script (2026-10-26):** with the script as its prompt, whisper heard only the
  last 13 s of a 39 s backup reading and the pause-cutting then removed the first 25 s of speech as "silence" (Short
  #32 came out 13 s long and the Reviewer held it three times). Now `hear()` gets no prompt (105 of 106 words heard,
  match 0.94), and `tighten()` only cuts quiet audio: where whisper heard nothing but the voice is speaking, only the
  real pauses in it go.
- **Whisper's lock (2026-10-26):** `hear()` holds the model's lock while `_model()` loads it, so the lock is
  re-entrant (`RLock`); a plain Lock deadlocked forever. The model loads from `.tmp/models/whisper` without asking
  Hugging Face (works offline).
- **His pace:** about 2.0-2.2 words a second on real scripts after the pauses are cut (2.5 on plain sample
  sentences; numbers and dates take longer). The Writer plans with 2.1 (`writer.WORDS_PER_SECOND`, also the
  dashboard's `PACE`): Tupperware ran 2.18, Western Sydney Airport 1.98 (72 s against a 65 s plan at 2.3).
- **Deeper:** Gemini's deep voices measured 118-130 Hz with his persona (Orus 118, Charon 119, Alnilam 121,
  Sadaltager 123, Algenib 124, Iapetus 130); 2 semitones takes Charon to about 113 Hz on the same pitch tracker, and
  whisper still matches every word.
- **No Google Search on the free tier:** Gemini's free tier doesn't include Grounding with Google Search (2026-10-25:
  "Not available"). So `tools/research_fetch.py` fetches the sources itself and Gemini only reads what it's given.
- **Every fact is checked in code** (`agents/researcher.py`): its quote must be in its source (accents, quotes and
  citation marks ignored: "Karṇa" = "Karna"; long quotes may differ slightly), and every digit in the claim must be in
  the quote. Spelled-out numbers count in quotes only, and never "one" ("one of the largest"). Facts the code
  calculates from the data (change over a decade, the IMF's expected growth, doubling time) are marked as such.
  Fewer than 6 checked facts and the Editor picks another topic. The story (the fact it opens on, people's decisions,
  the twist) only keeps parts whose fact survived.
- **The Writer** (careful mode: the bigger Flash model, a little thinking) writes the user's five-part format
  (2026-10-26): the hook (one line framing the whole story: the decision, mistake or discovery at its heart and its
  consequence), the setup (the person, company, event or mystery), the turning point (decisions, each line ending on a
  pull forward), the reveal (the outcome and why it matters) and the narrator's closing thought (one reflective line
  in his own words, "And that is why..."). Before that date: hook, question, context, turns, reveal, echo. Code catches
  lecture habits and asks for one rewrite: a line starting with a date, more than 3 dates, more than one number in a
  sentence, a moral or conclusion ("this shows", "proving", "the lesson") anywhere but the closing thought, a
  greeting, lists, 3 lines in a row each with a number. The fact-checker treats the closing thought as a reflection,
  unless it slips in a new fact or number. The Writer also gives 2-5 words for the thumbnail, the key one *starred*.
  A big number or quote card stays only on a line citing its fact (a quote about 2007 salespeople once appeared under
  a line about bankruptcy); a line that only repeats an earlier one's fact goes.
- **The retention editor** (one more free Gemini reading) scores hook, open loop, pace, specifics and payoff and
  rewrites only weak lines; a rewrite with a number its facts don't support, or a lecture habit, is ignored. Then
  **the fact-checker** reads every line against its facts' quotes: fixes overstated lines, cuts unsupported ones;
  framing lines with no claim ("So what went wrong?") are marked "no claim" and stay. More than 3 cuts or the hook cut
  means one rewrite. Lines you edit are marked "edited by you" and aren't re-checked: keep their numbers to the facts.
- **Gemini copies examples.** A prompt that shows an example got that exact text back (2026-10-25). Prompts describe
  what a good line does instead of giving one to copy.
- **Stock footage is illustrative:** Pexels portrait first (fills the frame), then landscape, then Pixabay. Gemini
  checks up to 3 frames of every candidate in one request; code enforces the hard rules (never a child, nothing
  graphic or sexual, no distress, no text or logo as the focus, no weapons or fighting, nothing blurry). The Writer
  never presents a stock clip as the real company, person or event; the description lists it as illustrative.
- **Archive film is the real thing:** only Internet Archive items marked public domain (`licenseurl:*publicdomain*`)
  from the Prelinger Archives and FedFlix (US government films), and NASA's own videos (not ones it credits to others;
  no "This Week @NASA" style news shows). Films about young people or grim subjects are skipped by their words. Three
  frames are read straight off the web (ffmpeg seeks; the film isn't downloaded) at 22%, 47% and 72% (past any opening
  titles); Gemini's best frame decides which 9 s are cut. Old 4:3 film (mostly 640x480) is shown whole, not cropped.
  A brand in its own old advert is fine there; period battles without gore are fine for history cases (`combat_ok`).
  Prelinger items without a public-domain licence URL are left out even when they look old.
- **Photos:** only public domain, CC0 and CC BY (share-alike off by default, `research.share_alike_images`), no SVGs,
  logos, emblems or screenshots, at least 800 px; Gemini drops ones with children, anything graphic, mostly text or
  logos, or poor quality; combat (warships, warplanes) only in history cases. Before 2026-10-26 "violent" also meant
  every warship, and the Battle of Leyte Gulf got no photos at all. If the check fails, no photo is used.
- **News:** GDELT answers 429 often (2026-10-25), so the news sites' RSS feeds (`research_fetch.FEEDS`) are searched
  first and GDELT is a best-effort extra. Feeds only hold the last few days.
- **User-Agents:** Wikimedia refuses bare library agents ("python-requests/x") with 403; the IMF's firewall refuses
  anything else. `research_fetch` sends each its own; `footage.py` sends its own to the Internet Archive and NASA.
- **Rate limits:** Wikimedia answers 429 when asked quickly; `_get_json` waits (Retry-After, up to 10 s) and tries
  again, and a failed photo search only skips that subject. Answers are cached in `.tmp/research/cache`.
- **Titles:** an emoji just before the closing "?" ("empire 📱?") is moved after it (`text_clean.title`).
- **Settings file:** edits keep quotes (`common.update_config`, ruamel `preserve_quotes`): an unquoted 14:00 would
  load as a number (YAML 1.1).
- **A video the Studio is playing is open (Windows, 2026-10-27):** served whole, the player kept the file open while
  the page showed it, and Windows refused to delete it: Discard and Make it again failed with an error (#62, #66;
  the case still went to "discarded", so pressing again said it wasn't waiting any more). Now the video is served in
  pieces of 2 MB, each read and closed at once (`api.preview`, `PREVIEW_PIECE`); a file that's still open is deleted
  in the background once it's let go (`animator.remove`, unless a new render took its place); and a case sent back to
  be made again loses its render record too, so an old file can't pass for the new video.
- **Adults only, never "made for kids":** the host is an old professor, photos and clips with children are dropped,
  and the upload always says "not made for kids". Topics about children are off-limits.
- **Disclosure:** a drawn host, real footage, real photos and charts aren't realistic synthetic media, so uploads keep
  `containsSyntheticMedia` false.
- **Off-limits topics** (the Editor's and Writer's rules): elections and voting; wars, attacks, disasters and crimes
  from the last 25 years; health or investment advice; anything sexual; mocking a faith, nation or group.
  Politics only as policy and economics, both sides, and after your OK.
- **Shorts from earlier versions** (the same database) show in the Studio as "Cartoon-host version" (v4), "Cartoon
  version" (v3) or "Cute-animal version": they can still be uploaded as they are (if their video was kept) or
  discarded. The agents never pick them, and the Analyst only learns from v5 cases.
- **Rhubarb missing or failing** falls back to mouth shapes from the loudness of the voice.
- **Gemini quota:** Flash-Lite models first for lists and checks, Flash for writing; quota errors (429) fall through
  to the next model. A case takes 7-8 text requests (Editor 1, Researcher 3, Writer 3, plus a rewrite now and then)
  and 1 voice request (measured on the 2026-10-26 dry runs). A whole case: 6-11 minutes to make (the worldwide trends
  refresh adds ~2.5 minutes every 6 hours; archive film ~2 minutes) and 4-5 minutes to animate.
- **Dropped connections:** Wikimedia sometimes closes a connection without answering (2026-10-26); `_get_json` tries
  again twice before giving up, so a case doesn't fail on one hiccup.
- **YouTube:** uploads have their own quota (100/day by default); comments cost 1 unit per Short a day. Titles and
  descriptions can't contain `<` or `>`; the tools strip them.
- **Interrupted run:** if a run is cut off (crash, PC asleep), its Short stays "making"; after 15 minutes the next
  check puts it back in the queue (or marks it skipped if it had no plan yet).
- **Failed upload:** the Short goes back to the queue and the next check retries it; after 2 failures it's marked
  "failed" with the error saved, and the slot gets a fresh Short on the next try.
- **Case types (12, since 2026-10-26):** dark history, mysteries, business case studies, AI and technology, trending
  news, psychology, mythology and legends, famous people's rise, fall and comeback, science and space, criminal cases,
  history, the economy (`cases.categories` weights). Crime cases only cover settled cases: victims treated with
  respect, proven facts kept apart from allegations.
- **The Reviewer's measurements (calibrated 2026-10-26 on #29-31):** one ffmpeg pass (~2 s) gives loudness (-14.8 LUFS
  typical), true peak (-0.6 to -1.4 dBTP, so only above -0.1 is noted) and black stretches; with the Professor always
  on screen a black shot is only ~89% black, so `blackdetect` uses pic_th 0.85 and pix_th 0.06 (a near-black neon-sign
  clip in #29 was caught at 1.8 s). Whisper hears the final mix with the music at 0.96 match. Gemini's frame look took
  a counting-up number for a wrong one until the prompt said so. A review takes ~45 s.
- **A review names the render it saw** (`render.id`): after the Animator makes a new version, the old verdict no
  longer counts (it once let a remade video through unreviewed). Videos made before reviews existed are made again
  (reusing the Professor's reading when the words haven't changed: no new voice call).
- **Thumbnails:** YouTube takes custom thumbnails only on channels verified by phone (youtube.com/verify); otherwise
  it answers 403 and the Short keeps a frame YouTube picks (the upload still succeeds).
- **Where a Short's thumbnail shows (checked 2026-10-27):** `thumbnails.set` answers 200, but YouTube uses a Short's
  custom thumbnail only in its 16:9 places: YouTube Studio, search on computers, shared-link previews and embeds
  (`maxresdefault.jpg`). We sent the tall cover and it came out small between blurred copies of itself, so the
  Publisher now sends the wide one (`thumb_<id>_wide.jpg`; `publisher.resend_thumbnail(id)` fixes one already up).
  The Shorts tab and feed show a frame YouTube picks (`oar2.jpg`, the same as its middle suggestion `hq2.jpg`, at no
  fixed point of the video). Custom Shorts covers are only for YouTube Partner Program channels (YouTube's blog,
  2026-07-24), added in YouTube Studio on a computer; the Data API has nothing for them. Until then, you can pick any
  frame as the cover in the YouTube app. Once the channel is in the Partner Program, try the tall 9:16 cover
  (`thumb_<id>.jpg`) in YouTube Studio first, then see whether the API puts it on the Shorts tab too. Instagram can't take an
  uploaded cover (only a frame, `thumb_offset`, or an image at a public web address), so the Reel's cover is the frame
  of the thumbnail's shot.
- **Instagram (Meta's docs, checked 2026-10-26):** Graph API v26.0 with Facebook Login (a Page access token; one from
  a long-lived user token doesn't expire); resumable upload to `rupload.facebook.com` with `Authorization: OAuth`,
  `offset` and `file_size` headers; Reels' sound at most 128 kbps; 100 posts a day by API. **Upload in pieces**
  (2026-10-27): every real Short sent in one request (47 and 95 MB, 1-2 minutes on this connection) came back
  `ProcessingFailedError` / "Request processing failed" (retriable: false), the container saying
  `bytes_transferred: 0` and error 1363008 "File not found", while a 0.25 MB test clip went through. Sent in 4 MB
  pieces (`instagram.CHUNK`; each POST at the offset where the last ended; Instagram answers 206 "Partial request"
  until the last, then 200) the same 47 MB file uploaded and processed fine. **All pieces on one kept-open connection**
  (`requests.Session`) **and sent within about a minute** (later the same day). What decides it is how long the
  pieces take: 47 MB in 53 s went through; 59 MB in 61-66 s failed three times; the same 30 MB went through in 33 s
  and failed when spread over 70 s; on one connection (pieces 3.7 s instead of 4.5 s, no new handshake each) #45's
  59 MB went in 55 s, but #46's 67 MB (about 60 s) failed three times. So the Reel copy is made to fit 30 MB (its
  picture's bitrate capped by its length: about 3.5 Mbps for a minute's Short, about 27 s to send here;
  `instagram.REEL_MB`). Even so Instagram drops uploads at its last step, in spells: it answered in 24-31 s when it
  worked and at 33-34 s when it didn't, whatever the size; #46's 28 MB copy went through three times in tests that
  afternoon, then was dropped ten times in a row over the next 90 minutes, and a 14 MB copy sent whole (one request,
  no pieces to put together) was dropped three times out of three, 43.5 s each. A drop is sent again at once to a new
  container (`instagram.UPLOAD_TRIES`, one copy), then the Publisher tries again over about nine hours (10, 20, 40,
  60, 90, 120, 180 minutes apart: `publisher.REEL_WAITS`). **A dropped container can say FINISHED** ("ready to be
  published") with `video_status.uploading_phase` "error", 0 bytes, and processing "error": no video. The ones that
  really worked say uploading "complete" with their byte count; `instagram._processed` takes only those for ready.
  **The link way** (`instagram.send: link`, the Channels page's step 5; off unless you switch it on): Instagram
  fetches the file itself from a temporary public link (`video_url`, Meta's original way to publish a video, with
  no upload server to drop it): `tools/tunnel.py` serves just that file at a random 32-character path from its own
  small server on 127.0.0.1, through Cloudflare's free quick tunnel (`cloudflared`, installed in
  `C:\Program Files (x86)\cloudflared`; no account), only while Instagram processes it; no link -> the video is sent
  instead. Claude Code's safety check stopped Claude from opening that tunnel itself (2026-10-27), so it's yours to
  switch on. (One 28 MB probe lost its connection at the last piece; the real upload sends a piece again after a
  network error.) Tested on containers that were never
  published (one that isn't published expires by itself, and nothing shows on the account). **No edit lists** in the MP4
  (Meta's spec): our renders have one per track (the picture's B-frames, AAC's start), so the Reel copy
  (`instagram._for_reels`) encodes the picture again without B-frames (`-bf 0`, up to 8 Mbps), the sound at
  128 kbps, with `-use_editlist 0` (about a minute a Short). Only dropping the edit lists while copying the
  picture made it start 0.083 s after the sound, visible on his lips, hence the re-encode. Deleting a post: `DELETE /<IG_MEDIA_ID>` (Reels, single posts,
  Stories and whole carousels; Facebook Login only; `instagram_basic` + `instagram_manage_contents`; checked
  2026-10-27). The reference shows a POST in one place and DELETE in its example; `instagram.delete` sends DELETE.
  Not yet tried on a real account: if it fails, the error is shown and the Reel stays.
- **His drawings** (`tools/host_prep.py`, 2026-10-26): the sheet's Headshot, upscaled 2x by waifu2x's swin_unet
  "art" model (its author's ONNX file, SHA-256 checked), cut out by a flood fill of the paper stopped by his ink lines
  (paper colour tolerance 14 in Lab, colour counted double), the biggest piece kept. His mouth: the jaw and beard below
  the moustache drop (a warp whose gap is exactly the opening), the opening in the colours of the sheet's speaking
  drawing. His eyelids: a smooth gradient fitted to the clean skin around each eye (inpainting smeared the lash line
  in), and a tapered lid line. The places were measured on the upscaled drawing; a new sheet needs them measured again.
- **What comes from outside is untrusted (security review, 2026-10-28).** Web pages, news feeds, trends, viewers'
  comments and the words in photos and frames are written by strangers, so:
  - an article is read only from an ordinary public site (`research_fetch.article`): each connection is checked once
    it's made, before anything is sent, so a link (or a redirect, or a name) that leads to this computer, the home
    network or a cloud's own addresses (169.254.169.254) reads nothing; at most 5 MB, for at most 45 s. Photos come
    only from `upload.wikimedia.org`; a feed that declares XML entities is skipped;
  - ffmpeg only opens an archive film's address if it's https at the Internet Archive or NASA, with web protocols only
    (`footage._film_url`, `WEB_ONLY`), and a clip's file is named from its key with nothing but letters, digits, dots,
    dashes and underscores; a stock clip over 400 MB isn't downloaded;
  - a description links a source only if its address is an ordinary page at a named site (no bare IP address, login,
    odd port or link shortener: `text_clean.linkable`), and web addresses are taken out of the Writer's title and
    description and of the pages' titles (`text_clean.no_links`);
  - every request to Gemini ends with `llm.MATERIAL`: what it quotes from outside is material, never instructions;
  - downloaded programs and models run only if they're exactly the published files: Rhubarb and cloudflared by
    SHA-256 (`lipsync.SHA256`, `tunnel.SHA256`, cloudflared pinned to one version), waifu2x by SHA-256, the depth
    and whisper models by their Hugging Face revision.
  A new source or download gets the same treatment.
- **Reels in the cloud (built 2026-10-28, your option A).** On GitHub's machine, wiped after each run, nothing
  stays for a Reel's slot, and Instagram's API can't schedule a Reel. So:
  - a Reel whose slot comes while the morning run that made it is still going is posted by that run, from a
    thread beside it (`jobs._reels_beside`, every minute, only Reels whose video is on its machine);
  - at the run's end, `python tools/jobs.py keep` encrypts the videos of its Reels still waiting (AES-256 with
    openssl, key `REELS_KEY`: anyone signed in to GitHub can download a public repository's run files) and the
    workflow stores them with the run for 3 days (`shorts-<run id>`). The Reel records the run as `kept_in`;
  - `.github/workflows/reels.yml` runs 5 and 35 minutes after each slot (UTC crons; the suite checks they
    match `schedule` in `config/channel.yaml`, so change both together), fetches each due Reel's video from
    its run (`kept.fetch`: `gh run download`, then decrypt) and posts it as before, staying up to 40 minutes
    for retries and for YouTube's lag;
  - a Reel whose run is still going is left to that run (no try counted). One whose run kept nothing fails
    with that reason and a Telegram alert. GitHub failing to hand the video over counts as a try (REEL_WAITS);
  - with the database in the cloud, this computer's dashboard only shows Reels: no Post now for a Reel kept in
    the cloud, and no remake (`publisher._made_here`). Reels pending from before the move have no video in
    the cloud and fail: move after the day's Reels are up.
  The way back: Reels off on the Channels page, or disable the Reels workflow on GitHub.
- **The link way's first real tries were refused (2026-10-28, #49 at 14:00 IST):** Instagram answered 400
  "Invalid parameter (code 100)" when given the temporary link (three automatic tries and your Post now). The
  error didn't say why, because `_check` kept only the message and code: it now adds Instagram's subcode and
  its own explanation (`error_user_title` / `error_user_msg`). And a refusal no longer fails the try: the video is
  then sent the upload way at once (`_by_link`), as when no link can be made, and why is kept on the Reel
  (`link_refused`). The next refusal said why: "video_status is not a valid parameter for the media type"
  (subcode 2207065). Instagram had taken the link; our own check while it processed asked for `video_status`,
  which exists only for a video sent to it (the check added on 2026-10-27 against the FINISHED-but-empty
  trap). Now `_processed(..., uploaded=False)` asks a fetched video for `status_code,status` only.
