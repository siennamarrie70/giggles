# Workflow: Weekly review

## Objective
Once a week, see what's working, steer the channel, check the facts are holding up, and keep everything free. About
15 minutes.

## Required Inputs
- The dashboard's **Results** page (Agent 7): the playbook's lessons, what each agent has learned, and what does
  better than usual, by case type,
  why now (trend, anniversary, evergreen, your request, a comment, a follow-up), kind of hook (a question, a contrast
  or paradox, a number, a plain claim), visuals used, archive film or not, the Professor's voice, his pace, the music's mood, hashtags, whether the Reviewer passed it at first look, length, number
  of lines, follow-up or first case, and posting time; the follow-up candidates
- The **Review** page (Agent 5): the cases being made again, what it finds most, and the lessons it has taught
- The **Topics**, **Research** and **Scripts** pages: the cases chosen, their story and checked facts, the retention
  editor's scores and the fact-check's marks
- The weekly check-in on Telegram (if set up) and YouTube Studio analytics

## Tools
- `.venv/Scripts/python tools/db.py recent`: latest Shorts, failures and runs
- `.venv/Scripts/python -m agents.analyst --learn`: read the numbers and comments and rewrite the playbook now
- `.venv/Scripts/python tools/stats_pull.py --id <video id>`: numbers for specific Shorts on demand
- `config/channel.yaml` or the dashboard's **Settings** page: what you change

## Steps
1. **Read the playbook** (Results → 7.1) and **what each agent has learned** (7.2). The weights are followed three
   times out of four, leaving the rest to variety so early noise doesn't lock the channel in; each agent's lessons
   are read every time. Disagree with a lesson? Say so to Claude and we'll adjust the agent's prompt.
2. **The Review page:** the cases being made again (turned down after the fixes; they're made again by themselves
   until they pass, nothing to press), the problems found most, and the standing fixes. A case made again many times,
   or the same problem every week, means a tool needs fixing, not just a lesson: tell Claude.
3. **Look at what does better than usual** (Results → 7.3). A group needs 5 cases that are 2 days old before it
   counts, so the bars fill in over the first weeks. Then steer in **Settings → Cases**: how often each case type
   comes up, the target length, approvals.
4. **Check the facts** on two or three cases: the Research page shows each fact with the source's own words, the
   Scripts page each line's mark (checked, fixed by the fact-check, edited by you). Many "dropped" facts or "cut"
   lines on one kind of case usually means thin sources: switch that kind down, or ask for better-covered topics.
5. **Approvals:** off since 2026-10-26 (the Publisher approves news and politics itself). Switch them on in Settings
   if you want to see those cases first; they then wait in the Studio and are discarded after
   `cases.approval_expires_days`.
6. **Requests and comments:** the Topics page shows what you asked for (made, waiting, or not made and why) and the
   comments Agent 7 saved. A follow-up candidate (Results → 7.4) gets a part 2 when Agent 1 thinks there's more story.
7. **Instagram:** the Schedule page (and the Studio) shows each Short's Reel beside its YouTube side: posted, waiting,
   failed, skipped or taken off. A failed one says why, most often an expired or revoked token (connect again on the
   Channels page); while its video is kept (2 days after the slot) Post now tries it again.
8. **Look for failures:** the Overview's agent cards ("Hit a snag") and the Activity page. Repeated failures usually
   mean an expired YouTube sign-in, a Gemini quota, or a source rate-limiting (see the Edge Cases in
   `workflows/produce_short.md`).
9. **The drawings** (the drawn look): open two or three cases in the Studio, which shows each line's drawing next to
   its description. Look for drawings that drift from his style, letters in a picture, odd hands, or a second person
   left out. One that keeps drifting: tell Claude, and the art words (**Settings → The look**) get adjusted; a scene
   kind that keeps failing becomes a rule for the Writer. Settings also shows today's drawing against the free 10,000
   neurons.
10. **Music** every few weeks: remove tracks you're tired of on the Music page and add new ones (with a mood and,
   if the licence asks, a credit line in `assets/music/tracks.yaml`).
11. **Monthly:** AI Studio → Usage: Gemini requests stay far from the daily limits (about 8 text and 1 voice request
    per case, plus 1 for each look the Reviewer takes and a voice request when it asks for a line to be read again).

## Expected Outputs
- Updated settings (if anything changed)
- New learnings recorded in the "Edge Cases" sections of the workflows when something new went wrong

## Edge Cases & Known Issues
- Analytics (percent viewed, subscribers gained) lag about two days; brand-new Shorts show views only.
- Small numbers are noisy. Give a change 1–2 weeks before judging it.
- The playbook only learns from v5's documentary cases: Shorts from the cartoon-host, cartoon and cute-animal
  versions are left out.
- YouTube's money rules (2025-26) don't pay for templated AI videos "with minimal narrative or educational value" or AI
  hosts giving financial advice. Keep the cases varied, with real analysis, and never advice; watch for a YouTube
  Partner Program message about "inauthentic content".
- **Empty slots because Gemini's voice was out** (there's no backup voice since 2026-10-27; the Activity page shows
  "waits for Gemini's voice"): a few a week is fine; many means the voice quota is too small for the posting
  schedule: post less often, or check the voice models in `tools/narration.py`.
- **Empty slots because Cloudflare couldn't draw** (the drawn look; the dashboard says "Cloudflare's drawing is
  resting"): today's free drawing was used up (it renews at 05:30 in India) or Cloudflare was out. Often means too
  many drawings for the free 10,000 neurons: fewer Shorts a day, or fewer drawings per Short (`writer.MAX_SCENES`).
- When the channel starts earning, that's the time to consider paid extras (better voices, a search API for research).
