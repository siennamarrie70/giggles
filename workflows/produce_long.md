# Produce the day's story (the motivation series)

## Objective
One 3-4 minute motivational story a day, every day a new storyline (your redirect, 2026-11-16): written by **your own
script-writer prompt** (sealed word for word in `prompts/script_writer.txt.enc`: six stages, a new character, incident,
place and change every time), briefed each day the way your examples do it, and pictured from that script alone:
its own places, its own people, a shot for every line, drawn in code in your silhouette look. A calm, warm narrator
tells it. It's posted on YouTube at `series.post_at`; its **short version** (the same story whole in under a minute,
its own script) follows as a YouTube Short `series.short_after_hours` later, and as an Instagram Reel when Instagram is
on. Everything runs on free tiers.

Settings: `series:` in `config/channel.yaml` (Settings page S2.1: the topics, the minutes, the times). Earlier versions
of the channel live only in git (tags `v5-before-motivation`, `v6-motivation-series`). Stories #3 and #4 (the fixed
eight-part arc, before the redirect) are set aside: they stay in the Studio and are never posted.

## The six agents
| Agent | What it does | Code |
|---|---|---|
| 1 Theme | Writes the day's **brief** for your writer, like your examples: "Write a story about LUST. <direction>" (a weakness one day, a virtue the next, from `series.themes`, never one used within `repeat_after_days`), or about one day in four "Choose a topic yourself. <direction>". The direction is one or two sentences, new every day, never close to a recent one. Your own brief from the Themes page goes first, word for word. One Gemini call (retried when too like an earlier one). | `agents/theme.py` |
| 2 Story | Your writer's prompt is the whole system prompt; the brief is the message, with the channel's facts under it (he's a man, always drawn the same way, so his looks are never described; everyone is an adult; about 430-490 words at the narrator's 2.3 words a second; the recent stories, so this one is new). Gemini answers in your output format (Title, Central Theme, Core Message, Full Script, Final Closing Line). Code checks: 380-560 words, a new title of at most 70 characters, adults only, nothing explicit, no gore, weapons or self-harm, no real brands (3 tries). Then `split_lines` cuts the script into the narrator's lines at sentence ends (a long sentence at a comma) without changing a word; the closing line is said last unless the script already ends on it. Later, the first time it's needed, the **short version's script** (`write_short`). | `agents/story.py` |
| 3 Animator | First the **storyboard** (`agents/storyboard.py`, one Gemini call, up to 3): from the script, your look text word for word and the library, Gemini designs this story's places (6-14, each a kind of place with its look, things, light, weather and effects), the people around him (each one's role and look), a shot for every line in order plus a few quiet ones (its stage, place, what he does where and with what eyes, who else is there, the framing: wide, medium, close or a detail of a thing, the camera's move, an event, what the picture shows, a few words of direction for the narrator), the shot where he realizes (the music starts there), six chapter names, the thumbnail's shot and words (a white lead-in and a yellow punch), the description and tags. Code checks it and repairs what it can (below). Then the narrator reads the script, every shot is timed to his lines and the film is drawn in code (`tools/silhouette_board.py`: every place built from the library), with the narrator's words as **subtitles** (below), the music from his realization, the thumbnail and a still of every scene; then the **short version** (drawn upright from the film's shots, its own lines, its own subtitles). | `agents/storyboard.py`, `agents/animator.py`, `tools/silhouette_board.py`, `tools/story_film.py`, `tools/silhouette_render.py`, `tools/subtitles.py`, `tools/thumbnail.py` |
| 4 Reviewer | Size, length, loudness, silence; every narrator line heard through the mix (whisper); his own voice (voiceprint); the same for the short version. One Gemini look at up to 24 frames: (nearly) every scene against what its shot should show, the title and the closing line, and 4 of the short version's, against your look. "Unsuitable" means sexual, gory or a child (a story's fire, an ambulance or a glass of wine is fine). A picture problem goes back to Agent 3, who draws that scene again with a change (a lighter light, him alone, a closer framing, a calmer camera); a problem only the short version has is fixed in it alone; after 2 rounds the story is made again, and from the third time Agent 2 writes it again. Recurring picture problems become lessons for the storyboard. | `agents/reviewer.py` |
| 5 Publisher | The film into its slot (Film & Animation, the storyboard's description, chapters, the music's credit), its thumbnail, then the short version as a Short a few hours later (#shorts, the film's link); the Reel = the short version. | `agents/publisher.py` |
| 6 Analyst | Daily numbers; long videos ranked by watch time; weekly lessons for the other five. | `agents/analyst.py` |

The autopilot's run (`python tools/jobs.py morning`) writes, storyboards, makes and uploads the next story
(`jobs.make_story`: brief, script, storyboard). The dashboard's "Make the 17:30 video now" does the same at once.

**When (since 2026-11-19, your choice):** the next story is made as soon as its slot is free: the moment the story
before it goes public (17:30), tomorrow's 17:30 slot is due (`slots.opens`, `schedule.ahead: true` in
`config/channel.yaml`; the Settings switch "Next story"). Only the next slot is filled: one story waits ahead, never
more. It's started only when the free quotas for all of it are there (`jobs.quota_short`): the narrator's readings
(`jobs.readings_needed`: a part each for the film, one for the short version, 2 spare; 10 of the day's 20 for a story
not written yet; fewer for one already written, none for one already made), his voice not resting, YouTube's room for
its two uploads. Otherwise nothing is started (in the cloud a story read half-way is lost with the machine) and the next
check starts it, at the latest in the hour after the readings renew (13:30 IST), hours before its slot. GitHub checks
every hour at :35 IST (`.github/workflows/morning.yml`, the workflow "Autopilot": `python tools/jobs.py due`, with
only the dashboard's packages; it ends in about a minute when there's nothing to do). Its verdict is kept (note
`autopilot:check`) and the Schedule page shows it ("Up next · being made" or "Waits for free quotas", with the reason).
Gemini's text quota can't be counted ahead: if it's out, the run stops before a reading is spent. With the switch off,
the morning run makes the day's story from `schedule.make_at` (07:00), as before. On this computer: `python tools/jobs.py prepare` writes and storyboards a story; `python tools/jobs.py
publish --dry-run --newest` makes and reviews it without uploading. Start the dashboard with `python app.py`
(http://localhost:8000): it never runs work on old code and restarts itself with new code when idle.

## The library (drawn in code)
- Your look text, word for word: `prompts/look_silhouette.txt.enc`. The reference GIF stays in `.tmp/reference/` and
  never goes into git (the repo is public).
- The words Gemini designs with: `tools/silhouette_words.py` (plain data). The places: `tools/silhouette_scene.py`
  (a room, a hall, a corridor, a city street, a street of houses, a bridge, nature: hills, mountains, sea, field,
  forest, lake; inside a car, a bus or a train with the world sliding past), laid out from their things
  (`tools/silhouette_props.py`: 91 things, each with the spots where people stand, sit or lie by it); what people do
  (`tools/silhouette_actions.py`: 42 actions, a hug, a handshake and an argument for two); effects
  (`tools/silhouette_fx.py`: fire, smoke, emergency lights, party lights, a spotlight, snow, fog; rain as before).
  People are made from the look's parts (`silhouette.look_from`); he is always the teal-hoodie man.
- Where an action happens: `silhouette_board.where` puts each person on the right spot of the thing the storyboard
  names (the bed to sleep in, its edge to sit on, the desk's chair, the stove) and two people at one thing on its two
  places. A wide shot slides along a big room to keep the people in it.
- The catalog of everything: `python tools/silhouette_catalog.py` (into `.tmp/library/index.html`, ~3 minutes).
  A story's storyboard as stills: `python tools/silhouette_board.py story.json --out .tmp/storyboard`.
- Every place is built from the library. The 12 ready-made sets of the first look (desk_room, bedroom, kitchen,
  hallway, street, hospital, office, cafe, rooftop, park, bright_office, new_flat) aren't offered to the storyboard
  any more (your call, 2026-11-17: story #6, storyboarded by Flash-Lite while the bigger models were busy, was drawn
  entirely in them and looked like the old films). An answer that still names one gets that place built from the
  library instead (`storyboard.SET_PLACES`); their code stays only to draw stories made before.
- What a script needs that the library lacks: the nearest thing is drawn, and it's listed (the Studio's "Missing
  pieces", most wanted first). That list is what's added to the library next.
- Thumbnail (`tools/thumbnail.py`, from the style test): him big on the left in the chosen moment, outlined like a
  sticker with the coral rim and his mood's marks, the story's own place dimmed behind him, the white lead-in over the
  big yellow punch with a dry-brush underline, and a red arrow from the words to him. You can change both lines and
  the scene in the Studio.

## The storyboard's checks (agents/storyboard.py `check`)
- Every line has its one shot, in the script's order; every stage has shots and none goes back. (Code's repair: a
  line's second shot loses the line; a line without one gets a copy of the shot before it.)
- Places 6-14 (fewer than 5 goes back); no place holds more than about a third of the shots (45% goes back); each
  is a kind the library has, with its things (an alias or a misspelling is fixed; anything else is listed missing).
- Every action has somewhere to happen in its place (typing needs a desk, cooking a stove): else it goes back.
- People: adults only (a hard rule: the storyboard is refused), never teal (his colour), the hero never in the cast;
  a hug, a handshake or an argument names the other one.
- A detail shot names a thing of its place; at most 4 labels; 2-8 quiet shots; the realization in rock bottom or the
  first of the transformation; six chapter names; the thumbnail's words (white 1-4, yellow 1-3); a description.
- Different from the recent stories: a place too like a recent one (the same kind and things) gets other colours and
  its things the other way round.
- Nothing explicit, no gore, weapons or self-harm, no brands, in anything it says (a hard rule).

## The sound
- Narrator: Algieba, calm and warm, on `gemini-3.8-flash-lite-tts` (`series.narrator`). Measured pace 2.3 words/s.
- His voice stays low: a line's direction (the storyboard's and the short version's) changes his mood and pace, never
  his loudness or pitch. Words like loud, shouting, booming, resonant, high or excited are taken out by code
  (`narrator.voice_direction`); a big moment is slower and firmer, not louder.
- His sample is the reading you chose him by (style test 2), kept with the code in `assets/voices/`
  (`narration.KEPT_SAMPLES`), so the cloud measures him against the same voice and spends no reading on a sample of its
  own. If the narrator or his settings change, put the new voice's sample there too (from `.tmp/voices/samples/`), or
  each cloud run reads one of its own again.
- Every reading is measured against his sample (`tools/voiceprint.py`). One that only came out too high (up to 3.5
  semitones) is brought down to 1 semitone above his sample, formants kept, and measured again: no reading spent. A
  part both his models read unlike him is read again in a steady "low, calm and unhurried" voice, and from then on that
  way (its `.steady` mark). Only when that fails too does the story wait, and the dashboard names the line and how it came
  out ("too high", "in a different tone of voice") and that it isn't the daily limit.
- The film's timing (`story_film.timeline`): a line's shot lasts what its line needs; 0.75 s between lines, almost
  none when a sentence goes on into the next shot, a little more breath before a new paragraph; the quiet shots as
  the storyboard planned them. Kept inside `series.minutes` by the quiet shots.
- Music: silent until his realization, then one of the full-length tracks in `assets/music/full/` (credited in the
  description), rising to the end, dipped under his voice.
- Beds by kind of place (a room's quiet, a street at night, birds by day in nature, crickets at dusk, a crowd in a hall
  with an audience), rain, steps for walking, typing, running, knocking, a page, the lamp's switch, the phone, a heart
  monitor's beeps.

## Subtitles (your request, 2026-11-17)
- The narrator's words on screen in the film and in its short version, burned into the picture (`tools/subtitles.py`
  cuts and times them, `silhouette_render` draws them in the look's type: Oswald, warm white).
- Each line is cut into as few cues of whole words as fit, broken after a full stop or a comma where it can, never
  after "the", "his" and the like, never a word alone. Each cue comes on just before its first word is said: the
  narrator's engine hears every word's time (whisper) and `narrator.cut_lines` keeps where each line's own sound starts
  ("from"). With no reading (a test), they're spread by their letters. A line's cues stay inside its shot.
- The film: one row (at most 52 letters) in the black band under the picture, so they never cover it. The short
  version: at most two rows (30 letters each) low in the picture (75% down) on a soft dark shadow, above the title and
  buttons YouTube and Instagram lay over a Short's bottom fifth.
- The closing line has none: it's on screen in big type as he says it. The Reviewer reads them too (a subtitle cut off
  or hard to read is "text_unreadable").

## Free limits (one story a day)
| | Per story | Free a day |
|---|---|---|
| Gemini text | brief 1, script 1-3, storyboard 1-3, short script 1, look 1 | the careful models' share is small (see below) |
| Gemini voice | about 6 readings for the film, 1 for the short version | 10 per TTS model, 2 models; renews 13:30 IST |
| Drawing | none: everything is drawn in code | |
| YouTube uploads | 2 (film + its short version) | ~10 per 24 h |

Learned 2026-11-17: Gemini's careful models (`gemini-3.6-flash`, `gemini-3.5-flash`), which the writer and the
storyboard ask first, answered "429 quota" after about one storyboard each, because the script tests of the evening
before fell in the same Gemini day (it renews at 13:30 IST). Then the lighter models answer, and their storyboards are
weaker (half a film in one room, fewer people). Don't spend the careful models' share on tests before a real run;
`llm.passed_over` and the storyboard's log say which model answered and why the others didn't.

Learned 2026-11-17 afternoon: right after the day renewed, `gemini-3.6-flash` and `gemini-3.5-flash` answered "503
high demand" for minutes, Flash-Lite answered instead, and drew story #6 entirely in the old ready-made sets. Now the
storyboard asks `llm.STRONG_MODELS` (3.6-flash, 3.5-flash, then 3.8-flash) first and waits 1, 2 and 3 minutes for
them while they're only busy (`generate_json(strong=True)`); Flash-Lite answers only when they can't today. A model
that says its free requests for the day are used up (429 with a "PerDay" quota; Google says when they renew) isn't
asked again until then, in that run.

Learned 2026-11-18: story #7 waited two days for one line. Its closing line, directed "resonant, calm" and read alone
as the last part, came back from both voice models 2.4-3.5 semitones too high or in another tone of voice, try after
try (39 of its 40 lines were read and kept). Each "Make it now" asked again the same way and spent 2-3 free readings,
and the message ("didn't read it in the narrator's voice; tried again at about 23:59") read like a quota wait. Now the
directions stay low, a too-high reading is brought down, a stubborn part is read steadier (above), and the message says
what happened. The closing line's direction was changed to "low, calm, unhurried" (its words unchanged).

## When something fails
- Every Gemini model busy (overloaded, the minute's quota, timing out): the writer, the storyboard, the short version's
  script and the Reviewer's look wait 1 minute and ask again, then 2 (`llm.generate_json(patient=True)`); all of them
  out of the day's quota: the run waits (`jobs._must_wait`). The storyboard first waits up to 6 minutes for the
  stronger models (above).
- The storyboard keeps a problem after 3 tries: code's repairs are kept and the story goes on, unless it breaks a hard
  rule (adults only, nothing explicit, no gore): then another brief is written (3 tries).
- Gemini's voice used up or silent: the story waits (VoiceResting), nothing counted; never another voice.
- A reading unlike him: brought down if it's only too high; else read steadier (above); still unlike him, the story
  waits (paused: until you press "Make it now"; else it's asked again after a rest). Editing that line's direction on the
  dashboard ("Edit the narration") reads only that part again.
- The Reviewer turns it down after 2 rounds: it's made again by itself; from the third time Agent 2 writes it again.
- The short version can't be written or still runs a minute or more after one rewrite: the making is tried again later.

## Known weak spots (2026-11-17)
- On this laptop on battery, Windows throttles drawing hard: plug it in before making a film here.
- The library can't show everything: the nearest thing stands in and the gap is listed; early stories lean on the
  first batch.
- People are drawn side-on only (a mirror shows him facing back); faces are eyes only, so poses and props carry the
  acting and the narrator carries the rest.
