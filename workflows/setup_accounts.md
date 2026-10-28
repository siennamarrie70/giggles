# Workflow: One-time account setup

## Objective
Get every free account and key the channel needs, test each one locally, then hand the daily work to the cloud:
GitHub Actions makes the Shorts every morning, Neon keeps the data, and Vercel can show the dashboard. Everything
here is free; no step needs a credit card.

## Required Inputs
- A Google account (for YouTube, Google Cloud and Gemini)
- About 1–2 hours

## Tools
- `tools/youtube_auth.py`: one-time YouTube sign-in, writes tokens to `.env`
- `tools/instagram.py`: one-time Instagram connection (optional), writes its token and account to `.env`
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
6. Check: the Channels page shows your channel name (or `.venv/Scripts/python tools/youtube_auth.py --check`).
7. Optional, for custom thumbnails: verify the channel by phone at youtube.com/verify. Without it YouTube refuses the
   Animator's thumbnails (the uploads still work; YouTube picks a frame).

### 2a. Instagram Reels (optional, free)
Each Short can also go up as a Reel on your Instagram at its slot. It uses Instagram's own API ("Instagram API with
Facebook Login"), from an app you own; nothing is shared with anyone else.
1. In Instagram: **Settings → Account type and tools → Switch to professional account** (Creator or Business).
2. Link it to a Facebook Page you manage (create one if needed): the Page's settings → **Linked accounts →
   Instagram**.
3. developers.facebook.com → **My Apps → Create app** → use case **Other** → type **Business**. Add the product
   **Instagram** (API setup with Facebook login). Development mode is enough: it works for accounts that have a role
   on the app, which yours does.
4. **Graph API Explorer** (developers.facebook.com/tools/explorer): pick your app, **User or Page → Get User Access
   Token**, add the permissions `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement` and `business_management`, plus `instagram_manage_contents` for the Schedule page's Delete
   of a posted Reel (2026-10-27; without it posting still works), press **Generate Access Token** and, in Facebook's
   window, tick your Page, your Instagram account and your business. Copy the token. (An empty permission list means the app
   lacks the Instagram use case: developers.facebook.com/apps → the app → Use cases → Manage messaging & content on
   Instagram → API setup with Facebook login. A Page in a Business portfolio isn't found without
   `business_management`: connect() then also looks through the portfolio's Pages, and its error names the Pages the
   token sees and the permissions it lacks. 2026-10-27.)
5. The app's **App ID** and **App secret**: App settings → Basic.
6. In the dashboard: **Channels → Instagram Reels**: paste the token, App ID and App secret → **Connect Instagram**.
   It exchanges the token for a long-lived one, finds the Page your Instagram is linked to and keeps the Page's token
   (it doesn't expire) in `.env` (`INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`, `INSTAGRAM_USERNAME`,
   `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`). Without the dashboard:
   `.venv/Scripts/python tools/instagram.py --connect <token> --app-id <id> --app-secret <secret>`.
7. Check: the page shows `@yourname` (or `.venv/Scripts/python tools/instagram.py --status`). Then **Switch on** Reels
   (`instagram.enabled` in `config/channel.yaml`). Posting needs this computer on at the slot time, until the
   cloud move (step 8): then GitHub posts them (`.github/workflows/reels.yml`).

### 3. Gemini key (Agents 1, 2, 3, 5 and 7: choosing cases, research, writing, the review's look, weekly lessons)
1. aistudio.google.com → **Get API key → Create API key** → put it in `.env` as `GEMINI_API_KEY`.
2. Check: `.venv/Scripts/python tools/llm.py --prompt "Give me a two-word name for a cat"`.

### 4. The Professor's voice, lip-sync and word timings (no new account)
1. His voice is Gemini's text-to-speech on the free tier: the same `GEMINI_API_KEY` as step 3, nothing to add. The
   dashboard's **Host** page plays samples of Gemini's deep voices and picks his (`voice` in `config/channel.yaml`).
2. The rest downloads itself into `.tmp/models/` the first time it's needed and runs on this computer: faster-whisper's
   small.en model (word timings, ~250 MB, MIT), Rhubarb Lip Sync (his mouth, ~90 MB, MIT), Depth Anything V2 Small
   (photos that move, ~100 MB, Apache 2.0). (Kokoro, the old backup voice, was removed on 2026-10-27; its ~120 MB
   in `.tmp/models/kokoro` can be deleted.)
