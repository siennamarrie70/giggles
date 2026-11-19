// Control room for the channel's daily motivation story. Plain JS, no build step; talks to dashboard/api.py.
// Every page has the same shape: a header with its actions, a row of numbers, then numbered sections.
// Pages 01-06 belong to the six agents: Theme, Story, Animator, Reviewer, Publisher, Analyst; then the Music and
// Narrator pages, the channels, the settings and the activity.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const SVG_NS = "http://www.w3.org/2000/svg";

const WHY_NOW = { rotation: "Next in turn", request: "Your request" };
const STATUS = { planned: ["Waiting", "run"], making: ["Being made", "run"],
                 scheduled: ["Scheduled", "run"], live: ["Live", "ok"], failed: ["Failed", "bad"], vetoed: ["Vetoed", "bad"],
                 discarded: ["Discarded", "idle"], skipped: ["Skipped", "idle"],
                 stopped: ["Stopped: private on YouTube", "idle"], deleted: ["Deleted from YouTube", "idle"] };
// What each posting slot says, by its state (see slot_board in tools/jobs.py).
const SLOT = { posted: ["Posted", "ok"], scheduled: ["Scheduled", "run"], making: ["Making…", "run"],
               late: ["Late · going out", "warn"], due: ["In today's run", "accent"], open: ["Next run", "idle"],
               missed: ["No post", "idle"], paused: ["Paused", "warn"] };
/** What a slot says. With the next story made as soon as its slot is free (schedule.ahead), a due slot's story is
 *  being made, waits for the free quotas, or is started by the next hourly check (slotDue). */
function slotLabel(s, a) {
  if (a.paused && ["due", "late"].includes(s.state)) return SLOT.paused;
  if (a.autopilot.schedule.ahead !== false) {
    if (s.state === "due") return slotDue(a.autopilot);
    if (s.state === "open") return ["After the next one", "idle"];
  }
  return SLOT[s.state] || [s.state, "idle"];
}
/** A due slot's story: "Being made" only while a run is going (or the last check has just started one, before its run
 *  begins), "Waits for free quotas" when the last check said so, else it's for the next hourly check to start. */
function slotDue(ap) {
  if (ap.run.running || checkStarting(ap)) return ["Being made", "run"];
  if (recentCheck(ap)?.waits) return ["Waits for free quotas", "warn"];
  return ["Up next · at the next check", "accent"];
}
/** The last check has just started a run: its packages install for a few minutes before the run itself begins. */
function checkStarting(ap) {
  const c = recentCheck(ap);
  return Boolean(c && c.work && !c.waits && Date.now() - Date.parse(c.at) < 20 * 60 * 1000);
}
/** How far ahead the stories are made, in words (schedule.ahead on: schedule.stories_ahead). */
function aheadWords(sch) {
  const n = Number(sch.stories_ahead || 1);
  return n > 1 ? `kept ${n} days ahead` : "made as soon as its slot is free";
}
/** The cloud's last hourly check (tools/jobs.py due), if it's from the last 90 minutes. */
function recentCheck(ap) {
  const c = ap.check;
  return c && c.at && Date.now() - Date.parse(c.at) < 90 * 60 * 1000 ? c : null;
}
/** The last check's verdict, as a sentence for the Schedule page ("" when there's none recent). */
function checkNote(ap) {
  const c = recentCheck(ap);
  return c ? ` Last check ${clockIn(c.at, scheduleTz())}: ${c.why}.` : "";
}
// Where a story stands on each platform (platforms() in agents/publisher.py), beside it on the Schedule page.
const ON_YOUTUBE = { making: ["Being made", "run"], scheduled: ["Scheduled", "run"], public: ["Public", "ok"],
                     hidden: ["Private in Studio", "warn"], rejected: ["Rejected", "bad"], gone: ["Deleted in Studio", "bad"],
                     stopped: ["Stopped", "idle"], deleted: ["Deleted", "idle"] };
const ON_INSTAGRAM = { making: ["After YouTube", "idle"], none: ["Not for Instagram", "idle"], waiting: ["Waits for its time", "run"],
                       due: ["Posting soon", "run"], retry: ["Trying again", "warn"], posting: ["Posting…", "run"],
                       posted: ["Posted", "ok"], failed: ["Didn't post", "bad"], skipped: ["Skipped", "idle"],
                       expired: ["Given up", "idle"], cancelled: ["Taken off", "idle"], deleted: ["Deleted", "idle"],
                       remaking: ["Making its short version…", "run"] };
// Which agents a dashboard task puts to work (for the "Working" badge on their cards).
const TASK_AGENTS = { prepare: ["theme", "story"], render: ["story", "animator", "reviewer"], "narrator-sample": ["animator"],
                      short: ["publisher"], publish: ["animator", "reviewer", "publisher"], instagram: ["publisher"],
                      reel: ["publisher"], remake: ["animator"],
                      autopilot: ["theme", "story", "animator", "reviewer", "publisher"], stats: ["analyst"],
                      morning: ["theme", "story", "animator", "reviewer", "publisher"] };
const AGENT_KEYS = ["theme", "story", "animator", "reviewer", "publisher", "analyst"];
// What the Reviewer's notes ask the Animator to do (agents/reviewer.py, agents/animator.py improve()).
const FIXES = { redraw: "draw that scene again", beds: "turn the sounds under him down", reread: "read it again",
                remake: "make it again" };
const TIMEZONES = ["Asia/Kolkata", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                   "Europe/London", "Europe/Berlin", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney", "UTC"];
const LIMITS = { style: 400 };
const VIEWS = ["overview", "topics", "scripts", "studio", "review", "schedule", "results", "music", "host",
               "youtube", "settings", "activity"];
// The audience is worldwide but US-heavy, so times are also shown for New York next to the schedule's own clock.
const AUDIENCE_TZ = "America/New_York";

const state = { app: null, videos: [], task: null, watching: null, dirty: new Set(),
                studio: { filter: "planned", selected: null, picked: false }, scripts: { selected: null } };

// ------------------------------------------------------------------ helpers

/** Build DOM safely: text always goes in as text, never as HTML. */
// A link or picture address from outside (a credit page, a link a service sends back) is used only if it's a web
// address, one of the dashboard's own, or an email: a "javascript:" address would run code here when clicked.
const SAFE_URL = /^(https?:\/\/|\/(?!\/)|#|mailto:|data:image\/)/i;

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if ((key === "href" || key === "src") && !SAFE_URL.test(String(value).trim())) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "style") el.style.cssText = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "value") el.value = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

function icon(id, cls = "") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#${id}`);
  svg.append(use);
  return svg;
}

async function api(path, { method = "GET", json, raw } = {}) {
  const init = { method, headers: {} };
  if (method !== "GET") init.headers["X-Dashboard"] = "1";
  if (json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  }
  if (raw !== undefined) {
    init.headers["Content-Type"] = "application/octet-stream";
    init.body = raw;
  }
  const res = await fetch(path, init);
  const data = (res.headers.get("content-type") || "").includes("json") ? await res.json() : null;
  if (!res.ok) {
    const detail = data && data.detail;
    if (res.status === 401 && detail?.signin) location.assign("/login");  // signed out (30 days, or a new password)
    const error = new Error(Array.isArray(detail) ? detail.map(d => d.msg).join("; ")
                            : detail?.message || detail || `${res.status} ${res.statusText}`);
    error.reconnect = Boolean(detail?.reconnect);  // YouTube needs your OK once on Google's page
    throw error;
  }
  return data;
}

function toast(message, kind = "info", ms = 4500) {
  const el = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  $("#toasts").append(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 320);
  }, ms);
}

const fmtWhen = iso => new Date(iso).toLocaleString(undefined,
  { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function fromNow(iso) {
  const diff = new Date(iso) - Date.now();
  const [unit, ms] = Math.abs(diff) < 3.6e6 ? ["minute", 6e4] : Math.abs(diff) < 8.64e7 ? ["hour", 3.6e6] : ["day", 8.64e7];
  return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(Math.round(diff / ms), unit);
}

const plural = (n, word) => `${n} ${n === 1 ? word : /[^aeiou]y$/.test(word) ? `${word.slice(0, -1)}ies` : `${word}s`}`;
const hours = n => `${n} hour${n === 1 ? "" : "s"}`;
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : "";
const nyTime = iso => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZone: AUDIENCE_TZ });
/** A moment on the schedule's clock, e.g. 16:00: slots are set in that time zone, not the browser's. */
const clockIn = (iso, tz) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: tz });
const scheduleTz = () => state.app.autopilot.schedule.timezone;
/** A moment on the schedule's clock: 16:00 today, or Tue 28 Oct 16:00 on another day. */
function onClock(iso) {
  const tz = scheduleTz();
  const day = t => new Date(t).toLocaleDateString("en-GB", { timeZone: tz });
  return (day(iso) === day(Date.now()) ? ""
    : `${new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: tz })} `)
    + clockIn(iso, tz);
}
const secs = s => s ? `${Math.round(s)} s` : "–";
const mmss = s => s == null ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** A story the dashboard shows as "live" once its publish time has passed. */
function shownStatus(v) {
  if (v.status === "scheduled" && v.publish_at && new Date(v.publish_at) <= new Date()) return "live";
  return v.status;
}

/** Your YouTube buttons beside a story: "now" (the film public at once), "stop" (the film and its short version
 *  private, never public by themselves) or "delete" (both gone from YouTube, public or not), each asked first. */
async function youtubeAction(v, action, asked = false) {
  const reel = v.platforms?.instagram || {};
  const isPublic = v.platforms?.youtube?.state === "public" || (v.publish_at && new Date(v.publish_at) <= new Date());
  const when = v.publish_at ? `${fmtWhen(v.publish_at)} (${fromNow(v.publish_at)})` : "at its slot";
  const refill = !v.slot || new Date(v.slot) > Date.now() - 3.6e6;  // the autopilot fills a slot up to an hour late
  const slot = !refill ? "Its slot has passed, so no other story is made for it."
    : state.app.paused ? "Its slot stays empty while the autopilot is paused."
    : "The autopilot then makes a new story for its slot (pause it to keep the slot empty).";
  const reelNote = reel.state === "posted" ? " Its Reel stays on Instagram (its own Delete removes it there)."
    : ["waiting", "due", "retry", "failed", "skipped"].includes(reel.state) ? " Its Reel won't go on Instagram either." : "";
  const text = {
    now: `Post “${v.title}” on YouTube now?\n\nThe film goes public right away instead of ${when}. Its slot stays its own, `
         + "so no other story is made for it, and its short version still goes public as a Short at its time.",
    stop: `Stop “${v.title}” from going public ${when}?\n\nThe film and its short version stay on YouTube as private videos `
          + `only you can see; you can still publish them yourself in YouTube Studio. ${slot}${reelNote}`,
    delete: isPublic
      ? `Delete “${v.title}” from YouTube?\n\nIt's public: this removes the film and its short version for good, with their `
        + `views and comments. ${slot}${reelNote}`
      : `Delete “${v.title}” from YouTube?\n\nIt was going public ${when}. This removes the film and its short version for `
        + `good. ${slot}${reelNote}`,
  }[action];
  if (!asked && !confirm(text)) return;
  try {
    await api(`/api/videos/${v.id}/youtube`, { method: "POST", json: { action } });
    toast({ now: "Public on YouTube now.",
            stop: "Stopped: the film and its short version are private on YouTube and won't go public.",
            delete: "Deleted from YouTube, with its short version." }[action], "ok");
    await loadState();
    loaders[currentView()]();
  } catch (e) {
    if (e.reconnect && state.app.local !== false) return allowManaging(() => youtubeAction(v, action, true), action);
    toast(e.message, "error", 9000);
  }
}

/** Your Instagram buttons beside a story: "now" posts its Reel (its short version) at once (a task: a few minutes),
 *  "delete" deletes a posted Reel from Instagram or takes one that isn't posted yet off, "schedule" makes the short
 *  version of one that went up while Reels were off again, so its Reel waits for its time. */
async function instagramAction(v, action) {
  const reel = v.platforms.instagram;
  const yt = v.platforms.youtube;
  if (action === "schedule") {
    const when = reel.at && new Date(reel.at) > new Date() ? `at ${onClock(reel.at)}` : "as soon as it's made (its time has passed)";
    if (!confirm(`Schedule “${v.title}” for Instagram?\n\nIt went up while Reels were off, so its short version wasn't `
                 + "kept: it's made again (a few minutes: the same short version, drawn again), then its "
                 + `Reel goes on Instagram ${when}.`)) return;
    try {
      watchTask(await api(`/api/videos/${v.id}/instagram`, { method: "POST", json: { action } }));
    } catch (e) {
      toast(e.message, "error", 9000);
    }
    return;
  }
  if (action === "now") {
    const early = yt.state !== "public" ? `, before it's public on YouTube (${yt.at ? onClock(yt.at) : "not yet"})` : "";
    if (!confirm(`Post “${v.title}” to Instagram now?\n\nIt goes up as a Reel right away${early}, with its caption `
                 + "and cover. Sending it and Instagram's processing take a few minutes.")) return;
    try {
      watchTask(await api(`/api/videos/${v.id}/instagram`, { method: "POST", json: { action } }));
    } catch (e) {
      toast(e.message, "error", 9000);
    }
    return;
  }
  const posted = reel.state === "posted";
  if (!confirm(posted
      ? `Delete the Reel of “${v.title}” from Instagram?\n\nThis removes it for good, with its likes and comments. `
        + "YouTube isn't affected."
      : `Take “${v.title}” off Instagram?\n\nIts Reel won't be posted. YouTube isn't affected. Changed your mind? `
        + "Post now still works for 2 days.")) return;
  try {
    await api(`/api/videos/${v.id}/instagram`, { method: "POST", json: { action } });
    toast(posted ? "Deleted from Instagram." : "Taken off: it won't be posted on Instagram.", "ok");
    await loadState();
    loaders[currentView()]();
  } catch (e) {
    toast(e.message, "error", 12000);
  }
}

/** Google's page for the one permission Post now, Stop and Delete need (sign-ins from before 26 Oct 2026 only upload
 *  and read); `then` runs once it's given, e.g. the Delete you pressed. */
async function allowManaging(then, action) {
  const after = action ? ` Then the ${{ now: "Post now", stop: "Stop", delete: "Delete" }[action]} finishes by itself.` : "";
  if (!confirm("YouTube hasn't let this app change or delete your videos yet. It needs your OK once.\n\n"
               + "Press OK and Google's page opens in your browser: pick your channel, tick “See, edit, and permanently "
               + `delete your YouTube videos…” (or Select all) and press Continue.${after}\n\n`
               + "If Google warns that it hasn't verified the app: it's your own app, so continue (Advanced → Go to …).")) return;
  try {
    watchTask(await api("/api/tasks/connect", { method: "POST", json: {} }),
              t => t.status === "done" && t.result?.manage && then?.());
  } catch (e) {
    toast(e.message, "error", 9000);
  }
}

function pill(text, tone = "idle") {
  return h("span", { class: "pill", dataset: { tone } }, text);
}

function statusPill(v) {
  const [text, tone] = STATUS[shownStatus(v)] || [v.status, "idle"];
  return pill(text, tone);
}

function pageHead({ eyebrow, agent, title, lede, actions = [] }) {
  return h("header", { class: "page-head" },
    h("div", {},
      h("p", { class: "eyebrow" }, agent && h("i", { class: "agent-dot", dataset: { agent } }), eyebrow),
      h("h1", {}, title),
      lede && h("p", { class: "lede" }, lede)),
    actions.length > 0 && h("div", { class: "actions" }, actions));
}

function kpis(items) {
  return h("div", { class: "kpis" }, items.filter(Boolean).map(({ label, value, unit, note, tone }) =>
    h("div", { class: "kpi", dataset: tone ? { tone } : {} },
      h("p", { class: "kpi-label" }, label),
      h("p", { class: "kpi-value" }, value, unit && h("small", {}, ` ${unit}`)),
      note && h("p", { class: "kpi-note" }, note))));
}

function section({ num, title, text, actions, body, cls = "" }) {
  return h("section", { class: `section ${cls}`.trim() },
    h("div", { class: "section-head" },
      h("div", {}, h("h2", {}, num && h("span", { class: "section-num" }, num), title), text && h("p", {}, text)),
      actions),
    body);
}

function table(head, rows, cls = "") {
  return h("div", { class: "card table-wrap" },
    h("table", { class: `table ${cls}`.trim() },
      h("thead", {}, h("tr", {}, head.map(c => typeof c === "string" ? h("th", {}, c) : h("th", c[1] || {}, c[0])))),
      h("tbody", {}, rows)));
}

function empty(title, text) {
  return h("div", { class: "card" }, h("div", { class: "empty" }, h("h3", {}, title), text && h("p", {}, text)));
}

// What stays usable while the autopilot's run goes on GitHub: it doesn't draw a film or upload.
const CLOUD_OK = ["prepare", "stats"];

function taskButton(kind, label, { primary = false, sm = false, title, videoId, confirmText } = {}) {
  return h("button", { class: `btn${primary ? " btn-primary" : ""}${sm ? " btn-sm" : ""}`, type: "button",
                       "data-needs-idle": true, title, dataset: { cloudOk: CLOUD_OK.includes(kind) ? "1" : "0" },
                       onclick: () => { if (!confirmText || confirm(confirmText)) runTask(kind, videoId); } }, label);
}

