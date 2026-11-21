# Produce the day's story (the motivation series)

## Objective
One 3-4 minute motivational story a day, every day a new storyline (your redirect, 2026-11-16): written by **your own
script-writer prompt** (sealed word for word in `prompts/script_writer.txt.enc`: six stages, a new character, incident,
place and change every time), briefed each day the way your examples do it, and pictured from it alone: its own
places, its own people, a shot for every moment, drawn in code in your silhouette look.

**No narrator (your choice, 2026-11-19):** the film is silent. Its people talk to each other in speech bubbles, he
thinks in thought clouds when he's alone, a shout is a spiky burst, and a cloud can hold a small picture. Every bubble
stays long enough for an average person to read it. The closing line stays the **end quote** on screen. The habit the
story is about is **shown big**, like a cartoon (exaggerated eyes, marks round the head, actions, things, effects), and
code makes sure every film does it.

It's posted on YouTube at `series.post_at`; its **short version** (the same story whole in under a minute, with its own
shorter bubbles) follows as a YouTube Short `series.short_after_hours` later, and as an Instagram Reel when Instagram
is on. Everything runs on free tiers.

Settings: `series:` in `config/channel.yaml` (Settings page S2.1: the topics, the minutes, the times). Earlier versions
of the channel live only in git (tags `v5-before-motivation`, `v6-motivation-series`). Stories #3 and #4 (the fixed
eight-part arc, before the redirect) are set aside: they stay in the Studio and are never posted. Stories #5-#7 were
narrated; #8 is the first silent one.

