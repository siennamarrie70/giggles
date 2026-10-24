# Workflow: Weekly review

## Objective
Once a week, see what's working, steer the channel, and keep the free tiers free. About 15 minutes.

## Required Inputs
- The Sunday Telegram "weekly check-in" (written by the `stats` job from your numbers)
- YouTube Studio analytics

## Tools
- `tools/db.py recent`: latest videos, failures and job runs
- `tools/stats_pull.py --id <video id>`: numbers for specific Shorts on demand
- `config/channel.yaml`: the settings you change

## Steps
1. **Read the check-in.** The lessons it lists are fed into next week's concepts automatically.
   Disagree with one? Say so to Claude and we'll adjust the prompt in `tools/concept_write.py`.
2. **Look for failures:** `tools/db.py recent`. Repeated failures usually mean an expired sign-in or a quota;
   see the Edge Cases in `workflows/produce_short.md`.
3. **Steer** in `config/channel.yaml`, then commit (Vercel redeploys):
   - `formats.rotation`: lean into what wins, e.g. `[top3, punchline, top3, pov]`
   - `content.animals`: drop animals that flop, add ones that work
   - `schedule`: first post, hours between posts, Shorts a day and time zone (or use the dashboard's Settings)
   - `channel.voice`: adjust the humour
4. **Refresh music** every few weeks with new Audio Library tracks in `assets/music/`.
5. **Monthly: check free-tier usage:**
   - Vercel → Usage: Active CPU should stay under 4 h/month (10 Shorts a day was estimated at ~2.5 h; if it runs
     higher, post fewer per day)
   - AI Studio → Usage: Gemini requests are far from the daily limits
   - Neon dashboard: storage well under 0.5 GB

## Expected Outputs
- Updated `config/channel.yaml` (if anything changed)
- New learnings recorded in the "Edge Cases" sections of the workflows when something new went wrong

## Edge Cases & Known Issues
- Analytics (percent viewed, subscribers gained) lag about two days; brand-new Shorts show views only.
- Small numbers are noisy. Give a change 1–2 weeks before judging it.
- When the channel starts earning, Vercel's Hobby plan no longer fits (non-commercial only): upgrade to Pro or move
  the same code to another host. That's also the time to consider paid extras like AI-generated originals.