/** "Make the 17:30 video now": takes the oldest story that's ready (or writes one), makes its film and uploads it. */
function makeButton({ primary = false, sm = false, short = false } = {}) {
  const a = state.app;
  const nextOpen = a.autopilot.next_open;
  const blocked = !a.services.youtube || !nextOpen;
  return h("button", { class: `btn${primary ? " btn-primary" : ""}${sm ? " btn-sm" : ""}`, type: "button",
    "data-needs-idle": true, dataset: { blocked: blocked ? "1" : "0" },
    title: !a.services.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
         : "Takes the oldest story that's ready (or writes one), makes its film and its short version and uploads them for that slot",
    onclick: () => {
      if (!storyHoursOk("autopilot")) return;
      const when = nextOpen ? `${clockIn(nextOpen, scheduleTz())} (${fromNow(nextOpen)})` : "the next free slot";
      if (confirm(`Make the story for ${when} now?\n\nAgent 5 takes the oldest story that's ready (Agents 1 and 2 write one `
          + "if none is waiting), Agent 3 draws the film and its short version, Agent 4 "
          + "reviews them, and the film is uploaded as private; YouTube makes it public at that time, and its short "
          + `version as a Short ${a.series.short_after_hours} hours later.`)) runTask("autopilot", undefined, {}, true);
    } }, short ? "Make it now" : nextOpen ? `Make the ${clockIn(nextOpen, scheduleTz())} video now` : "Make the next video now");
}

const caseButton = (opts = {}) => taskButton("prepare", "Write a new story",
  { title: "Agent 1 writes the day's brief, your script writer writes the story, Agent 3 designs its pictures", ...opts });

/** The box where you write your own brief: it goes to your script writer word for word, before Agent 1's. */
function requestBox({ onDone } = {}) {
  const input = h("input", { class: "input", placeholder: "e.g. Write a story about GREED. Let the incident cost him his oldest friend.",
                             "aria-label": "Your brief", maxlength: 800 });
  const send = async () => {
    const text = input.value.trim();
    if (!text) return input.focus();
    try {
      await api("/api/topics", { method: "POST", json: { text } });
      input.value = "";
      toast("Added. It's the next story's brief, word for word (a word or two: the next story's topic).", "ok");
      await loadState().catch(() => {});
      if (onDone) onDone();
    } catch (e) {
      toast(e.message, "error", 7000);
    }
  };
  input.addEventListener("keydown", e => { if (e.key === "Enter") send(); });
  return h("div", { class: "request-box" }, input, h("button", { class: "btn btn-primary", type: "button", onclick: send }, "Ask"));
}

// ------------------------------------------------------------------ shell: sidebar, top bar, task

async function loadState() {
  state.app = await api("/api/state");
  renderShell();
  if (state.app.task && state.watching !== state.app.task.id) watchTask(state.app.task);
}

function renderShell() {
  const a = state.app;
  const s = a.services;
  $("#channel-name").textContent = a.channel;
  $("#signout-box").hidden = !a.login;
  document.title = `${a.channel} · Control room`;

  const rows = [
    ["Gemini", s.gemini ? "ok" : "bad", s.gemini ? "Ready" : "Add key", null],
    ["YouTube", s.youtube ? "ok" : "warn", s.youtube ? "Connected" : "Not connected", "#youtube"],
    ["Instagram", s.instagram?.down ? "bad" : s.instagram?.on ? "ok" : "off",
     s.instagram?.down ? "Refused by Meta"
       : s.instagram?.on ? `Reels on${s.instagram.username ? ` · @${s.instagram.username}` : ""}`
       : s.instagram?.connected ? "Connected, Reels off" : "Optional", "#youtube"],
    ["Music", s.music ? "ok" : "warn", s.music ? plural(s.music, "track") : "No tracks", "#music"],
    ["Database", "ok", s.database === "cloud" ? "Cloud" : "This PC", null],
    ["Telegram", s.telegram ? "ok" : "off", s.telegram ? "Alerts on" : "Optional", "#activity"],
  ];
  $("#services").replaceChildren(...rows.map(([name, tone, text, href]) => h("li", {},
    h(href ? "a" : "span", { href },
      h("span", { class: "inline" }, h("span", { class: "dot", dataset: { tone } }), name), h("small", {}, text)))));

  const agent = key => a.agents.find(x => x.key === key);
  $("#count-topics").textContent = a.requests || "";
  $("#count-scripts").textContent = agent("story")?.count || "";
  $("#count-review").textContent = a.held || "";
  $("#count-schedule").textContent = agent("publisher")?.count || "";
  $("#count-music").textContent = s.music || "";

  const ap = a.autopilot;
  const on = !a.paused;
  $("#autopost").checked = on;
  $("#autopost-label").textContent = on ? "Autopilot on" : "Autopilot paused";
  $("#autopost-sub").textContent = !on ? "The agents wait for you"
    : `One story a day at ${ap.schedule.post_at}, ${ap.schedule.ahead !== false ? aheadWords(ap.schedule)
       : `made from ${ap.schedule.make_at}`}${ap.here ? "" : " on GitHub"}`;
  $("#pause-switch").title = "Off stops the autopilot and all automatic work, here and in the cloud "
                             + "(your own buttons keep working)";
  $("#stale").replaceChildren(a.stale ? h("div", { class: "callout banner", dataset: { tone: "warn" }, role: "status" },
    h("b", {}, "The software on this computer was updated after this dashboard started. "),
    a.stale.restarts ? "It restarts by itself with the new version as soon as nothing is running: reload this page in a moment."
      : "It starts no new work on its old code: restart the dashboard (start it with “python app.py” and it restarts by "
        + "itself after updates).") : "");
  syncButtons();
}

function syncButtons() {
  const going = state.task?.status === "running" ? state.task : null;
  const local = state.app?.local !== false;  // in the cloud the scheduled jobs do the work
  for (const b of $$("[data-needs-idle]")) {
    // (the autopilot's run on GitHub: what would draw a film or upload waits for it)
    const waits = Boolean(going) && (!going.cloud || b.dataset.cloudOk !== "1");
    b.disabled = waits || !local || b.dataset.blocked === "1";
  }
}

// Tasks that write or make a story with Gemini. Stories are made after Gemini's free allowance renews (13:30 in India)
// until midnight, so its stronger models write them (your choice, 2026-11-20): outside those hours the page asks first.
const STORY_TASKS = ["prepare", "render", "autopilot"];

/** May a story be written or made now? Inside its hours, yes; outside them, you're asked. */
function storyHoursOk(kind) {
  const g = state.app?.gemini;
  if (!STORY_TASKS.includes(kind) || !g || g.open) return true;
  return confirm(`Stories are made between ${g.opens} and ${g.closes}, after Gemini's free allowance renews, so its `
    + "stronger models write them.\n\nMade now, those models may be used up for today: then a lighter model writes it, "
    + "slowly (it can take half an hour or more) and less well.\n\nMake it now anyway?");
}

async function runTask(kind, videoId, extra = {}, asked = false) {
  if (!asked && !storyHoursOk(kind)) return;
  try {
    watchTask(await api(`/api/tasks/${kind}`, { method: "POST", json: { ...(videoId ? { video_id: videoId } : {}), ...extra } }));
  } catch (e) {
    toast(e.message, "error", 7000);
  }
}

function watchTask(task, after) {
  state.task = task;
  state.watching = task.id;
  renderTask();
  syncButtons();
  const poll = async () => {
    if (state.watching !== task.id) return;
    try {
      state.task = await api(`/api/tasks/${task.id}`);
    } catch (e) {
      state.task = { ...state.task, status: "error", error: e.message };
    }
    renderTask();
    if (state.task.status === "running") return setTimeout(poll, task.cloud ? 10000 : 1000);
    const finished = state.task;  // (finishTask reloads the state, which may follow another task that's going)
    state.watching = null;
    syncButtons();
    await finishTask(finished);
    after?.(finished);
  };
  setTimeout(poll, task.cloud ? 10000 : 700);
}

function taskSummary(t) {
  const r = t.result || {};
  if (typeof r.skipped === "string") return `Nothing to do: ${r.skipped}.`;
  if (t.kind === "cloud") {  // (the autopilot's run on GitHub)
    if (r.made) return `The autopilot's run is done: ${plural(r.made, "story")} made and scheduled.`;
    if (r.stopped) return `The autopilot's run stopped: ${r.stopped}.`;
    return "The autopilot's run is done.";
  }
  if (t.kind === "prepare") {
    const p = r.planned?.[0];
    return p ? `New story: ${p.title}` : "Done.";
  }
  if (t.kind === "render" || r.rendered) {
    return `Film and short version ready (${mmss(r.length)})${r.passed ? ", passed review" : r.held ? ": the Reviewer turned it down, it's made again by itself" : ""}. Press play in the Studio.`;
  }
  if (t.kind === "publish" || t.kind === "autopilot") {
    return r.live_now ? `Posted: ${r.title}. It's live now.` : `Uploaded: ${r.title}. It goes public ${fmtWhen(r.publish_at)}.`;
  }
  if (t.kind === "stats") {
    if (r.skipped) return r.skipped;
    return `Numbers for ${plural(r.updated || 0, "film")}.` + (r.learn?.lessons ? " The playbook is updated." : "");
  }
  if (t.kind === "reel") return r.instagram === "posted" ? "On Instagram now: its Reel is up." : "Done.";
  if (t.kind === "remake") return r.instagram === "pending" ? "Made again: its Reel goes on Instagram at its time." : "Done.";
  if (t.kind === "narrator-sample") return `Sample of ${r.voice}'s voice ready (${secs(r.seconds)}).`;
  if (t.kind === "short") return r.youtube_id ? `Short version uploaded: public ${fmtWhen(r.publish_at)}.` : "Done.";
  if (t.kind === "connect") {
    return `YouTube connected: ${r.channel}` + (r.manage === false ? ". Stop and Delete still can't work: “See, edit, "
      + "and permanently delete your YouTube videos…” was left unticked on Google's page." : "");
  }
  return "Done.";
}

async function finishTask(t) {
  const partly = t.kind === "connect" && t.result?.manage === false;  // connected, but Stop and Delete still can't
  if (t.status === "error") toast(t.error, "error", 9000);
  else toast(taskSummary(t), partly ? "error" : "ok", partly ? 12000 : 6000);
  if (t.kind === "prepare" && t.result?.planned?.length) state.scripts.selected = t.result.planned[0].id;
  await loadState().catch(() => {});
  loaders[currentView()]().catch(() => {});
}

function renderTask() {
  const t = state.task;
  const box = $("#task");
  if (!t) return box.replaceChildren();
  const running = t.status === "running";
  const last = t.steps[t.steps.length - 1];
  const steps = h("ol", { class: "task-steps", hidden: true },
    t.steps.map(s => h("li", {}, h("span", { class: "t" }, `${Math.round(s.at)}s`), h("span", {}, s.text))),
    t.error && h("li", {}, h("span", { class: "t" }, "!"), h("span", { class: "err" }, t.error)),
    !t.steps.length && !t.error && h("li", {}, h("span", { class: "t" }, "0s"),
      h("span", {}, t.cloud ? "This run doesn't report its steps here: they're on its GitHub page." : "Starting…")));
  box.replaceChildren(
    h("div", { class: "task-chip", dataset: { status: t.status } },
      running ? h("span", { class: "spinner", "aria-hidden": "true" })
              : h("span", { class: "task-mark", "aria-hidden": "true" }, t.status === "done" ? "✓" : "!"),
      h("span", { class: "task-text" },
        h("b", {}, running ? `${t.label}…` : t.status === "done" ? `${t.label}: done` : `${t.label}: didn't work`),
        h("small", {}, t.error ? t.error : last ? last.text : t.cloud ? "Working…" : "Starting…")),
      t.cloud && t.url && h("a", { class: "btn btn-sm btn-ghost", href: t.url, target: "_blank", rel: "noopener",
                                   title: "The run's page on GitHub, with its whole log" }, "GitHub ↗"),
      h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: () => { steps.hidden = !steps.hidden; } }, "Steps"),
      !running && h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": "Dismiss",
                                onclick: () => { state.task = null; renderTask(); } }, "✕")),
    steps);
}

// ------------------------------------------------------------------ the agents' runs

/** One line about a run of an agent or a job, from what it logged. */
function runSummary(job, ok, d = {}) {
  if (ok === null) return "Working…";
  if (d.error) return d.error;
  if (typeof d.skipped === "string") return `Skipped: ${d.skipped}`;
  if (job === "theme" && d.topic) return `${cap(d.topic)}${d.kind ? ` (${d.kind})` : ""}${d.title ? `: ${d.title}` : ""}`;
  if (job === "story" && d.shots) return `${d.shots} shots, ${d.words || "?"} words, about ${mmss(d.estimate)}`;
  if (job === "animator" && d.length) return `Story #${d.video_id}: a ${mmss(d.length)} film, made in ${mmss(d.render_seconds)}`
    + (d.voice ? ` · ${String(d.voice).split(" (")[0]}` : "");
  if (job === "reviewer" && d.passed !== undefined) return `Story #${d.video_id}, look ${d.round}: `
    + (d.passed ? `passed${d.notes ? ` (${plural(d.notes, "small note")})` : ""}` : `failed: ${(d.problems || []).slice(0, 2).join("; ")}`);
  if (job === "morning" && d.slots) return `Today's run: ${d.scheduled ? "the story is scheduled" : "the story isn't scheduled"}`
    + (d.made ? " (made in this run)" : "") + (d.missed ? ", its slot had passed before the run" : "")
    + (d.held?.length ? ", turned down by the Reviewer (made again by itself)" : "") + (d.stopped ? ` (${d.stopped})` : "");
  if (d.instagram) return `Reel for #${d.video_id}: ${d.instagram}${d.url ? "" : d.error ? ` (${d.error})` : ""}`;
  if (d.reels) return d.reels.map(x => `Reel #${x.video_id}: ${x.instagram}`).join(", ");
  if (d.youtube_id) return `${d.live_now ? "Posted" : "Uploaded"} #${d.video_id} “${d.title}”, ${d.live_now ? "live now" : `goes public ${fmtWhen(d.publish_at)}`}`;
  if (d.planned) return d.planned.map(p => `#${p.id} ${p.title}`).join(", ") || "Nothing written";
  if (d.rendered) return (d.video_id ? `Film of #${d.video_id} made${d.length ? ` (${mmss(d.length)})` : ""}`
                                     : `Film made: ${d.title || ""}`)
    + (d.passed ? ", passed review" : d.held ? ", turned down by the Reviewer: it's made again by itself" : d.passed === false ? ", failed review" : "")
    + (d.rounds > 1 ? ` after ${plural(d.rounds - 1, "fix")}` : "");
  if (d.updated !== undefined) return `Numbers for ${plural(d.updated, "film")}${d.vetoed ? `, ${d.vetoed} vetoed` : ""}`
    + (d.learn?.lessons ? "; playbook updated" : "");
  return d.what || d.text || "Done";
}

function agentStatus(agent) {
  const last = agent.last;
  const busy = state.task?.status === "running" && (TASK_AGENTS[state.task.kind] || []).includes(agent.key);
  if (busy || (last && last.ok === null && Date.now() - new Date(last.at) < 15 * 6e4)) return ["Working", "run"];
  if (last && last.ok === 0 && Date.now() - new Date(last.at) < 6 * 3.6e6) return ["Hit a snag", "bad"];
  return last ? ["Ready", "ok"] : ["Not run yet", "idle"];
}

function agentAction(key) {
  if (key === "theme") return h("a", { class: "btn btn-sm", href: "#topics" }, "Themes & requests");
  if (key === "story") return caseButton({ sm: true });
  if (key === "animator") return h("a", { class: "btn btn-sm", href: "#studio" }, "Open the Studio");
  if (key === "reviewer") return h("a", { class: "btn btn-sm", href: "#review" }, "See the reviews");
  if (key === "publisher") return makeButton({ sm: true, short: true });
  return taskButton("stats", "Read the numbers", { sm: true });
}

function pipelineSteps() {
  return h("div", { class: "pipeline" }, state.app.agents.map(agent => {
    const [label, tone] = agentStatus(agent);
    const last = agent.last;
    return h("article", { class: "step", dataset: { agent: agent.key } },
      h("div", { class: "step-top" }, h("span", { class: "step-num" }, `0${agent.number}`), pill(label, tone)),
      h("div", { class: "row", style: "gap:10px;flex-wrap:nowrap" }, icon(`em-${agent.key}`, "step-icon"),
        h("div", {}, h("h3", {}, agent.name), h("p", { class: "role" }, agent.role))),
      h("div", { class: "step-metric" }, h("b", {}, agent.count ?? 0), h("span", {}, agent.what)),
      h("p", { class: "step-last", title: last?.detail?.error || "" },
        last ? [last.ok === 0 ? "Failed: " : "Last: ", h("b", {}, runSummary(agent.key, last.ok, last.detail).slice(0, 90)),
                ` · ${fromNow(last.at)}`] : "Hasn't worked yet"),
      agentAction(agent.key));
  }));
}

function runsTable(runs) {
  if (!runs.length) return empty("Nothing has run yet", "The agents' work and the jobs that call them appear here.");
  return table([["When", { class: "col-time" }], "Who", "Result", "What happened"], runs.map(r => {
    const agent = AGENT_KEYS.includes(r.job) ? state.app.agents.find(a => a.key === r.job) : null;
    return h("tr", {},
      h("td", { class: "col-time small" }, fmtWhen(r.started_at)),
      h("td", {}, agent ? h("span", { class: "agent-badge", dataset: { agent: r.job } }, h("i"), `${agent.number} ${agent.name}`)
                        : h("span", { class: "tag" }, r.job)),
      h("td", {}, r.ok === null ? pill("Working", "run") : r.ok === 0 ? pill("Failed", "bad") : pill("Done", "ok")),
      h("td", { class: "log-what" }, runSummary(r.job, r.ok, r.detail || {})));
  }));
}

// ------------------------------------------------------------------ 00 overview

