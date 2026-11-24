# Workflow: Weekly review

## Objective
Once a week, see what's working, steer the channel, and keep everything free. About 15 minutes.

## Required Inputs
- The dashboard's **Results** page (Agent 7): the playbook's lessons, what each agent has learned, and what does
  better than usual by watch time (views × the share watched): by theme, vice or virtue, the title's shape, the
  story's motif, length, hashtags, whether the Reviewer passed it at first look, and posting time
- The **Review** page (Agent 5): the stories being made again, what it finds most, and the lessons it has taught
- The **Themes**, **Stories** and **Studio** pages: the themes chosen, the stories' bubbles (what the people say and think), the films and their scenes
- The weekly check-in on Telegram (if set up) and YouTube Studio analytics (audience retention: where viewers leave)

## Tools
- `.venv/Scripts/python tools/db.py recent`: latest stories, failures and runs
- `.venv/Scripts/python -m agents.analyst --learn`: read the numbers and rewrite the playbook now
- `.venv/Scripts/python tools/stats_pull.py --id <video id>`: numbers for specific videos on demand
- `config/channel.yaml` or the dashboard's **Settings** page: what you change

## Steps
1. **Read the playbook** (Results → 7.1) and **what each agent has learned** (7.2). The weights are followed three
   times out of four, leaving the rest to variety so early noise doesn't lock the channel in; each agent's lessons
   are read every time. Disagree with a lesson? Say so to Claude and we'll adjust the agent's prompt.
2. **The Review page:** the stories being made again (turned down after the fixes; they're made again by themselves
   until they pass, nothing to press), the problems found most, and the standing fixes. A story made again many times,
   or the same problem every week, means a tool needs fixing, not just a lesson: tell Claude.
3. **Look at what does better than usual** (Results → 7.3). A group needs 5 films that are 2 days old before it
   counts, so the bars fill in over the first weeks. Then steer in **Settings → The stories**: the themes, the length,
   the posting time, the hashtags.
4. **Watch two or three films** in the Studio, start to end, and their short versions: does the story land, does each
   scene read, can each bubble be read in time (and is it over the right person), does the short version tell the whole story in under a
   minute and hook in its first seconds? A scene kind that keeps failing becomes a rule for Agent 2 or a fix in the
   drawing: tell Claude. YouTube Studio's audience retention shows where viewers leave (for the Shorts: how many swiped
   away in the first seconds).
5. **Requests:** the Themes page shows what you asked for (made, waiting, or not made and why).
6. **Instagram:** the Schedule page (and the Studio) shows each short version's Reel beside its YouTube side: posted,
   waiting, failed, skipped or taken off. A failed one says why, most often an expired or revoked token (connect again
   on the Channels page); while its short version is kept (2 days after its time) Post now tries it again.
7. **Look for failures:** the Overview's agent cards ("Hit a snag") and the Activity page. Repeated failures usually
   mean an expired YouTube sign-in or a Gemini quota (see the Edge Cases in `workflows/produce_long.md`).
8. **Music** every few weeks: remove tracks you're tired of on the Music page and add new full-length ones (with a
   credit line in `assets/music/tracks.yaml` if the licence asks).
9. **Monthly:** AI Studio → Usage: Gemini stays far from the daily limits (2-4 text calls a story, its storyboard and
   up to 3 new silhouettes from Agent 3 (2-4 calls each), 1 look by the Reviewer, a weekly lesson call).

## Expected Outputs
- Updated settings (if anything changed)
- New learnings recorded in the "Known weak spots" of `workflows/produce_long.md` when something new went wrong

## Edge Cases & Known Issues
- Analytics (percent viewed, subscribers gained) lag about two days; brand-new films show views only.
- Small numbers are noisy. Give a change 1–2 weeks before judging it.
- The playbook only learns from the stories: videos earlier versions of the channel made are left out.
- YouTube's money rules (2025-26) don't pay for templated AI videos "with minimal narrative or educational value".
  Keep the stories varied (the themes, the blows, the places, the turn-down) and watch for a YouTube Partner Program
  message about "inauthentic content".
- **A day without its story because Gemini was out** (its free daily limits used up, or busy; the Activity page shows
  the story waiting): the free limits renew at 13:30 in India and the hourly check after that makes it. The stories have
  been silent since 2026-11-19 (bubbles, no narrator), so there are no readings to wait for.
- When the channel starts earning, that's the time to consider paid extras (stronger Gemini models, more of them).
