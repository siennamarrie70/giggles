# Workflow: One-time account setup

## Objective
Get every free account and key the channel needs, test each one locally, then hand the daily work to the cloud:
GitHub Actions makes the day's story every morning, a free cloud database keeps the data (Aiven since 2026-11-15; Neon
before), and Vercel can show the dashboard. Everything here is free; no step needs a credit card.

## Required Inputs
- A Google account (for YouTube, Google Cloud and Gemini)
- About 1–2 hours

## Tools
- `tools/youtube_auth.py`: one-time YouTube sign-in, writes tokens to `.env`
- `tools/instagram.py`: one-time Instagram connection (optional), writes its token and account to `.env`
- `tools/llm.py`, `tools/narrator.py`, `tools/prompts.py`, `tools/notify.py`: quick checks that each key and model works

All commands run from the project folder with the venv's Python: `.venv/Scripts/python tools/<tool>.py`.

## Steps

### 1. YouTube channel
1. On youtube.com, profile picture → **Create a channel**. Pick the name; update `channel.name` in `config/channel.yaml` to match.

### 2. YouTube API access (Google Cloud, free, no billing)
1. console.cloud.google.com → create a project (e.g. "ezzy-stories").
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
Each story's short version can also go up as a Reel on your Instagram at its time. It uses Instagram's own API ("Instagram API
with Facebook Login"), from an app you own; nothing is shared with anyone else.
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

### 3. Gemini key (Agents 1, 2, 4 and 6: the theme and title, the story, the review's look, weekly lessons)
1. aistudio.google.com → **Get API key → Create API key** → put it in `.env` as `GEMINI_API_KEY`.
2. Check: `.venv/Scripts/python tools/llm.py --prompt "Give me a two-word name for a cat"`.

### 4. The narrator's voice and word timings (no new account)
1. His voice is Gemini's text-to-speech on the free tier: the same `GEMINI_API_KEY` as step 3, nothing to add. The
   dashboard's **Narrator** page plays samples of four warm voices and picks his (`series.narrator` in
   `config/channel.yaml`; Algieba since 2026-11-16). Each model gives 10 free readings a day, renewed at 13:30 in India;
   a story takes 3-4.
2. faster-whisper's small.en model (word timings, ~250 MB, MIT) downloads itself into `.tmp/models/` the first time
   it's needed and runs on this computer.