function slotRows(slots) {
  const a = state.app;
  const nextAt = a.autopilot.next?.at;
  return slots.map(s => {
    const v = s.video;
    const waiting = ["due", "late"].includes(s.state);
    const [label, tone] = slotLabel(s, a);
    const live = s.state === "posted";
    const link = v?.youtube_id && h("a", { class: "platform", dataset: { tone: live ? "ok" : "run" }, target: "_blank", rel: "noopener",
      href: live ? `https://www.youtube.com/watch?v=${v.youtube_id}` : `https://studio.youtube.com/video/${v.youtube_id}/edit`,
      title: live ? "Watch on YouTube" : "Open in YouTube Studio" }, live ? "Watch ↗" : "Studio ↗");
    const reel = v?.platforms?.instagram;
    return h("tr", { class: "slot-row", dataset: { state: s.state, next: s.at === nextAt && !a.paused ? "1" : "0" } },
      h("td", { class: "col-time" }, h("b", {}, clockIn(s.at, scheduleTz()))),
      h("td", { class: "col-time muted" }, nyTime(s.at)),
      h("td", {}, pill(label, tone)),
      h("td", {}, reel ? pill(...(ON_INSTAGRAM[reel.state] || [cap(reel.state), "idle"])) : h("span", { class: "muted" }, "–")),
      h("td", { class: "title-cell" }, v
        ? [h("a", { href: `#studio/${v.id}` }, h("b", {}, v.title || `Story #${v.id}`)), v.theme && h("small", {}, cap(v.theme))]
        : h("span", { class: "slot-title muted" }, s.state === "missed" ? "Nothing went out" : "Not made yet")),
      h("td", { class: "col-actions" }, link));
  });
}

/** While Meta refuses Instagram's connection (the token or the Meta app, not one video): what happens to the Reels
 *  meanwhile, and what to do (agents/publisher.py instagram_down). */
function instagramDown(a) {
  const down = a.services.instagram?.down;
  return down && h("div", { class: "callout banner", dataset: { tone: "warn" } },
    h("b", {}, `Instagram has taken no Reels since ${fmtWhen(down.since)}: Meta refuses the connection. `),
    `(${down.error}) The Reels wait, none is given up for this (until 2 days after its slot), and they go up by `
    + "themselves once it works again. To fix it: open developers.facebook.com, My Apps, your app: it shows whether Meta "
    + "blocked or restricted it, and why. With a new app or token, connect Instagram again. ",
    h("a", { href: "#youtube" }, "Channels page →"));
}

/** While YouTube's daily upload limit holds: when it should take the next upload, and that nothing waits for you
 *  (tools/jobs.py upload_room_at). */
function youtubeLimit(a) {
  const lim = a.youtube_limit;
  return lim && h("div", { class: "callout banner", dataset: { tone: "warn" } },
    h("b", {}, `YouTube takes no more uploads until about ${clockIn(lim.room, scheduleTz())}. `),
    `It's the channel's daily upload limit (${lim.count ?? "its"} uploads in 24 hours, deleted ones included). The `
    + "day's story goes up then, by itself: a run in the cloud waits for it, or the next one uploads it, "
    + "and a film already made is kept for it, not made again. Nothing to do.");
}

function overviewLede(a) {
  const sch = a.autopilot.schedule;
  const rhythm = `one story a day, public at ${sch.post_at} (${sch.timezone}), its short version as a Short `
    + `${a.series.short_after_hours} hours later`;
  const made = (sch.ahead !== false
      ? (Number(sch.stories_ahead || 1) > 1
        ? `the stories are kept ${sch.stories_ahead} days ahead (when one goes public, the next is started), when the free quotas allow: `
        : `each story is made as soon as its slot is free (the one before it is public), between ${a.gemini?.opens || "13:30"} and `
          + `${a.gemini?.closes || "00:00"} (after Gemini's free allowance renews), when the free quotas allow: `)
      : `the morning run makes it from ${sch.make_at}: `)
    + "the theme, the story told in bubbles, the film drawn in your look and its short version";
  if (a.paused) return `The autopilot is paused, so the agents wait for you. Switch it on (top right) for ${rhythm}; ${made}.`;
  if (!a.services.youtube) return "The autopilot is on, but YouTube isn't connected yet, so nothing can be posted.";
  return `The autopilot is on: ${rhythm}; ${made}${a.autopilot.here ? "" : " (on GitHub)"}.`;
}

async function loadOverview() {
  const a = state.app;
  const ap = a.autopilot;
  const posted = ap.slots.filter(s => s.state === "posted").length;
  const next = ap.next;
  const run = ap.run;
  const ranToday = run.last && run.last.at >= run.starts;  // (a run since the day's slot opened)
  const ahead = ap.schedule.ahead !== false;
  const runNote = run.running ? "running now"
    : ahead && !run.scheduled && checkStarting(ap) ? "starting now"
    : ahead && !run.scheduled && recentCheck(ap)?.waits ? "waits for the free quotas (Schedule page)"
    : ranToday && run.last.finished ? (run.last.ok ? `done at ${clockIn(run.last.finished, scheduleTz())}` : "stopped early: see Activity")
    : ahead ? "at the next hourly check" : `starts at ${clockIn(run.starts, scheduleTz())}`;
  const root = $("#view-overview");
  const today = new Date(ap.slots[0].at).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", timeZone: scheduleTz() });

  root.replaceChildren(...[
    pageHead({ eyebrow: `00 · ${today}`, title: "Overview", lede: overviewLede(a),
      actions: [caseButton(), makeButton({ primary: true })] }),
    a.held > 0 && h("div", { class: "callout banner" },
      h("b", {}, `The Reviewer turned down ${plural(a.held, "story")} after the Animator's fixes. `),
      "Each is being made again by itself (the scenes it named drawn again, later a new story) until "
      + "the Reviewer passes it; nothing waits for you. ",
      h("a", { href: "#review" }, "Review page →")),
    instagramDown(a),
    youtubeLimit(a),
    kpis([
      { label: "Posted today", value: posted, unit: `/ ${ap.slots.length}` },
      { label: "Next story", value: next ? clockIn(next.at, scheduleTz()) : "–",
        note: next ? `${fromNow(next.at)} · ${nyTime(next.at)} in New York` : "" },
      { label: "Today's run", value: run.scheduled ? "Scheduled" : "–", note: runNote,
        tone: ranToday && !run.running && run.last.ok === 0 ? "warn" : null },
      { label: "Stories ready", value: a.ready ?? "–",
        note: a.held ? `${plural(a.held, "story")} being made again` : "waiting for their slots" },
      { label: "Autopilot", value: a.paused ? "Paused" : "On", tone: a.paused ? "warn" : "ok",
        note: ap.here ? "checks every minute on this PC" : `checks hourly on GitHub${ap.last_check ? `, last ${fromNow(ap.last_check)}` : ""}` },
    ]),
    section({ num: "01–06", title: "The six agents", text: "In order: each one hands its work to the next, and all of them "
      + "learn from the Reviewer's checks and the Analyst's numbers.", body: pipelineSteps() }),
    h("div", { class: "grid-2-1" },
      section({ num: "A", title: "Today's story", text: `On the ${scheduleTz()} clock, with New York time beside it. `
        + "The Schedule page has its buttons for YouTube and Instagram.",
        actions: h("a", { class: "btn btn-sm", href: "#schedule" }, "Full schedule"),
        body: table([["Time", { class: "col-time" }], ["New York", { class: "col-time" }], "YouTube", "Instagram", "Story",
                     ["", { class: "col-actions" }]], slotRows(ap.slots)) }),
      section({ num: "B", title: "Ask for a theme",
        text: a.requests ? `${plural(a.requests, "request")} waiting; Agent 1 takes one that names a theme first.`
                         : "Name one of the themes (Settings): Agent 1 makes it the next story.",
        body: h("div", { class: "card card-pad" }, requestBox()) })),
    h("div", { id: "overview-activity", style: "margin-top:30px" })].filter(Boolean));
  syncButtons();
  const act = await api("/api/activity");
  const box = $("#overview-activity");
  if (box) box.replaceChildren(section({ num: "C", title: "Latest work", text: "What the agents did most recently.",
    actions: h("a", { class: "btn btn-sm", href: "#activity" }, "All activity"),
    body: runsTable(act.runs.slice(0, 6)) }));
}

// ------------------------------------------------------------------ 01 themes (Agent 1)

const REQUEST_STATUS = { waiting: ["Waiting", "accent"], used: ["Made", "ok"], dropped: ["Not made", "idle"] };

/** Agent 1's page: your requests, the themes in turn and the stories named so far. */
async function loadTopics() {
  const t = await api("/api/topics");
  const se = state.app.series;
  const waiting = t.requests.filter(r => r.status === "waiting");
  const month = t.briefs.filter(b => Date.now() - new Date(b.created_at) < 30 * 8.64e7);
  $("#view-topics").replaceChildren(
    pageHead({ eyebrow: "01 · Agent 1 · Theme", agent: "theme", title: "Themes",
      lede: "Agent 1 writes each day's brief for your script writer, the way your examples do: “Write a story about LUST. …” "
        + "(a weakness one day, a virtue the next, never one used in the last few weeks), and now and then “Choose a topic "
        + "yourself. …”, each with a direction of its own. Your own brief comes first, word for word.",
      actions: [caseButton({ primary: true })] }),
    kpis([
      { label: "Your briefs", value: waiting.length, note: "waiting; taken first" },
      { label: "Stories briefed", value: month.length, note: "in the last 30 days" },
      { label: "Vices", value: se.themes.vices.length, note: "in Settings" },
      { label: "Virtues", value: se.themes.virtues.length, note: "in Settings" },
    ]),
    section({ num: "1.1", title: "Your own brief", text: "Write it the way you'd brief the writer (“Write a story about GREED. Let the incident cost him his oldest friend.”): it's sent word for word, before anything Agent 1 would choose. A word or two (“envy”) makes it the next story's topic.",
      body: h("div", {}, h("div", { class: "card card-pad" }, requestBox({ onDone: loadTopics })),
        t.requests.length > 0 && h("div", { style: "margin-top:12px" }, table(
          [["Asked", { class: "col-time" }], "Request", "Status", ["", { class: "col-actions" }]],
          t.requests.map(r => {
            const [label, tone] = REQUEST_STATUS[r.status] || [r.status, "idle"];
            return h("tr", {},
              h("td", { class: "col-time small" }, fmtWhen(r.created_at)),
              h("td", { class: "title-cell" }, h("b", {}, r.text), r.reason && h("small", {}, r.reason)),
              h("td", {}, r.video_id ? h("a", { href: `#studio/${r.video_id}` }, pill(`${label} · #${r.video_id}`, tone)) : pill(label, tone)),
              h("td", { class: "col-actions" }, r.status === "waiting" && h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button",
                onclick: async () => {
                  try { await api(`/api/topics/${r.id}`, { method: "DELETE" }); loadTopics(); loadState(); }
                  catch (e) { toast(e.message, "error"); }
                } }, "Remove")));
          }))) ) }),
    section({ num: "1.2", title: "Stories briefed", text: "Newest first: each brief and the title your writer gave it. Open one in the Studio.",
      body: t.briefs.length
        ? table([["#", { class: "col-num" }], "Theme", "Title and brief", "Why", "Status"], t.briefs.map(b => h("tr", {},
            h("td", { class: "col-num" }, `#${b.id}`),
            h("td", {}, h("span", { class: "tag" }, `${cap(b.theme || (b.mode === "choose" ? "writer's choice" : ""))}${b.kind ? ` · ${b.kind}` : ""}`)),
            h("td", { class: "title-cell" }, h("a", { href: `#studio/${b.id}` }, h("b", {}, b.title || b.theme)), h("small", {}, b.instruction || b.angle)),
            h("td", { class: "small" }, WHY_NOW[b.why_now] || b.why_now || ""),
            h("td", {}, statusPill(b)))))
        : empty("No stories yet", "Press “Write a new story”: Agent 1 writes the brief, your script writer the story, Agent 3 its pictures.") }),
    section({ num: "1.3", title: "The themes", text: "Change them in Settings (S2.1).",
      actions: h("a", { class: "btn btn-sm", href: "#settings" }, "Settings"),
      body: h("div", { class: "grid-2" },
        h("div", { class: "card card-pad" }, h("h3", {}, "Vices"), h("div", { class: "chapters" }, se.themes.vices.map(x => h("span", { class: "tag" }, x)))),
        h("div", { class: "card card-pad" }, h("h3", {}, "Virtues"), h("div", { class: "chapters" }, se.themes.virtues.map(x => h("span", { class: "tag" }, x))))) }));
  syncButtons();
}

// ------------------------------------------------------------------ 02 stories (Agent 2)

async function loadScripts() {
  state.videos = await api("/api/videos");
  const sub = Number(location.hash.split("/")[1]);
  if (sub) {
    state.scripts.selected = sub;
    history.replaceState(null, "", "#scripts");
  }
  renderScripts();
}

function renderScripts() {
  const root = $("#view-scripts");
  const list = state.videos.filter(v => v.status === "planned" && v.story && v.current);
  if (!list.some(v => v.id === state.scripts.selected)) state.scripts.selected = list[0]?.id ?? null;
  renderStories(root, list, list.find(v => v.id === state.scripts.selected));
}

/** The waiting stories, to pick one to edit. */
function caseList(list, selectedId, onPick, note) {
  return h("div", { class: "card studio-list" },
    h("div", { class: "card-head" }, h("h3", {}, plural(list.length, "story")), h("p", {}, note)),
    h("ul", { class: "vlist" }, list.map(v => h("li", {},
      h("button", { class: "vrow", type: "button", "aria-current": String(v.id === selectedId), onclick: () => onPick(v.id) },
        h("span", { class: "vid" }, `#${v.id}`),
        h("span", { class: "vtitle" }, v.title || "A story"),
        h("span", { class: "vmeta" }, h("span", { class: "tag" }, `${cap(v.theme || "")}${v.kind ? ` · ${v.kind}` : ""}`),
          statusPill(v), v.preview && pill("Film made", "ok")))))));
}

/** Asks before throwing away unsaved edits. */
function leaveDirty(id, go) {
  if (state.dirty.has(id) && !confirm("Leave without saving your changes to this story?")) return;
  state.dirty.delete(id);
  go();
}

// ------------------------------------------------------------------ 03 studio (Agent 3)

const STUDIO_FILTERS = [
  ["planned", "Waiting", v => v.status === "planned" || beingMade(v)],
  ["coming", "Coming up", v => (v.status === "making" && !beingMade(v)) || shownStatus(v) === "scheduled"],
  ["published", "Published", v => shownStatus(v) === "live"],
  ["stopped", "Stopped", v => ["failed", "vetoed", "discarded", "skipped", "stopped", "deleted"].includes(v.status)],
];
/** A story the autopilot's run is making that isn't storyboarded yet (being written, or Agent 3 designing it). */
const beingMade = v => v.status === "making" && !v.story && !v.youtube_id && !v.legacy;
const STUDIO_TEXT = {
  planned: "Written stories, and the one the autopilot is making. Their films are made and reviewed ahead; watch one before its turn.",
  coming: "Uploaded as private. Each goes public at its slot, its short version later; delete it in YouTube Studio before then to veto it.",
  published: "Public on YouTube.",
  stopped: "Stories that failed, were stopped or deleted on YouTube, vetoed or discarded.",
};

async function loadStudio() {
  state.videos = await api("/api/videos");
  const sub = Number(location.hash.split("/")[1]);
  if (sub) {  // a link like #studio/12 opens that story on its tab
    const v = state.videos.find(x => x.id === sub);
    if (v) state.studio = { filter: STUDIO_FILTERS.find(([, , test]) => test(v))?.[0] || "planned", selected: v.id, picked: true };
    history.replaceState(null, "", "#studio");
  } else if (!state.studio.picked) {  // until you pick a tab, open on the first one with stories in it
    const first = STUDIO_FILTERS.find(([, , test]) => state.videos.some(test));
    if (first) state.studio.filter = first[0];
  }
  renderStudio();
}