3. Check: `.venv/Scripts/python tools/host.py` writes `.tmp/out/host_test.mp4`: him saying his line from the sheet in
   his voice (one free Gemini call). Or press **Make a test clip** on the Host page.

### 4a. Stock footage keys (free)
1. pexels.com → sign up → **Image & Video API** → copy the key → `PEXELS_API_KEY` in `.env`.
2. Optional: pixabay.com → sign up → **API** docs page shows your key → `PIXABAY_API_KEY`.
3. Both licences allow free use on YouTube, edited and monetised, with no credit required; the description credits
   every creator anyway and marks the clips as illustrative.
4. Check: `.venv/Scripts/python tools/footage.py --query "stock market screen"` lists clips. Archive film (the
   Internet Archive, NASA) needs no key: `... footage.py --archive Tupperware`.

### 4a-2. Cloudflare: the drawn look's scenes (free, no card)
1. dash.cloudflare.com → sign up with an email (the Free plan; no card asked).
2. In the dashboard: **AI → Workers AI → Use REST API → Create a Workers AI API token**. The token form's permission
   rows: Workers AI **Read** (the row showing "0" can be set to Read or deleted); Account Resources: your account; TTL
   empty. Copy the token once (it isn't shown again) and the **Account ID** from the same page.
3. Paste them into `.env` as `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (never into a chat).
4. Check: `.venv/Scripts/python tools/draw.py --check` draws `.tmp/out/draw_check.jpg` in about 3 s and says
   today's neurons (about 58 of the free 10,000).
5. The free plan gives 10,000 neurons a day (renewed at 00:00 UTC) and never charges: past the allocation Cloudflare
   refuses. `draw.py` stops at 9,000. Turn the drawn look on in **Settings → The look**.

### 4b. Research sources (no accounts)
1. Nothing to sign up for: Agent 2 reads Wikipedia, Wikimedia Commons (photos with free licences), the IMF and World
   Bank data APIs, news sites' public RSS feeds and GDELT, all without keys.
2. Check: `.venv/Scripts/python tools/research_fetch.py wiki Nokia` prints the article's sections, and
   `... research_fetch.py data gdp_growth IND` the IMF's numbers up to its forecasts.
3. Viewers' comments are read with the YouTube permission from step 2 ("View your YouTube account"). If the Activity
   page shows a comments error after the first cases go public, press **Reconnect** on the YouTube page once.

### 4c. The host
1. Nothing to do: the Professor's drawings are in `assets/host/`, made once from the user's character sheet
   (`assets/host/sheet.png`) by `tools/host_prep.py`. The Host page sets his name (for the dashboard only), his size
   and his voice.

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

### 8. Cloud: the morning run on GitHub Actions (free for a public repository)
One Short needs 10-15 minutes and about 1.6 GB of models and packages. Vercel's free functions stop after 5 minutes
and a Python function may be 500 MB unzipped (2026), so Vercel only shows the dashboard: it installs
`requirements.txt` alone (the dashboard's packages), and the morning run `requirements-worker.txt` (those plus the
video-making ones, ~650 MB). GitHub Actions is free for public repositories (4 cores,
16 GB, up to 6 hours a job); a private one gets 2,000 minutes a month, about 3 Shorts a day (2026-10-26).
1. **Database (Neon, free):** neon.tech → sign up with GitHub → create a project (region near you, e.g. Singapore) →
   copy its connection string. Put it in `.env` as `DATABASE_URL`, then copy this computer's data there once:
   `.venv/Scripts/python tools/db_copy.py` (every row keeps its number; the counts are checked). Restart the dashboard:
   it now shows the cloud's data, and its own autopilot stays off, so only the cloud posts. Keep `DATABASE_URL` in
   `.env` from then on.
2. **GitHub:** `winget install GitHub.cli`, then `gh auth login` (sign in once in the browser). Then (Claude can do
   it) `gh repo create <name> --public --source . --push`. Before the repository goes public: `.env`,
   `credentials.json`, `token.json`, `.tmp/` and `backups/` are in `.gitignore`, and neither the files to push nor the
   history hold a key (checked again 2026-10-28 against every value in `.env`). The Professor's sheet, the music
   (credited, CC BY) and `config/channel.yaml` (your settings, no keys) become public. So do the Actions run logs:
   GitHub hides the secrets in them, and the tokens made during a run too (`common.keep_secret`); they show the
   cases' topics and progress.
3. **Secrets:** the repository → Settings → Secrets and variables → Actions → **New repository secret**, one for each:
   `GEMINI_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
   `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`,
   `YOUTUBE_REFRESH_TOKEN`, `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and for Reels
   `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`, `INSTAGRAM_USERNAME` and `REELS_KEY` (it encrypts the Reels'
   videos kept between runs; posting needs no Facebook app ID or secret). Claude can copy them all from `.env`
   with `gh secret set`, without showing them. Two workflows then run: **Morning run** and **Reels** (5 and 35
   minutes after each slot, posting the Reels of Shorts whose morning run has ended). Variables tab: `PAUSED` = `false` (`true` stops the cloud run;
   the dashboard's switch does too).
4. **Test:** Actions tab → **Morning run** → **Run workflow**, tick **test**: it makes and reviews one video and
   uploads nothing. The first run downloads the models (about 1 GB, kept for the next runs). The log's ffmpeg step
   says whether the bundled ffmpeg has rubberband (his deeper voice); if not, the run uses Ubuntu's.
5. From then on it runs by itself: every day at 06:55 India time (`.github/workflows/morning.yml`), with catch-up runs
   at 13:00 and 19:00. GitHub emails you when a run fails; Telegram gets the day's summary.
6. **The YouTube sign-in must not expire:** in Testing it lasts 7 days, and the cloud run would stop every week. Publish
   the app (step 2.3), which needs the `/about` and `/privacy` pages online: step 7.
7. **Optional, the dashboard online (Vercel, Hobby):** vercel.com → sign up with GitHub → **Add New → Project** →
   import the repository → **Settings → Environment Variables**: `DATABASE_URL` (the same Neon string), the keys from
   `.env`, `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` (the sign-in page asks for both: the password 12 characters
   or more and hard to guess, zxcvbn's 4 of 4, or the dashboard stays off and says why; ten wrong tries lock that
   address out for ten minutes, thirty from everywhere rest sign-in for ten; a browser stays signed in for 30 days,
   and a new password signs every browser out; the same two in `.env` make this computer's dashboard ask too) and
   `CRON_SECRET` (32+ random characters, for `/api/health`; it also locks the sign-in cookies) →
   Deploy. It shows the cloud's data from anywhere and its pause switch stops the cloud run; making videos, settings
   and music stay with this computer and GitHub. Every page carries security headers (no framing by other sites,
   scripts only from the app itself, nothing cached, https only, not listed by search engines except `/about` and
   `/privacy`), and a change needs the page's own header, so another site can't press its buttons.
   **Then the firewall (free on Hobby: 3 custom rules, 1 rate limit), project → Firewall → Configure:**
   - Rate limit rule: request path equals `/login` and method equals `POST` → 10 requests per 60 seconds per IP →
     **Deny** (picking 429 may open a Pro upgrade prompt on Hobby, 2026-10). Vercel counts across all its servers,
     which the app's own limit (per server) can't.
   - Optional custom rule, if you only open the dashboard from India: country is not India AND path is not `/about`
     AND path is not `/privacy` → **Deny** (Google must still reach those two). Switch it off when travelling.
   - Settings → Deployment Protection: keep **Vercel Authentication** on (the default), so preview deployments need
     your Vercel sign-in.

## Expected Outputs
- `.env` filled in locally; the same keys as the GitHub repository's secrets
- The data in Neon (`tools/db_copy.py`), with `DATABASE_URL` in `.env`
- A green **test** run on the Actions tab, then the Morning run scheduled every day at 06:55 India time

## Edge Cases & Known Issues
- **The switch, as done on 2026-10-28:** stop the dashboard first (its loop writes to the laptop database), take off
  the day's Reels whose videos are only on the laptop (`publisher.cancel_reel`; the cloud can't post them, the
  YouTube Shorts are unaffected) or wait until after the day's last slot, back up `.tmp/ezzy.db` to `backups/`, run
  `db_copy.py`, put the Neon string in `.env` as `DATABASE_URL`, restart the dashboard, then the GitHub secret
  `DATABASE_URL` and `PAUSED=false`. The dashboard's pause switch is copied too (it lives in the database): if it
  was off, the cloud stays paused until you switch it on.
- **Vercel's screens (2026-10):** variables are under Settings → **Environment Variables** ("Environments" is a
  Pro feature: Cancel); type **Secret**, Production; a change needs **Redeploy** ("Use existing Build Cache" is
  fine). In the firewall, the **AND** button adds a second condition.
- **Reconnect on the YouTube page opens Google's page in the default browser** (Microsoft Edge on this laptop), not
  necessarily the dashboard's; another click says "Busy" until it's finished or 5 minutes pass.
- **Vercel deployed before the data copy (2026-10-28):** leave out `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD` until
  `db_copy.py` has run. Without them the online dashboard is off (404), so nothing writes into the empty Neon
  database; `db_copy` refuses only when it already has cases, and rows in its other tables would break the count
  check. `/about` and `/privacy` work without them.
- **"invalid_grant" errors** mean the YouTube sign-in was revoked or the consent screen was left in Testing. Fix: publish the consent screen, run `youtube_auth.py` again, update `YOUTUBE_REFRESH_TOKEN` in `.env` and in the GitHub secrets (and Vercel). The morning run stops at once on it and says so.
- **Publish app asks for home page / privacy policy links (2026-10-24):** expected; Google requires them for any External app in production. Use the app's own `/about` and `/privacy` pages (above). If Google refuses `<project>.vercel.app` as an authorized domain, the $0 fallback is staying in Testing and reconnecting weekly.
- **Wrong channel**: if your Google account has several channels, re-run `youtube_auth.py` and pick the right one in the browser.
- **Stop and Delete need one more permission (2026-10-26):** they need the sign-in to change and delete videos
  (`youtube.force-ssl`), which earlier sign-ins didn't ask for. Only you can give it, on Google's page: the first Stop
  or Delete offers to open it (or the Schedule page's "Allow it now", or Reconnect on the YouTube page), and the
  Stop or Delete finishes once it's allowed. Connecting runs beside a task that's going (it used to wait "Busy" for
  the whole morning run). Then copy the new `YOUTUBE_REFRESH_TOKEN` from `.env` to the GitHub secrets (and Vercel)
  too.
- **Google's page has a box for each permission (granular consent):** an unticked box used to fail the sign-in with
  oauthlib's "Scope has changed from … to …". `youtube_auth.run` now accepts the smaller grant
  (`OAUTHLIB_RELAX_TOKEN_SCOPE`) and checks it. It saves nothing if "Manage your YouTube videos", "View your YouTube
  account" or "View YouTube Analytics reports…" was left unticked, because uploads and the numbers need them. It does
  save without "See, edit, and permanently delete your YouTube videos…", but then Stop and Delete stay off and the
  dashboard says so. A timeout (5 minutes) or Cancel changes nothing either.
- **Instagram "none of the Facebook Pages ... has an Instagram professional account"**: the account is personal, or
  not linked to a Page the token can manage; fix it in Instagram's settings, generate a new token and connect again.
- **Instagram token stops working**: a token connected without the App ID and secret lasts only hours; connect again
  with them (the Page token from a long-lived token doesn't expire unless you change your password or remove the app).
- **Vercel Hobby is for non-commercial use.** Fine while growing; once the channel earns money, upgrade to Pro or move hosts.
- **Vercel no longer runs the autopilot (2026-10-26):** its cron jobs are gone from `vercel.json`; GitHub Actions makes
  the Shorts.
- **GitHub starts scheduled runs late at busy times** (often 5-30 minutes; the 08:00 Short takes 10-15), and the
  13:00 and 19:00 catch-ups cover a run it skipped. **A public repository's schedules switch off after 60 days
  without a commit:** the workflow re-enables itself every run; if GitHub still emails a warning, press **Enable** on
  the Actions tab. **The run logs are public:** they show topics and titles, never the keys (GitHub hides secrets).
- **Gemini free tier**: Google may use free-tier prompts to improve its products. Nothing private is sent: the channel's settings, trend topics, text from public sources, photos to check, scripts, public view counts and the text of public comments (never who wrote them). Grounding with Google Search isn't on the free tier, which is why the research reads its sources itself.
