# Workflow: One-time account setup

## Objective
Get every free account and key the channel needs, test each one locally, then deploy to Vercel.
Everything here is free; no step needs a credit card.

## Required Inputs
- A Google account (for YouTube, Google Cloud and Gemini)
- About 1–2 hours

## Tools
- `tools/youtube_auth.py`: one-time YouTube sign-in, writes tokens to `.env`
- `tools/llm.py`, `tools/clips_search.py`, `tools/notify.py`: quick checks that each key works

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

### 3. Gemini key (AI writing + frame checks)
1. aistudio.google.com → **Get API key → Create API key** → put it in `.env` as `GEMINI_API_KEY`.
2. Check: `.venv/Scripts/python tools/llm.py --prompt "Give me a two-word name for a cat"`.

### 4. Stock footage keys
1. pexels.com/api → sign up → copy your key → `PEXELS_API_KEY` (required).
2. pixabay.com/api/docs → log in; the key is shown on that page → `PIXABAY_API_KEY` (optional backup).
3. Check: `.venv/Scripts/python tools/clips_search.py --query "kitten yawning"`.

### 5. Phone alerts (optional, Telegram)
1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts → copy the token → `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `"chat":{"id": …}` number → `TELEGRAM_CHAT_ID`.
3. Check: `.venv/Scripts/python tools/notify.py --text "hello"`.

### 6. Music
1. YouTube Studio → **Audio Library** → filter **Attribution not required**.
2. Download 10–15 upbeat, playful tracks (moods like Happy, Bright, Funny) into `assets/music/`.
   Only use this library: it's the safest against copyright claims. No popular songs.

### 7. First Short, locally
Follow `workflows/produce_short.md` until one Short is uploaded as private and looks right in YouTube Studio.

### 8. Cloud (Vercel, free Hobby plan)
1. Put the project in a **private** GitHub repo (Claude can do this with git once you say so).
2. vercel.com → sign up with GitHub (Hobby) → **Add New → Project** → import the repo → Deploy.
3. Project → **Storage → Create Database → Neon (Free)** → connect it to the project. This sets `DATABASE_URL`.
4. Project → **Settings → Environment Variables**: add every filled-in key from your `.env`
   (Gemini, Pexels, Pixabay, the three YouTube values, `CRON_SECRET`, Telegram, `PAUSED=false`). Then **Redeploy**.
   Optional: `DASHBOARD_PASSWORD` turns on the dashboard at your Vercel URL (browser asks for the password) so you
   can check and edit the queue from anywhere. Planning, rendering, uploading, settings, music and the YouTube
   sign-in only work from the dashboard on your computer; in the cloud the hourly autopilot does that work.
5. **Hand the autopilot to the cloud:** copy `DATABASE_URL` from Vercel (Settings → Environment Variables) into your
   local `.env` and restart the local server. Your dashboard then shows the cloud's queue, and its own autopilot loop
   stops, because two autopilots on two databases would post every slot twice.
6. Check the deployment (replace the URL and secret):
   `curl -H "Authorization: Bearer <CRON_SECRET>" https://<project>.vercel.app/api/health`
   It should show `font: true`, your music count, an ffmpeg version and `true` for each key.
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
- **Gemini free tier**: Google may use free-tier prompts to improve its products. Nothing private is sent, only captions and stock frames.