function renderStudio() {
  const root = $("#view-studio");
  const { filter } = state.studio;
  const counts = Object.fromEntries(STUDIO_FILTERS.map(([key, , test]) => [key, state.videos.filter(test).length]));
  const list = state.videos.filter(STUDIO_FILTERS.find(([key]) => key === filter)[2]);
  if (!list.some(v => v.id === state.studio.selected)) state.studio.selected = list[0]?.id ?? null;
  const selected = list.find(v => v.id === state.studio.selected);
  const waiting = state.videos.filter(v => v.status === "planned" && v.story && v.current);

  const tabs = h("div", { class: "segmented", role: "tablist" }, STUDIO_FILTERS.map(([key, label]) =>
    h("button", { type: "button", role: "tab", "aria-selected": String(key === filter),
                  onclick: () => { state.studio = { filter: key, selected: null, picked: true }; renderStudio(); } },
      label, h("span", { class: "n" }, counts[key]))));

  root.replaceChildren(
    pageHead({ eyebrow: "03 · Agent 3 · Animator", agent: "animator", title: "Studio",
      lede: "Agent 3 first storyboards each story: its own places, the people around him and a shot for every moment, "
        + "with the habit the story is about shown big. Then it draws the film in code in your silhouette look (no AI "
        + "pictures, no narrator): what the people say and think in bubbles over their heads, each held long enough to "
        + "read, the music low from the start and lifting at his realization, its thumbnail and a still of every scene. "
        + "Then its short version: the whole story in under a minute for YouTube Shorts and Instagram Reels, the film's "
        + "scenes drawn upright with Agent 2's shorter bubbles. Agent 4 then checks both; one that fails comes back here "
        + "with notes and is fixed.",
      actions: [makeButton()] }),
    kpis([
      { label: "Made", value: waiting.filter(v => v.preview).length, unit: `/ ${waiting.length}`, note: "waiting stories ready to watch" },
      { label: "Passed review", value: waiting.filter(v => v.review?.current && (v.review.passed || v.review.override)).length,
        note: "ready for the Publisher" },
      { label: "Short versions", value: waiting.filter(v => v.short?.video).length, unit: `/ ${waiting.length}`,
        note: "the whole story in under a minute" },
      { label: "Coming up", value: counts.coming, note: "uploaded, not public yet" },
      { label: "Published", value: counts.published, note: "in the last 60 videos" },
    ]),
    section({ num: "3.1", title: "Stories", text: STUDIO_TEXT[filter], actions: tabs,
      body: !state.videos.length
        ? empty("No stories yet", "Press “Write a new story” on the Themes page, then make its film here.")
        : !list.length ? empty(`Nothing ${STUDIO_FILTERS.find(([k]) => k === filter)[1].toLowerCase()}`, STUDIO_TEXT[filter])
        : h("div", { class: "studio" },
            h("div", { class: "card studio-list" },
              h("div", { class: "card-head" }, h("h3", {}, plural(list.length, "story")), h("p", {}, "newest first")),
              h("ul", { class: "vlist" }, list.map(v => h("li", {},
                h("button", { class: "vrow", type: "button", "aria-current": String(v.id === state.studio.selected),
                              onclick: () => { state.studio.selected = v.id; renderStudio(); } },
                  h("span", { class: "vid" }, `#${v.id}`),
                  h("span", { class: "vtitle" }, v.title || (beingMade(v) ? "A new story, being written" : "A story")),
                  h("span", { class: "vmeta" }, statusPill(v),
                    v.legacy ? h("span", { class: "tag" }, v.legacy)
                      : h("span", { class: "tag" }, `${cap(v.theme || "")}${v.kind ? ` · ${v.kind}` : ""}`),
                    v.slot && v.status !== "planned" && h("span", {}, clockIn(v.slot, scheduleTz())),
                    v.status === "planned" && v.current && reviewPill(v)) ))))),
            selected && studioDetail(selected)) }),
    section({ num: "3.2", title: "Missing pieces", text: "What the scripts asked for that the code-drawn library doesn't have "
      + "yet: Agent 3 drew the nearest thing instead. Most wanted first: it's what's added to the library next.",
      body: missingList() }));
  syncButtons();
}

/** The library's missing pieces across the recent stories (filled in when it arrives). */
function missingList() {
  const box = h("div", {}, h("p", { class: "muted" }, "Loading…"));
  api("/api/missing").then(m => box.replaceChildren(m.pieces.length
    ? table(["Missing", "Wanted by"], m.pieces.map(p => h("tr", {}, h("td", {}, h("b", {}, p.what)),
        h("td", { class: "small" }, p.stories.map(id => h("a", { href: `#studio/${id}`, style: "margin-right:8px" }, `#${id}`))))))
    : h("p", { class: "muted" }, "Nothing yet: every script so far could be drawn with what the library has.")))
    .catch(e => box.replaceChildren(h("p", { class: "muted" }, e.message)));
  return box;
}

/** A scheduled story in the Studio: when it goes public, and its YouTube and Instagram parts (as on the Schedule page). */
function scheduledBox(v) {
  const live = v.publish_at && new Date(v.publish_at) <= new Date();
  const part = (id, name, which) => h("div", {}, h("p", { class: "part-name" }, icon(id, "th-ic"), name), platformPart(v, which));
  return h("div", { class: "callout", dataset: { tone: "ok" } },
    live ? "Public since " : "Goes public ", h("b", {}, fmtWhen(v.publish_at)), live ? "" : ` (${fromNow(v.publish_at)})`, ".",
    v.platforms && h("div", { class: "parts" }, part("ic-youtube", "YouTube", "youtube"),
                     part("ic-instagram", "Instagram", "instagram")),
    v.youtube_thumbnail && !v.youtube_thumbnail.set && h("small", { class: "muted", style: "display:block;margin-top:8px" },
      "YouTube kept its own thumbnail: custom ones need a channel verified by phone (youtube.com/verify)."));
}

/** The Reviewer's mark on a waiting story, for the list. */
function reviewPill(v) {
  const r = v.review;
  if (!v.preview) return h("span", {}, "not made yet");
  if (!r || !r.current) return pill("Being reviewed", "run");
  if (r.held) return pill("Being made again", "run");
  if (r.override) return pill("Posting anyway", "warn");
  return r.passed ? pill("Passed review", "ok") : pill("Being fixed", "warn");
}

/** What the Reviewer found in the latest film, what the Animator changed, and the earlier looks. */
function reviewBox(v) {
  const r = v.review;
  if (!v.preview) return null;
  if (!r || !r.current) return h("div", { class: "callout", dataset: { tone: "run" } },
    h("b", {}, "Not reviewed yet. "), "Agent 4 watches it before the Publisher may post it.");
  const major = (r.issues || []).filter(i => i.severity === "major");
  const minor = (r.issues || []).filter(i => i.severity !== "major");
  const tone = r.held ? "run" : r.passed || r.override ? "ok" : "warn";
  const head = r.held ? "Turned down: being made again by itself" : r.override ? "Posting anyway (your call)" : r.passed ? "Passed review" : "Failed review: being fixed";
  const issue = i => h("li", { dataset: { major: i.severity === "major" ? "1" : "0" } },
    pill(i.severity === "major" ? "Problem" : "Note", i.severity === "major" ? "bad" : "idle"),
    h("span", {}, i.detail, i.fix && h("span", { class: "fix" }, `Fix: ${FIXES[i.fix] || i.fix}`)));
  return h("div", { class: "callout review", dataset: { tone } },
    h("div", { class: "review-head" }, h("b", {}, head),
      h("span", { class: "muted" }, `look ${r.round + 1} of up to ${r.max_rounds + 1}${r.at ? ` · ${fromNow(r.at)}` : ""}`)),
    r.held && r.held_because && h("p", {}, r.held_because),
    r.held && h("p", {}, `The Animator makes it again by itself${r.remake_at ? ` at about ${r.remake_at}` : ""} `
      + `(${r.remakes ? `time ${r.remakes + 1}: ` : ""}the scenes it named drawn again; from the third time a new story), `
      + "over and over until the Reviewer passes it. Nothing for you to do."),
    h("div", { class: "measures" },
      r.match != null && h("span", { title: "How much of the narration faster-whisper made out in the final mix" }, `voice ${Math.round(r.match * 100)}%`),
      r.words_per_second != null && h("span", {}, `${r.words_per_second} words/s`),
      r.loudness != null && h("span", {}, `${r.loudness} LUFS`),
      r.look != null && h("span", { title: "Gemini's look at a frame of every scene, 0-10" }, `look ${r.look}/10`)),
    major.length > 0 && h("ul", { class: "issues" }, major.map(issue)),
    r.changes?.length > 0 && h("p", { class: "small" }, h("b", {}, "The Animator changed: "), r.changes.join("; ")),
    minor.length > 0 && h("details", { class: "more" }, h("summary", {}, plural(minor.length, "small note")),
      h("ul", { class: "issues" }, minor.map(issue))),
    r.history?.length > 0 && h("details", { class: "more" }, h("summary", {}, `Earlier ${plural(r.history.length, "look")}`),
      h("ul", { class: "issues" }, r.history.map(x => h("li", {}, pill(x.passed ? "Passed" : "Failed", x.passed ? "ok" : "bad"),
        h("span", {}, `Look ${x.round + 1}: ` + ((x.issues || []).filter(i => i.severity === "major").map(i => i.detail).join("; ") || "no problems"),
          x.changes?.length > 0 && h("span", { class: "fix" }, `Then: ${x.changes.join("; ")}`)))))));
}

/** The thumbnail (1280x720): change its words or pick another scene, and it's made again. */
function thumbEditor(v) {
  const t = v.thumbnail;
  if (!t || (!t.wide && !t.choices?.length)) return null;
  const editable = v.status === "planned" && v.current;
  let picked = t.background;
  const lead = h("input", { class: "input", value: t.lead ?? "", maxlength: 40, disabled: !editable,
                            "aria-label": "The thumbnail's white words", placeholder: "ONE TEXT" });
  const punch = h("input", { class: "input", value: t.punch ?? t.text ?? "", maxlength: 40, disabled: !editable,
                             "aria-label": "The thumbnail's yellow words", placeholder: "DESTROYED EVERYTHING" });
  const stills = h("div", { class: "stills" }, (t.choices || []).map(c => h("button", {
    class: "still", type: "button", title: c.label, disabled: !editable, "aria-pressed": String(c.name === picked),
    onclick: e => { picked = c.name; for (const b of $$(".still", stills)) b.setAttribute("aria-pressed", String(b === e.currentTarget)); } },
    c.thumb ? h("img", { src: c.thumb, alt: c.label, loading: "lazy" }) : c.label)));
  const save = async () => {
    try {
      const updated = await api(`/api/videos/${v.id}/thumbnail`, { method: "POST", json: { lead: lead.value, punch: punch.value, background: picked } });
      Object.assign(v, updated);
      toast("Thumbnail made again.", "ok");
      renderStudio();
    } catch (e) {
      toast(e.message, "error", 7000);
    }
  };
  return h("details", { class: "more", open: true }, h("summary", {}, "Thumbnail"),
    h("div", { class: "thumb-form" },
      t.wide ? h("img", { class: "wide", src: t.wide, alt: "The thumbnail" }) : h("p", { class: "muted" }, "Made with the film."),
      editable && [h("label", { class: "label" }, "White words, above (up to 4)"), lead,
        h("label", { class: "label" }, "Yellow words, big (1-4)"), punch,
        h("label", { class: "label" }, "Scene"), stills,
        h("div", {}, h("button", { class: "btn btn-sm", type: "button", onclick: save }, t.wide ? "Make it again" : "Make the thumbnail"))],
      h("p", { class: "note" }, "YouTube shows it on the film in search, on the home page and beside other videos.")));
}

async function answerReviewer(v, action) {
  const text = action === "post"
    ? `Post “${v.title}” anyway?\n\nThe Reviewer found problems it couldn't get fixed. It goes up at its turn as it is.`
    : `Make “${v.title}” again from scratch?\n\nThe Animator makes a new video (the earlier fixes are forgotten) and the Reviewer checks it.`;
  if (!confirm(text)) return;
  try {
    await api(`/api/videos/${v.id}/review`, { method: "POST", json: { action } });
    toast(action === "post" ? "It goes up at its turn." : "The Animator makes it again by itself shortly.", "ok");
    await loadState();
    loaders[currentView()]();
  } catch (e) {
    toast(e.message, "error");
  }
}

function studioDetail(v) {
  if (beingMade(v)) return makingDetail(v);
  if (v.legacy || !v.story) return legacyDetail(v);
  return storyDetail(v);
}

/** A story the autopilot's run is making: where the run is (the bar at the top has every step), and its script as soon
 *  as your script writer has written it; its storyboard, film and short version follow here as each is made. */
function makingDetail(v) {
  const d = v.draft;
  const cloud = state.app.autopilot.cloud;
  const now = cloud?.steps?.length ? cloud.steps[cloud.steps.length - 1].text : null;
  const where = cloud ? ["The autopilot's run is making it ",
    cloud.url ? h("a", { href: cloud.url, target: "_blank", rel: "noopener" }, "on GitHub ↗") : "on GitHub", ". "]
    : ["The autopilot is making it. "];
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, d?.theme && h("span", { class: "tag" }, cap(d.theme)), statusPill(v),
        h("span", { class: "muted small" }, [`#${v.id}`, v.slot && `for ${fmtWhen(v.slot)}`,
          d?.words && `${d.words} words`, d?.estimate && `~${Math.round(d.estimate / 6) / 10} min`].filter(Boolean).join(" · "))),
      h("h2", {}, d?.title || "A new story"),
      d?.core_message && h("p", { class: "angle" }, d.core_message),
      d?.brief && h("p", { class: "muted small" }, h("b", {}, "The brief: "), d.brief)),
    h("div", { class: "detail-body" },
      h("div", { class: "phone" }, h("div", { class: "phone-blank" },
        d ? "Written. Its moments and bubbles come next, then Agent 3's pictures, then the film."
          : "Being made: its script first, then its moments and bubbles, Agent 3's pictures and the film.")),
      h("div", {},
        h("div", { class: "callout" }, ...where, d ? "Its storyboard, film and short version show here as each is made."
          : "Its script shows here once it's written.", " The bar at the top of the page follows every step."),
        now && h("p", { class: "small" }, h("b", {}, "Now: "), now),
        d?.closing_line && h("p", { class: "muted small" }, "Closing line: ", h("b", {}, d.closing_line)),
        d?.script && h("details", { class: "more", open: true }, h("summary", {}, "The script, as your script writer wrote it"),
          h("p", { class: "desc-ro" }, d.script)))));
}

/** A video made by an earlier version of the channel: shown as it is; the agents don't make or post this kind any more. */
function legacyDetail(v) {
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, statusPill(v), v.legacy && h("span", { class: "tag" }, v.legacy), h("span", { class: "muted small" }, `#${v.id}`)),
      h("h2", {}, v.title || "A video")),
    h("div", { class: "detail-body" },
      h("div", { class: "phone" }, v.preview
        ? h("video", { src: v.preview, controls: true, playsinline: true, preload: "metadata" })
        : h("div", { class: "phone-blank" }, "No video kept for this one.")),
      h("div", {},
        v.status === "scheduled" && scheduledBox(v),
        v.status === "planned" && h("div", { class: "callout", dataset: { tone: "warn" } },
          "Made by an earlier version of the channel. The agents don't make or post this kind any more: discard it."),
        h("details", { class: "more" }, h("summary", {}, "Description"), h("p", { class: "desc-ro" }, v.description || "")))),
    v.status === "planned" && h("div", { class: "detail-actions" },
      h("span", { class: "spacer" }),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")));
}

function upload(v) {
  const slot = state.app.autopilot.next_open;
  const when = slot ? `${fmtWhen(slot)} (${fromNow(slot)})` : "at the next free slot";
  if (!confirm(`Upload “${v.title}” to YouTube?\n\nThe Reviewer checks its film and its short version first (a held one `
             + `isn't posted). The film goes up as private and becomes public ${when}, its short version as a Short `
             + `${state.app.series.short_after_hours} hours later. Until then you can still delete them in YouTube Studio.`)) return;
  runTask("publish", v.id);
}

