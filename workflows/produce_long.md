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

**What goes out (your plan of 2026-11-23, `tools/slots.py`):** two **Shorts** a night for three nights, at 21:00 and
03:00 IST (the 03:00 one after midnight, that same night), each a story of its own told in 2-3 minutes, drawn upright,
posted as a YouTube Short and, when Instagram is on, as a Reel at the same time; then a night with one **long story**
(3-4 minutes) at 21:00, on YouTube only; then round again (`series.cycle` in `config/channel.yaml`: its start date, the
nights of Shorts, the times). Every night before the start date has one long story (the stories made before the plan).
The short version of each film (the whole story in under a minute, 2026-11-16 to 11-23) isn't made any more.
Everything runs on free tiers.

Settings: `series:` in `config/channel.yaml` (Settings page S2.1: the topics, the minutes, the times). Earlier versions
of the channel live only in git (tags `v5-before-motivation`, `v6-motivation-series`). Stories #3 and #4 (the fixed
eight-part arc, before the redirect) are set aside: they stay in the Studio and are never posted. Stories #5-#7 were
narrated; #8 is the first silent one.

## The six agents
| Agent | What it does | Code |
|---|---|---|
| 1 Theme | Writes the day's **brief** for your writer, like your examples: "Write a story about LUST. <direction>" (a weakness one day, a virtue the next, from `series.themes`, never one used within `repeat_after_days`), or about one day in four "Choose a topic yourself. <direction>". The direction is one or two sentences, new every day, never close to a recent one. Your own brief from the Themes page goes first, word for word. One Gemini call (retried when too like an earlier one). | `agents/theme.py` |
| 2 Story | **The story:** your writer's prompt is the whole system prompt; the brief is the message, with the channel's facts under it (he's a man, always drawn the same way, so his looks are never described; everyone is an adult; about 430-490 words, a Short 280-340; the film is shown without a narrator, its people speaking and thinking in bubbles, so give them real moments to speak and think; the recent stories, so this one is new). Gemini answers in your output format (Title, Central Theme, Core Message, Full Script, Final Closing Line). Code checks: 380-560 words (a Short 230-400), a new title of at most 70 characters, adults only, nothing explicit, no gore, weapons or self-harm, no real brands (3 tries). **The moments** (`write_moments`, a second call with the channel's own prompt, not yours): 28-45 moments across the six stages (at least 2 in each), each with what we see, who is in it and 0-2 bubbles (say, think, shout, or a picture from the library); at most 12 words a bubble (4 under a picture), at least 18 bubbles, 95-195 seconds of reading in all (a Short: 18-28 moments, at least 12 bubbles, 70-115 s), at most 8 people, the closing line never a bubble. Code checks it (the speakers among the moment's people, adults only, nothing explicit, no brands; 3 tries). (Until 2026-11-23 the **short version** was written here too: `write_short`, kept for going back.) | `agents/story.py` |
| 3 Animator | First the **storyboard** (`agents/storyboard.py`, one Gemini call, up to 3): from the moments, your look text word for word and the library, Gemini designs this story's places (6-14, a Short 4-9, each a kind of place with its look, things, light, weather and effects), the people around him (the moments' people, by their ids, each with a look), a shot for every moment in order plus 2-8 quiet ones (its stage, place, what he does where and with what eyes and marks, who else is there, a phone's screen, the framing: wide, medium, close or a detail of a thing, the camera's move, an event, what the picture shows), the habit it shows big, the shot where he realizes (the music lifts there), six chapter names, the thumbnail's shot and words (a white lead-in and a yellow punch), the description and tags. Code checks it and repairs what it can (below). Then every shot is timed from its bubbles (below) and the film is drawn in code (`tools/silhouette_board.py`: every place built from the library; `tools/silhouette_bubbles.py`: the bubbles), with the music and a still of every scene: a long story wide (1920x1080) with its thumbnail; a Short upright (1080x1920) at 2-3 minutes, never 3:00 or more (refused before it's drawn), with no thumbnail. | `agents/storyboard.py`, `agents/animator.py`, `tools/silhouette_board.py`, `tools/silhouette_bubbles.py`, `tools/story_film.py`, `tools/silhouette_render.py`, `tools/thumbnail.py` |
| 4 Reviewer | Size and length by its form (a long story 1920x1080 and 3-4 minutes; a Short 1080x1920, 2-3 minutes and under 3:00), loudness, silence; the bubbles measured (at least 12, each on screen its reading time, none past the end); a story made before the plan with its short version: that too. One Gemini look at up to 24 frames: (nearly) every scene against what its shot should show and the closing line, against your look, the bubbles (one over a face, cut off or pointing at the wrong person) and the habit shown big in his fall. "Unsuitable" means sexual, gory or a child (a story's fire, an ambulance, a glass of wine, or desire's symbols, hearts and lips and a censored phone screen, are fine). A picture problem goes back to Agent 3, who draws that scene again with a change (a lighter light, him alone, a closer framing, a calmer camera); a problem only the short version has is fixed in it alone; after 2 rounds the story is made again, and from the third time Agent 2 writes it again. Recurring picture problems become lessons for the storyboard. | `agents/reviewer.py` |
| 5 Publisher | Each video into its slot: a long story as Film & Animation (the storyboard's description, chapters, "Animated in code, frame by frame: no AI pictures, no AI voice", the music's credit) with its thumbnail; a Short with #shorts, no chapters and no thumbnail, and its Reel on Instagram at the same minute (Instagram can't schedule: the Reels workflow posts it within about an hour). | `agents/publisher.py` |
| 6 Analyst | Daily numbers; long videos ranked by watch time; weekly lessons for the other five. A silent film's "voice" group is "none: told in bubbles", so the narrated films and the silent ones can be compared. | `agents/analyst.py` |

