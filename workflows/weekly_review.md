# Workflow: Weekly review

## Objective
Once a week, see what's working, steer the channel, check the facts are holding up, and keep everything free. About
15 minutes.

## Required Inputs
- The dashboard's **Results** page (Agent 6): the playbook's lessons and what does better than usual, by case type,
  why now (trend, anniversary, evergreen, your request, a comment, a follow-up), kind of hook, visuals used, length,
  number of lines, follow-up or first case, and posting time; the follow-up candidates
- The **Topics**, **Research** and **Scripts** pages: the cases chosen, their checked facts and the fact-check's marks
- The weekly check-in on Telegram (if set up) and YouTube Studio analytics

## Tools
- `.venv/Scripts/python tools/db.py recent`: latest Shorts, failures and runs
- `.venv/Scripts/python -m agents.analyst --learn`: read the numbers and comments and rewrite the playbook now
- `.venv/Scripts/python tools/stats_pull.py --id <video id>`: numbers for specific Shorts on demand
- `config/channel.yaml` or the dashboard's **Settings** page: what you change

## Steps
1. **Read the playbook** (Results → 6.1). Agents 1 and 3 follow it three times out of four, leaving the rest to
   variety so early noise doesn't lock the channel in. Disagree with a lesson? Say so to Claude and we'll adjust the
   agent's prompt (`agents/editor.py`, `agents/writer.py`).
2. **Look at what does better than usual** (Results → 6.2). A group needs 5 cases that are 2 days old before it
   counts, so the bars fill in over the first weeks. Then steer in **Settings → Cases**: how often each case type
   comes up, the target length, approvals.
3. **Check the facts** on two or three cases: the Research page shows each fact with the source's own words, the
   Scripts page each line's mark (checked, fixed by the fact-check, edited by you). Many "dropped" facts or "cut"
   lines on one kind of case usually means thin sources: switch that kind down, or ask for better-covered topics.
4. **Approvals:** news and politics wait in the Studio for your OK and are discarded after
   `cases.approval_expires_days`. If you never approve them, switch "In the news" off in Settings instead.
5. **Requests and comments:** the Topics page shows what you asked for (made, waiting, or not made and why) and the
   comments Agent 6 saved. A follow-up candidate (Results → 6.3) gets a part 2 when Agent 1 thinks there's more story.
6. **Look for failures:** the Overview's agent cards ("Hit a snag") and the Activity page. Repeated failures usually
   mean an expired YouTube sign-in, a Gemini quota, or a source rate-limiting (see the Edge Cases in
   `workflows/produce_short.md`).
7. **Music** every few weeks: remove tracks you're tired of on the Music page and add new ones (with a mood and,
   if the licence asks, a credit line in `assets/music/tracks.yaml`).
8. **Monthly:** AI Studio → Usage: Gemini requests stay far from the daily limits (about 5 per case).

## Expected Outputs
- Updated settings (if anything changed)
- New learnings recorded in the "Edge Cases" sections of the workflows when something new went wrong

## Edge Cases & Known Issues
- Analytics (percent viewed, subscribers gained) lag about two days; brand-new Shorts show views only.
- Small numbers are noisy. Give a change 1–2 weeks before judging it.
- The playbook only learns from case studies: Shorts from the cartoon and cute-animal versions are left out.
- YouTube's money rules (2025-26) don't pay for templated AI videos "with minimal narrative or educational value" or AI
  hosts giving financial advice. Keep the cases varied, with real analysis, and never advice; watch for a YouTube
  Partner Program message about "inauthentic content".
- When the channel starts earning, that's the time to consider paid extras (better voices, a search API for research).