async function discard(v) {
  if (!confirm(`Discard “${v.title || v.angle}”? It won't be posted.`)) return;
  try {
    await api(`/api/videos/${v.id}`, { method: "DELETE" });
    state.dirty.delete(v.id);
    toast("Discarded.");
    await loadState();
    loaders[currentView()]();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ------------------------------------------------------------------ a story in the Studio

const ACT_NAMES = { ordinary: "His life", falls_apart: "It falls apart", rock_bottom: "Rock bottom", spark: "The spark",
                    work: "The work", dream: "The life he built", turn_down: "The turn-down", closing: "The last word",
                    hook: "The hook", incident: "The major incident", collapse: "The collapse",
                    transformation: "The transformation", payoff: "The dream life" };

/** A stage's name, and the chapter Agent 3 named it ("The hook · “The Double Life”"). */
function stageName(v, act) {
  const own = v.stage_names?.[act];
  return `${ACT_NAMES[act] || cap(act || "")}${own ? ` · “${own}”` : ""}`;
}

/** A story in the Studio: its film and its short version, the Reviewer's verdict, every shot with its bubbles (the
 *  film's and the short version's), the scenes, the thumbnail. */
function storyDetail(v) {
  const editable = v.status === "planned" && v.current;
  const s = state.app.services;
  const nextOpen = state.app.autopilot.next_open;
  const blocked = !s.youtube || !nextOpen;
  const notMade = !editable ? "Uploaded: the film is on YouTube."
    : v.review?.held ? `Turned down by the Reviewer: the Animator makes it again by itself${v.review.remake_at ? ` at about ${v.review.remake_at}` : ""}.`
    : state.app.paused ? "Not made yet. Press “Make it now” (about 15-20 minutes), or switch the autopilot on and the Animator makes it by itself."
    : "Not made yet: the Animator makes it by itself, review included (or press “Make it now”).";
  const film = h("div", { class: "screen" }, v.preview
    ? h("video", { src: v.preview, controls: true, playsinline: true, preload: "metadata", poster: v.cover || undefined })
    : v.cover ? h("img", { src: v.cover, alt: "" }) : h("div", { class: "phone-blank" }, notMade));
  const sv = v.short;
  const short = h("div", { class: "phone" }, sv?.video
    ? h("video", { src: sv.video, controls: true, playsinline: true, preload: "metadata" })
    : h("div", { class: "phone-blank" }, !editable ? "Not kept on this computer."
      : v.preview ? (state.app.paused
        ? "Not made yet: press “Make the short version” (a few minutes), or switch the autopilot on and the Animator makes it by itself."
        : "Not made yet: the Animator makes it from the film by itself (or press “Make the short version”).")
      : "Made after the film: the whole story in under a minute, drawn upright."));
  const shortFacts = sv && [sv.seconds ? `${Math.round(sv.seconds)} s` : sv.estimate ? `~${Math.round(sv.estimate)} s` : "",
    sv.scenes && `${sv.scenes} scenes`, sv.words && `${sv.words} words`].filter(Boolean).join(" · ");
  const length = v.duration ? mmss(v.duration) : v.estimate ? `~${Math.round(v.estimate / 6) / 10} min` : "";
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, h("span", { class: "tag" }, `${cap(v.theme || "")} · ${v.kind || ""}`), statusPill(v),
        h("span", { class: "muted small" }, [`#${v.id}`, length, `${v.shot_count || 0} shots`, `${v.plates?.length || 0} scenes`,
          v.voice?.voice && `narrator: ${v.voice.voice.split(" (")[0]}`].filter(Boolean).join(" · "))),
      h("h2", {}, v.title),
      h("p", { class: "angle" }, v.logline || v.angle),
      v.brief && h("p", { class: "muted small" }, h("b", {}, "The brief: "), v.brief)),
    h("div", { class: "story-top" },
      h("div", {}, film, v.chapters?.length > 0 && h("div", { class: "chapters" }, v.chapters.map(c =>
        h("span", { class: "tag" }, c.at != null ? `${mmss(c.at)} ` : "", c.name))),
        v.closing_line && h("p", { class: "muted small", style: "margin-top:8px" }, "Closing line: ", h("b", {}, v.closing_line))),
      h("div", { class: "story-short" }, h("p", { class: "sub-head", style: "margin-top:0" }, "Short version"), short,
        h("p", { class: "muted small" }, shortFacts || "Shorts and Reels"))),
    h("div", { class: "detail-body single" },
      h("div", {},
        v.status === "planned" && !v.current && h("div", { class: "callout", dataset: { tone: "warn" } },
          h("b", {}, "Made by an earlier version of the channel. "), "Its film was drawn in a look the channel doesn't make any "
          + "more, so it's never uploaded: discard it."),
        editable && reviewBox(v),
        editable && !v.preview && v.preview_failed_at && h("div", { class: "callout", dataset: { tone: "warn" } },
          "The last try to make it didn't work (see Activity). The Animator tries again by itself in about half an hour; "
          + "after three failed tries a new story takes its place."),
        v.status === "making" && v.slot && h("div", { class: "callout", dataset: { tone: "warn" } }, "Being made for the ",
          h("b", {}, clockIn(v.slot, scheduleTz())), " slot right now."),
        v.status === "scheduled" && scheduledBox(v),
        v.status === "scheduled" && shortBox(v),
        v.error && h("div", { class: "callout", dataset: { tone: "bad" } }, v.error),
        v.notes?.length > 0 && editable && h("details", { class: "more" }, h("summary", {}, "The Story writer's notes"),
          h("ul", { class: "issues" }, v.notes.map(n => h("li", {}, n)))),
        h("p", { class: "sub-head" }, v.silent === false ? "The narrator's script" : "The film, shot by shot"),
        storyMoments(v),
        h("p", { class: "sub-head" }, "The short version, shot by shot"),
        shortMoments(v),
        boardPanel(v, editable),
        h("p", { class: "sub-head" }, "The scenes"),
        platesGrid(v),
        thumbEditor(v),
        h("details", { class: "more" }, h("summary", {}, "Description and chapters, as on YouTube"),
          h("p", { class: "desc-ro" }, v.full_description || v.description || "")))),
    v.status === "planned" && !v.current && h("div", { class: "detail-actions" }, h("span", { class: "spacer" }),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")),
    editable && h("div", { class: "detail-actions" },
      v.review?.held && h("button", { class: "btn btn-sm btn-primary", type: "button",
                                      onclick: () => answerReviewer(v, "post") }, "Post it anyway"),
      v.preview ? !v.review?.held && h("button", { class: "btn btn-sm", type: "button", onclick: () => answerReviewer(v, "remake") }, "Make it again")
        : h("button", { class: "btn btn-sm btn-primary", type: "button", "data-needs-idle": true, onclick: () => runTask("render", v.id),
                        title: "Draws the film and its short version, and the Reviewer checks them (nothing is uploaded)" },
            "Make it now"),
      v.preview && !v.short?.video && !v.review?.held && h("button", { class: "btn btn-sm btn-primary", type: "button",
        "data-needs-idle": true, onclick: () => runTask("render", v.id),
        title: "Agent 2 writes its short version if it has none, Agent 3 draws it upright and the Reviewer checks it (the film stays as it is)" },
        "Make the short version"),
      h("a", { class: "btn btn-sm", href: `#scripts/${v.id}` }, "Edit the words"),
      h("button", { class: "btn btn-sm", type: "button", "data-needs-idle": true, dataset: { blocked: blocked ? "1" : "0" },
        title: !s.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
             : `The Reviewer checks it first, then the film goes up as private for the next free slot (${clockIn(nextOpen, scheduleTz())}) and its short version after it`,
        onclick: () => upload(v) }, "Upload & schedule"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")));
}

/** Where a scheduled story's short version stands on YouTube (as a Short). */
function shortBox(v) {
  const t = v.short_upload;
  if (!t) return null;
  if (t.youtube_id) return h("div", { class: "callout" }, "Its short version goes public as a Short ", h("b", {}, fmtWhen(t.publish_at)),
    ` (${fromNow(t.publish_at)}), linking to the film. `,
    h("a", { href: `https://studio.youtube.com/video/${t.youtube_id}/edit`, target: "_blank", rel: "noopener" }, "Short in YouTube Studio ↗"));
  return h("div", { class: "callout", dataset: { tone: "warn" } }, h("b", {}, "The short version didn't go up. "), t.error || "",
    v.short?.video && h("div", { style: "margin-top:8px" }, h("button", { class: "btn btn-sm", type: "button", "data-needs-idle": true,
      onclick: () => runTask("short", v.id) }, "Send the short version")));
}

const BUBBLE_VERBS = { say: "says", think: "thinks", shout: "shouts", picture: "pictures" };

/** A shot's bubbles: who, how (says, thinks, shouts, pictures), the words (a picture's name in brackets) and the second
 *  each comes. */
function bubbleList(bubbles) {
  return h("ul", { class: "bubbles" }, bubbles.map(b => h("li", { dataset: { kind: b.kind } },
    h("span", { class: "bubble-who" }, `${b.who} ${BUBBLE_VERBS[b.kind] || b.kind}`),
    h("span", { class: "bubble-said" }, b.kind === "picture"
      ? `[${String(b.picture || "").replace(/_/g, " ")}]${b.text ? ` “${b.text}”` : ""}` : `“${b.text}”`),
    b.at != null && h("small", { class: "muted" }, mmss(b.at)))));
}

/** One shot of the film or its short version: its stage (on its first shot), its number, its second, what it shows and
 *  its bubbles (a narrated film's line, from before 2026-11-19). */
function momentItem(v, m, k, first, { last = false, film = true } = {}) {
  return h("li", { class: last ? "punch" : "" },
    h("span", { class: "beat-k" }, k + 1),
    h("div", {},
      h("span", { class: "who" }, first ? (film ? stageName(v, m.act) : (ACT_NAMES[m.act] || cap(m.act || ""))) : "", first && " · ",
        h("small", { class: "muted" }, [`${film ? "shot" : "scene"} ${m.shot}`, m.at != null && mmss(m.at),
                                         m.quiet && "quiet"].filter(Boolean).join(" · "))),
      m.shows && h("p", { class: "muted small" }, m.shows),
      m.line && h("p", { class: "line" }, m.line),
      m.bubbles?.length > 0 && bubbleList(m.bubbles)));
}

/** The film shot by shot: what each shows, and what its people say and think. */
function storyMoments(v) {
  const list = v.moments || [];
  if (!list.length) return h("p", { class: "muted" }, v.status === "making" ? "Agents 1 and 2 are still writing it." : "No shots yet.");
  let act = null;
  return h("ol", { class: "script" }, list.map((m, k) => {
    const first = m.act !== act;
    act = m.act;
    return momentItem(v, m, k, first, { last: k === list.length - 1 });
  }));
}

/** The short version shot by shot: the film's scene each shows, with its own shorter bubbles. */
function shortMoments(v) {
  const list = v.short?.shots || [];
  if (!list.length) return h("p", { class: "muted" }, "Agent 2 writes it from the finished film, the first time the "
    + "Animator makes it: some of the film's scenes with shorter bubbles, the whole story in under a minute.");
  let act = null;
  return h("ol", { class: "script" }, list.map((m, k) => {
    const first = m.act !== act;
    act = m.act;
    return momentItem(v, m, k, first, { last: k === list.length - 1, film: false });
  }));
}

/** Agent 3's storyboard: the places it designed for this story, the people around him, what the library lacked. */
function boardPanel(v, editable) {
  if (!v.places?.length) return null;
  return h("div", {},
    h("p", { class: "sub-head" }, "The places"),
    h("div", { class: "plates" }, v.places.map(p => h("figure", { class: "plate" },
      p.thumb ? h("img", { src: p.thumb, alt: p.name || p.id, loading: "lazy" }) : h("div", { class: "plate-blank" }, "not drawn yet"),
      h("figcaption", {}, h("b", {}, p.name || p.id),
        h("span", {}, [p.light, p.weather && p.weather !== "clear" && p.weather, p.words].filter(Boolean).join(" · ")))))),
    h("p", { class: "sub-head" }, "The people"),
    h("ul", { class: "issues" }, h("li", {}, h("span", {}, h("b", {}, "him"), ": always the same man, in his teal hoodie")),
      (v.cast || []).map(c => h("li", {}, h("span", {}, h("b", {}, c.id), `: ${c.role || ""}`,
        c.words && h("span", { class: "muted" }, ` (${c.words})`))))),
    v.realization && h("p", { class: "muted small" }, `The music starts at shot ${v.realization}: his realization.`),
    v.missing?.length > 0 && h("details", { class: "more" }, h("summary", {}, `Missing from the library (${v.missing.length})`),
      h("ul", { class: "issues" }, v.missing.map(m => h("li", {}, m)))),
    editable && v.board_notes?.length > 0 && h("details", { class: "more" }, h("summary", {}, "What code changed in the storyboard"),
      h("ul", { class: "issues" }, v.board_notes.map(n => h("li", {}, n)))));
}

/** The story's scenes: a still of every shot, drawn in code. */
function platesGrid(v) {
  if (!v.plates?.length) return h("p", { class: "muted" }, "No scenes yet.");
  return h("div", { class: "plates" }, v.plates.map(p => h("figure", { class: "plate" },
    p.thumb ? h("a", { href: p.thumb, target: "_blank", title: "Full size" }, h("img", { src: p.thumb, alt: p.scene, loading: "lazy" }))
      : h("div", { class: "plate-blank" }, "not drawn yet"),
    h("figcaption", {}, h("b", {}, p.id), p.redraws ? ` · drawn ${p.redraws + 1} times` : "", h("span", {}, p.scene)))));
}

// ------------------------------------------------------------------ 02 stories (Agent 2): the page itself

function renderStories(root, list, selected) {
  const avg = list.length ? list.reduce((n, v) => n + (v.estimate || 0), 0) / list.length : 0;
  root.replaceChildren(
    pageHead({ eyebrow: "02 · Agent 2 · Story", agent: "story", title: "Stories",
      lede: "Agent 2 is your script writer: your own prompt, word for word, writes each day's story from Agent 1's brief, "
        + "in its six stages (the hook, the major incident, the collapse, rock bottom, the transformation, the dream life), "
        + "with its title, its core message and its closing line. There's no narrator: Agent 2 then turns the story into "
        + "moments, what we see and what the people say and think in bubbles, and code checks the channel's rules (adults "
        + "only, nothing explicit, no gore, no brands, the length). Change any bubble's words before the film is made.",
      actions: [caseButton({ primary: true })] }),
    kpis([
      { label: "Waiting", value: list.length, note: "written, not posted yet", tone: list.length ? null : "warn" },
      { label: "Average length", value: avg ? (Math.round(avg / 6) / 10) : "–", unit: avg ? "min" : "", note: "estimated from the words" },
      { label: "Bubbles", value: list.length ? Math.round(list.reduce((n, v) => n + (v.bubble_count || 0), 0) / list.length) : "–",
        note: "in a story, on average: what its people say and think" },
      { label: "Posting", value: state.app.series.post_at, note: `its short version ${state.app.series.short_after_hours} h later` },
    ]),
    section({ num: "2.1", title: "Stories waiting", text: "The autopilot posts the ready ones oldest first, one a day.",
      body: !list.length
        ? empty("Nothing written yet", "Press “Write a new story”: Agent 1 picks the theme and title, Agent 2 writes it (a minute or two).")
        : h("div", { class: "studio" },
            caseList([...list].reverse(), state.scripts.selected,
                     id => leaveDirty(state.scripts.selected, () => { state.scripts.selected = id; renderScripts(); }), "oldest last"),
            selected && storyEditor(selected)) }));
  syncButtons();
}

/** The story's words to edit: its title, every bubble's words, and the closing line (the end quote). */
function storyEditor(v) {
  const dirty = () => state.dirty.add(v.id);
  const title = h("input", { class: "input", value: v.title || "", maxlength: 60, oninput: dirty, "aria-label": "The title" });
  const closing = h("input", { class: "input", value: v.closing_line || "", maxlength: 200, oninput: dirty, "aria-label": "The closing line" });
  const shots = (v.moments || []).filter(m => m.bubbles?.length).map(m => ({ m, inputs: m.bubbles.map((b, i) => {
    const text = h("input", { class: "input", value: b.text || "", maxlength: 90, oninput: dirty,
                              placeholder: b.kind === "picture" ? "a few words with the picture (optional)" : "",
                              "aria-label": `Shot ${m.shot}, bubble ${i + 1}` });
    return { b, i, text };
  }) }));
  const save = async () => {
    const bubbles = shots.flatMap(({ m, inputs }) => inputs.filter(x => x.text.value.trim() !== (x.b.text || "").trim())
      .map(x => ({ shot: m.shot, bubble: x.i + 1, text: x.text.value })));
    try {
      const updated = await api(`/api/videos/${v.id}`, { method: "PATCH", json: {
        title: title.value, closing_line: closing.value, bubbles } });
      state.dirty.delete(v.id);
      Object.assign(v, updated);
      toast("Saved. The Animator makes the film again with the new words.", "ok");
      renderScripts();
    } catch (e) {
      toast(e.message, "error", 8000);
    }
  };
  const who = b => `${b.who} ${BUBBLE_VERBS[b.kind] || b.kind}${b.kind === "picture" ? ` [${String(b.picture || "").replace(/_/g, " ")}]` : ""}`;
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, h("span", { class: "tag" }, `${cap(v.theme || "")} · ${v.kind || ""}`), statusPill(v),
        h("span", { class: "muted small" }, `#${v.id} · ${v.bubble_count || 0} bubbles · ~${Math.round((v.estimate || 0) / 6) / 10} min`)),
      h("h2", {}, v.title), h("p", { class: "angle" }, v.logline)),
    h("div", { class: "detail-body single" }, h("div", {},
      h("label", { class: "label" }, "Title"), title,
      h("p", { class: "sub-head" }, "The bubbles"),
      shots.length ? h("ol", { class: "script" }, shots.map(({ m, inputs }) => h("li", {},
        h("span", { class: "beat-k" }, m.shot),
        h("div", { style: "display:grid;gap:6px" },
          h("span", { class: "who" }, stageName(v, m.act), h("small", { class: "muted" }, ` · shot ${m.shot}`)),
          m.shows && h("p", { class: "muted small" }, m.shows),
          inputs.map(({ b, text }) => h("label", { class: "bubble-edit", dataset: { kind: b.kind } },
            h("span", { class: "bubble-who" }, who(b)), text))))))
        : h("p", { class: "muted" }, "Its bubbles come with its storyboard, when the Animator makes the film; then their "
            + "words can be changed here."),
      h("label", { class: "label", style: "margin-top:12px" }, "Closing line (the end quote: shown on screen at the end)"),
      closing)),
    h("div", { class: "detail-actions" },
      h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: save }, "Save"),
      h("a", { class: "btn btn-sm", href: `#studio/${v.id}` }, "Open in the Studio")));
}

// ------------------------------------------------------------------ L2 the look

/** The look every story is drawn in: the silhouettes, the bubbles its people talk and think in, its habit shown big. */
function loadLook() {
  const item = (head, text) => h("li", {}, h("b", {}, head), text);
  $("#view-host").replaceChildren(
    pageHead({ eyebrow: "L2 · Library", title: "The look",
      lede: "Every story is drawn in code in your own look (your description, kept word for word and encrypted): black "
        + "silhouettes with a thin red rim, two white eyes, his teal hoodie, film light, letterbox bars and grain. There's "
        + "no narrator: the people talk and think in bubbles, and the habit each story is about is shown big." }),
    section({ num: "L2.1", title: "The bubbles", text: "What the people say and think, drawn over their heads in the same look.",
      body: h("div", { class: "card card-pad" }, h("ul", { class: "lessons" },
        item("Four kinds: ", "a rounded speech bubble when people talk to each other, a thought cloud when he's alone, a "
          + "spiky burst for a shout (swearing only as “#@%!”), and a cloud with a small picture in it."),
        item("How they look: ", "a cream fill, the thin coral-red rim and dark plum letters; at most 12 words and 3 rows."),
        item("Time to read: ", "1 second to find a bubble, then 2.5 words a second (at least 2.5 seconds; a picture 2.5 "
          + "seconds, 1 more with words). In a conversation the earlier bubble stays, dimmed, until the reply is read: at "
          + "most two on screen."),
        item("The end quote: ", "the closing line is shown on screen at the end, as before."))) }),
    section({ num: "L2.2", title: "The habit, shown big", text: "Each story's own habit, exaggerated like a cartoon. No piece "
      + "belongs to a topic: the storyboard picks what fits the story.",
      body: h("div", { class: "card card-pad" }, h("ul", { class: "lessons" },
        item("Eyes: ", "hearts, dollar signs, spirals, droopy, furious, side-eye, smug, sobbing, terrified, on fire."),
        item("Marks round the head: ", "steam, a throbbing vein, sweat, drool, Zzz, hearts, $, a rain cloud, flies, dizzy "
          + "stars, a jolt, trembling, “?”, “!”, sparkles, auras, notification dots."),
        item("Actions, things and effects: ", "31 exaggerated actions, 17 things that overdo a place, 9 effects (the room "
          + "flushing red, the colours draining, time racing by, the camera shaking...), a phone seen face-on with 8 "
          + "screens, and 66 small pictures for the bubbles."),
        item("Always used: ", "code checks that every storyboard shows its habit big in at least 6 shots of his fall (a "
          + "virtue: 4 before his realization and 2 after), and adds it itself when one falls short."))) }),
    section({ num: "L2.3", title: "Tests", text: "The look's tests, made on this computer.",
      body: h("p", {}, h("a", { href: "/style-test" }, "See the style tests →")) }));
  syncButtons();
}