## The six agents
| Agent | What it does | Code |
|---|---|---|
| 1 Theme | Writes the day's **brief** for your writer, like your examples: "Write a story about LUST. <direction>" (a weakness one day, a virtue the next, from `series.themes`, never one used within `repeat_after_days`), or about one day in four "Choose a topic yourself. <direction>". The direction is one or two sentences, new every day, never close to a recent one. Your own brief from the Themes page goes first, word for word. One Gemini call (retried when too like an earlier one). | `agents/theme.py` |
| 2 Story | **The story:** your writer's prompt is the whole system prompt; the brief is the message, with the channel's facts under it (he's a man, always drawn the same way, so his looks are never described; everyone is an adult; about 430-490 words; the film is shown without a narrator, its people speaking and thinking in bubbles, so give them real moments to speak and think; the recent stories, so this one is new). Gemini answers in your output format (Title, Central Theme, Core Message, Full Script, Final Closing Line). Code checks: 380-560 words, a new title of at most 70 characters, adults only, nothing explicit, no gore, weapons or self-harm, no real brands (3 tries). **The moments** (`write_moments`, a second call with the channel's own prompt, not yours): 28-45 moments across the six stages (at least 2 in each), each with what we see, who is in it and 0-2 bubbles (say, think, shout, or a picture from the library); at most 12 words a bubble (4 under a picture), at least 18 bubbles, 95-195 seconds of reading in all, at most 8 people, the closing line never a bubble. Code checks it (the speakers among the moment's people, adults only, nothing explicit, no brands; 3 tries). Later, the first time it's needed, the **short version** (`write_short`). | `agents/story.py` |
| 3 Animator | First the **storyboard** (`agents/storyboard.py`, one Gemini call, up to 3): from the moments, your look text word for word and the library, Gemini designs this story's places (6-14, each a kind of place with its look, things, light, weather and effects), the people around him (the moments' people, by their ids, each with a look), a shot for every moment in order plus 2-8 quiet ones (its stage, place, what he does where and with what eyes and marks, who else is there, a phone's screen, the framing: wide, medium, close or a detail of a thing, the camera's move, an event, what the picture shows), the habit it shows big, the shot where he realizes (the music lifts there), six chapter names, the thumbnail's shot and words (a white lead-in and a yellow punch), the description and tags. Code checks it and repairs what it can (below). Then every shot is timed from its bubbles (below) and the film is drawn in code (`tools/silhouette_board.py`: every place built from the library; `tools/silhouette_bubbles.py`: the bubbles), with the music, the thumbnail and a still of every scene; then the **short version** (drawn upright from the film's shots with its own bubbles). | `agents/storyboard.py`, `agents/animator.py`, `tools/silhouette_board.py`, `tools/silhouette_bubbles.py`, `tools/story_film.py`, `tools/silhouette_render.py`, `tools/thumbnail.py` |
| 4 Reviewer | Size, length, loudness, silence; the bubbles measured (at least 12, each on screen its reading time, none past the end); the same for the short version. One Gemini look at up to 24 frames: (nearly) every scene against what its shot should show and the closing line, and 4 of the short version's, against your look, the bubbles (one over a face, cut off or pointing at the wrong person) and the habit shown big in his fall. "Unsuitable" means sexual, gory or a child (a story's fire, an ambulance, a glass of wine, or desire's symbols, hearts and lips and a censored phone screen, are fine). A picture problem goes back to Agent 3, who draws that scene again with a change (a lighter light, him alone, a closer framing, a calmer camera); a problem only the short version has is fixed in it alone; after 2 rounds the story is made again, and from the third time Agent 2 writes it again. Recurring picture problems become lessons for the storyboard. | `agents/reviewer.py` |
| 5 Publisher | The film into its slot (Film & Animation, the storyboard's description, chapters, "Animated in code, frame by frame: no AI pictures, no AI voice", the music's credit), its thumbnail, then the short version as a Short a few hours later (#shorts, the film's link); the Reel = the short version. | `agents/publisher.py` |
| 6 Analyst | Daily numbers; long videos ranked by watch time; weekly lessons for the other five. A silent film's "voice" group is "none: told in bubbles", so the narrated films and the silent ones can be compared. | `agents/analyst.py` |

The autopilot's run (`python tools/jobs.py morning`) writes, storyboards, makes and uploads the next story
(`jobs.make_story`: brief, story and moments, storyboard). The dashboard's "Make the 17:30 video now" does the same at
once. A story written before 2026-11-19 (for the narrator) gets its moments and a new storyboard first, when its film is
made (`animator.animate`).

**When (since 2026-11-19, your choice):** the stories are kept two days ahead: when a story goes public (17:30), the
slot two days later is due (`slots.opens`, `schedule.ahead: true` and `schedule.stories_ahead: 2` in
`config/channel.yaml`; Settings "Next story" and "Stories ready ahead"), so tomorrow's story is always made and the next
one is on its way: one that gets stuck (Gemini, GitHub) has a whole spare day before a slot could go empty (the first
day makes the extra one; then one a day). A story is started only when YouTube has room for its two uploads and only
in **the hours stories are made in** (`jobs.story_window`, your choice of 2026-11-20: from Gemini's free allowance
renewing, midnight in California = 13:30 IST in winter, 12:30 in summer, until midnight IST), so Gemini's stronger
models still have the day's requests (20 each) and write it. Outside them a due story waits for the renewal, unless
waiting would leave its slot empty (`jobs.cant_wait`: less than `STORY_TIME` left); a story already made and passed
uploads at any hour. The loop on this computer makes waiting films only in those hours too, and the dashboard's make
buttons ask before starting a story outside them. When what it waits for is there while the run still has time for the
story (`jobs.quota_ready_at`, `STORY_TIME` 2 h within the run's 5 h 40 min), the run waits for it; otherwise it ends and
a later check starts it. GitHub checks every hour at :35 IST (`.github/workflows/morning.yml`,
the workflow "Autopilot": `python tools/jobs.py due`, with only the dashboard's packages; it ends in about a minute when
there's nothing to do), but **GitHub starts this repo's scheduled runs 50-65 minutes late** (measured 2026-11-18/19 on
both workflows): the check starts a run up to 75 minutes before what it waits for is there (`jobs.DUE_EARLY`), e.g. at 12:35 for the
13:30 renewal. Its verdict is
kept (note `autopilot:check`) and the Schedule page shows it ("Being made", "Waits for free quotas" or "Up next · at
the next check", with the reason); the bar at the top of the dashboard follows a run on GitHub step by step
(`jobs.LiveSteps`, note `run:live`), and the Studio shows its story from the moment its script is written (plan
`draft`). Gemini's text quota can't be counted ahead: if it's out, the run stops and waits. With the switch off, the
morning run makes the day's story from `schedule.make_at` (07:00), as before.

On this computer: `python tools/jobs.py prepare` writes and storyboards a story; `python tools/jobs.py publish --dry-run
--newest` makes and reviews it without uploading. Start the dashboard with `python app.py` (http://localhost:8000): it
never runs work on old code and restarts itself with new code when idle.

## The library (drawn in code)
- Your look text, word for word: `prompts/look_silhouette.txt.enc`. The reference GIF stays in `.tmp/reference/` and
  never goes into git (the repo is public).
- The words Gemini designs with: `tools/silhouette_words.py` (plain data). The places: `tools/silhouette_scene.py`
  (a room, a hall, a corridor, a city street, a street of houses, a bridge, nature: hills, mountains, sea, field,
  forest, lake; inside a car, a bus or a train with the world sliding past), laid out from their things
  (`tools/silhouette_props.py`, each with the spots where people stand, sit or lie by it); what people do
  (`tools/silhouette_actions.py`, a hug, a handshake and an argument for two); effects (`tools/silhouette_fx.py`).
  People are made from the look's parts (`silhouette.look_from`); he is always the teal-hoodie man.
- **The habit, shown big (2026-11-19):** exaggerated eyes (hearts, dollar signs, spirals, droopy, furious, side-eye,
  smug, sobbing, terrified, on fire: `silhouette.Eyes`), 18 marks round a head (steam, a throbbing vein, sweat, drool,
  Zzz, hearts, $, a rain cloud, flies, dizzy stars, a jolt, trembling, "?", "!", sparkles, auras, notification dots:
  `tools/silhouette_marks.py`), 31 exaggerated actions (`tools/silhouette_habits.py`), 17 things that overdo a place
  (a tower of dishes, pizza boxes, a calendar of red X's, stacks of money...), 9 effects (the room flushing red, a pink
  phone glow, the colours draining, time racing by, the camera shaking, tunnel vision, notifications, creeping
  shadows), a phone seen face-on with 8 screens, and 66 small pictures for the bubbles (`tools/silhouette_icons.py`).
  **None of them belongs to a topic** (your words, 2026-11-19: lust, anger and laziness were examples, never the
  system's centre): the storyboard names the story's own habit and picks what fits; `silhouette_words.IDEAS` only
  offers ideas for some topics, and a topic outside the list works the same way. Desire stays symbolic: hearts, lips,
  heart eyes, a censored phone screen ("18+" over pink squares); never a body, and never in a thumbnail.
- **The bubbles** (`tools/silhouette_bubbles.py`): a cream fill (#F4EDE2), the thin coral rim, plum letters in Rubik;
  42 px letters in the film, 56 px in the upright short version; at most 12 words and 3 rows. Each sits above its
  speaker's head on the side with room, inside the picture and the letterbox bars, off every face, with its tail to the
  speaker; it pops in and fades out, and follows the head.
- Where an action happens: `silhouette_board.where` puts each person on the right spot of the thing the storyboard
  names (the bed to sleep in, its edge to sit on, the desk's chair, the stove) and two people at one thing on its two
  places. A wide shot slides along a big room to keep the people in it.
- **Framing is measured before a shot is drawn** (`silhouette_board.frame_problems`, since 2026-11-19, after films
  #5-#7 cut off heads, arms and the things in use): every head (with its hair and marks) inside the picture and out of
  the bars, no two heads overlapping, the thing in use in view. A close or medium shot that can't keep them is widened
  (`_fit`); one still failing falls back to a wide shot.
- The catalog of everything: `python tools/silhouette_catalog.py` (into `.tmp/library/index.html`, a few minutes; its
  "Marks" and "Ideas" sections show the habit pieces). A story's storyboard as stills:
  `python tools/silhouette_board.py story.json --out .tmp/storyboard`.
- Every place is built from the library. The 12 ready-made sets of the first look (desk_room, bedroom, kitchen,
  hallway, street, hospital, office, cafe, rooftop, park, bright_office, new_flat) aren't offered to the storyboard
  any more (your call, 2026-11-17: story #6, storyboarded by Flash-Lite while the bigger models were busy, was drawn
  entirely in them and looked like the old films). An answer that still names one gets that place built from the
  library instead (`storyboard.SET_PLACES`); their code stays only to draw stories made before.
- What a story needs that the library lacks: the nearest thing is drawn, and it's listed (the Studio's "Missing
  pieces", most wanted first). That list is what's added to the library next.
- Thumbnail (`tools/thumbnail.py`, from the style test): him big on the left in the chosen moment, outlined like a
  sticker with the coral rim and his mood's marks, the story's own place dimmed behind him, the white lead-in over the
  big yellow punch with a dry-brush underline, and a red arrow from the words to him. You can change both lines and
  the scene in the Studio.

## The storyboard's checks (agents/storyboard.py `check`)
- Every moment has its one shot, in order, with its bubbles; every stage has shots and none goes back. (Code's
  repair: a moment's second shot loses it; a moment without one gets a copy of the shot before it.)
- Whoever has a bubble is in the shot (code puts them in, standing, when the answer left them out); the moments'
  people are all in the cast, by their ids.
- **The habit shown big:** at least 6 shots of his fall (the hook, the incident, the collapse, rock bottom) with
  exaggerated eyes, marks, a habit action, thing or effect, or a phone screen; a virtue story 4 before his realization
  and 2 after it (the virtue). When the answer still falls short after its tries, code exaggerates what the shots
  already show (sad eyes become sobbing with a rain cloud, angry ones furious with steam, tired ones droopy with Zzz...)
  or reuses the story's own choices. A piece isn't used two stories in a row when there are others.
- Places 6-14 (fewer than 5 goes back); no place holds more than about a third of the shots (45% goes back); each
  is a kind the library has, with its things (an alias or a misspelling is fixed; anything else is listed missing).
- Every action has somewhere to happen in its place (typing needs a desk, cooking a stove): else it goes back.
- People: adults only (a hard rule: the storyboard is refused), never teal (his colour), the hero never in the cast;
  a hug, a handshake or an argument names the other one.
- A detail shot names a thing of its place; at most 4 labels; 2-8 quiet shots; the realization in rock bottom or the
  first of the transformation; six chapter names; the thumbnail's words (white 1-4, yellow 1-3); a description.
- Different from the recent stories: a place too like a recent one (the same kind and things) gets other colours and
  its things the other way round.
- Nothing explicit, no gore, weapons or self-harm, no brands, in anything it says, the bubbles included (a hard rule).

## The timing (tools/story_film.py `timeline`)
- **The reading rule** (`silhouette_words.read_seconds`): 1 second to find a bubble, then 2.5 words a second; at least
  2.5 seconds (12 words: 5.8 s). A picture alone 2.5 s; with words, 1 s more. Slower than subtitles on purpose: the
  viewer also looks at the picture.
- **A conversation:** each bubble comes when the one before it has been read; the earlier one stays, dimmed, until its
  reply is read, so at most two are on screen.
- A shot with bubbles lasts 0.5 s before the first, the bubbles, and 0.8 s after the last is read. **No title in the
  picture** (your choice, 2026-11-20): the film begins straight with the story, its first bubble 1 s after the picture
  fades in (`story_film.OPENING`). The last shot shows the closing line after its bubbles, held its reading time and
  2.5 s more.
- The film is kept inside `series.minutes` (3-4) by the shots without bubbles, each 2.5-8 s.

## The sound
- Music: one of the full-length tracks in `assets/music/full/` (credited in the description), **low from the first
  second** (-9 dB), lifting over 6 s at his realization, then swelling to the end. Nothing to leave room for: the
  pictures and the bubbles need its mood.
- A soft, round pop as each bubble comes (never a click).
- Beds by kind of place (a room's quiet, a street at night, birds by day in nature, crickets at dusk, a crowd in a hall
  with an audience), rain, steps for walking, typing, running, knocking, a page, the lamp's switch, the phone, a heart
  monitor's beeps.
- Loudness: -17 LUFS (`film_sound.LUFS_TARGET`, a calm wordless film); the Reviewer measures it.

## The short version (Shorts and Reels)
- Agent 2 picks 8-12 of the film's shots (in its order, at least one from every stage, ending on its last) and gives
  them shorter bubbles: at most 9 words each, 20-38 s of reading in all.
- It's timed before anything is drawn (`story_film.short_timeline`: 45-58 s, never 59.5 s or more); one that would run
  a minute or more is written again shorter, once.
- Drawn upright (1080x1920) from the film's shots, beginning straight with the story (no title in the picture; the
  first shot's bubble is the hook), the closing line at its end. The Reel's cover is 2 s in (the hook's bubble in).

## Free limits (one story a day)
| | Per story | Free a day |
|---|---|---|
| Gemini text | brief 1, story 1-3, moments 1-3, storyboard 1-3, short version 1, look 1 | the careful models' share is small (see below) |
| Gemini voice | none (no narrator since 2026-11-19) | |
| Drawing | none: everything is drawn in code | |
| YouTube uploads | 2 (film + its short version) | ~10 per 24 h |

Learned 2026-11-17: Gemini's careful models (`gemini-3.6-flash`, `gemini-3.5-flash`), which the writer, the moments and
the storyboard ask first, answered "429 quota" after about one storyboard each, because the script tests of the evening
before fell in the same Gemini day (it renews at 13:30 IST). Then the lighter models answer, and their storyboards are
weaker (half a film in one room, fewer people). Don't spend the careful models' share on tests before a real run;
`llm.passed_over` and the storyboard's log say which model answered and why the others didn't.

Learned 2026-11-17 afternoon: right after the day renewed, `gemini-3.6-flash` and `gemini-3.5-flash` answered "503
high demand" for minutes, Flash-Lite answered instead, and drew story #6 entirely in the old ready-made sets. Now the
storyboard and the moments ask `llm.STRONG_MODELS` (3.6-flash, 3.5-flash, then 3.8-flash) first and wait 1, 2 and 3
minutes for them while they're only busy (`generate_json(strong=True)`); Flash-Lite answers only when they can't today.
A model that says its free requests for the day are used up (429 with a "PerDay" quota; Google says when they renew)
isn't asked again until then, in that run.

Learned 2026-11-20: a story started from the dashboard at 02:18 IST sat for half an hour on "Gemini's stronger models
are busy": 3.6-flash (and 3.5-flash, which shares its allowance) had used up its 20 free requests for the day, and
3.8-flash was answering a one-word request in 42 s, so the long requests timed out and were waited for again and again.
Hence the hours stories are made in (above).

Learned 2026-11-21: inside those hours it happened again (the first silent run in the cloud): 3.6-flash ran past the
storyboard's 5-minute limit (504 "Deadline expired"), and each such model was asked twice, then waited for (60/120/180 s)
and asked again, over an hour for one storyboard. Now (`tools/llm.py`, `slow`) a model past the time limit (504, or our
own timeout) isn't asked again for that request, nor waited for: the next model answers at once. Busy ones (429 for the
minute, 503 overloaded) are still waited for, as before.

Learned 2026-11-19: films #5-#7 passed the Reviewer (#5 got 10/10) with heads cut off by the frame, hands knotted into
blobs, hair as loose discs, his head grey under a lamp and giant tree blobs over the sky. Gemini's look doesn't catch
framing reliably: the framing is now measured in code before a shot is drawn (above), and the hair, the hug, the
clasped hands, the bowed and lying poses, the lamp's cone and the trees were redrawn.

## When something fails
- Every Gemini model busy (overloaded, the minute's quota, timing out): the writer, the moments, the storyboard, the
  short version and the Reviewer's look wait 1 minute and ask again, then 2 (`llm.generate_json(patient=True)`); all
  of them out of the day's quota: the run waits (`jobs._must_wait`). The moments and the storyboard first wait up to
  6 minutes for the stronger models (above).
- The moments or the storyboard keep a problem after 3 tries: code's repairs are kept and the story goes on, unless
  it breaks a hard rule (adults only, nothing explicit, no gore): then another brief is written (3 tries).
- The Reviewer turns it down after 2 rounds: it's made again by itself; from the third time Agent 2 writes it again.
- The short version can't be written or still runs a minute or more after one rewrite: the making is tried again later.
- A bubble's words can be changed in the dashboard (Stories page, "Edit the words") before the film is made; the film
  is then made again with them.

## Known weak spots (2026-11-19)
- On this laptop on battery, Windows throttles drawing hard: plug it in before making a film here.
- The library can't show everything: the nearest thing stands in and the gap is listed.
- People are drawn side-on only (a mirror shows him facing back); faces are eyes only, so poses, props, the marks and
  the bubbles carry the acting.

## Going back to the narrator
The narrator's code stays (`tools/narrator.py`, `tools/narration.py`, `tools/voiceprint.py`, his sample in
`assets/voices/`; the Reviewer still listens to a narrated film). The settings he was read with (Algieba on
`gemini-3.8-flash-lite-tts`, 2.3 words a second, directions kept low, a too-high reading brought down) and the
lessons of 2026-11-18 (story #7 stuck on one line) are in git history: this file before 2026-11-19.