The autopilot's run (`python tools/jobs.py morning`) writes, storyboards, makes and uploads the next story
(`jobs.make_story`: brief, story and moments, storyboard). The dashboard's "Make the 21:00 video now" does the same at
once, for the next open slot (with a story of its form). A story written before 2026-11-19 (for the narrator) gets its moments and a new storyboard first, when its film is
made (`animator.animate`).

**When (since 2026-11-19, your choice; counted in videos since 2026-11-23):** about two days of videos are kept
ahead: when a video goes public, the slot four videos after it is due (`slots.opens`, `schedule.ahead: true` and
`schedule.stories_ahead: 4` in `config/channel.yaml`; Settings "Next story" and "Videos ready ahead"), and it's made
with a story of that slot's form (a Short or a long story), so one that gets stuck (Gemini, GitHub) has time before its
slot could go empty. A story is started only when YouTube has room for its upload and only
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
  (a tower of dishes, pizza boxes, a calendar of red X's, stacks of money...), 7 effects (the room flushing red, a pink
  phone glow, a sickly green tint, time racing by, the camera shaking, tunnel vision, notifications; the colours
  draining was dropped on 2026-11-24 because you saw the pictures go grey instead of their real colours, creeping
  shadows on 2026-11-21), a phone seen face-on with 8 screens, and 66 small pictures for the bubbles (`tools/silhouette_icons.py`).
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

## What gets made when: the line of turns (since 2026-11-24)
- Every video is made for a turn. The turns in posting order (`jobs.line`; the Studio's "The line" and the Schedule
  page show the same) each take the oldest written story of their own form, or one written for them: a Short is only
  ever written for a Short's turn, the long story for the long story's.
- The autopilot starts a turn's story when the turn opens (`slots.opens`: when the video `stories_ahead` turns before
  it goes public). "Write the next Short" (`jobs.prepare`) writes for the first turn with no story at all
  (`jobs.next_to_make`), in its form; with every turn of the next 12 days covered it writes nothing.
- A written story no turn in view needs waits in the Studio's "Later" tab for the next turn of its form.

## The Shorts (since 2026-11-23)
- A Short is a story of its own: its own brief, script (your prompt; the facts under the brief ask for 280-340 words, a
  2-3 minute short film), moments (18-28, at least 12 bubbles, 70-115 s of reading) and storyboard (4-9 places, the
  habit big in at least 4 shots of his fall; it's told the film is upright).
- Timed to 2-3 minutes (`story_film.short_bounds`: its quiet shots fitted to end by 2:52); one that would run 2:58 or
  more is refused before anything is drawn (YouTube takes 3:00 or more as an ordinary video, not a Short).
- Drawn upright (1080x1920), beginning straight with the story, the closing line at its end. No thumbnail; the Reel's
  cover is 2 s in.
- A Short over a minute that gets a Content ID claim is blocked by YouTube; the music is Kevin MacLeod's (not
  registered for claims), so it should be rare.