/** The stories' own settings card (Settings, S2.1): saved on its own. */
function seriesCard(s) {
  const se = s.series || {};
  const ro = !s.editable;
  const row = (label, hint, control) => h("div", { class: "form-row" },
    h("div", {}, h("label", { class: "label" }, label), hint && h("p", { class: "hint" }, hint)), h("div", {}, control));
  const postAt = h("input", { class: "input", type: "time", value: se.post_at || "17:30", disabled: ro });
  const after = h("input", { class: "input", type: "number", min: 0, max: 12, step: 0.5, value: se.short_after_hours ?? 3, disabled: ro });
  const low = h("input", { class: "input", type: "number", min: 2, max: 8, step: 0.5, value: (se.minutes || [3, 4])[0], disabled: ro });
  const high = h("input", { class: "input", type: "number", min: 2, max: 10, step: 0.5, value: (se.minutes || [3, 4])[1], disabled: ro });
  const repeat = h("input", { class: "input", type: "number", min: 1, max: 365, value: se.repeat_after_days ?? 30, disabled: ro });
  const vices = h("textarea", { class: "input", rows: 2, disabled: ro });
  vices.value = (se.themes?.vices || []).join(", ");
  const virtues = h("textarea", { class: "input", rows: 2, disabled: ro });
  virtues.value = (se.themes?.virtues || []).join(", ");
  const tags = h("input", { class: "input", value: (se.hashtags || []).join(" "), disabled: ro });
  const list = (text, sep = ",") => String(text || "").split(sep).map(x => x.trim()).filter(Boolean);
  const save = async () => {
    try {
      await api("/api/series", { method: "PUT", json: {
        post_at: postAt.value, short_after_hours: Number(after.value),
        minutes: [Number(low.value), Number(high.value)], repeat_after_days: Number(repeat.value),
        vices: list(vices.value), virtues: list(virtues.value), hashtags: list(tags.value, " ") } });
      toast("Saved. The next stories use it.", "ok");
      await loadState();
      loadSettings();
    } catch (e) {
      toast(e.message, "error", 7000);
    }
  };
  return h("div", { class: "card", id: "set-series" },
    h("div", { class: "card-head" }, h("h3", {}, h("span", { class: "muted", style: "font-family:var(--font-mono);font-weight:500;margin-right:8px" }, "S2.1"), "The stories")),
    row("Goes public at", `Every day, on the schedule's clock (${s.schedule?.timezone}). ${s.schedule?.ahead !== false
      ? (Number(s.schedule?.stories_ahead || 1) > 1 ? `The stories are kept ${s.schedule.stories_ahead} days ahead (S2.3).`
        : "The next story is made as soon as the one before it is public (S2.3).") : `It's made by the morning run (${s.schedule?.make_at}).`}`, postAt),
    row("Short version", "Hours after the film it goes public as a Short (the whole story in under a minute); it's also the Reel when Instagram is on.", after),
    row("Length", "Minutes, shortest and longest.", h("div", { class: "inline-fields" }, low, high)),
    row("Vices", "Agent 1 alternates a vice and a virtue. Commas between themes.", vices),
    row("Virtues", null, virtues),
    row("Repeat a theme after", "Days before a theme comes back.", repeat),
    row("Hashtags", "On every film and short version (#shorts only on the short version), plus the theme's own.", tags),
    h("div", { class: "savebar" }, h("button", { class: "btn btn-primary", type: "button", disabled: ro, onclick: save }, "Save the stories' settings")));
}

// ------------------------------------------------------------------ 04 review (Agent 4)

const ISSUE_KINDS = { too_dark: "Too dark to see", hard_to_read: "Hard to read", mismatch: "Doesn't show the shot",
                      broken_picture: "Broken picture", unsuitable: "Unsuitable", off_look: "Outside the look",
                      text_unreadable: "Text hard to read", unclear: "Narrator unclear", not_narrator: "Not the narrator's voice",
                      bubbles: "Bubbles", bubble_short: "A bubble too short to read", bubble_wrong: "A bubble misplaced",
                      habit_not_shown: "The habit not shown big", short_bubbles: "Short version: bubbles",
                      short_bubble_short: "Short version: a bubble too short to read",
                      short: "Short version", short_length: "Short version's length",
                      short_unclear: "Short version: narrator unclear", short_voice: "Short version: not his voice",
                      length: "Length", loudness: "Loudness", silence: "Silence", size: "Wrong size",
                      sound: "No sound", dark: "Very dark stretch", peak: "Peaks", look: "The look" };

async function loadReview() {
  const r = await api("/api/review");
  const firsts = r.history.filter(x => x.round === 0);
  const firstPass = firsts.filter(x => x.passed).length;
  const finals = Object.values(r.history.reduce((m, x) => (m[x.video_id] ??= x, m), {}));  // newest look of each story
  const fixed = finals.filter(x => x.passed && x.round > 0).length;
  const counts = r.lessons.counts || {};
  const taught = r.lessons.for || {};
  const c = r.checks;
  const names = Object.fromEntries(state.app.agents.map(a => [a.key, `${a.number} ${a.name}`]));
  $("#view-review").replaceChildren(...[
    pageHead({ eyebrow: "04 · Agent 4 · Reviewer", agent: "reviewer", title: "Review",
      lede: "Agent 4 watches every film and its short version before the Publisher may post them. One that "
            + `fails goes back to the Animator with notes, at most ${plural(r.max_rounds, "time")} (only the short version is `
            + "made again when only it failed); one that still fails is made again by itself, until it passes. "
            + "Problems that keep coming back become lessons the other agents apply from then on." }),
    kpis([
      { label: "Passed at first look", value: firsts.length ? `${Math.round(firstPass / firsts.length * 100)}` : "–",
        unit: firsts.length ? "%" : "", note: `of the last ${plural(firsts.length, "film")}` },
      { label: "Fixed by the Animator", value: fixed, note: "failed, then passed" },
      { label: "Being made again", value: r.held.length, note: "turned down after the fixes: made again by themselves" },
      { label: "Lessons taught", value: Object.values(taught).reduce((n, t) => n + (t.advice?.length || 0), 0),
        note: r.lessons.updated_at ? `updated ${fromNow(r.lessons.updated_at)}` : "none yet" },
    ]),
    r.held.length > 0 && section({ num: "4.1", title: "Being made again", text: "Turned down after the Animator's fixes: each is made again by itself (the scenes it named drawn again; from the third time a new story), until the Reviewer passes it. Nothing for you to do.",
      body: table(["Story", "Why it was turned down", "Next making"], r.held.map(x => h("tr", {},
        h("td", { class: "title-cell" }, h("a", { href: `#studio/${x.id}` }, h("b", {}, x.title || `Story #${x.id}`))),
        h("td", { class: "small" }, x.because || ""),
        h("td", { class: "small" }, `${x.remake_at ? `about ${x.remake_at}` : "next"}${x.remakes ? ` (time ${x.remakes + 1})` : ""}`)))) }),
    section({ num: "4.2", title: "What it checks", text: "On the finished film and its short version, the way a viewer sees and hears them.",
      body: h("div", { class: "card card-pad" }, h("ul", { class: "lessons" },
        h("li", {}, h("b", {}, "Size and length: "), `the film 1920×1080, ${c.minutes[0]}-${c.minutes[1]} minutes; the short version 1080×1920, `
          + `under a minute (${c.short_seconds[0]}-${c.short_seconds[1]} seconds is the aim; under ${c.short_least} or ${c.short_most} and over fails), with sound.`),
        h("li", {}, h("b", {}, "The short version: "), "its bubbles measured like the film's, and 4 of its frames in the "
          + "look below (its first shot, two scenes, its closing line). A problem only it has is fixed in it alone: "
          + "the sounds under it, or a new script from Agent 2."),
        h("li", {}, h("b", {}, "Sound: "), `loudness near ${c.loudness} LUFS, no clipping, no dead silence.`),
        h("li", {}, h("b", {}, "The bubbles: "), `at least ${c.bubbles_least} in a film (its people talk and think), each on screen long enough to read (1 second to find it, then 2.5 words a second), none past the end; in the frames, none over a face, cut off or pointing at the wrong person.`),
        h("li", {}, h("b", {}, "The habit: "), "shown big where the story needs it, in his fall: exaggerated eyes, marks round his head, exaggerated actions."),
        h("li", {}, h("b", {}, "The look: "), `Gemini looks at a frame of every scene (up to ${c.frames}), the title and the closing line, against what each should show and your look description: too dark, unreadable, broken, unsuitable or outside the look sends that scene back to be drawn again.`))) }),
    section({ num: "4.3", title: "Lessons it has taught", text: `A problem in ${c.recurring} of the last ${c.lookback} first looks becomes a standing fix or advice.`,
      body: Object.keys(taught).length
        ? h("div", { class: "taught" }, Object.entries(taught).map(([agent, t]) => h("div", { class: "card card-pad", dataset: { agent } },
            h("span", { class: "agent-badge", dataset: { agent } }, h("i"), names[agent] || agent),
            Object.keys(t.settings || {}).length > 0 && h("div", {}, Object.entries(t.settings).map(([k, x]) => h("span", { class: "setting-chip" }, `${k}: ${x}`))),
            h("ul", {}, (t.advice || []).map(a => h("li", {}, a))))))
        : empty("Nothing yet", "Lessons appear once the same problem turns up again and again.") }),
    Object.keys(counts).length > 0 && section({ num: "4.4", title: "What it finds most", text: `In the last ${plural(firsts.length, "first look")}.`,
      body: h("div", { class: "card card-pad" }, h("div", { class: "rounds" },
        Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => h("span", { class: "tag" }, `${ISSUE_KINDS[k] || k} · ${n}`)))) }),
    section({ num: "4.5", title: "Recent reviews", text: "Newest first; each look at a film is a row.",
      body: r.history.length
        ? table([["When", { class: "col-time" }], "Story", "Look", "Result", "Problems"], r.history.slice(0, 30).map(x => h("tr", {},
            h("td", { class: "col-time small" }, fmtWhen(x.at)),
            h("td", { class: "title-cell" }, h("a", { href: `#studio/${x.video_id}` }, h("b", {}, x.title || `Story #${x.video_id}`))),
            h("td", {}, `${x.round + 1}`),
            h("td", {}, x.passed ? pill("Passed", "ok") : pill("Failed", "bad")),
            h("td", { class: "small" }, (x.kinds || []).map(k => ISSUE_KINDS[k] || k).join(", ") || "–"))))
        : empty("No reviews yet", "Every film is reviewed once it's made.") })].filter(Boolean));
}

// ------------------------------------------------------------------ 05 schedule (Agent 5)

/** What a story's YouTube or Instagram part says beside its state, e.g. "goes public 17:30 · in 2 hours". */
function partDetail(p, which) {
  const at = iso => iso ? `${onClock(iso)} · ${fromNow(iso)}` : "at its slot";
  if (which === "youtube") {
    return { making: "uploaded once it's made and reviewed",
             scheduled: `goes public ${at(p.at)}${p.processing ? " · YouTube is still processing it" : ""}`,
             public: p.at ? `since ${onClock(p.at)}` : "",
             hidden: `made ${p.privacy === "unlisted" ? "unlisted" : "private"} in YouTube Studio: it won't go public by itself`,
             rejected: `YouTube rejected it${p.why ? ` (${p.why})` : ""}`,
             gone: "deleted in YouTube Studio: Delete clears it here" }[p.state] || "";
  }
  return { making: "goes once it's on YouTube",
           none: p.why || "",
           waiting: `goes ${at(p.at)}`,
           due: state.app.paused ? "the autopilot is paused: Post now sends it" : "goes within a minute",
           retry: `tries again ${p.retry_at ? onClock(p.retry_at) : "soon"}${p.error ? ` · ${p.error}` : ""}`,
           posting: "sending it to Instagram",
           posted: p.posted_at ? `since ${onClock(p.posted_at)}` : "",
           failed: p.error || "",
           skipped: "its short version wasn't public on YouTube at its time",
           expired: "not posted within 2 days of its time (this PC was off)",
           cancelled: p.because || "you took it off",
           deleted: "deleted from Instagram",
           remaking: "its short version made again for Instagram, then it waits for its time" }[p.state] || "";
}

/** Why a button on a story's YouTube or Instagram part is greyed out. */
function partWhy(p, which, action) {
  if (which === "instagram") {
    if (action === "now") return p.why;
    if (action === "open") return "It isn't on Instagram";
    return p.state === "posted" ? "Connect Instagram first (the Channels page)"
      : p.state === "posting" ? "It's being posted right now" : "There's no Reel to delete or take off";
  }
  if (["making", "gone"].includes(p.state)) return p.state === "making" ? "It isn't on YouTube yet" : "It isn't on YouTube any more";
  if (action === "now") return p.state === "rejected" ? "YouTube rejected it" : "It's public already";
  return "It's public already: make it private in YouTube Studio";
}

/** A story's part on YouTube or on Instagram: where it stands there, and Open, Post now and Delete (and Stop on
 *  YouTube), each greyed out with the reason when it can't be done now. */
function platformPart(v, which) {
  const p = v.platforms?.[which];
  if (!p) return h("span", { class: "muted" }, "–");
  const yt = which === "youtube";
  const [label, tone] = (yt ? ON_YOUTUBE : ON_INSTAGRAM)[p.state] || [cap(p.state), "idle"];
  const detail = partDetail(p, which);
  const button = (action, text, danger = false) => h("button", {
    class: `btn btn-xs${danger ? " btn-danger" : ""}`, type: "button", disabled: !p.can[action],
    title: p.can[action] ? null : partWhy(p, which, action), onclick: () => (yt ? youtubeAction : instagramAction)(v, action) }, text);
  const href = yt ? p.url : p.url || p.profile;
  const open = p.can.open
    ? h("a", { class: "btn btn-xs", href, target: "_blank", rel: "noopener",
               title: yt ? (p.state === "public" ? "Watch it on YouTube" : "Open it in YouTube Studio")
                         : p.url ? "Open the Reel on Instagram" : "Instagram didn't give the Reel's own link: your profile" },
        "Open ↗")
    : h("button", { class: "btn btn-xs", type: "button", disabled: true, title: partWhy(p, which, "open") }, "Open ↗");
  return h("div", { class: "part", dataset: { platform: which } },
    h("div", { class: "part-state" }, pill(label, tone), detail && h("small", { title: detail }, detail)),
    h("div", { class: "part-actions" }, open,
      !yt && p.can.schedule
        ? h("button", { class: "btn btn-xs", type: "button", title: "Makes its short version again, then its Reel waits for "
                        + "its time", onclick: () => instagramAction(v, "schedule") }, "Schedule")
        : button("now", "Post now"),
      yt && button("stop", "Stop"), button("delete", "Delete", true)));
}

const partHead = (id, name) => [[icon(id, "th-ic"), name], { class: "col-part" }];
const partCell = (v, which) => h("td", { class: "col-part", "data-label": which === "youtube" ? "YouTube" : "Instagram" },
  v ? platformPart(v, which) : h("span", { class: "muted" }, "–"));

/** A slot on the Schedule page: its time, its story, and the story's YouTube and Instagram parts. */
function scheduleRow(s) {
  const a = state.app;
  const v = s.video;
  const [label, tone] = slotLabel(s, a);
  return h("tr", { class: "slot-row", dataset: { state: s.state, next: s.at === a.autopilot.next?.at && !a.paused ? "1" : "0" } },
    h("td", { class: "col-time" }, h("b", {}, clockIn(s.at, scheduleTz()))),
    h("td", { class: "col-time muted" }, nyTime(s.at)),
    h("td", { class: "title-cell" }, v
      ? [h("a", { href: `#studio/${v.id}` }, h("b", {}, v.title || `Story #${v.id}`)), v.theme && h("small", {}, cap(v.theme))]
      : [pill(label, tone), h("small", {}, s.state === "missed" ? "Nothing went out" : "Not made yet")]),
    partCell(v, "youtube"), partCell(v, "instagram"));
}

