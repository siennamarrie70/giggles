# Workflow: Switch between versions

## Objective
Move between the saved versions of the channel's software safely (try an old one, go back to it for good, or return to
the newest) without losing data or posting twice.

## Required Inputs
- The project folder with git (versions are git branches and tags)
- 2 minutes

## The versions
| Version | Where it lives | Database on this computer |
|---|---|---|
| **v4, case studies** (newest): six agents (Editor, Researcher, Writer, Animator, Publisher, Analyst) make 60-second case studies told by two cartoon hosts | branch `v4-case-studies` | `.tmp/ezzy.db` (its rows: format `case`) |
| **v3, cartoon sketches**: five agents (Casting, Writer, Animator, Publisher, Analyst) make cartoon comedy sketches | branch `v3-cartoons`, tag `v3-cartoons` | `.tmp/ezzy.db` (format `sketch`) |
| **v1, cute animals, final**: one autopilot, stock clips of cute animals, the systematic white dashboard, music with its credit line | branch `master`, tag `v1-cute-final` | `.tmp/ezzy.db` (the clip formats) |
| **v1, first release**: one autopilot | tag `v1-shorts-autopilot` | `.tmp/ezzy.db` |
| **v2, cute animals**: six agents (Scout, Writer, Editor, Designer, Publisher, Analyst) with HQ; 4 animal formats; YouTube and Instagram | branch `v2-cute-animals`, from tag `v2-animals-only` | `.tmp/ezzy-v2.db` |
| **v2, every topic**: 16 topics and 12 sticker-card formats | tag `v2-every-topic` | `.tmp/ezzy-v2.db` |
| **v2, meme bar**: memes, jokes, old public-domain films and NASA footage with meme-bar captions | branch `v2-agents`, tag `v2-meme-bar` | `.tmp/ezzy-v2.db` |

- **v1, v3 and v4 share `.tmp/ezzy.db`.** Each only makes and picks its own kind of Short (the `format` column), so
  the others' rows just show as older Shorts; tables and columns are only ever added, never changed, so an older
  version still works on a newer database.
- **The v2 versions share `.tmp/ezzy-v2.db`**, separate from the rest.
- **Snapshots** in `backups/`:
  - `ezzy-v1-2026-10-24.db`: v1's database from before v2 existed;
  - `ezzy-v2-every-topic-2026-10-24.db` and `ezzy-v2-meme-bar-2026-10-25.db`: the v2 database at those versions;
  - `ezzy-v1-before-clear-2026-10-25.db`: v1's before its history was cleared;
  - `ezzy-before-v4-2026-10-25.db`: the shared database just before v4.
- **Settings** (`config/`) are in git, so each version brings its own. `.env` (keys, `PAUSED`) stays the same for all.
- **Models and caches** in `.tmp/` (Kokoro, Rhubarb, research cache) are shared; nothing to do.

## Steps

### Switch to another version
1. **Pause the autopilot** (the switch at the top of the dashboard), so nothing posts halfway through.
2. Stop the dashboard server (Ctrl+C in its terminal).
3. Save unsaved work on the branch you're on: `git add -A` then `git commit -m "work in progress"`.
   (Commit only what you mean to keep; ask Claude if unsure.)
4. Back up the database you're leaving: copy `.tmp/ezzy.db` (or `.tmp/ezzy-v2.db`) into `backups/` with today's date.
5. `git switch <branch>` (e.g. `git switch v3-cartoons`). For a tag with no branch: `git switch --detach <tag>`.
6. Install that version's packages: `.venv/Scripts/python -m pip install -r requirements.txt`.
7. Start the server: `.venv/Scripts/python -m uvicorn app:app --port 8000`, check the Overview, then switch the
   autopilot on if you want it posting.

### Come back to the newest
1. Same steps, with `git switch v4-case-studies`.

### Go back to a database snapshot
1. Stop the server, copy the current database aside (it may hold things you want), then copy the snapshot over
   `.tmp/ezzy.db` (or `.tmp/ezzy-v2.db`) and start the server again.

## Expected Outputs
- The dashboard of the version you switched to, on its own database, with its own settings

## Edge Cases & Known Issues
- **Shorts already on YouTube stay there** whatever the version: switching changes what's made next, not what's posted.
- **Another version's queued Shorts** show as older ones ("Cartoon version", "Cute-animal version"): they can still go
  up as they are, if their video was kept, or be discarded. The agents never pick them.
- **A version's own pages and buttons** (e.g. v3's Cast page, v4's Topics and Research) only exist in that version.
- **Uncommitted work blocks a switch**: git refuses to switch if it would overwrite changes; commit them first.