- The short version of a film (2026-11-16 to 11-23: the whole story in under a minute, drawn from the film's shots)
  isn't made any more; its code stays for going back (`story.write_short`, `animator.make_short`).
- Everything whole inside the upright frame (2026-11-24, #33: a bubble ran 283 px off the side, bodies were cut, the
  closing line lay over him). Framing made for a wide frame left "room before him", which put his head a third of the
  way in and cut off his back. So in an upright frame:
  - a medium or close shot centres whoever it shows, their whole figure across (head, body, arms:
    `silhouette_board.sights` "figure");
  - a closer framing that still cuts a body by the side is framed wider;
  - a bubble is kept inside the frame on every frame (one following a moving head stops, whole, at the edge;
    `silhouette_bubbles._within`) and keeps off the shot's label;
  - the notification cards stay whole;
  - the closing line goes where nobody is (`silhouette_render.closing_place`; a soft dark band behind it when it
    can't).

  The wide film is unchanged: every shot of #15 and #16 frames exactly as before. To check a Short, measure every shot
  as the film draws it (bubbles past the edge, bodies cut by the side, the closing line over someone) before trusting
  a contact sheet: a still taken in mid-shot hides a bubble that drifted.

## A long story's title and thumbnail (2026-11-24)
- **Title** (yours): its topic in capitals, then " | An animated short film", e.g. "PROCRASTINATION | An animated
  short film" (`story.youtube_title`).
  - The topic comes from the brief.
  - When the brief left the topic to the script writer, it's the first part of the central theme ("Harsh Gossip and
    Kindness": "HARSH GOSSIP").
  - In the Studio, a long story's title box sets the topic part.
  - A Short keeps its own title.
- **Thumbnail**, from your reference "ARE YOU BURNT OUT?". The left changes with the video: him in the chosen shot
  doing what he does there; where he sits in the film he sits here too, at a desk at its glowing screen. The right is
  always written the same way:
  - the white lead-in on one line;
  - the yellow punch big on two lines;
  - every line ending at the same right edge;
  - a brush stroke under the last line, rising;
  - the red arrow hooking from that line down to him.

  The storyboard writes the words to fit: lead 1-3 words (18 letters at most), punch 1-3 words (16 at most). A longer
  line is drawn smaller, never laid out differently.

## Agent 3, Visuals: the pictures for each script (since 2026-11-24, your plan)
- **The agents:**
  1. Theme
  2. Story (your script writer, and the bubbles)
  3. **Visuals**
  4. Animator
  5. Reviewer
  6. Publisher
  7. Analyst
- **Where it sits:** `jobs.make_story` hands each written script to `agents/visuals.py`.
- **Step 1, the storyboard** (`agents/storyboard.py`, unchanged): places, people, a shot for every moment, the habit, the
  thumbnail. Everything the library has is reused.
- **Step 2, what the library lacks.** At most 3 new visuals a story (`MOST_NEW`), always as silhouettes (your rule):
  - **Which wishes:**
    - a thing the storyboard listed missing (`"glue (wanted in shop_front)"`);
    - a picture a bubble wished for. The bubble step may now say `wish` when no picture fits; it still picks the
      closest.
  - **The design:** Gemini designs it as a recipe (`tools/visual_recipes.py`): data, never code. It can only be solid
    shapes (box, shape, bar, circle, oval) in the silhouette tones the library's things are drawn in. Paper or a
    screen's glow only for a small part. No text, outline or gradient option exists.
  - **A thing** stands on a table or shelf (small), on the floor by the wall (floor_small) or hangs on the wall. Never
    furniture: that would move where people stand.
  - **A picture** is a dark pictogram with at most one accent colour.
  - **The checks:**
    - code checks the recipe;
    - code checks its drawing: mostly dark, solid, not a line drawing (a 2-px shrink must leave its middle);
    - Gemini looks at it beside three of the library's own silhouettes: the same style, and clearly what it should
      be.
  - **If it fails:** one redesign with what was wrong. If it still fails, the closest is used, as before.
  - **Cost:** 2-4 free Gemini calls a new visual. While Gemini is down none is made, and the story never waits.
- **Step 3, the library grows.** Accepted ones are saved in the database's `visuals` table, created by itself like the
  other tables.
  - Every later story's storyboard is offered them (`visuals.library()` before the storyboard).
  - Each story keeps its own copies (`story["visuals"]`). Planning, drawing processes (`jobs_for` carries them), stills
    and the thumbnail register them first, so a film always draws the same.
  - The Studio's "Visuals" panel shows them with previews; Remove takes one out for later stories.
- **Not made:** actions (the rig's code) and furniture. The closest is drawn, and they stay listed in
  `story["missing"]`, the Studio's "Still missing".
- **Measured 2026-11-24:**
  - 30 of the library's 47 small and wall things are light by nature (paper, screens, money, flowers, clocks), and 47
    of its 81 bubble pictures are coloured icons. The silhouette rule is for the new ones.
  - A new picture is compared with silhouette things when few library pictures are dark.
- **Lessons:** the Reviewer's picture lessons (too dark, hard to read, mismatch) go to Visuals. Its storyboard reads
  them.
- **Its suite:** `visuals_suite.py` (offline: a throwaway database, Gemini faked).

## Free limits (7 videos every 4 nights: about 1.75 stories a day)
| | Per story | Free a day |
|---|---|---|
| Gemini text | brief 1, story 1-3, moments 1-3, storyboard 1-3, look 1 | the careful models' share is small (see below): on a busy day a lighter model writes |
| Gemini voice | none (no narrator since 2026-11-19) | |
| Drawing | none: everything is drawn in code | |
| YouTube uploads | 1 (a Short, or a long story) | ~10 per 24 h |

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
- A Short whose bubbles would take it to 3:00 or more is refused before it's drawn: its making fails and the slot
  takes another story (rare: its moments are held to 70-115 s of reading).
- **Gemini down** (no model could answer: overloaded, 503/504, or out of its free requests, 429; the dashboard says
  "Waiting for Gemini"): not the story's fault (`llm.down`). The brief is kept and written first at the next try
  (`jobs.keep_brief`: no new brief is asked for while Gemini is down), a finished story goes back to the queue with no
  try counted, and a run that keeps meeting it stops as a wait; the hourly check tries again. Learned the evening of
  2026-11-23: Gemini was overloaded for hours, 16 new briefs were made and thrown away (using up the stronger models'
  20 free requests for the day) and finished story #16 was given up. Their requests come back at 13:30 IST.
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