async function loadSchedule() {
  const a = state.app;
  const ap = a.autopilot;
  const data = await api("/api/schedule");
  const now = new Date();
  const stories = [...data.slots.map(s => s.video).filter(Boolean), ...data.later];
  const ahead = stories.filter(v => v.status === "scheduled" && v.publish_at && new Date(v.publish_at) > now).length;
  const posted = data.slots.filter(s => s.state === "posted").length;
  const ig = a.services.instagram || {};
  $("#view-schedule").replaceChildren(...[
    pageHead({ eyebrow: "05 · Agent 5 · Publisher", agent: "publisher", title: "Schedule",
      lede: "Agent 5 uploads each story that passed the Reviewer as private with its slot as the publish time, so YouTube "
            + "makes it public on the minute (Film & Animation, its chapters, how it was made and the music's credit in "
            + "the description, its thumbnail), then its short version (the whole story in under a minute) as a Short, "
            + `public ${a.series.short_after_hours} hours later and linking to the film. With Instagram on, the short version `
            + "also goes up as a Reel at its time. Beside each story: where it stands on YouTube and on Instagram, with "
            + "Open, Post now and Delete for each (and Stop, which keeps the film and its short version private on YouTube).",
      actions: [h("a", { class: "btn", href: "#settings" }, "Change the time"), makeButton({ primary: true })] }),
    kpis([
      { label: "Posted today", value: posted, unit: `/ ${data.slots.length}` },
      { label: "Next story", value: ap.next ? clockIn(ap.next.at, scheduleTz()) : "–", note: ap.next ? fromNow(ap.next.at) : "" },
      { label: "Scheduled ahead", value: ahead, note: "uploaded, waiting to go public" },
      { label: "Next free slot", value: ap.next_open ? clockIn(ap.next_open, scheduleTz()) : "–",
        note: ap.next_open ? fromNow(ap.next_open) : "every slot this week is taken" },
      { label: "Reels", value: ig.connected ? (ig.on ? "On" : "Off") : "–",
        note: ig.connected ? (ig.on ? "each short version also goes on Instagram" : "Reels are switched off") : "Instagram isn't connected" },
    ]),
    a.services.youtube && !a.services.youtube_manage && h("div", { class: "callout banner", dataset: { tone: "warn" } },
      h("b", {}, "Post now, Stop and Delete need your OK on YouTube once. "),
      a.local !== false
        ? h("span", {}, "Google's page asks whether this app may change or delete your videos. ",
            h("button", { class: "btn btn-sm", type: "button", onclick: () => allowManaging() }, "Allow it now"))
        : "Allow it from the dashboard on your computer; until then use YouTube Studio."),
    !ig.connected && h("div", { class: "callout banner" },
      h("b", {}, "Instagram isn't connected yet, "), "so its side shows “Not for Instagram”. Connect it on the ",
      h("a", { href: "#youtube" }, "Channels page"), ": the stories uploaded after that get their Reels."),
    instagramDown(a),
    youtubeLimit(a),
    data.youtube.error && h("div", { class: "callout banner", dataset: { tone: "warn" } },
      h("b", {}, "YouTube didn't say how they stand just now "), `(${data.youtube.error}). The YouTube side shows what `
      + "the dashboard knows; it asks again in 2 minutes."),
    section({ num: "5.1", title: "Today's story", text: `One story a day at ${ap.schedule.post_at} (${scheduleTz()}), ${ap.schedule.ahead !== false
      ? `${aheadWords(ap.schedule)}, when the free quotas allow` : `made in the morning run from ${ap.schedule.make_at}`}.${checkNote(ap)}`,
      body: table([["Time", { class: "col-time" }], ["New York", { class: "col-time" }], "Story",
                   partHead("ic-youtube", "YouTube"), partHead("ic-instagram", "Instagram")],
                  data.slots.map(scheduleRow), "schedule") }),
    data.later.length > 0 && section({ num: "5.2", title: "Later days", text: "Uploaded for a later day, private on YouTube until their time.",
      body: table([["Goes public", { class: "col-time" }], "Story", partHead("ic-youtube", "YouTube"), partHead("ic-instagram", "Instagram")],
        data.later.map(v => h("tr", {},
          h("td", { class: "col-time" }, onClock(v.publish_at), h("small", { class: "muted", style: "display:block" }, fromNow(v.publish_at))),
          h("td", { class: "title-cell" }, h("a", { href: `#studio/${v.id}` }, h("b", {}, v.title)), v.theme && h("small", {}, cap(v.theme))),
          partCell(v, "youtube"), partCell(v, "instagram"))), "schedule") })].filter(Boolean));
  syncButtons();
}

// ------------------------------------------------------------------ 06 results (Agent 6)

const LIFT_KINDS = [["theme", "Theme"], ["kind", "Vice or virtue"], ["title_pattern", "The title's shape"], ["motif", "Motif"],
                    ["length", "Length"], ["voice", "Narrator"], ["hashtag", "Hashtags"], ["review", "Review"],
                    ["hour", "Posting time"]];

function liftCard(title, weights) {
  const entries = Object.entries(weights || {}).sort((a, b) => b[1] - a[1]);
  return h("div", { class: "card card-pad lift" }, h("p", { class: "sub-head" }, title),
    entries.length ? h("ul", {}, entries.map(([name, x]) => {
      const pct = Math.min(Math.abs(x - 1), 1) * 50;
      return h("li", {}, h("span", { class: "lift-name", title: name }, cap(name)),
        h("span", { class: "lift-bar" }, h("span", { class: x >= 1 ? "up" : "down", style: `width:${pct}%` })),
        h("span", { class: "lift-num" }, `${x.toFixed(2)}x`));
    })) : h("p", { class: "note" }, "Not enough films in any group yet."));
}

async function loadResults() {
  const r = await api("/api/results");
  const book = r.playbook;
  const rows = r.rows;
  const views = rows.map(x => x.views);
  const sorted = [...views].sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
  const pcts = rows.map(x => x.avg_view_pct).filter(x => x !== null && x !== undefined);
  $("#view-results").replaceChildren(
    pageHead({ eyebrow: "06 · Agent 6 · Analyst", agent: "analyst", title: "Results",
      lede: "Agent 6 reads YouTube's numbers every day and, once a week, writes the playbook. Long films live by watch "
            + "time, so each film is judged by its views times the share watched, against the channel's usual: by theme, "
            + "title, motif, length, narrator and posting time, with a few lessons for each agent. Every agent reads its "
            + "lessons each time it works; the playbook's weights are followed three times out of four, so the channel "
            + "keeps trying new things.",
      actions: [taskButton("stats", "Read the numbers now", { primary: true })] }),
    kpis([
      { label: "Films published", value: rows.length },
      { label: "Views", value: views.reduce((a, b) => a + b, 0).toLocaleString() },
      { label: "Median views", value: median.toLocaleString() },
      { label: "Average watched", value: pcts.length ? Math.round(pcts.reduce((a, b) => a + b, 0) / pcts.length) : "–",
        unit: pcts.length ? "%" : "", note: "YouTube Analytics, ~2 days late" },
    ]),
    section({ num: "6.1", title: "The playbook", text: book.updated_at ? `Written ${fromNow(book.updated_at)} from ${plural(book.samples, "film")}.` : "",
      body: book.samples
        ? h("div", { class: "card card-pad" }, book.summary && h("p", {}, book.summary),
            book.lessons?.length > 0 && h("ol", { class: "lessons", style: "margin-top:10px" }, book.lessons.map(l => h("li", {}, l))))
        : empty("No playbook yet", `Agent 6 writes one once ${r.min_samples} films are at least 2 days old (${r.judged} so far).`) }),
    section({ num: "6.2", title: "What each agent has learned", text: "From the Analyst's numbers and the Reviewer's checks; each agent reads its own every time it works.",
      body: h("div", { class: "taught" }, state.app.agents.filter(a => a.key !== "analyst").map(a => {
        const t = r.taught?.[a.key] || { settings: {}, advice: [] };
        return h("div", { class: "card card-pad", dataset: { agent: a.key } },
          h("span", { class: "agent-badge", dataset: { agent: a.key } }, h("i"), `${a.number} ${a.name}`),
          Object.keys(t.settings || {}).length > 0 && h("div", {}, Object.entries(t.settings).map(([k, x]) => h("span", { class: "setting-chip" }, `${k}: ${x}`))),
          t.advice?.length ? h("ul", {}, t.advice.map(l => h("li", {}, l))) : h("p", { class: "note" }, "Nothing yet."));
      })) }),
    section({ num: "6.3", title: "What does better than usual", text: `Each group's median watch time against the channel's median; a group needs ${r.min_samples} films.`,
      body: h("div", { class: "lift-grid" }, LIFT_KINDS.map(([key, title]) => liftCard(title, book.weights?.[key]))) }),
    section({ num: "6.4", title: "Films and their numbers", text: "Newest first.",
      body: rows.length
        ? table(["Film", ["Published", { class: "col-time" }], ["Views", { class: "col-right" }], ["Likes", { class: "col-right" }],
                 ["Comments", { class: "col-right" }], ["Watched", { class: "col-right" }]],
            [...rows].reverse().map(x => h("tr", {},
              h("td", { class: "title-cell" }, h("a", { href: `#studio/${x.id}` }, h("b", {}, x.title)),
                h("small", {}, cap(x.traits.theme?.[0] || ""))),
              h("td", { class: "col-time small" }, fmtWhen(x.publish_at)),
              h("td", { class: "col-right" }, x.views.toLocaleString()),
              h("td", { class: "col-right" }, x.likes.toLocaleString()),
              h("td", { class: "col-right" }, x.comments.toLocaleString()),
              h("td", { class: "col-right" }, x.avg_view_pct !== null && x.avg_view_pct !== undefined ? `${Math.round(x.avg_view_pct)}%` : "–"))))
        : empty("No numbers yet", "They appear once films are public and Agent 6 has read YouTube's numbers.") }));
  syncButtons();
}

// ------------------------------------------------------------------ L1 music

async function loadMusic() {
  const tracks = await api("/api/music");
  const input = h("input", { type: "file", accept: ".mp3,.m4a,.aac,.wav,.ogg,audio/*", multiple: true, hidden: true,
                             onchange: e => addTracks([...e.target.files]) });
  const zone = h("label", { class: "dropzone" }, input,
    h("b", {}, "Drop music files here, or click to choose"),
    h("small", {}, "Full-length tracks only: each film gets one, silent until the spark, then rising to the end. Use "
                   + "only music you may post on YouTube; a track with a credit line on file (tracks.yaml) gets it added at upload."));
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", e => { e.preventDefault(); zone.classList.remove("over"); addTracks([...e.dataTransfer.files]); });
  const mb = tracks.reduce((sum, t) => sum + t.size, 0) / 1e6;

  $("#view-music").replaceChildren(
    pageHead({ eyebrow: "L1 · Library", title: "Music",
      lede: "The stories' music: each film gets one of these tracks, chosen from its title. It plays low from the first "
        + "second, lifts at his realization and swells to the end." }),
    kpis([
      { label: "Tracks", value: tracks.length, tone: tracks.length ? null : "warn", note: tracks.length ? "one per story" : "the films have no music" },
      { label: "With a credit line", value: tracks.filter(t => t.credit).length, note: "added to the description at upload" },
      { label: "Library size", value: mb.toFixed(1), unit: "MB" },
    ]),
    section({ num: "L1.1", title: "Add tracks", body: zone }),
    section({ num: "L1.2", title: "Tracks", text: "Press play to listen.",
      body: tracks.length
        ? table(["Track", "Listen", ["", { class: "col-actions" }]], tracks.map(t => h("tr", {},
            h("td", { class: "title-cell" }, h("b", { title: t.name }, t.name),
              h("small", {}, `${(t.size / 1e6).toFixed(1)} MB${t.credit ? " · credit added at upload" : " · no credit line on file"}`)),
            h("td", {}, h("audio", { src: t.url, controls: true, preload: "none" })),
            h("td", { class: "col-actions" }, h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button",
                                                            onclick: () => removeTrack(t) }, "Remove")))))
        : empty("No tracks yet", "Add a few full-length tracks above. Until then, the films are made without music.") }));
}

async function addTracks(files) {
  for (const file of files) {
    try {
      await api(`/api/music/${encodeURIComponent(file.name)}`, { method: "PUT", raw: file });
      toast(`Added ${file.name}`, "ok");
    } catch (e) {
      toast(`${file.name}: ${e.message}`, "error", 7000);
    }
  }
  await loadState();
  loadMusic();
}

async function removeTrack(t) {
  if (!confirm(`Remove ${t.name}?`)) return;
  try {
    await api(`/api/music/${encodeURIComponent(t.name)}`, { method: "DELETE" });
    await loadState();
    loadMusic();
  } catch (e) {
    toast(e.message, "error");
  }
}

const DEEPER = [[0, "As Gemini reads it"], [1, "1 semitone deeper"], [2, "2 semitones deeper"]];

// ------------------------------------------------------------------ S1 YouTube

async function loadYouTube(refresh = false) {
  const y = await api(`/api/youtube${refresh ? "?refresh=1" : ""}`);
  const connecting = state.task?.kind === "connect" && state.task.status === "running";
  const ok = y.connected && !y.error;
  const fileInput = h("input", { type: "file", accept: ".json,application/json", hidden: true,
                                 onchange: e => e.target.files[0] && saveClientFile(e.target.files[0]) });
  const step = (n, done, title, ...body) => h("div", { class: "card setup-step", dataset: { done: done ? "1" : "0" } },
    h("span", { class: "setup-num" }, done ? "✓" : n), h("h3", {}, title), pill(done ? "Done" : "To do", done ? "ok" : "idle"),
    h("div", { class: "setup-body" }, body));
  const link = (href, text) => h("a", { href, target: "_blank", rel: "noopener" }, text);

  $("#view-youtube").replaceChildren(
    pageHead({ eyebrow: "S1 · Setup", title: "Channels",
      lede: "Where the stories go: YouTube (the film, and its short version as a Short), and Instagram (the short version as "
            + "a Reel) if you like. Each needs your permission once; your passwords never touch this software.",
      actions: [h("button", { class: "btn", type: "button", onclick: () => loadYouTube(true).catch(e => toast(e.message, "error")) },
                  "Check connection")] }),
    kpis([
      { label: "Channel", value: ok ? (y.channel || "Connected") : "Not connected", tone: ok ? "ok" : "warn",
        note: ok ? "uploads, stats and comments are ready" : y.error ? `saved sign-in didn't work: ${y.error}` : "finish the steps below" },
      { label: "OAuth client file", value: y.client_file ? "Saved" : "Missing", tone: y.client_file ? "ok" : "warn", note: "credentials.json" },
    ]),
    section({ num: "S1.1", title: "Connect in three steps",
      body: h("div", { class: "setup" },
        step(1, y.client_file || y.connected, "Create a Google Cloud project (about 10 minutes)",
          h("ol", {},
            h("li", {}, "Open ", link("https://console.cloud.google.com/projectcreate", "Google Cloud: new project"), " with the Google account that owns your channel. Any name works."),
            h("li", {}, h("b", {}, "APIs & Services → Library"), ": enable ", h("b", {}, "YouTube Data API v3"), " and ", h("b", {}, "YouTube Analytics API"), "."),
            h("li", {}, h("b", {}, "Google Auth Platform → Branding"), ": app name, support email and developer email. Skip the logo (uploading one forces Google’s verification review)."),
            h("li", {}, h("b", {}, "Audience"), ": choose ", h("b", {}, "External"), " and add your own Gmail under ", h("b", {}, "Test users"), ". In ", h("b", {}, "Testing"),
              " the sign-in lasts 7 days (press Reconnect below). To make it permanent, put your site’s ",
              h("a", { href: "/about", target: "_blank" }, "/about"), " and ", h("a", { href: "/privacy", target: "_blank" }, "/privacy"),
              " links into Branding and press ", h("b", {}, "Publish app"), "."),
            h("li", {}, h("b", {}, "Clients → Create client → Desktop app"), ", then download its JSON file."))),
        step(2, y.client_file, "Add the OAuth client file",
          h("p", {}, y.client_file ? "Client file saved (credentials.json). You can replace it if needed."
                                   : "Choose the JSON file you just downloaded. It stays on this computer."),
          h("div", { class: "row" }, fileInput,
            h("button", { class: "btn btn-sm", type: "button", disabled: !y.local, onclick: () => fileInput.click() },
              y.client_file ? "Replace client file" : "Choose client file"))),
        step(3, ok, "Connect your channel",
          y.connected
            ? (y.error ? h("div", { class: "callout", dataset: { tone: "bad" } }, `Saved sign-in didn't work: ${y.error}`)
                       : [h("p", {}, "Connected to ", h("b", {}, y.channel || "your channel"), ". Uploads, stats and comments are ready."),
                          !y.manage && h("div", { class: "callout", dataset: { tone: "warn" } },
                            "Stop and Delete on the Schedule page need one more permission: press Reconnect and tick “See, "
                            + "edit, and permanently delete your YouTube videos…” on Google's page.")])
            : h("p", {}, "A Google page opens in your browser: choose your channel and allow access."),
          h("div", { class: "row" },
            h("button", { class: "btn btn-primary btn-sm", type: "button", disabled: !y.client_file || !y.local || connecting,
                          onclick: () => runTask("connect") },
              connecting ? "Waiting for you in the browser…" : y.connected ? "Reconnect" : "Connect YouTube"),
            !y.local && h("span", { class: "note" }, "Connect from the dashboard on your computer.")))) }),
    h("div", { id: "instagram-box" }));
  loadInstagram().catch(e => toast(e.message, "error"));
}

