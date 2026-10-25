# Workflow: One-time account setup

## Objective
Get every free account and key the channel needs, test each one locally, then deploy to Vercel.
Everything here is free; no step needs a credit card.

## Required Inputs
- A Google account (for YouTube, Google Cloud and Gemini)
- About 1–2 hours

## Tools
- `tools/youtube_auth.py`: one-time YouTube sign-in, writes tokens to `.env`
- `tools/llm.py`, `tools/voice_tts.py`, `tools/notify.py`: quick checks that each key and model works

All commands run from the project folder with the venv's Python: `.venv/Scripts/python tools/<tool>.py`.

## Steps

### 1. YouTube channel
1. On youtube.com, profile picture → **Create a channel**. Pick the name; update `channel.name` in `config/channel.yaml` to match.

### 2. YouTube API access (Google Cloud, free, no billing)
1. console.cloud.google.com → create a project (e.g. "ezzy-shorts").
2. **APIs & Services → Library** → enable **YouTube Data API v3** and **YouTube Analytics API**.
3. **Google Auth Platform** (called "OAuth consent screen" in older menus):
   - Branding: app name, user support email, developer contact email. **No logo**: uploading one forces Google's
     verification review.
   - Audience: **External**, and add your own Gmail under **Test users**. Stay in **Testing** for now. It works
     immediately, but the sign-in expires every 7 days (Reconnect in the dashboard's YouTube tab).
   - Later, to make it permanent: Google requires a home page and privacy policy for every app "In production".
     The app serves both: deploy to Vercel (step 8), then in Branding set
     Home page `https://<project>.vercel.app/about`, Privacy policy `https://<project>.vercel.app/privacy`,
     Authorized domain `<project>.vercel.app`, leave Terms of service empty, save, and press **Publish app**.
     The app stays "unverified": don't submit it for verification (not needed for one personal account).
     Then Reconnect once; you'll see "Google hasn't verified this app" → Advanced → Go to … (unsafe).
4. **Clients → Create client → Desktop app** → download the JSON file.
5. In the dashboard (http://localhost:8000 → **YouTube** tab): **Choose client file** (saved as `credentials.json`,
   gitignored), then **Connect YouTube**. In the browser pick the account **and the channel**.
   Google warns the app is unverified because it's your own private app: **Advanced → Go to … (unsafe)** → Allow.
   Without the dashboard: save the file as `credentials.json` and run `.venv/Scripts/python tools/youtube_auth.py`.
6. Check: the YouTube tab shows your channel name (or `.venv/Scripts/python tools/youtube_auth.py --check`).

### 3. Gemini key (Agents 1, 2, 3 and 6: choosing cases, research, writing, weekly lessons)
1. aistudio.google.com → **Get API key → Create API key** → put it in `.env` as `GEMINI_API_KEY`.
2. Check: `.venv/Scripts/python tools/llm.py --prompt "Give me a two-word name for a cat"`.

### 4. Voices and lip-sync (no account; downloads by itself)
1. Nothing to sign up for: Agent 3 downloads the Kokoro voice model (~120 MB, Apache 2.0) and Rhubarb Lip Sync
   (~90 MB, MIT) into `.tmp/models/` the first time it animates. Both run on this computer.
2. Check: `.venv/Scripts/python tools/voice_tts.py --voice af_heart --text "Hello there"` writes a WAV you can play.
   The dashboard's sidebar shows "Kokoro ready" and "Rhubarb ready" once they're downloaded.
3. Pexels and Pixabay keys (`PEXELS_API_KEY`, `PIXABAY_API_KEY`) were for the cute-animal version's stock clips; the
   case studies don't use them, so they can stay in `.env` or go.

### 4b. Research sources (no accounts)
1. Nothing to sign up for: Agent 2 reads Wikipedia, Wikimedia Commons (photos with free licences), the IMF and World
   Bank data APIs, news sites' public RSS feeds and GDELT, all without keys.
2. Check: `.venv/Scripts/python tools/research_fetch.py wiki Nokia` prints the article's sections, and
   `... research_fetch.py data gdp_growth IND` the IMF's numbers up to its forecasts.
3. Viewers' comments are read with the YouTube permission from step 2 ("View your YouTube account"). If the Activity
   page shows a comments error after the first cases go public, press **Reconnect** on the YouTube page once.

### 4c. The two hosts
1. They're designed by themselves with the first case (one Gemini call), or press **Design the hosts** on the
   dashboard's Hosts page. Change their look, voice or speed there any time.

### 5. Phone alerts (optional, Telegram)
1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts → copy the token → `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `"chat":{"id": …}` number → `TELEGRAM_CHAT_ID`.
3. Check: `.venv/Scripts/python tools/notify.py --text "hello"`.

### 6. Music
1. `assets/music/` already has 36 tracks by Kevin MacLeod (incompetech.com, CC BY 4.0), 3 for each of 12 moods, with
   their credit lines in `assets/music/tracks.yaml`. The Publisher adds the right line to every description: keep it,
   his tracks are in YouTube's Content ID.
2. To add your own: the dashboard's **Music** page, or drop files into `assets/music/` (YouTube Audio Library tracks
   marked "Attribution not required" are the safest). Add a `mood` (and a `credit` if the licence asks) for each in
   `tracks.yaml` so the Animator can match it to a script's mood. No popular songs.

### 7. First Short, locally
Follow `workflows/produce_short.md`: make a case (or ask for one on the Topics page), read its research and script,
animate it, watch it in the Studio, then upload it as private and check it in YouTube Studio. Only then switch the
autopilot on.

### 8. Cloud (Vercel, free Hobby plan): not for the case studies yet
The case studies are made on this computer: the voices, lip-sync and drawing need more than Vercel's free plan allows
(4 CPU-hours a month, 250 MB per function). The steps below are kept for the public `/about` and `/privacy` pages
Google asks for (step 2.3) and for a later cloud setup, e.g. GitHub Actions running the same jobs.
1. Put the project in a **private** GitHub repo (Claude can do this with git once you say so).
2. vercel.com → sign up with GitHub (Hobby) → **Add New → Project** → import the repo → Deploy.
3. Project → **Storage → Create Database → Neon (Free)** → connect it to the project. This sets `DATABASE_URL`.
4. Project → **Settings → Environment Variables**: add every filled-in key from your `.env`
   (Gemini, the three YouTube values, `CRON_SECRET`, Telegram, `PAUSED=true` while the cases are made locally).
   Then **Redeploy**.
   Optional: `DASHBOARD_PASSWORD` turns on the dashboard at your Vercel URL (browser asks for the password) so you
   can check and edit the queue from anywhere. Planning, rendering, uploading, settings, music and the YouTube
   sign-in only work from the dashboard on your computer; in the cloud the hourly autopilot does that work.
5. **Hand the autopilot to the cloud:** copy `DATABASE_URL` from Vercel (Settings → Environment Variables) into your
   local `.env` and restart the local server. Your dashboard then shows the cloud's queue, and its own autopilot loop
   stops, because two autopilots on two databases would post every slot twice.
6. Check the deployment (replace the URL and secret):
   `curl -H "Authorization: Bearer <CRON_SECRET>" https://<project>.vercel.app/api/health`
   It should show `font: true`, your music count, an ffmpeg version and `true` for each key (the voice model and
   lip-sync show `false` there: they only exist on this computer).
7. Project → **Settings → Cron Jobs**: within the 2½ hours before a slot, run one of the **autopilot** entries and watch
   **Logs**. A private Short scheduled for that slot should appear in YouTube Studio. Outside that window the run
   answers "no slot is due yet", which is also correct.

## Expected Outputs
- `.env` filled in locally; the same values in Vercel
- One test Short in YouTube Studio (private, scheduled for its slot)
- 25 cron jobs listed in Vercel: 24 hourly autopilot checks and the daily stats

## Edge Cases & Known Issues
- **"invalid_grant" errors** mean the YouTube sign-in was revoked or the consent screen was left in Testing. Fix: publish the consent screen, run `youtube_auth.py` again, update `YOUTUBE_REFRESH_TOKEN` in `.env` and Vercel.
- **Publish app asks for home page / privacy policy links (2026-10-24):** expected; Google requires them for any External app in production. Use the app's own `/about` and `/privacy` pages (above). If Google refuses `<project>.vercel.app` as an authorized domain, the $0 fallback is staying in Testing and reconnecting weekly.
- **Wrong channel**: if your Google account has several channels, re-run `youtube_auth.py` and pick the right one in the browser.
- **Vercel Hobby is for non-commercial use.** Fine while growing; once the channel earns money, upgrade to Pro or move hosts.
- **Hobby cron runs once a day per entry, at a random minute of its hour (2026-10-24).** That's why `vercel.json` has
  24 autopilot entries (one per hour) and why each Short is made ahead and scheduled: YouTube publishes it on the
  minute even though the check itself is imprecise.
- **Gemini free tier**: Google may use free-tier prompts to improve its products. Nothing private is sent: the channel's settings, trend topics, text from public sources, photos to check, scripts, public view counts and the text of public comments (never who wrote them). Grounding with Google Search isn't on the free tier, which is why the research reads its sources itself.