3. Check: `.venv/Scripts/python tools/narrator.py --sample` (his sample, kept: one free reading if it isn't made yet).

### 4a. The look's description (your words, encrypted)
1. Your description of the silhouette look is kept word for word in `prompts/look_silhouette.txt.enc`, encrypted
   because the repository is public. The key is `PROMPTS_KEY` in `.env` (and in GitHub's secrets, step 8).
2. Check: `.venv/Scripts/python tools/prompts.py --check` says its size, never its text.

### 5. Phone alerts (optional, Telegram)
1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts → copy the token → `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `"chat":{"id": …}` number → `TELEGRAM_CHAT_ID`.
3. Check: `.venv/Scripts/python tools/notify.py --text "hello"`.

### 6. Music
1. `assets/music/full/` has the stories' four full-length tracks by Kevin MacLeod (incompetech.com, CC BY 4.0), with
   their credit lines in `assets/music/tracks.yaml`. The Publisher adds the right line to every description: keep it,
   his tracks are in YouTube's Content ID.
2. To add your own: the dashboard's **Music** page (full-length tracks: the music runs from the spark to the end). Add
   a `full/<file>` entry with its `credit` in `tracks.yaml` if the licence asks for one. No popular songs.

### 7. First story, locally
Follow `workflows/produce_long.md`: write a story (the Themes page, or ask for a theme), read it on the Stories page,
make its film (**Make it now** in the Studio), watch it, then upload it as private and check it in YouTube Studio. Only
then switch the autopilot on.

### 8. Cloud: the morning run on GitHub Actions (free for a public repository)
One story needs 15-30 minutes of drawing and about 1.5 GB of models and packages. Vercel's free functions stop after
5 minutes and a Python function may be 500 MB unzipped (2026), so Vercel only shows the dashboard: it installs
`requirements.txt` alone (the dashboard's packages), and the morning run `requirements-worker.txt` (those plus the
video-making ones). GitHub Actions is free for public repositories (4 cores, 16 GB, up to 6 hours a job).
1. **Database (free):** a free PostgreSQL database (Aiven since 2026-11-15, after Neon's free allowance locked the
   old one) → copy its connection string. Put it in `.env` as `DATABASE_URL`, then copy this computer's data there once:
   `.venv/Scripts/python tools/db_copy.py` (every row keeps its number; the counts are checked). Restart the dashboard:
   it now shows the cloud's data, and its own autopilot stays off, so only the cloud posts. Keep `DATABASE_URL` in
   `.env` from then on.
2. **GitHub:** `winget install GitHub.cli`, then `gh auth login` (sign in once in the browser). Then (Claude can do
   it) `gh repo create <name> --public --source . --push`. Before the repository goes public: `.env`,
   `credentials.json`, `token.json`, `.tmp/` and `backups/` are in `.gitignore`, and neither the files to push nor the
   history hold a key (checked again 2026-10-28 against every value in `.env`). The music (credited, CC BY), the sounds
   (CC0) and `config/channel.yaml` (your settings, no keys) become public; your look description stays encrypted
   (step 4a). So do the Actions run logs: GitHub hides the secrets in them, and the tokens made during a run too
   (`common.keep_secret`); they show the stories' titles and progress.
3. **Secrets:** the repository → Settings → Secrets and variables → Actions → **New repository secret**, one for each:
   `GEMINI_API_KEY`, `PROMPTS_KEY` (it opens your look description: `tools/prompts.py`), `YOUTUBE_CLIENT_ID`,
   `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`, `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and for
   Reels `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`, `INSTAGRAM_USERNAME` and `REELS_KEY` (it encrypts the short
   versions kept between runs; posting needs no Facebook app ID or secret). Claude can copy them all from `.env` with
   `gh secret set`, without showing them. Two workflows then run: **Morning run** and **Reels** (at the short version's time,
   posting the Reels whose morning run has ended). Variables tab: `PAUSED` = `false` (`true` stops the cloud run; the
   dashboard's switch does too).
4. **Test:** Actions tab → **Morning run** → **Run workflow**, tick **test**: it writes, makes and reviews one story
   and uploads nothing. The first run downloads the models (about 1 GB, kept for the next runs). The log's ffmpeg step
   says whether the bundled ffmpeg has rubberband (his deeper voice); if not, the run uses Ubuntu's.
5. From then on it runs by itself: every day at 06:55 India time (`.github/workflows/morning.yml`), with a catch-up
   run at 13:00. GitHub emails you when a run fails; Telegram tells you when the day's story is scheduled.
6. **The YouTube sign-in must not expire:** in Testing it lasts 7 days, and the cloud run would stop every week. Publish
   the app (step 2.3), which needs the `/about` and `/privacy` pages online: step 7.
7. **Optional, the dashboard online (Vercel, Hobby):** vercel.com → sign up with GitHub → **Add New → Project** →
   import the repository → **Settings → Environment Variables**: `DATABASE_URL` (the same database string), the keys from
   `.env`, `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` (the sign-in page asks for both: the password 12 characters
   or more and hard to guess, zxcvbn's 4 of 4, or the dashboard stays off and says why; ten wrong tries lock that
   address out for ten minutes, thirty from everywhere rest sign-in for ten; a browser stays signed in for 30 days,
   and a new password signs every browser out; the same two in `.env` make this computer's dashboard ask too) and
   `CRON_SECRET` (32+ random characters, for `/api/health`; it also locks the sign-in cookies) →
   Deploy. It shows the cloud's data from anywhere and its pause switch stops the cloud run; making stories, settings
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
- The data in the cloud database (`tools/db_copy.py`), with `DATABASE_URL` in `.env`
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
- **Meta blocked the app (2026-10-29):** the Reels were refused with "Any of the pages_read_engagement, ...
  permission(s) must be granted before impersonating a user's page" (code 190), and Meta's token check, asked with
  the app's ID and secret, answered "API access blocked" (code 200). Meanwhile the Reels wait, no try counted, and
  the dashboard and a daily failed Reels run (GitHub's email) say so (`agents/publisher.py`). To fix it:
  1. developers.facebook.com → **My Apps** → the app (signed in as the Facebook account that made it). The top of its
     dashboard, and the bell (alerts), say why: e.g. a verification to complete, a request for information to
     answer, or a policy finding to appeal. Meta also emails that account. Do what it asks.
  2. If Meta lifts the block, the same token usually works again by itself: the Reels go up within 30 minutes, with
     nothing to do. If it doesn't (or you make a new app instead: step 2a.3 onwards), make a new token in the Graph
     API Explorer and connect again on the Channels page.
  3. **The cloud has its own copy of the token** (GitHub's secrets). Connecting on the dashboard on this computer
     copies the new values there by itself (`tools/cloud_secrets.py`, through the signed-in `gh`, each value on
     standard input); the page says whether it worked. If it didn't: `.venv/Scripts/python tools/cloud_secrets.py`.
     The online dashboard can't connect (keys live only in `.env` and GitHub's secrets): connect on this computer.
- **Vercel Hobby is for non-commercial use.** Fine while growing; once the channel earns money, upgrade to Pro or move hosts.
- **Vercel no longer runs the autopilot (2026-10-26):** its cron jobs are gone from `vercel.json`; GitHub Actions makes
  the stories.
- **GitHub starts scheduled runs late at busy times** (often 5-30 minutes; a story takes 15-30), and the 13:00
  catch-up covers a run it skipped. **A public repository's schedules switch off after 60 days
  without a commit:** the workflow re-enables itself every run; if GitHub still emails a warning, press **Enable** on
  the Actions tab. **The run logs are public:** they show themes and titles, never the keys (GitHub hides secrets).
- **Gemini free tier**: Google may use free-tier prompts to improve its products. Nothing private is sent: the channel's settings and your look description, the stories' scripts, frames of the finished films, and public view counts.
