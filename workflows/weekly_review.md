# Workflow: Weekly review

## Objective
Once a week, see what's working, steer the channel, and keep everything free. About 15 minutes.

## Required Inputs
- The dashboard's **Results** page (Agent 5): the playbook's lessons and what does better than usual, by setting,
  kind of character, voice, outfit, length, number of lines, trend or evergreen, and posting time
- The weekly check-in on Telegram (if set up) and YouTube Studio analytics

## Tools
- `.venv/Scripts/python tools/db.py recent`: latest Shorts, failures and runs
- `.venv/Scripts/python -m agents.analyst --learn`: read the numbers and rewrite the playbook now
- `.venv/Scripts/python tools/stats_pull.py --id <video id>`: numbers for specific Shorts on demand
- `config/channel.yaml` or the dashboard's **Settings** page: what you change

## Steps
1. **Read the playbook** (Results → 5.1). Agents 1 and 2 follow it three times out of four, leaving the rest to
   variety so early noise doesn't lock the channel in. Disagree with a lesson? Say so to Claude and we'll adjust the
   agent's prompt (`agents/casting.py`, `agents/writer.py`).
2. **Look at what does better than usual** (Results → 5.2). A group needs 5 Shorts that are 2 days old before it
   counts, so the bars fill in over the first weeks.
3. **Watch a few episodes** in the Studio. If a character type, voice or setting keeps falling flat, steer:
   - **Settings → Episodes**: switch off settings that don't work, cap characters at 2, shorten the longest sketch
   - **Settings → Channel → Humour and voice**: the tone both agents follow
   - **Settings → Posting**: first post, hours between posts, Shorts a day and time zone
4. **Look for failures:** the Overview's agent cards ("Hit a snag") and the Activity page. Repeated failures usually
   mean an expired YouTube sign-in or a Gemini quota; see the Edge Cases in `workflows/produce_short.md`.
5. **Music** every few weeks: remove tracks you're tired of on the Music page and add new ones (with a mood and,
   if the licence asks, a credit line in `assets/music/tracks.yaml`).
6. **Monthly:** AI Studio → Usage: Gemini requests stay far from the daily limits (about 2 per episode).

## Expected Outputs
- Updated settings (if anything changed)
- New learnings recorded in the "Edge Cases" sections of the workflows when something new went wrong

## Edge Cases & Known Issues
- Analytics (percent viewed, subscribers gained) lag about two days; brand-new Shorts show views only.
- Small numbers are noisy. Give a change 1–2 weeks before judging it.
- The playbook only learns from cartoons: Shorts from the cute-animal version are left out.
- When the channel starts earning, that's the time to consider paid extras (better voices, AI-drawn art).