async function loadInstagram() {
  const ig = await api("/api/instagram");
  const box = $("#instagram-box");
  if (!box) return;
  const link = (href, text) => h("a", { href, target: "_blank", rel: "noopener" }, text);
  const step = (n, done, title, ...body) => h("div", { class: "card setup-step", dataset: { done: done ? "1" : "0" } },
    h("span", { class: "setup-num" }, done ? "✓" : n), h("h3", {}, title), pill(done ? "Done" : "To do", done ? "ok" : "idle"),
    h("div", { class: "setup-body" }, body));
  const token = h("input", { class: "input", type: "password", placeholder: "Access token", autocomplete: "off", "aria-label": "Access token" });
  const appId = h("input", { class: "input", placeholder: "App ID", autocomplete: "off", "aria-label": "App ID" });
  const secret = h("input", { class: "input", type: "password", placeholder: "App secret", autocomplete: "off", "aria-label": "App secret" });
  const connect = async () => {
    try {
      const r = await api("/api/instagram/connect", { method: "POST", json: { token: token.value, app_id: appId.value, app_secret: secret.value } });
      toast(`Connected to @${r.username}${r.long_lived ? "" : ". Add the app's ID and secret too, or the token stops working within hours"}.`,
            r.long_lived ? "ok" : "info", 9000);
      if (r.cloud?.copied) toast("The cloud (GitHub) has the new token too: its next runs use it.", "ok", 9000);
      else if (r.cloud?.error) toast(`Connected here, but the cloud (GitHub) still has the old token: ${r.cloud.error}. `
                                     + "Ask Claude to copy it, or run: python tools/cloud_secrets.py", "error", 15000);
      await loadState();
      loadInstagram();
    } catch (e) {
      toast(e.message, "error", 9000);
    }
  };
  const call = async (method, json, done) => {
    try {
      await api("/api/instagram", { method, json });
      toast(done, "ok");
      await loadState();
      loadInstagram();
    } catch (e) {
      toast(e.message, "error", 7000);
    }
  };
  const expires = ig.expires_at === 0 ? "never expires" : ig.expires_at ? `expires ${fmtWhen(new Date(ig.expires_at * 1000).toISOString())}` : null;
  box.replaceChildren(
    kpis([
      { label: "Instagram", value: ig.connected ? `@${ig.username}` : ig.username ? "Not working" : "Not connected",
        tone: ig.connected ? "ok" : ig.username ? "bad" : null, note: ig.connected ? (expires || "connected") : ig.error || "optional" },
      { label: "Reels", value: ig.on ? "On" : "Off", tone: ig.on ? "ok" : null, note: ig.on ? "each short version also goes up as a Reel" : "switch on once connected" },
      ig.connected && { label: "Posted today by API", value: ig.used_today ?? "–", unit: ig.daily_limit ? `/ ${ig.daily_limit}` : "" },
    ]),
    section({ num: "S1.2", title: "Instagram Reels (optional)",
      text: "Each story's short version also goes up as a Reel at its time, with the same caption and credits. Instagram's own API, free.",
      body: h("div", { class: "setup" },
        step(1, ig.connected, "Make your Instagram a professional account, linked to a Facebook Page",
          h("ol", {},
            h("li", {}, "In Instagram: ", h("b", {}, "Settings → Account type and tools → Switch to professional account"), " (Creator or Business)."),
            h("li", {}, "Link it to a Facebook Page you manage (create one if needed): in the Page's settings, ", h("b", {}, "Linked accounts → Instagram"), "."))),
        step(2, ig.connected, "Create your own Meta app and an access token (about 10 minutes)",
          h("ol", {},
            h("li", {}, "Open ", link("https://developers.facebook.com/apps/creation/", "Meta for Developers: create app"), "; choose ", h("b", {}, "Other → Business"), "."),
            h("li", {}, "Add the product ", h("b", {}, "Instagram"), " (API setup with Facebook login). In development mode it works for your own accounts."),
            h("li", {}, "Open the ", link("https://developers.facebook.com/tools/explorer/", "Graph API Explorer"), ", pick your app, and add the permissions ",
              h("b", {}, "instagram_basic, instagram_content_publish, pages_show_list, pages_read_engagement, business_management"),
              " and, for Delete on the Schedule page, ", h("b", {}, "instagram_manage_contents"), "; press ",
              h("b", {}, "Generate Access Token"), " and allow it (tick your Page, your Instagram account and your business)."),
            h("li", {}, "Copy the token, and the app's ", h("b", {}, "App ID"), " and ", h("b", {}, "App secret"), " (App settings → Basic). They stay on this computer, in .env."))),
        step(3, ig.connected, "Connect",
          ig.connected ? h("p", {}, "Connected to ", h("b", {}, `@${ig.username}`), expires ? ` (the token ${expires}).` : ".") : null,
          !ig.local && h("div", { class: "callout", dataset: { tone: "warn" }, style: "margin:8px 0" },
            h("b", {}, "Connect from the dashboard on your computer. "),
            "Keys are kept only there (in .env), so this online page can't take them. On your computer, open the "
            + "dashboard, paste the token, App ID and App secret here and press Connect: it also gives the new token "
            + "to the cloud (GitHub) by itself."),
          ig.refused && h("div", { class: "callout", dataset: { tone: "warn" }, style: "margin:8px 0" },
            h("b", {}, "Meta refuses this connection. "), "If Meta blocked or restricted your app, its page on ",
            link("https://developers.facebook.com/apps/", "Meta for Developers"), " says why and what to do. Once it's "
            + "fixed, or with a new app, make a new token (step 2) and connect again. The Reels wait meanwhile."),
          ig.connected && ig.can_delete === false && h("div", { class: "callout", dataset: { tone: "warn" }, style: "margin:8px 0" },
            "Posting works. Delete on the Schedule page needs one more permission, instagram_manage_contents: make a new "
            + "token with it (step 2) and connect again. Until then, delete Reels in the Instagram app."),
          h("div", { class: "grid-3", style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px" }, token, appId, secret),
          h("div", { class: "row", style: "margin-top:8px" },
            h("button", { class: "btn btn-primary btn-sm", type: "button", disabled: !ig.local, onclick: connect },
              ig.connected ? "Connect again" : "Connect Instagram"),
            ig.username && h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", disabled: !ig.local,
              onclick: () => confirm("Disconnect Instagram? Reels stop until you connect again.") && call("DELETE", undefined, "Disconnected.") }, "Disconnect"))),
        step(4, ig.on, "Switch Reels on",
          h("p", {}, ig.on ? "On: every short version goes up as a Reel at its time (posted by the cloud, or this computer while its "
                             + "database is its own)." : "Off: nothing goes to Instagram."),
          h("div", { class: "row" },
            h("button", { class: `btn btn-sm${ig.on ? "" : " btn-primary"}`, type: "button", disabled: !ig.local || (!ig.on && !ig.connected),
              onclick: () => call("PATCH", { on: !ig.on }, ig.on ? "Reels off." : "Reels on.") }, ig.on ? "Switch off" : "Switch on"))),
        step(5, ig.send === "link", "How each video gets to Instagram",
          h("p", {}, ig.send === "link"
            ? "Instagram fetches it: for the minute or two it takes, that one video file (nothing else on this computer) is "
              + "reachable at a random temporary address through Cloudflare's free quick tunnel, then the address is gone. "
              + "Instagram's own way to receive a video, with nothing to drop. If no link can be made, or Instagram won't take it, the video is sent instead."
            : "This computer sends it to Instagram's upload server, which drops uploads in spells (#46 ten times in a row on "
              + "27 October): a Reel can take hours of tries to go up. With a temporary link, Instagram fetches the file itself "
              + "instead (Cloudflare's free quick tunnel, already on this computer; only that one file, only for a minute or two)."),
          h("div", { class: "row" },
            h("button", { class: `btn btn-sm${ig.send === "link" ? "" : " btn-primary"}`, type: "button", disabled: !ig.local,
              onclick: () => call("PATCH", { send: ig.send === "link" ? "upload" : "link" },
                ig.send === "link" ? "This computer sends the videos again." : "Instagram fetches the videos from a temporary link now.") },
              ig.send === "link" ? "Send from this computer instead" : "Let Instagram fetch it (temporary link)")))) }));
}

async function saveClientFile(file) {
  try {
    await api("/api/youtube/client", { method: "PUT", raw: await file.text() });
    toast("Client file saved. Now connect your channel.", "ok");
    loadYouTube();
  } catch (e) {
    toast(e.message, "error", 8000);
  }
}

// ------------------------------------------------------------------ S2 settings

async function loadSettings() {
  const s = await api("/api/settings");
  const ro = !s.editable;
  const sch = s.schedule;
  const row = (label, hint, control, forId) => h("div", { class: "form-row" },
    h("div", {}, h("label", { class: "label", for: forId }, label), hint && h("p", { class: "hint" }, hint)),
    h("div", {}, control));
  const text = (name, value) => h("input", { class: "input", id: `s-${name}`, name, value: value ?? "", disabled: ro });
  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zones = [...new Set([sch.timezone, browserZone, ...TIMEZONES])];
  const select = (name, options, current) => h("select", { class: "input", id: `s-${name}`, name, disabled: ro },
    options.map(([value, label]) => h("option", { value, selected: String(value) === String(current) }, label)));
  const card = (id, num, title, ...rows) => h("div", { class: "card", id: `set-${id}` },
    h("div", { class: "card-head" }, h("h3", {}, h("span", { class: "muted", style: "font-family:var(--font-mono);font-weight:500;margin-right:8px" }, num), title)),
    rows);
  const form = h("form", { class: "settings-sections", novalidate: true, onsubmit: saveSettings },
    card("channel", "S2.2", "Channel",
      row("Channel name", "Shown on this dashboard and your public About and Privacy pages; never in the videos.",
          text("name", s.channel.name), "s-name"),
      row("Public contact email", h("span", {}, "Optional. Shown on your public ", h("a", { href: "/about", target: "_blank" }, "About"), " and ",
            h("a", { href: "/privacy", target: "_blank" }, "Privacy"), " pages, which Google asks for."),
          text("contact_email", s.channel.contact_email), "s-contact_email")),
    card("schedule", "S2.3", "The clock",
      row("Time zone", "The posting time and the morning run are on this clock.",
          select("timezone", zones.map(z => [z, z === browserZone ? `${z} (this device)` : z]), sch.timezone), "s-timezone"),
      row("Next story", "Made as soon as its slot is free (the story before it is public), between "
            + `${state.app.gemini?.opens || "13:30"} and ${state.app.gemini?.closes || "00:00"} (after Gemini's free `
            + "allowance renews, so its stronger models write it), when YouTube can take its uploads. Off: the morning run "
            + "below makes the day's story.",
          h("label", { class: "switch", style: "margin-left:0;width:fit-content" },
            h("input", { type: "checkbox", id: "s-ahead", name: "ahead", role: "switch", checked: sch.ahead !== false, disabled: ro }),
            h("span", { class: "switch-track", "aria-hidden": "true" }, h("span", { class: "switch-thumb" })),
            h("span", { class: "switch-text" }, h("b", {}, "As soon as its slot is free"))), "s-ahead"),
      row("Stories ready ahead", "With the switch on. 2: tomorrow's story is always made and the next one on its way, so "
            + "one that gets stuck (Gemini, GitHub's late checks) has a whole spare day before a slot could go "
            + "empty. The first day makes the extra one, then one a day as before. 1: only the next one.",
          select("stories_ahead", [[1, "1 · the next story"], [2, "2 · a spare day"], [3, "3 · two spare days"]],
                 sch.stories_ahead ?? 2), "s-stories_ahead"),
      row("Morning run", `With the switch above off: when the day's story is made, at least an hour before it goes public (${s.series.post_at}); `
            + `never before Gemini's free allowance renews (${state.app.gemini?.opens || "13:30"}).`,
          h("input", { class: "input", type: "time", id: "s-make_at", name: "make_at", value: sch.make_at || "07:00", disabled: ro }), "s-make_at")),
    h("div", { class: "savebar" },
      h("p", { class: "note" }, ro ? "Settings can only be changed on your computer." : "Saved to config/channel.yaml."),
      h("button", { class: "btn btn-primary", type: "submit", disabled: ro }, "Save")));

  const nav = [["series", "S2.1", "The stories"], ["channel", "S2.2", "Channel"], ["schedule", "S2.3", "The clock"]];
  $("#view-settings").replaceChildren(
    pageHead({ eyebrow: "S2 · Setup", title: "Settings", lede: "How the channel behaves. Saved to config/channel.yaml." }),
    h("div", { class: "settings" },
      h("nav", { class: "settings-nav", "aria-label": "Settings sections" }, nav.map(([id, num, label]) =>
        h("a", { href: "#settings", onclick: e => { e.preventDefault(); $(`#set-${id}`).scrollIntoView({ behavior: "smooth" }); } },
          h("span", {}, num), label))),
      h("div", { class: "settings-sections" }, seriesCard(s), form)));
}

async function saveSettings(event) {
  event.preventDefault();
  const f = new FormData(event.target);
  const body = {
    channel: { name: f.get("name"), contact_email: f.get("contact_email") },
    schedule: { timezone: f.get("timezone"), make_at: f.get("make_at"), ahead: f.get("ahead") === "on",
                stories_ahead: Number(f.get("stories_ahead") || 2) },
  };
  try {
    await api("/api/settings", { method: "PUT", json: body });
    toast("Settings saved.", "ok");
    loadState();
  } catch (e) {
    toast(e.message, "error", 7000);
  }
}

// ------------------------------------------------------------------ S3 activity

async function loadActivity() {
  const a = await api("/api/activity");
  const failed = a.runs.filter(r => r.ok === 0).length;
  $("#view-activity").replaceChildren(
    pageHead({ eyebrow: "S3 · Setup", title: "Activity",
      lede: "Every piece of the agents' work, the jobs that call them, and the buttons you press here." }),
    kpis([
      { label: "Runs", value: a.runs.length, note: "most recent first" },
      { label: "Failed", value: failed, tone: failed ? "bad" : null },
      { label: "Alerts", value: a.alerts.length, note: "since the server started" },
      { label: "Phone alerts", value: a.telegram ? "On" : "Off", tone: a.telegram ? "ok" : null, note: "through Telegram" },
    ]),
    section({ num: "S3.1", title: "Runs", body: runsTable(a.runs) }),
    h("div", { class: "grid-2 section" },
      section({ num: "S3.2", title: "Alerts", text: a.telegram ? "Also sent to your phone." : "Shown here; add Telegram to get them on your phone.",
        body: a.alerts.length
          ? table([["When", { class: "col-time" }], "Alert"], a.alerts.map(n => h("tr", {},
              h("td", { class: "col-time small" }, fmtWhen(n.at), n.sent ? h("small", { class: "muted" }, " · sent") : null),
              h("td", { class: "log-what" }, n.text))))
          : empty("No alerts", "Nothing has gone wrong since the server started.") }),
      section({ num: "S3.3", title: "Phone alerts",
        body: h("div", { class: "card card-pad" },
          h("p", { class: "note", style: "margin-bottom:12px" }, a.telegram ? "Telegram is set up. Send yourself a test."
            : "Optional: create a bot with @BotFather, then add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env and restart."),
          h("button", { class: "btn btn-sm", type: "button", disabled: !a.telegram, onclick: async () => {
            try { await api("/api/notify/test", { method: "POST" }); toast("Sent. Check Telegram.", "ok"); }
            catch (e) { toast(e.message, "error", 7000); }
          } }, "Send test message")) })));
}

// ------------------------------------------------------------------ routing

const loaders = { overview: loadOverview, topics: loadTopics, scripts: loadScripts, studio: loadStudio, host: loadLook,
                  review: loadReview, schedule: loadSchedule, results: loadResults, music: loadMusic,
                  youtube: () => loadYouTube(),
                  settings: loadSettings, activity: loadActivity };

/** "#studio/12" -> "studio"; older page names land on their new pages. */
function currentView() {
  const view = location.hash.slice(1).split("/")[0];
  const name = { shorts: "studio", queue: "studio", stories: "scripts", themes: "topics", narrator: "host", channels: "youtube",
                 instagram: "youtube" }[view] || view;
  return VIEWS.includes(name) ? name : "overview";
}

let lastView = null;
async function route() {
  const view = currentView();
  if (lastView === "scripts" && view !== "scripts" && state.scripts.selected && state.dirty.has(state.scripts.selected)
      && !confirm("Leave without saving your changes to this story?")) {
    history.replaceState(null, "", "#scripts");
    return;
  }
  closeMenu();
  for (const v of VIEWS) $(`#view-${v}`).hidden = v !== view;
  for (const a of $$("#nav a")) {
    const on = a.dataset.view === view;
    a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  if (view !== lastView) window.scrollTo(0, 0);
  lastView = view;
  try {
    await loadState();
    await loaders[view]();
  } catch (e) {
    toast(e.message, "error", 7000);
  }
}

function closeMenu() {
  document.body.classList.remove("menu-open");
  $("#scrim").hidden = true;
  $("#menu-btn").setAttribute("aria-expanded", "false");
}

function init() {
  $("#menu-btn").addEventListener("click", () => {
    document.body.classList.add("menu-open");
    $("#scrim").hidden = false;
    $("#menu-btn").setAttribute("aria-expanded", "true");
  });
  $("#scrim").addEventListener("click", closeMenu);
  $("#signout").addEventListener("click", async () => {
    try {
      await api("/logout", { method: "POST" });
      location.assign("/login?e=out");
    } catch (err) {
      toast(err.message, "error");
    }
  });

  $("#autopost").addEventListener("change", async e => {
    try {
      await api("/api/pause", { method: "POST", json: { paused: !e.target.checked } });
      toast(e.target.checked ? "Autopilot on. The agents get to work: the day's story made and posted on time."
                             : "Autopilot paused. The agents wait; your own buttons still work.", "ok");
    } catch (err) {
      e.target.checked = !e.target.checked;
      toast(err.message, "error");
    }
    await loadState().catch(() => {});
    if (currentView() === "overview") loadOverview().catch(() => {});
  });

  // Keep the numbers current and notice when the agents start work by themselves.
  setInterval(async () => {
    if (document.hidden || state.watching) return;
    await loadState().catch(() => {});
    if (["overview", "schedule"].includes(currentView())) loaders[currentView()]().catch(() => {});
  }, 30000);
  window.addEventListener("hashchange", route);
  window.addEventListener("beforeunload", e => {
    if (state.dirty.size) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  route();
}

init();
