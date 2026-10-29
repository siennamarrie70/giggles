// Control room for the case-study channel. Plain JS, no build step; talks to dashboard/api.py.
// Every page has the same shape: a header with its actions, a row of numbers, then numbered sections.
// Pages 01-07 belong to the seven agents: Editor, Researcher, Writer, Animator, Reviewer, Publisher, Analyst.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const SVG_NS = "http://www.w3.org/2000/svg";

// Each line's part in the mystery (agents/writer.py).
const BEATS = { hook: "Hook", setup: "Setup", turn: "Turning point", reveal: "Reveal", closing: "Closing thought" };
// ...and the beats of v5's first scripts (before the five-part format), so they still read right.
const BEAT_NAMES = { ...BEATS, question: "Question", context: "Setup", echo: "Echo" };
const RETENTION = { hook: "hook", open_loop: "open loop", pace: "pace", specificity: "specifics", payoff: "payoff" };
const CATEGORY = { dark_history: "Dark history", mysteries: "Mysteries", business: "Business", technology: "AI & technology",
                   trending: "In the news", psychology: "Psychology", mythology: "Mythology", people: "Rise & fall",
                   science: "Science & space", crime: "Crime & investigations", history: "History", economy: "Economy" };
const WHY_NOW = { trend: "Trending", anniversary: "Anniversary", evergreen: "Evergreen", request: "Your request",
                  comment: "A viewer's comment", follow_up: "Follow-up" };
// The fact-check's mark on each line (agents/writer.py).
const CHECK = { ok: ["Checked", "ok"], framing: ["No claim: story glue", "ok"], fixed: ["Fixed by the fact-check", "warn"],
                edited: ["Edited by you", "run"], "edited-unsourced": ["Edited: a number isn't in the sources", "bad"] };
const STATUS = { planned: ["Ready", "run"], waiting: ["Waits for your OK", "warn"], making: ["Being made", "run"],
                 scheduled: ["Scheduled", "run"], live: ["Live", "ok"], failed: ["Failed", "bad"], vetoed: ["Vetoed", "bad"],
                 discarded: ["Discarded", "idle"], skipped: ["Skipped", "idle"],
                 stopped: ["Stopped: private on YouTube", "idle"], deleted: ["Deleted from YouTube", "idle"] };
// What each posting slot says, by its state (see slot_board in tools/jobs.py).
const SLOT = { posted: ["Posted", "ok"], scheduled: ["Scheduled", "run"], making: ["Making…", "run"],
               late: ["Late · going out", "warn"], due: ["In today's run", "accent"], open: ["Next run", "idle"],
               missed: ["No post", "idle"], paused: ["Paused", "warn"] };
// Where a Short stands on each platform (platforms() in agents/publisher.py), beside it on the Schedule page.
const ON_YOUTUBE = { making: ["Being made", "run"], scheduled: ["Scheduled", "run"], public: ["Public", "ok"],
                     hidden: ["Private in Studio", "warn"], rejected: ["Rejected", "bad"], gone: ["Deleted in Studio", "bad"],
                     stopped: ["Stopped", "idle"], deleted: ["Deleted", "idle"] };
const ON_INSTAGRAM = { making: ["After YouTube", "idle"], none: ["Not for Instagram", "idle"], waiting: ["Waits for its slot", "run"],
                       due: ["Posting soon", "run"], retry: ["Trying again", "warn"], posting: ["Posting…", "run"],
                       posted: ["Posted", "ok"], failed: ["Didn't post", "bad"], skipped: ["Skipped", "idle"],
                       expired: ["Given up", "idle"], cancelled: ["Taken off", "idle"], deleted: ["Deleted", "idle"],
                       remaking: ["Making its video…", "run"] };
// Which agents a dashboard task puts to work (for the "Working" badge on their cards).
const TASK_AGENTS = { prepare: ["editor", "researcher", "writer"], render: ["animator", "reviewer"],
                      publish: ["animator", "reviewer", "publisher"], instagram: ["publisher"], reel: ["publisher"],
                      remake: ["animator"],
                      autopilot: ["editor", "researcher", "writer", "animator", "reviewer", "publisher"], stats: ["analyst"],
                      morning: ["editor", "researcher", "writer", "animator", "reviewer", "publisher"],
                      "host-sample": ["animator"], "host-test": ["animator"] };
const AGENT_KEYS = ["editor", "researcher", "writer", "animator", "reviewer", "publisher", "analyst"];
// What the Reviewer's notes ask the Animator to do (agents/reviewer.py, agents/animator.py improve()).
const FIXES = { drop: "take it off that line", title: "the title leaves sooner", swap: "swap the shot", slower: "read it slower",
                pauses: "longer pauses", reread: "read it again", trim: "cut a line", remake: "make it again" };
const TIMEZONES = ["Asia/Kolkata", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                   "Europe/London", "Europe/Berlin", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney", "UTC"];
const EVERY_HOURS = [1, 1.5, 2, 3, 4, 6, 8, 12];
const REGIONS = ["US", "GB", "CA", "AU", "IE", "NZ", "IN", "PH", "SG", "ZA", "DE", "FR", "ES", "BR", "MX", "JP"];
const HOW_OFTEN = [[0, "Off"], [0.5, "Rarely"], [1, "Normal"], [2, "Often"]];
const LIMITS = { line: 160, title: 100, caseTitle: 32, style: 400 };
// The same pacing the Writer uses for the Professor (agents/writer.py: words a second, the pause between lines).
const PACE = { wordsPerSecond: 2.1, gap: 0.2, extra: 0.6 };
const VIEWS = ["overview", "topics", "research", "scripts", "studio", "review", "schedule", "results", "music", "host",
               "youtube", "settings", "activity"];
// The audience is worldwide but US-heavy, so times are also shown for New York next to the schedule's own clock.
const AUDIENCE_TZ = "America/New_York";

const state = { app: null, videos: [], task: null, watching: null, dirty: new Set(),
                studio: { filter: "planned", selected: null, picked: false }, scripts: { selected: null },
                research: { selected: null }, signals: null, signalsPoll: null };

// ------------------------------------------------------------------ helpers

/** Build DOM safely: text always goes in as text, never as HTML. */
// A link or picture address from outside (a source the Researcher found, a credit page) is used only if it's a web
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

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
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
const category = key => CATEGORY[key] || cap(key || "");

/** A video the dashboard shows as "live" once its publish time has passed, or "waiting" for your OK. */
function shownStatus(v) {
  if (v.status === "scheduled" && v.publish_at && new Date(v.publish_at) <= new Date()) return "live";
  if (v.status === "planned" && v.approval === "waiting") return "waiting";
  return v.status;
}

/** How long a script will run, the way the Writer estimates it. */
function estimate(lines) {
  const words = lines.reduce((n, l) => n + l.text.split(/\s+/).filter(Boolean).length, 0);
  return words / PACE.wordsPerSecond + PACE.gap * Math.max(0, lines.length - 1) + PACE.extra;
}

/** Your YouTube buttons beside a Short: "now" (public at once), "stop" (private, never public by itself) or "delete"
 *  (gone from YouTube, public or not), each asked first. */
async function youtubeAction(v, action, asked = false) {
  const reel = v.platforms?.instagram || {};
  const isPublic = v.platforms?.youtube?.state === "public" || (v.publish_at && new Date(v.publish_at) <= new Date());
  const when = v.publish_at ? `${fmtWhen(v.publish_at)} (${fromNow(v.publish_at)})` : "at its slot";
  const refill = !v.slot || new Date(v.slot) > Date.now() - 3.6e6;  // the autopilot fills a slot up to an hour late
  const slot = !refill ? "Its slot has passed, so no other Short is made for it."
    : state.app.paused ? "Its slot stays empty while the autopilot is paused."
    : "The autopilot then makes a new Short for its slot (pause it to keep the slot empty).";
  const reelNote = reel.state === "posted" ? " Its Reel stays on Instagram (its own Delete removes it there)."
    : ["waiting", "due", "retry", "failed", "skipped"].includes(reel.state) ? " Its Reel won't go on Instagram either." : "";
  const text = {
    now: `Post “${v.title}” on YouTube now?\n\nIt goes public right away instead of ${when}. Its slot stays its own, so no `
         + "other Short is made for it." + (reel.state === "waiting"
           ? ` Its Reel still goes on Instagram at ${onClock(reel.at)} (or press Post now on its Instagram side).` : ""),
    stop: `Stop “${v.title}” from going public ${when}?\n\nIt stays on YouTube as a private video only you can see; you `
          + `can still publish it yourself in YouTube Studio. ${slot}${reelNote}`,
    delete: isPublic
      ? `Delete “${v.title}” from YouTube?\n\nIt's public: this removes it for good, with its views and comments. ${slot}${reelNote}`
      : `Delete “${v.title}” from YouTube?\n\nIt was going public ${when}. This removes the video for good. ${slot}${reelNote}`,
  }[action];
  if (!asked && !confirm(text)) return;
  try {
    await api(`/api/videos/${v.id}/youtube`, { method: "POST", json: { action } });
    toast({ now: "Public on YouTube now.", stop: "Stopped: it's private on YouTube and won't go public.",
            delete: "Deleted from YouTube." }[action], "ok");
    await loadState();
    loaders[currentView()]();
  } catch (e) {
    if (e.reconnect && state.app.local !== false) return allowManaging(() => youtubeAction(v, action, true), action);
    toast(e.message, "error", 9000);
  }
}

/** Your Instagram buttons beside a Short: "now" posts its Reel at once (a task: a few minutes), "delete" deletes a
 *  posted Reel from Instagram or takes one that isn't posted yet off, "schedule" makes the video of one that went up
 *  while Reels were off again, so its Reel waits for its slot. */
async function instagramAction(v, action) {
  const reel = v.platforms.instagram;
  const yt = v.platforms.youtube;
  if (action === "schedule") {
    const when = reel.at && new Date(reel.at) > new Date() ? `at ${onClock(reel.at)}` : "as soon as it's made (its slot has passed)";
    if (!confirm(`Schedule “${v.title}” for Instagram?\n\nIt went up while Reels were off, so its video wasn't kept: it's `
                 + "made again (about 5 minutes, the same case, music and drawings, read again by the same voice), then "
                 + `its Reel goes on Instagram ${when}.`)) return;
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

/** The Professor's face, the channel's host (assets/host). */
function professor() {
  const name = state.app?.host?.name || "The Professor";
  return h("span", { class: "avatars" }, h("img", { src: "/media/host/face.png", alt: name, title: `${name}, the host` }));
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

function taskButton(kind, label, { primary = false, sm = false, title, videoId, confirmText } = {}) {
  return h("button", { class: `btn${primary ? " btn-primary" : ""}${sm ? " btn-sm" : ""}`, type: "button",
                       "data-needs-idle": true, title,
                       onclick: () => { if (!confirmText || confirm(confirmText)) runTask(kind, videoId); } }, label);
}

/** "Make the 14:00 Short now": takes the oldest ready case (or makes one), animates and uploads it. */
function makeButton({ primary = false, sm = false, short = false } = {}) {
  const a = state.app;
  const nextOpen = a.autopilot.next_open;
  const blocked = !a.services.youtube || !nextOpen;
  return h("button", { class: `btn${primary ? " btn-primary" : ""}${sm ? " btn-sm" : ""}`, type: "button",
    "data-needs-idle": true, dataset: { blocked: blocked ? "1" : "0" },
    title: !a.services.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
         : "Takes the oldest case that's ready (or makes one), animates it and uploads it for that slot",
    onclick: () => {
      const when = nextOpen ? `${clockIn(nextOpen, scheduleTz())} (${fromNow(nextOpen)})` : "the next free slot";
      if (confirm(`Make a Short for ${when} now?\n\nAgent 6 takes the oldest case that's ready (Agents 1 to 3 make one `
                  + "if none is waiting), Agent 4 makes its video, Agent 5 reviews it (and has it fixed if needed), and it's "
                  + "uploaded as private. YouTube makes it public at that time.")) runTask("autopilot");
    } }, short ? "Make it now" : nextOpen ? `Make the ${clockIn(nextOpen, scheduleTz())} Short now` : "Make the next Short now");
}

const caseButton = (opts = {}) => taskButton("prepare", "Make a new case",
  { title: "Agent 1 picks it, Agent 2 researches it, Agent 3 writes and fact-checks it", ...opts });

/** The box where you ask for a case; the Editor takes requests first. */
function requestBox({ onDone } = {}) {
  const input = h("input", { class: "input", placeholder: "e.g. Why did Nokia fail?  ·  What if India keeps growing at 7%?",
                             "aria-label": "Ask for a case", maxlength: 200 });
  const send = async () => {
    const text = input.value.trim();
    if (!text) return input.focus();
    try {
      await api("/api/topics", { method: "POST", json: { text } });
      input.value = "";
      toast("Added. Agent 1 makes it the next case (unless it breaks the channel's rules).", "ok");
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
    ["Lip-sync", s.lipsync ? "ok" : "off", s.lipsync ? "Rhubarb ready" : "Downloads on first use", null],
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
  $("#count-scripts").textContent = agent("writer")?.count || "";
  $("#count-studio").textContent = a.approvals || "";
  $("#count-review").textContent = a.held || "";
  $("#count-schedule").textContent = agent("publisher")?.count || "";
  $("#count-music").textContent = s.music || "";

  const ap = a.autopilot;
  const on = !a.paused;
  $("#autopost").checked = on;
  $("#autopost-label").textContent = on ? "Autopilot on" : "Autopilot paused";
  $("#autopost-sub").textContent = !on ? "The agents wait for you"
    : `${plural(ap.schedule.posts_per_day, "Short")} a day, made from ${ap.schedule.make_at}${ap.here ? "" : " on GitHub"}`;
  $("#pause-switch").title = "Off stops the morning run and all automatic work, here and in the cloud "
                             + "(your own buttons keep working)";
  syncButtons();
}

function syncButtons() {
  const busy = state.task?.status === "running";
  const local = state.app?.local !== false;  // in the cloud the scheduled jobs do the work
  for (const b of $$("[data-needs-idle]")) b.disabled = busy || !local || b.dataset.blocked === "1";
}

async function runTask(kind, videoId, extra = {}) {
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
    if (state.task.status === "running") return setTimeout(poll, 1000);
    const finished = state.task;  // (finishTask reloads the state, which may follow another task that's going)
    state.watching = null;
    syncButtons();
    await finishTask(finished);
    after?.(finished);
  };
  setTimeout(poll, 700);
}

function taskSummary(t) {
  const r = t.result || {};
  if (typeof r.skipped === "string") return `Nothing to do: ${r.skipped}.`;
  if (t.kind === "prepare") {
    const p = r.planned?.[0];
    return p ? `New case: ${p.title}${p.waits_for_approval ? " (it waits for your OK in the Studio)" : ""}` : "Done.";
  }
  if (t.kind === "render" || r.rendered) return `Video ready (${secs(r.length)}). Press play in the Studio.`;
  if (t.kind === "publish" || t.kind === "autopilot") {
    return r.live_now ? `Posted: ${r.title}. It's live now.` : `Uploaded: ${r.title}. It goes public ${fmtWhen(r.publish_at)}.`;
  }
  if (t.kind === "stats") {
    if (r.skipped) return r.skipped;
    return `Numbers for ${plural(r.updated || 0, "Short")}.` + (r.learn?.lessons ? " The playbook is updated." : "");
  }
  if (t.kind === "reel") return r.instagram === "posted" ? "On Instagram now: its Reel is up." : "Done.";
  if (t.kind === "remake") return r.instagram === "pending" ? "Made again: its Reel goes on Instagram at its slot." : "Done.";
  if (t.kind === "host-sample") return `Sample of ${r.voice}'s voice ready (${secs(r.seconds)}).`;
  if (t.kind === "host-test") return `Test clip ready (${secs(r.seconds)}): watch it on the Host page.`;
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
    !t.steps.length && !t.error && h("li", {}, h("span", { class: "t" }, "0s"), h("span", {}, "Starting…")));
  box.replaceChildren(
    h("div", { class: "task-chip", dataset: { status: t.status } },
      running ? h("span", { class: "spinner", "aria-hidden": "true" })
              : h("span", { class: "task-mark", "aria-hidden": "true" }, t.status === "done" ? "✓" : "!"),
      h("span", { class: "task-text" },
        h("b", {}, running ? `${t.label}…` : t.status === "done" ? `${t.label}: done` : `${t.label}: didn't work`),
        h("small", {}, t.error ? t.error : last ? last.text : "Starting…")),
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
  if (job === "editor" && d.topic) return `${category(d.category)}: ${d.topic}${d.needs_approval ? " · waits for your OK" : ""}`;
  if (job === "researcher" && d.facts !== undefined) {
    return `${plural(d.facts, "fact")} checked (${d.dropped} dropped) from ${plural(d.sources, "source")}, ${plural(d.images, "photo")}`
      + (d.footage !== undefined ? `, ${plural(d.footage, "clip")}` : "") + (d.archive ? `, ${plural(d.archive, "archive film")}` : "");
  }
  if (job === "writer" && d.lines) return `${d.lines} lines, about ${secs(d.estimate)}${d.cut ? ` (${d.cut} cut by the fact-check)` : ""}`;
  if (job === "animator" && d.length) return `Case #${d.video_id}: a ${secs(d.length)} video, made in ${secs(d.seconds)}`
    + (d.voice ? ` · ${d.voice}` : "");
  if (job === "reviewer" && d.passed !== undefined) return `Case #${d.video_id}, look ${d.round}: `
    + (d.passed ? `passed${d.notes ? ` (${plural(d.notes, "small note")})` : ""}` : `failed: ${(d.problems || []).slice(0, 2).join("; ")}`);
  if (job === "morning" && d.slots) return `Today's run: ${d.scheduled} of ${d.slots} Shorts scheduled (${d.made} made in this run)`
    + (d.missed ? `, ${plural(d.missed, "slot")} had passed before it` : "")
    + (d.held?.length ? `, ${d.held.length} turned down by the Reviewer (made again by itself)` : "") + (d.stopped ? ` (${d.stopped})` : "");
  if (d.instagram) return `Reel for #${d.video_id}: ${d.instagram}${d.url ? "" : d.error ? ` (${d.error})` : ""}`;
  if (d.reels) return d.reels.map(x => `Reel #${x.video_id}: ${x.instagram}`).join(", ");
  if (d.youtube_id) return `${d.live_now ? "Posted" : "Uploaded"} #${d.video_id} “${d.title}”, ${d.live_now ? "live now" : `goes public ${fmtWhen(d.publish_at)}`}`;
  if (d.planned) return d.planned.map(p => `#${p.id} ${p.title}`).join(", ") || "Nothing made";
  if (d.rendered) return (d.video_id ? `Video of #${d.video_id} made${d.length ? ` (${secs(d.length)})` : ""}`
                                     : `Video made: ${d.title || ""}`)
    + (d.passed ? ", passed review" : d.held ? ", turned down by the Reviewer: it's made again by itself" : d.passed === false ? ", failed review" : "")
    + (d.rounds > 1 ? ` after ${plural(d.rounds - 1, "fix")}` : "");
  if (d.updated !== undefined) return `Numbers for ${plural(d.updated, "Short")}${d.vetoed ? `, ${d.vetoed} vetoed` : ""}`
    + (d.comments ? `, ${plural(d.comments, "new comment")}` : "") + (d.learn?.lessons ? "; playbook updated" : "");
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
  if (key === "editor") return h("a", { class: "btn btn-sm", href: "#topics" }, "Topics & requests");
  if (key === "researcher") return h("a", { class: "btn btn-sm", href: "#research" }, "See the research");
  if (key === "writer") return caseButton({ sm: true });
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

/** A tiny line chart of a data series (forecast years dashed). */
function sparkline(points, forecastFrom) {
  const w = 160, h_ = 40;
  if (!points?.length) return null;
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pt = ([x, y]) => `${((x - x0) / ((x1 - x0) || 1) * (w - 4) + 2).toFixed(1)},${(h_ - 2 - (y - y0) / ((y1 - y0) || 1) * (h_ - 4)).toFixed(1)}`;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h_}`);
  svg.setAttribute("class", "spark");
  const line = (pts, dashed) => {
    if (pts.length < 2) return;
    const el = document.createElementNS(SVG_NS, "polyline");
    el.setAttribute("points", pts.map(pt).join(" "));
    if (dashed) el.setAttribute("stroke-dasharray", "4 3");
    svg.append(el);
  };
  const cut = forecastFrom ? points.findIndex(p => p[0] >= forecastFrom) : -1;
  if (cut > 0) { line(points.slice(0, cut), false); line(points.slice(cut - 1), true); } else line(points, false);
  return svg;
}

// ------------------------------------------------------------------ 00 overview

function slotRows(slots) {
  const a = state.app;
  const nextAt = a.autopilot.next?.at;
  return slots.map(s => {
    const v = s.video;
    const waiting = ["due", "late"].includes(s.state);
    const [label, tone] = SLOT[a.paused && waiting ? "paused" : s.state] || [s.state, "idle"];
    const live = s.state === "posted";
    const link = v?.youtube_id && h("a", { class: "platform", dataset: { tone: live ? "ok" : "run" }, target: "_blank", rel: "noopener",
      href: live ? `https://youtube.com/shorts/${v.youtube_id}` : `https://studio.youtube.com/video/${v.youtube_id}/edit`,
      title: live ? "Watch on YouTube" : "Open in YouTube Studio" }, live ? "Watch ↗" : "Studio ↗");
    const reel = v?.platforms?.instagram;
    return h("tr", { class: "slot-row", dataset: { state: s.state, next: s.at === nextAt && !a.paused ? "1" : "0" } },
      h("td", { class: "col-time" }, h("b", {}, clockIn(s.at, scheduleTz()))),
      h("td", { class: "col-time muted" }, nyTime(s.at)),
      h("td", {}, pill(label, tone)),
      h("td", {}, reel ? pill(...(ON_INSTAGRAM[reel.state] || [cap(reel.state), "idle"])) : h("span", { class: "muted" }, "–")),
      h("td", { class: "title-cell" }, v
        ? [h("a", { href: `#studio/${v.id}` }, h("b", {}, v.title || `Short #${v.id}`)), v.category && h("small", {}, category(v.category))]
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

function overviewLede(a) {
  const sch = a.autopilot.schedule;
  const rhythm = `${plural(sch.posts_per_day, "Short")} a day, one every ${hours(sch.every_hours)} from ${sch.first_post} (${sch.timezone})`;
  const run = `the morning run makes them all from ${sch.make_at}, one after another, and rests once they're scheduled`;
  if (a.paused) return `The autopilot is paused, so the agents wait for you. Switch it on (top right) for ${rhythm}: ${run}.`;
  if (!a.services.youtube) return "The autopilot is on, but YouTube isn't connected yet, so nothing can be posted.";
  return `The autopilot is on: ${rhythm}; ${run}${a.autopilot.here ? "" : " (on GitHub)"}.`;
}

async function loadOverview() {
  const a = state.app;
  const ap = a.autopilot;
  const posted = ap.slots.filter(s => s.state === "posted").length;
  const next = ap.next;
  const run = ap.run;
  const ranToday = run.last && run.last.at >= run.starts;
  const runNote = run.running ? "running now"
    : ranToday && run.last.finished ? (run.last.ok ? `done at ${clockIn(run.last.finished, scheduleTz())}` : "stopped early: see Activity")
    : `starts at ${clockIn(run.starts, scheduleTz())}`;
  const root = $("#view-overview");
  const today = new Date(ap.slots[0].at).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", timeZone: scheduleTz() });

  root.replaceChildren(...[
    pageHead({ eyebrow: `00 · ${today}`, title: "Overview", lede: overviewLede(a),
      actions: [caseButton(), makeButton({ primary: true })] }),
    a.approvals > 0 && h("div", { class: "callout banner", dataset: { tone: "warn" } },
      h("b", {}, `${plural(a.approvals, "case")} ${a.approvals === 1 ? "waits" : "wait"} for your OK`),
      " (news or politics). Watch them and approve or discard them in the Studio. ",
      h("a", { href: "#studio" }, "Open the Studio →")),
    a.held > 0 && h("div", { class: "callout banner" },
      h("b", {}, `The Reviewer turned down ${plural(a.held, "case")} after the Animator's fixes. `),
      "Each is being made again by itself (new drawings or a new reading where it failed, later a new script) until "
      + "the Reviewer passes it; nothing waits for you, and the day's slots go to other cases meanwhile. ",
      h("a", { href: "#review" }, "Review page →")),
    a.host?.resting && h("div", { class: "callout banner", dataset: { tone: "warn" } },
      h("b", {}, `${a.host.name}'s voice is resting. `),
      (a.host.used_up
        ? `Today's ${a.host.daily} free readings of his voice are used up; they renew at ${a.host.resting}. Until then `
          + "the Shorts wait for them (no other voice reads him: one that doesn't sound like him is never used). "
        : `Gemini's free voice didn't answer, so it's asked again at ${a.host.resting}. Until then the Shorts wait for `
          + "it (no other voice reads him), and the morning run carries on as soon as it answers. "),
      h("a", { href: "#host" }, "Host page →")),
    a.drawing?.resting && a.drawing.look === "drawn" && h("div", { class: "callout banner", dataset: a.drawing.fallback ? {} : { tone: "warn" } },
      h("b", {}, "Cloudflare's drawing is resting. "),
      `${a.drawing.why ? `${a.drawing.why.replace(/\.?$/, ".")} ` : ""}It's asked again at ${a.drawing.resting}. Until then the `
      + (a.drawing.fallback
        ? "Shorts are made with real footage (stock video, archive film and photos), so the day's Shorts still go up. "
        : "drawn Shorts wait (no other look is used instead), and the morning run carries on as soon as it can draw. "),
      h("a", { href: "#settings" }, "Settings →")),
    instagramDown(a),
    kpis([
      { label: "Posted today", value: posted, unit: `/ ${ap.slots.length}` },
      { label: "Next post", value: next ? clockIn(next.at, scheduleTz()) : "–",
        note: next ? `${fromNow(next.at)} · ${nyTime(next.at)} in New York` : "" },
      { label: "Today's run", value: run.scheduled, unit: `/ ${run.slots} scheduled`, note: runNote,
        tone: ranToday && !run.running && run.last.ok === 0 ? "warn" : null },
      { label: "Waiting for your OK", value: a.approvals, note: "news and politics", tone: a.approvals ? "warn" : null },
      { label: "Autopilot", value: a.paused ? "Paused" : "On", tone: a.paused ? "warn" : "ok",
        note: ap.here ? "checks every minute on this PC" : `runs on GitHub${ap.last_check ? `, last ${fromNow(ap.last_check)}` : ""}` },
    ]),
    section({ num: "01–07", title: "The seven agents", text: "In order: each one hands its work to the next, and all of them "
      + "learn from the Reviewer's checks and the Analyst's numbers.", body: pipelineSteps() }),
    h("div", { class: "grid-2-1" },
      section({ num: "A", title: "Today's schedule", text: `On the ${scheduleTz()} clock, with New York time beside it. `
        + "The Schedule page has each one's buttons for YouTube and Instagram.",
        actions: h("a", { class: "btn btn-sm", href: "#schedule" }, "Full schedule"),
        body: table([["Time", { class: "col-time" }], ["New York", { class: "col-time" }], "YouTube", "Instagram", "Short",
                     ["", { class: "col-actions" }]], slotRows(ap.slots)) }),
      h("div", {},
        section({ num: "B", title: "Ask for a case", text: a.requests ? `${plural(a.requests, "request")} waiting; Agent 1 takes them first.`
                                                                       : "Agent 1 makes it next.",
          body: h("div", { class: "card card-pad" }, requestBox()) }),
        section({ num: "C", title: "Coming up", text: "Holidays and world days the Editor can tie a case to.",
          body: h("div", { class: "card card-pad" }, a.events.length
            ? h("ul", { class: "events" }, a.events.slice(0, 6).map(e => h("li", {}, h("span", {}, e.name),
                h("small", {}, e.in_days === 0 ? "today" : `in ${plural(e.in_days, "day")}`))))
            : h("p", { class: "note" }, "Nothing in the next few days.")) }))),
    h("div", { id: "overview-activity", style: "margin-top:30px" })].filter(Boolean));
  syncButtons();
  const act = await api("/api/activity");
  const box = $("#overview-activity");
  if (box) box.replaceChildren(section({ num: "D", title: "Latest work", text: "What the agents did most recently.",
    actions: h("a", { class: "btn btn-sm", href: "#activity" }, "All activity"),
    body: runsTable(act.runs.slice(0, 6)) }));
}

// ------------------------------------------------------------------ 01 topics (Agent 1)

const REQUEST_STATUS = { waiting: ["Waiting", "accent"], used: ["Made", "ok"], dropped: ["Not made", "idle"] };

async function loadTopics() {
  const t = await api("/api/topics");
  const month = t.briefs.filter(b => Date.now() - new Date(b.created_at) < 30 * 8.64e7);
  const waiting = t.requests.filter(r => r.status === "waiting");
  $("#view-topics").replaceChildren(
    pageHead({ eyebrow: "01 · Agent 1 · Editor", agent: "editor", title: "Topics",
      lede: "Agent 1 decides each case: its type (business, the economy, this week's news, history or mythology), "
            + "the topic, the paradox it opens on and the mystery it solves, and what footage to look for: from today's "
            + "trends, Wikipedia's news and history pages, your requests (always first), viewers' comments and cases "
            + "that did well enough for a part 2.",
      actions: [caseButton({ primary: true })] }),
    kpis([
      { label: "Your requests", value: waiting.length, note: "waiting; taken first" },
      { label: "Cases chosen", value: month.length, note: "in the last 30 days" },
      { label: "From comments", value: t.briefs.filter(b => b.from_comment).length, note: "viewers' ideas made" },
      { label: "Follow-ups", value: t.briefs.filter(b => b.follow_up_of).length, note: "part 2s of cases that did well" },
    ]),
    section({ num: "1.1", title: "Ask for a case", text: "Type a topic or a question. Agent 1 makes it next, unless it breaks the channel's rules (then it says why).",
      body: h("div", {}, h("div", { class: "card card-pad" }, requestBox({ onDone: loadTopics })),
        t.requests.length > 0 && h("div", { style: "margin-top:12px" }, table(
          [["Asked", { class: "col-time" }], "Request", "Status", ["", { class: "col-actions" }]],
          t.requests.map(r => {
            const [label, tone] = REQUEST_STATUS[r.status] || [r.status, "idle"];
            return h("tr", {},
              h("td", { class: "col-time small" }, fmtWhen(r.created_at)),
              h("td", { class: "title-cell" }, h("b", {}, r.text), r.reason && h("small", {}, r.reason)),
              h("td", {}, r.video_id ? h("a", { href: `#research/${r.video_id}` }, pill(`${label} · #${r.video_id}`, tone)) : pill(label, tone)),
              h("td", { class: "col-actions" }, r.status === "waiting" && h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button",
                onclick: async () => {
                  try { await api(`/api/topics/${r.id}`, { method: "DELETE" }); loadTopics(); loadState(); }
                  catch (e) { toast(e.message, "error"); }
                } }, "Remove")));
          }))) ) }),
    section({ num: "1.2", title: "Cases chosen", text: "Newest first. Open one to see its research.",
      body: t.briefs.length
        ? table([["#", { class: "col-num" }], "Type", "The question", "Why now", "Status"], t.briefs.map(b => h("tr", {},
            h("td", { class: "col-num" }, `#${b.id}`),
            h("td", {}, h("span", { class: "tag", dataset: { cat: b.category } }, category(b.category))),
            h("td", { class: "title-cell" }, h("a", { href: `#research/${b.id}` }, h("b", {}, b.angle)), h("small", {}, b.topic)),
            h("td", { class: "small" }, WHY_NOW[b.why_now] || b.why_now, b.trend && h("small", { class: "muted", style: "display:block" }, b.trend)),
            h("td", {}, statusPill(b)))))
        : empty("No cases yet", "Press “Make a new case”: Agent 1 picks it, Agent 2 researches it, Agent 3 writes it.") }),
    h("div", { class: "grid-2 section" },
      section({ num: "1.3", title: "The mix", text: "How often each type is picked; change it in Settings.",
        actions: h("a", { class: "btn btn-sm", href: "#settings" }, "Settings"),
        body: h("div", { class: "card card-pad" }, h("ul", { class: "mix" }, Object.entries(t.categories).map(([key, text]) => {
          const w = Number(t.weights[key] || 0);
          return h("li", { dataset: { cat: key } }, h("div", {}, h("b", {}, category(key)), h("p", { class: "hint" }, text)),
            pill((HOW_OFTEN.find(([n]) => n === w) || [w, `×${w}`])[1], w ? "ok" : "idle"));
        }))) }),
      section({ num: "1.4", title: "Viewers' comments", text: t.comment_requests ? "Read daily by Agent 7; Agent 1 can make a case a comment asks for."
                                                                                  : "Switched off in Settings.",
        body: t.comments.length
          ? h("div", { class: "card card-pad" }, h("ul", { class: "events" }, t.comments.slice(0, 12).map(c => h("li", {},
              h("span", {}, c.text), h("small", {}, c.used_by ? `made: #${c.used_by}` : `♥ ${c.likes || 0}`)))))
          : empty("No comments yet", "They appear once cases are public and people comment.") })),
    h("div", { id: "signals" }));
  syncButtons();
  if (state.signals) renderSignals();
  loadSignals();
}

// The signals Agent 1 reads: out-of-date trends come back at once while today's load in the background
// (asking every country takes minutes), so the section checks again shortly.
async function loadSignals(refresh = false) {
  clearTimeout(state.signalsPoll);
  if (refresh) { state.signals = { ...(state.signals || {}), fetching: true }; renderSignals(); }
  try {
    state.signals = await api(`/api/trends${refresh ? "?refresh=1" : ""}`);
  } catch (e) {
    if (refresh || !state.signals) toast(e.message, "error");
  }
  if (currentView() !== "topics") return;
  renderSignals();
  if (state.signals?.refreshing) state.signalsPoll = setTimeout(() => {
    if (currentView() === "topics") loadSignals();
  }, 15000);
}

function renderSignals() {
  const box = $("#signals");
  const t = state.signals;
  if (!box) return;
  if (!t || !t.google_trends) {
    box.replaceChildren(section({ num: "1.5", title: "What the Editor reads today", body: h("p", { class: "loading" }, "Reading today's signals…") }));
    return;
  }
  const world = t.region === "ALL";
  const note = t.fetching ? "Asking every country for today's trends… this can take a few minutes."
    : t.refreshing ? `Showing the trends from ${t.fetched_at ? fromNow(t.fetched_at) : "before"} while today's load in the background.`
    : t.errors?.length ? `Notes: ${t.errors.join(" · ")}` : `Fetched ${t.fetched_at ? fromNow(t.fetched_at) : "–"}; reused for up to 6 hours.`;
  const ranked = (items, empty_) => items.length ? h("ol", { class: "ranked" }, items) : h("p", { class: "note" }, empty_);
  box.replaceChildren(section({ num: "1.5", title: "What the Editor reads today", text: note,
    actions: h("button", { class: "btn btn-sm", type: "button", disabled: !!t.fetching, onclick: () => loadSignals(true) },
      t.fetching ? "Fetching…" : "Refresh trends"),
    body: h("div", { class: "grid-2" },
      h("div", { class: "card card-pad" },
        h("p", { class: "sub-head" }, "In the news · Wikipedia's Current events"),
        ranked((t.news || []).slice(0, 10).map(n => h("li", {}, h("span", {}, n.text),
          h("small", { title: n.outlets.join(", ") }, n.section.split(" ")[0]))), t.news_error || "Nothing found."),
        h("p", { class: "sub-head" }, "On this day in history"),
        ranked((t.on_this_day || []).slice(0, 8).map(e => h("li", {}, h("span", {}, e.text), h("small", {}, e.year))),
               t.on_this_day_error || "Nothing found.")),
      h("div", { class: "card card-pad" },
        h("p", { class: "sub-head" }, world ? `Trending searches · ${t.countries ?? "every"} countries` : `Trending searches · ${t.region}`),
        ranked(t.google_trends.slice(0, 10).map(g => h("li", {}, h("span", {}, g.term),
          h("small", { title: (g.countries || []).join(", ") }, world ? `${(g.countries || []).length} ctry` : g.traffic || ""))), "Nothing yet."),
        h("p", { class: "sub-head" }, "Popular explainers on YouTube"),
        t.youtube_popular.length
          ? ranked(t.youtube_popular.slice(0, 8).map(p => h("li", {}, h("span", {}, p.title),
              h("small", {}, p.countries?.length > 1 ? `${p.countries.length} ctry` : p.views ? `${(p.views / 1e6).toFixed(1)}M` : ""))), "")
          : h("p", { class: "note" }, state.app.services.youtube ? "Nothing came back this time."
                                      : ["Connect YouTube to see these. ", h("a", { href: "#youtube" }, "How →")]))) }));
}

// ------------------------------------------------------------------ the case list both 02 and 03 use

function caseList(list, selectedId, onPick, note) {
  return h("div", { class: "card studio-list" },
    h("div", { class: "card-head" }, h("h3", {}, plural(list.length, "case")), h("p", {}, note)),
    h("ul", { class: "vlist" }, list.map(v => h("li", {},
      h("button", { class: "vrow", type: "button", "aria-current": String(v.id === selectedId), onclick: () => onPick(v.id) },
        h("span", { class: "vid" }, `#${v.id}`),
        h("span", { class: "vtitle" }, v.title || v.angle || "A case"),
        h("span", { class: "vmeta" }, h("span", { class: "tag", dataset: { cat: v.category } }, category(v.category)), statusPill(v),
          v.preview && pill("Animated", "ok")))))));
}

// ------------------------------------------------------------------ 02 research (Agent 2)

async function loadResearch() {
  state.videos = await api("/api/videos");
  const sub = Number(location.hash.split("/")[1]);
  if (sub) {
    state.research.selected = sub;
    history.replaceState(null, "", "#research");
  }
  renderResearch();
}

function renderResearch() {
  const list = state.videos.filter(v => !v.legacy && v.research);
  if (!list.some(v => v.id === state.research.selected)) state.research.selected = list[0]?.id ?? null;
  const selected = list.find(v => v.id === state.research.selected);
  const waiting = list.filter(v => v.status === "planned");
  const facts = waiting.reduce((n, v) => n + v.research.facts.length, 0);
  const dropped = waiting.reduce((n, v) => n + (v.research.dropped || 0), 0);
  $("#view-research").replaceChildren(
    pageHead({ eyebrow: "02 · Agent 2 · Researcher", agent: "researcher", title: "Research",
      lede: "Agent 2 reads free sources (Wikipedia, news sites, IMF and World Bank data) and lists what they say, then "
            + "the story: the most surprising fact, the decisions people made, the twist. Code checks every fact: its quote "
            + "must really be in its source and its numbers in the quote. It also finds the pictures: real photos "
            + "(Wikimedia Commons), stock video (Pexels, Pixabay) and archive film of the real thing, all checked by Gemini: "
            + "never a child, nothing graphic." }),
    kpis([
      { label: "Facts in the queue", value: facts, note: `checked, across ${plural(waiting.length, "case")}` },
      { label: "Dropped", value: dropped, note: "not found in their sources" },
      { label: "Photos", value: waiting.reduce((n, v) => n + v.research.images.length, 0), note: "free licences, credited" },
      { label: "Video clips", value: waiting.reduce((n, v) => n + (v.research.footage || []).length + (v.research.archive || []).length, 0),
        note: "stock and archive, credited" },
    ]),
    section({ num: "2.1", title: "Cases", text: "Newest first.",
      body: !list.length ? empty("No research yet", "Press “Make a new case” on the Topics page.")
        : h("div", { class: "studio" },
            caseList(list, state.research.selected, id => { state.research.selected = id; renderResearch(); }, "newest first"),
            selected && researchDetail(selected)) }));
  syncButtons();
}

function researchDetail(v) {
  const r = v.research;
  const sources = Object.fromEntries(r.sources.map(s => [s.id, s]));
  const byFact = Object.fromEntries(r.facts.map(f => [f.id, f]));
  const sourceChip = id => {
    const s = sources[id];
    return s ? h("a", { class: "tag", href: s.url, target: "_blank", rel: "noopener", title: s.title }, s.publisher || s.title, " ↗") : h("span", { class: "tag" }, id);
  };
  const story = r.story || {};
  const clips = (items, archive) => h("div", { class: "photo-grid" }, items.map(c => h("figure", { class: "photo" },
    h("img", { src: c.thumb, alt: c.shows, loading: "lazy" }),
    h("figcaption", {}, h("b", {}, `${c.id} · ${c.shows}`),
      archive ? h("span", { class: "small" }, `${c.title}${c.year ? ` (${c.year})` : ""}`) : h("span", { class: "small muted" }, `searched: ${c.query}`),
      h("a", { href: c.page_url, target: "_blank", rel: "noopener" }, archive ? `${c.source}, public domain ↗` : `${c.source} ↗`)))));
  const storyBlock = (story.paradox || (story.decisions || []).length || story.twist) && h("div", { class: "callout" },
    h("p", {}, h("b", {}, "Opens on: "), byFact[story.paradox]?.claim || "–"),
    (story.decisions || []).length > 0 && h("ul", { class: "story-list" }, story.decisions.map(d =>
      h("li", {}, h("b", {}, d.who), ": ", d.decision, " ", h("span", { class: "tag fact-chip", title: byFact[d.fact]?.claim || "" }, d.fact)))),
    h("p", {}, h("b", {}, "The twist: "), byFact[story.twist]?.claim || "–"));
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, h("span", { class: "tag", dataset: { cat: v.category } }, category(v.category)),
        h("span", { class: "tag" }, WHY_NOW[v.why_now] || v.why_now), statusPill(v),
        h("span", { class: "muted small" }, `#${v.id} · researched ${fromNow(v.created_at)}`)),
      h("h2", {}, v.angle),
      v.paradox && h("p", { class: "angle" }, `The paradox: ${v.paradox}`),
      v.trend && h("p", { class: "angle" }, `Why now: ${v.trend}`)),
    h("div", { class: "detail-body single" },
      h("div", {},
        r.answer && h("div", { class: "callout" }, h("b", {}, "What the sources say: "), r.answer),
        storyBlock && h("p", { class: "sub-head" }, "The story · from the checked facts"),
        storyBlock,
        h("dl", { class: "dl", style: "margin-top:14px" },
          h("dt", {}, "Checked facts"), h("dd", {}, `${r.facts.length}${r.dropped ? ` (${r.dropped} dropped: their quote or numbers weren't in the source)` : ""}`),
          h("dt", {}, "Sources"), h("dd", {}, r.sources.length),
          h("dt", {}, "Photos"), h("dd", {}, r.images.length || "none"),
          h("dt", {}, "Video"), h("dd", {}, `${plural((r.footage || []).length, "stock clip")}, ${plural((r.archive || []).length, "archive film")}`),
          r.notes.length > 0 && [h("dt", {}, "Notes"), h("dd", { class: "muted" }, r.notes.join(" · "))]),
        h("p", { class: "sub-head" }, "Facts · each one's quote is in its source"),
        h("ol", { class: "facts" }, r.facts.map(f => h("li", {},
          h("span", { class: "fid" }, f.id),
          h("div", {},
            h("p", {}, f.claim),
            h("div", { class: "how" }, h("span", { class: "tag" }, cap(f.kind.replace("_", " "))),
              f.calculated ? h("span", { class: "tag" }, "Calculated from the data") : sourceChip(f.source)),
            !f.calculated && h("details", { class: "quote" }, h("summary", {}, "The source's words"), h("blockquote", {}, f.quote)))))),
        (r.timeline.length > 0 || r.stats.length > 0) && h("div", { class: "grid-2", style: "margin-top:18px" },
          h("div", {}, h("p", { class: "sub-head" }, "Timeline"), r.timeline.length
            ? h("ul", { class: "events" }, r.timeline.map(t => h("li", {}, h("span", {}, t.event), h("small", {}, t.when))))
            : h("p", { class: "note" }, "No dated events.")),
          h("div", {}, h("p", { class: "sub-head" }, "Big numbers"), r.stats.length
            ? h("ul", { class: "events" }, r.stats.map(s => h("li", {}, h("span", {}, s.label), h("small", {}, s.value))))
            : h("p", { class: "note" }, "None picked."))),
        r.series.length > 0 && [h("p", { class: "sub-head" }, "Data"),
          table(["Series", "Trend", ["From", { class: "col-right" }], ["To", { class: "col-right" }], "Source"], r.series.map(s => {
            const [first, last] = [s.points[0], s.points[s.points.length - 1]];
            return h("tr", {},
              h("td", { class: "title-cell" }, h("b", {}, `${s.title}, ${s.country}`), h("small", {}, s.unit + (s.forecast_from ? ` · forecasts from ${s.forecast_from}` : ""))),
              h("td", {}, sparkline(s.points, s.forecast_from)),
              h("td", { class: "col-right small" }, first ? `${first[1]} (${first[0]})` : "–"),
              h("td", { class: "col-right small" }, last ? `${last[1]} (${last[0]})` : "–"),
              h("td", {}, h("a", { href: s.url, target: "_blank", rel: "noopener", class: "small" }, s.source, " ↗")));
          }))],
        r.images.length > 0 && [h("p", { class: "sub-head" }, "Photos · free licences, credited in the description"),
          h("div", { class: "photo-grid" }, r.images.map(i => h("figure", { class: "photo" },
            h("img", { src: i.url, alt: i.shows, loading: "lazy" }),
            h("figcaption", {}, h("b", {}, `${i.id} · ${i.shows}`),
              h("a", { href: i.page, target: "_blank", rel: "noopener" }, `${i.author}, ${i.licence} ↗`)))))],
        (r.archive || []).length > 0 && [h("p", { class: "sub-head" }, "Archive film · the real thing, public domain"),
          clips(r.archive, true)],
        (r.footage || []).length > 0 && [h("p", { class: "sub-head" }, "Stock video · illustrative only, credited"),
          clips(r.footage, false)],
        h("p", { class: "sub-head" }, "Sources"),
        h("ol", { class: "sources" }, r.sources.map(s => h("li", {},
          h("span", { class: "fid" }, s.id),
          h("span", {}, h("span", { class: "tag" }, cap(s.kind)), " ",
            h("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title),
            s.publisher && s.publisher !== s.title && s.kind !== "wikipedia" && h("small", { class: "muted" }, ` · ${s.publisher}`),
            s.date && h("small", { class: "muted" }, ` · ${String(s.date).slice(0, 10)}`))))))),
    h("div", { class: "detail-actions" },
      h("a", { class: "btn btn-sm btn-primary", href: `#scripts/${v.id}` }, "See the script"),
      h("a", { class: "btn btn-sm", href: `#studio/${v.id}` }, "Open in the Studio")));
}

// ------------------------------------------------------------------ 03 scripts (Agent 3)

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
  const list = state.videos.filter(v => v.status === "planned" && !v.legacy && v.lines);
  if (!list.some(v => v.id === state.scripts.selected)) state.scripts.selected = list[0]?.id ?? null;
  const selected = list.find(v => v.id === state.scripts.selected);
  const avg = list.length ? list.reduce((n, v) => n + (v.estimate || 0), 0) / list.length : 0;

  root.replaceChildren(
    pageHead({ eyebrow: "03 · Agent 3 · Writer", agent: "writer", title: "Scripts",
      lede: "Agent 3 turns the research into the Professor's script, told as a mystery: the paradox, the question, the "
            + "people's decisions, the reveal, and a last line that echoes the first. Every line cites its facts, says how "
            + "he says it and what's on screen; a retention editor tightens it and a fact-checker reads it again. Edit "
            + "anything before it's animated.",
      actions: [caseButton({ primary: true })] }),
    kpis([
      { label: "Waiting", value: list.length, note: "written, not posted yet", tone: list.length ? null : "warn" },
      { label: "Waiting for your OK", value: list.filter(v => v.approval === "waiting").length, note: "news and politics" },
      { label: "Average length", value: avg ? Math.round(avg) : "–", unit: avg ? "s" : "", note: "estimated from the words" },
      { label: "Fixed or cut", value: list.reduce((n, v) => n + (v.cut || 0) + v.lines.filter(l => l.check === "fixed").length, 0),
        note: "lines the fact-check changed" },
    ]),
    section({ num: "3.1", title: "Cases waiting", text: "The autopilot posts the ready ones oldest first.",
      body: !list.length
        ? empty("Nothing written yet", "Press “Make a new case”. On this PC the agents also keep a few ready while the autopilot is on.")
        : h("div", { class: "studio" },
            caseList([...list].reverse(), state.scripts.selected,
                     id => leaveDirty(state.scripts.selected, () => { state.scripts.selected = id; renderScripts(); }), "oldest last"),
            selected && scriptEditor(selected)) }));
  syncButtons();
}

/** Asks before throwing away unsaved edits. */
function leaveDirty(id, go) {
  if (state.dirty.has(id) && !confirm("Leave without saving your changes to this case?")) return;
  state.dirty.delete(id);
  go();
}

function counted(input, limit) {
  const counter = h("span", { class: "counter", "aria-live": "polite" });
  const count = () => {
    const left = limit - input.value.length;
    counter.textContent = left >= 0 ? `${left} left` : `${-left} too long`;
    counter.classList.toggle("over", left < 0);
  };
  input.addEventListener("input", count);
  count();
  return counter;
}

function scriptEditor(v) {
  const root = h("article", { class: "card" });
  const lines = v.lines.map(l => ({ ...l, visuals: [...(l.visuals || [])] }));
  const facts = Object.fromEntries(v.research.facts.map(f => [f.id, f]));
  const lengthNote = h("span", { class: "muted small" });
  const markDirty = () => {
    state.dirty.add(v.id);
    lengthNote.textContent = `~${Math.round(estimate(lines.filter(l => l.text.trim())))} s when spoken`;
  };
  const select = (options, value, onchange, label) =>
    h("select", { class: "input", "aria-label": label, onchange: e => { onchange(e.target.value); markDirty(); } },
      options.map(([val, text]) => h("option", { value: val, selected: String(val) === String(value) }, text)));
  const body = h("ol", { class: "beat-list" });
  const labelled = (text, control) => h("label", {}, text, control);
  const visuals = Object.entries(v.visuals).map(([key, text]) => [key, `${key} · ${text}`.slice(0, 90)]);
  const drawn = v.look === "drawn";
  const drawLines = () => body.replaceChildren(...lines.map((l, k) => {
    const text = h("input", { class: "input", value: l.text, "aria-label": `Line ${k + 1}`,
                              oninput: e => { l.text = e.target.value; markDirty(); } });
    const direction = h("input", { class: "input", value: l.direction || "", placeholder: "low, intrigued",
                                   "aria-label": `How line ${k + 1} is said`, oninput: e => { l.direction = e.target.value; markDirty(); } });
    const [checkText, checkTone] = CHECK[l.check] || ["Not checked", "idle"];
    return h("li", { class: `beat${["closing", "echo"].includes(l.beat) ? " punch" : ""}${k === 0 ? " hook" : ""}` },
      h("span", { class: "k" }, k + 1),
      h("div", { class: "beat-main" },
        select(Object.entries(BEATS), l.beat, x => { l.beat = x; }, "Its beat in the story"),
        h("div", {}, text, h("div", { class: "line-foot" }, counted(text, LIMITS.line),
          pill(checkText, checkTone), l.was && h("span", { class: "muted small", title: l.was }, "was: ", l.was.slice(0, 60), "…"),
          (l.facts || []).map(id => h("span", { class: "tag fact-chip", title: facts[id]?.claim || "" }, id))))),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", title: "Remove this line",
        disabled: lines.length <= 4, onclick: () => { lines.splice(k, 1); markDirty(); drawLines(); } }, "✕"),
      drawn ? h("div", { class: "beat-how three drawn" },
        labelled("How he says it", direction),
        labelled("Drawing", h("input", { class: "input", value: l.scene || "same", placeholder: "same = keep the drawing before",
          title: "What's drawn behind this line, in his art: one main subject, where, the period, the light. No names, no writing.",
          "aria-label": `The drawing behind line ${k + 1}`, oninput: e => { l.scene = e.target.value; markDirty(); } })),
        labelled("Then", select([["", "Nothing more"], ...visuals], l.visuals[0] || "",
          x => { l.visuals = [x].filter(Boolean); }, "What's shown after the drawing")))
      : h("div", { class: "beat-how three" },
        labelled("How he says it", direction),
        labelled("On screen", select([["", "Keep the last picture"], ...visuals], l.visuals[0] || "",
          x => { l.visuals = [x, l.visuals[1]].filter(Boolean); }, "What's on screen first")),
        labelled("Then", select([["", "Nothing more"], ...visuals], l.visuals[1] || "",
          x => { l.visuals = [l.visuals[0], x].filter(Boolean); }, "What's on screen next"))));
  }));
  drawLines();

  const caseTitle = h("input", { class: "input", value: v.case_title, oninput: markDirty, "aria-label": "Case title on screen" });
  const title = h("input", { class: "input", value: v.title, oninput: markDirty, "aria-label": "YouTube title" });
  const description = h("textarea", { class: "input", rows: 4, oninput: markDirty, "aria-label": "Description" });
  description.value = v.description || "";
  markDirty();
  state.dirty.delete(v.id);  // measuring the length isn't an edit

  const save = async () => {
    try {
      const updated = await api(`/api/videos/${v.id}`, { method: "PATCH", json: {
        case_title: caseTitle.value, title: title.value, description: description.value,
        lines: lines.filter(l => l.text.trim()).map(l => ({ text: l.text, beat: l.beat, direction: l.direction || "",
                                                            facts: l.facts || [], visuals: l.visuals || [],
                                                            ...(drawn ? { scene: l.scene || "same" } : {}) })) } });
      state.dirty.delete(v.id);
      const i = state.videos.findIndex(x => x.id === v.id);
      if (i >= 0) state.videos[i] = updated;
      renderScripts();
      toast("Saved. Agent 4 animates the new version (or press Animate in the Studio).", "ok");
    } catch (e) {
      toast(e.message, "error", 7000);
    }
  };
  const scores = v.retention?.scores || {};
  const scoreText = Object.keys(scores).length
    ? Object.entries(scores).map(([k, n]) => `${RETENTION[k] || k} ${n}`).join(" · ") : null;

  root.append(
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, professor(), h("span", { class: "tag", dataset: { cat: v.category } }, category(v.category)),
        statusPill(v), h("span", { class: "muted small" }, `#${v.id} · written ${fromNow(v.created_at)}`)),
      h("h2", {}, v.angle),
      v.paradox && h("p", { class: "angle" }, `Opens on: ${v.paradox}`)),
    h("div", { class: "detail-body single" },
      h("div", {},
        v.approval === "waiting" && h("div", { class: "callout", dataset: { tone: "warn" } },
          "This case is about the news or politics, so it waits for your OK: watch it in the Studio, then approve it there."),
        (scoreText || (v.habits || []).length > 0) && h("div", { class: "callout" },
          scoreText && h("p", {}, h("b", {}, "Retention editor: "), scoreText, v.retention.rewritten ? ` · ${plural(v.retention.rewritten, "line")} rewritten` : ""),
          (v.habits || []).length > 0 && h("p", {}, h("b", {}, "Still sounds like a lecture: "), v.habits.join("; "))),
        h("div", { class: "field" }, h("label", {}, h("span", {}, "Case title · over the opening"), counted(caseTitle, LIMITS.caseTitle)), caseTitle),
        h("p", { class: "sub-head" }, "The Professor's script · the hook, the setup, the turning point, the reveal, his closing thought"),
        body,
        h("div", { class: "row", style: "margin-top:10px" },
          h("button", { class: "btn btn-sm", type: "button", disabled: lines.length >= 18, onclick: () => {
            lines.push({ text: "", beat: "turn", direction: "", facts: [], visuals: [], check: "edited",
                         ...(drawn ? { scene: "same" } : {}) });
            markDirty();
            drawLines();
          } }, "Add a line"),
          lengthNote),
        h("p", { class: "hint", style: "margin-top:6px" }, "A line you change is marked “edited by you”: the fact-checker doesn't read it again, so keep its numbers to the facts (F1, F2…) it cites. ",
          drawn ? "Every line plays over a drawing in his art: describe it (one main subject, no names, no writing), or write “same” to stay on the one before. A changed drawing is drawn again when the video is made."
            : "Stock video is illustrative: real photos and archive film carry the specific claims."),
        h("p", { class: "sub-head" }, "On YouTube"),
        h("div", { class: "field" }, h("label", {}, h("span", {}, "Title"), counted(title, LIMITS.title)), title),
        h("div", { class: "field" }, h("label", {}, h("span", {}, "Summary")), description),
        h("details", { class: "more" }, h("summary", {}, "The whole description at upload (sources, photo, footage and music credits)"),
          h("p", { class: "desc-ro" }, v.full_description || "")))),
    h("div", { class: "detail-actions" },
      h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: save }, "Save changes"),
      h("a", { class: "btn btn-sm", href: `#studio/${v.id}` }, v.preview ? "Watch in the Studio" : "Animate in the Studio"),
      h("a", { class: "btn btn-sm", href: `#research/${v.id}` }, "The research"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")));
  return root;
}

// ------------------------------------------------------------------ 04 studio (Agent 4)

const STUDIO_FILTERS = [
  ["planned", "Waiting", v => v.status === "planned"],
  ["coming", "Coming up", v => v.status === "making" || shownStatus(v) === "scheduled"],
  ["published", "Published", v => shownStatus(v) === "live"],
  ["stopped", "Stopped", v => ["failed", "vetoed", "discarded", "skipped"].includes(v.status)],
];
const STUDIO_TEXT = {
  planned: "Written cases. Their videos are made and reviewed ahead; watch one before its turn.",
  coming: "Uploaded as private. Each goes public at its slot; delete it in YouTube Studio before then to veto it.",
  published: "Public on YouTube.",
  stopped: "Cases that failed, were vetoed or were discarded.",
};

async function loadStudio() {
  state.videos = await api("/api/videos");
  const sub = Number(location.hash.split("/")[1]);
  if (sub) {  // a link like #studio/12 opens that Short on its tab
    const v = state.videos.find(x => x.id === sub);
    if (v) state.studio = { filter: STUDIO_FILTERS.find(([, , test]) => test(v))?.[0] || "planned", selected: v.id, picked: true };
    history.replaceState(null, "", "#studio");
  } else if (!state.studio.picked) {  // until you pick a tab, open on the first one with Shorts in it
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
  const waiting = state.videos.filter(v => v.status === "planned" && !v.legacy);

  const tabs = h("div", { class: "segmented", role: "tablist" }, STUDIO_FILTERS.map(([key, label]) =>
    h("button", { type: "button", role: "tab", "aria-selected": String(key === filter),
                  onclick: () => { state.studio = { filter: key, selected: null, picked: true }; renderStudio(); } },
      label, h("span", { class: "n" }, counts[key]))));

  root.replaceChildren(
    pageHead({ eyebrow: "04 · Agent 4 · Animator", agent: "animator", title: "Studio",
      lede: "Agent 4 has the Professor read the script (Gemini's voice, free), moves his mouth with the words (Rhubarb), "
            + "cuts the real footage, archive film, photos, maps, charts and numbers to every line, adds music in the "
            + "script's mood, makes the video on this PC with him floating in the corner, and its thumbnail. Agent 5 "
            + "then checks every video; one that fails comes back here with notes and is fixed.",
      actions: [makeButton()] }),
    kpis([
      { label: "Made", value: waiting.filter(v => v.preview).length, unit: `/ ${waiting.length}`, note: "waiting cases ready to watch" },
      { label: "Passed review", value: waiting.filter(v => v.review?.current && (v.review.passed || v.review.override)).length,
        note: "ready for the Publisher" },
      { label: "Waiting for your OK", value: waiting.filter(v => v.approval === "waiting").length, note: "news and politics",
        tone: waiting.some(v => v.approval === "waiting") ? "warn" : null },
      { label: "Coming up", value: counts.coming, note: "uploaded, not public yet" },
      { label: "Published", value: counts.published, note: "in the last 60 Shorts" },
    ]),
    section({ num: "4.1", title: "Cases", text: STUDIO_TEXT[filter], actions: tabs,
      body: !state.videos.length
        ? empty("No cases yet", "Press “Make a new case” on the Topics page, then animate it here.")
        : !list.length ? empty(`Nothing ${STUDIO_FILTERS.find(([k]) => k === filter)[1].toLowerCase()}`, STUDIO_TEXT[filter])
        : h("div", { class: "studio" },
            h("div", { class: "card studio-list" },
              h("div", { class: "card-head" }, h("h3", {}, plural(list.length, "Short")), h("p", {}, "newest first")),
              h("ul", { class: "vlist" }, list.map(v => h("li", {},
                h("button", { class: "vrow", type: "button", "aria-current": String(v.id === state.studio.selected),
                              onclick: () => { state.studio.selected = v.id; renderStudio(); } },
                  h("span", { class: "vid" }, `#${v.id}`),
                  h("span", { class: "vtitle" }, v.title || v.angle || "A case"),
                  h("span", { class: "vmeta" }, !v.legacy && professor(), statusPill(v),
                    v.legacy ? h("span", { class: "tag" }, v.legacy) : h("span", { class: "tag", dataset: { cat: v.category } }, category(v.category)),
                    v.slot && v.status !== "planned" && h("span", {}, clockIn(v.slot, scheduleTz())),
                    v.status === "planned" && !v.legacy && reviewPill(v)) ))))),
            selected && studioDetail(selected)) }));
  syncButtons();
}

/** A scheduled Short in the Studio: when it goes public, and its YouTube and Instagram parts (as on the Schedule page). */
function scheduledBox(v) {
  const live = v.publish_at && new Date(v.publish_at) <= new Date();
  const part = (id, name, which) => h("div", {}, h("p", { class: "part-name" }, icon(id, "th-ic"), name), platformPart(v, which));
  return h("div", { class: "callout", dataset: { tone: "ok" } },
    live ? "Public since " : "Goes public ", h("b", {}, fmtWhen(v.publish_at)), live ? "" : ` (${fromNow(v.publish_at)})`, ".",
    v.platforms && h("div", { class: "parts" }, part("ic-youtube", "YouTube", "youtube"),
                     part("ic-instagram", "Instagram", "instagram")),
    v.youtube_thumbnail && !v.youtube_thumbnail.set && h("small", { class: "muted", style: "display:block;margin-top:8px" },
      "YouTube kept its own thumbnail: custom ones need a channel verified by phone (youtube.com/verify)."),
    v.youtube_thumbnail?.set && h("small", { class: "muted", style: "display:block;margin-top:8px" },
      "Thumbnail on YouTube: the wide one (YouTube Studio, search, shared links). The Shorts tab shows a frame YouTube "
      + "picks until the channel is in the Partner Program."));
}

/** The Reviewer's mark on a waiting case, for the case list. */
function reviewPill(v) {
  const r = v.review;
  if (!v.preview) return h("span", {}, "not made yet");
  if (!r || !r.current) return pill("Being reviewed", "run");
  if (r.held) return pill("Being made again", "run");
  if (r.override) return pill("Posting anyway", "warn");
  return r.passed ? pill("Passed review", "ok") : pill("Being fixed", "warn");
}

/** What the Reviewer found in the latest version, what the Animator changed, and the earlier looks. */
function reviewBox(v) {
  const r = v.review;
  if (!v.preview && !v.held_upload) return null;
  if (!r || !r.current) return h("div", { class: "callout", dataset: { tone: "run" } },
    h("b", {}, "Not reviewed yet. "), "Agent 5 watches it before the Publisher may post it.");
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
      + `(${r.remakes ? `time ${r.remakes + 1}: ` : ""}new drawings or a new reading where it failed; from the third time a new script), `
      + "over and over until the Reviewer passes it. Nothing for you to do."),
    v.held_upload && h("p", {}, "It's on YouTube as a private video, not scheduled: ",
      h("a", { href: v.held_upload.studio_url, target: "_blank", rel: "noopener" }, "watch it in YouTube Studio ↗"),
      ". Publish it there if you want it out, then discard it here; or have it made again."),
    h("div", { class: "measures" },
      r.match != null && h("span", { title: "How much of the script faster-whisper made out in the final mix" }, `voice ${Math.round(r.match * 100)}%`),
      r.words_per_second != null && h("span", {}, `${r.words_per_second} words/s`),
      r.loudness != null && h("span", {}, `${r.loudness} LUFS`),
      r.look != null && h("span", { title: "Gemini's look at 8 frames, 0-10" }, `look ${r.look}/10`)),
    major.length > 0 && h("ul", { class: "issues" }, major.map(issue)),
    r.changes?.length > 0 && h("p", { class: "small" }, h("b", {}, "The Animator changed: "), r.changes.join("; ")),
    minor.length > 0 && h("details", { class: "more" }, h("summary", {}, plural(minor.length, "small note")),
      h("ul", { class: "issues" }, minor.map(issue))),
    r.history?.length > 0 && h("details", { class: "more" }, h("summary", {}, `Earlier ${plural(r.history.length, "look")}`),
      h("ul", { class: "issues" }, r.history.map(x => h("li", {}, pill(x.passed ? "Passed" : "Failed", x.passed ? "ok" : "bad"),
        h("span", {}, `Look ${x.round + 1}: ` + ((x.issues || []).filter(i => i.severity === "major").map(i => i.detail).join("; ") || "no problems"),
          x.changes?.length > 0 && h("span", { class: "fix" }, `Then: ${x.changes.join("; ")}`)))))));
}

/** The thumbnail, in the channel's one style: change its words or pick another still, and it's made again. */
function thumbEditor(v) {
  const t = v.thumbnail;
  if (!t || (!t.cover && !t.choices?.length)) return null;
  const editable = v.status === "planned";
  let picked = t.background;
  const text = h("input", { class: "input", value: t.text || "", maxlength: 60, disabled: !editable,
                            "aria-label": "The thumbnail's words", placeholder: "One phone *sank* Nokia" });
  const stills = h("div", { class: "stills" }, (t.choices || []).map(c => h("button", {
    class: "still", type: "button", title: c.label, disabled: !editable, "aria-pressed": String(c.name === picked),
    onclick: e => { picked = c.name; for (const b of $$(".still", stills)) b.setAttribute("aria-pressed", String(b === e.currentTarget)); } },
    c.thumb ? h("img", { src: c.thumb, alt: c.label, loading: "lazy" }) : c.name.split(":")[0])));
  const save = async () => {
    try {
      const updated = await api(`/api/videos/${v.id}/thumbnail`, { method: "POST", json: { text: text.value, background: picked } });
      Object.assign(v, updated);
      toast("Thumbnail made again.", "ok");
      renderStudio();
    } catch (e) {
      toast(e.message, "error", 7000);
    }
  };
  return h("details", { class: "more", open: true }, h("summary", {}, "Thumbnail"),
    h("div", { class: "thumbs" },
      t.cover ? h("img", { class: "cover", src: t.cover, alt: "The thumbnail" }) : h("div", { class: "cover" }),
      h("div", { class: "thumb-form" },
        t.wide && h("img", { class: "wide", src: t.wide, alt: "The wide thumbnail" }),
        editable && [h("label", { class: "label" }, "Words (2-5; *star* the coloured one)"), text,
          h("label", { class: "label" }, "Still"), stills,
          h("div", {}, h("button", { class: "btn btn-sm", type: "button", onclick: save }, t.cover ? "Make it again" : "Make the thumbnail"))],
        h("p", { class: "note" }, "On YouTube the wide one shows in YouTube Studio, search on computers and shared links. "
          + "The Shorts tab and feed show a frame YouTube picks from the video: custom Shorts covers are only for "
          + "channels in the YouTube Partner Program, added in YouTube Studio on a computer. The tall one is the Reel's "
          + "cover on Instagram."))));
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

function scriptView(v) {
  // A case still being made, or one stopped before its script, has no lines yet (the Studio opened blank on it)
  if (!v.lines?.length) return h("p", { class: "muted" }, v.status === "making" ? "Agents 1-3 are still writing it." : "No script.");
  return h("ol", { class: "script" }, v.lines.map((l, k) => {
    const [checkText, checkTone] = CHECK[l.check] || ["Not checked", "idle"];
    return h("li", { class: ["closing", "echo"].includes(l.beat) || k === v.lines.length - 1 ? "punch" : "" },
      h("span", { class: "beat-k" }, k + 1),
      h("div", {},
        h("span", { class: "who" }, BEAT_NAMES[l.beat] || cap(l.beat || ""), l.direction && h("small", { class: "muted" }, ` · ${l.direction}`)),
        h("p", { class: "line" }, l.text),
        v.look === "drawn" && l.scene && l.scene !== "same" && h("div", { class: "scene-row" },
          v.drawings?.[k + 1] && h("a", { href: v.drawings[k + 1], target: "_blank", title: "The drawing, full size" },
            h("img", { src: v.drawings[k + 1], alt: "", loading: "lazy" })),
          h("p", { class: "muted small" }, h("b", {}, "Drawing: "), l.scene, l.redraws ? ` · drawn ${l.redraws + 1} times` : "")),
        h("div", { class: "how" }, (l.visuals || []).map(name => h("span", { class: "tag" }, name)),
          !["ok", "framing"].includes(l.check) && pill(checkText, checkTone))));
  }));
}

function studioDetail(v) {
  if (v.legacy) return legacyDetail(v);
  const editable = v.status === "planned";
  const waits = v.approval === "waiting";
  const s = state.app.services;
  const nextOpen = state.app.autopilot.next_open;
  const blocked = !s.youtube || !nextOpen || waits;
  const phone = h("div", { class: "phone" },
    v.preview ? h("video", { src: v.preview, controls: true, playsinline: true, preload: "metadata", poster: v.cover || undefined })
      : v.cover ? [h("img", { src: v.cover, alt: "" }), h("span", { class: "phone-badge" }, "Uploaded; preview cleared")]
      : h("div", { class: "phone-blank" }, !editable ? "No video here."
          : v.review?.held ? `Turned down by the Reviewer: the Animator makes it again by itself${v.review.remake_at ? ` at about ${v.review.remake_at}` : ""}.`
          : state.app.paused ? "Not made yet. The autopilot is paused: switch it on and the Animator makes it by itself."
          : state.app.host?.resting ? `Not made yet: the Animator makes it when Gemini's voice is back (${state.app.host.resting}).`
          : v.look === "drawn" && state.app.drawing?.resting ? (state.app.drawing.fallback
              ? `Not made yet: Cloudflare can't draw until ${state.app.drawing.resting}, so the Animator makes it with real footage in a few minutes, review included.`
              : `Not made yet: the Animator draws it when Cloudflare can draw again (${state.app.drawing.resting}).`)
          : "Not made yet: the Animator makes it by itself in a few minutes, review included."));
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, professor(), h("span", { class: "tag", dataset: { cat: v.category } }, category(v.category)), statusPill(v),
        h("span", { class: "muted small" }, `#${v.id} · ${v.duration ? secs(v.duration) : `~${secs(v.estimate)}`}`
          + (v.music ? ` · ♪ ${v.music.replace(/\.[^.]+$/, "")}` : "")
          + (v.voice?.voice ? ` · voice: ${v.voice.voice.split(" (")[0]}${v.voice.deeper ? `, ${v.voice.deeper} lower` : ""}` : ""))),
      h("h2", {}, v.title || v.angle),
      h("p", { class: "angle" }, v.angle)),
    h("div", { class: "detail-body" },
      phone,
      h("div", {},
        editable && reviewBox(v),
        editable && v.voice?.backup && h("div", { class: "callout", dataset: { tone: "warn" } },
          h("b", {}, "Read by the old backup voice. "), "The Animator makes it again in the Professor's own voice before "
          + "it goes up."),
        v.switched && h("div", { class: "callout" },
          h("b", {}, "Made with real footage. "), "It was written for drawings, but Cloudflare couldn't draw it then, so "
          + "the Writer wrote it again for stock video, archive film and photos (Settings: When Cloudflare can't draw)."),
        editable && !v.preview && v.preview_failed_at && h("div", { class: "callout", dataset: { tone: "warn" } },
          "The last try to make it didn't work (see Activity). The Animator tries again by itself in about half an "
          + "hour; after three failed tries a new case takes its place."),
        editable && waits && h("div", { class: "callout", dataset: { tone: "warn" } },
          h("b", {}, "Waits for your OK. "), "It's about the news or politics: watch it, check the research, then approve it "
          + "(it then goes up at its turn) or discard it. Unapproved, it's discarded after a couple of days."),
        v.approval === "approved" && editable && h("div", { class: "callout", dataset: { tone: "ok" } },
          `${v.approved_by === "publisher" ? "Approved by the Publisher" : "Approved"} ${fromNow(v.approved_at)}.`),
        v.status === "making" && v.slot && h("div", { class: "callout", dataset: { tone: "warn" } }, "Being made for the ",
          h("b", {}, clockIn(v.slot, scheduleTz())), " slot right now."),
        v.status === "scheduled" && scheduledBox(v),
        v.error && h("div", { class: "callout", dataset: { tone: "bad" } }, v.error),
        h("p", { class: "sub-head" }, "The script"),
        scriptView(v),
        thumbEditor(v),
        h("details", { class: "more" }, h("summary", {}, "Description, sources & credits"),
          h("p", { class: "desc-ro" }, v.full_description || v.description || "")))),
    editable && h("div", { class: "detail-actions" },
      waits && h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: () => approve(v) }, "Approve"),
      v.review?.held && !v.held_upload && h("button", { class: "btn btn-sm btn-primary", type: "button",
                                                        onclick: () => answerReviewer(v, "post") }, "Post it anyway"),
      v.preview ? !v.review?.held && h("button", { class: "btn btn-sm", type: "button", onclick: () => answerReviewer(v, "remake") }, "Make it again")
        : h("button", { class: "btn btn-sm", type: "button", "data-needs-idle": true, onclick: () => runTask("render", v.id),
                    title: "Optional: the Animator makes it by itself anyway" }, "Make it now"),
      h("a", { class: "btn btn-sm", href: `#scripts/${v.id}` }, "Edit the script"),
      h("button", { class: `btn btn-sm${waits ? "" : " btn-primary"}`, type: "button", "data-needs-idle": true, dataset: { blocked: blocked ? "1" : "0" },
        title: waits ? "Approve it first" : !s.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
             : `The Reviewer checks it first, then it's uploaded as private for the next free slot (${clockIn(nextOpen, scheduleTz())})`,
        onclick: () => upload(v) }, "Upload & schedule"),
      h("span", { class: "spacer" }),
      !s.youtube && h("a", { class: "note", href: "#youtube" }, "Connect YouTube to upload"),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")));
}

/** A Short made by an earlier version: it can still go up as it is, but the agents don't make this kind. */
function legacyDetail(v) {
  const s = state.app.services;
  const canUpload = v.status === "planned" && v.preview && s.youtube && state.app.autopilot.next_open;
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, statusPill(v), h("span", { class: "tag" }, v.legacy), h("span", { class: "muted small" }, `#${v.id}`)),
      h("h2", {}, v.title || "A Short")),
    h("div", { class: "detail-body" },
      h("div", { class: "phone" }, v.preview
        ? h("video", { src: v.preview, controls: true, playsinline: true, preload: "metadata" })
        : h("div", { class: "phone-blank" }, "No video kept for this one.")),
      h("div", {},
        v.status === "scheduled" && scheduledBox(v),
        v.status === "planned" && h("div", { class: "callout", dataset: { tone: "warn" } },
          `Made by an earlier version of the channel (the ${v.legacy.toLowerCase()}). It can still go up exactly as it is`
          + (v.preview ? "" : " (but its video wasn't kept)") + ", or be discarded; the agents don't make this kind any more."),
        h("details", { class: "more" }, h("summary", {}, "Description"), h("p", { class: "desc-ro" }, v.description || "")))),
    v.status === "planned" && h("div", { class: "detail-actions" },
      h("button", { class: "btn btn-sm btn-primary", type: "button", "data-needs-idle": true, dataset: { blocked: canUpload ? "0" : "1" },
        onclick: () => upload(v) }, "Upload & schedule"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")));
}

async function approve(v) {
  if (!confirm(`Approve “${v.title}”?\n\nIt then goes up at its turn like any other case (or now, with “Upload & schedule”).`)) return;
  try {
    await api(`/api/videos/${v.id}/approve`, { method: "POST" });
    toast("Approved.", "ok");
    await loadState();
    loaders[currentView()]();
  } catch (e) {
    toast(e.message, "error");
  }
}

function upload(v) {
  const slot = state.app.autopilot.next_open;
  const when = slot ? `${fmtWhen(slot)} (${fromNow(slot)})` : "at the next free slot";
  if (!confirm(`Upload “${v.title}” to YouTube?\n\nThe Reviewer checks its video first (a held one isn't posted). It goes up `
             + `as private and becomes public ${when}. Until then you can still delete it in YouTube Studio.`)) return;
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

// ------------------------------------------------------------------ 05 review (Agent 5)

const ISSUE_KINDS = { number: "Big number collided", title: "Title collided", overlap: "Words overlapped",
                      covers_host: "Words over his face", unsafe: "Under YouTube's buttons", frozen: "Clip stood still",
                      dark: "Too dark", unclear: "Voice unclear", rushed: "Line rushed", fast: "Too fast overall",
                      silence: "Silence", loudness: "Loudness", long: "Too long", short: "Too short", size: "Wrong size",
                      sound: "No sound", text_cut_off: "Words cut off", broken_picture: "Broken picture", watermark: "Watermark",
                      child_visible: "A child visible", graphic: "Graphic" };

async function loadReview() {
  const r = await api("/api/review");
  const firsts = r.history.filter(x => x.round === 0);
  const firstPass = firsts.filter(x => x.passed).length;
  const finals = Object.values(r.history.reduce((m, x) => (m[x.video_id] ??= x, m), {}));  // newest look of each case
  const fixed = finals.filter(x => x.passed && x.round > 0).length;
  const counts = r.lessons.counts || {};
  const taught = r.lessons.for || {};
  const c = r.checks;
  const names = Object.fromEntries(state.app.agents.map(a => [a.key, `${a.number} ${a.name}`]));
  $("#view-review").replaceChildren(...[
    pageHead({ eyebrow: "05 · Agent 5 · Reviewer", agent: "reviewer", title: "Review",
      lede: "Agent 5 watches and listens to every video before the Publisher may post it. A video that fails goes back to "
            + `the Animator with notes, at most ${plural(r.max_rounds, "time")}; one that still fails is made again by itself, until it passes. `
            + "Problems that keep coming back become lessons the other agents apply from then on." }),
    kpis([
      { label: "Passed at first look", value: firsts.length ? `${Math.round(firstPass / firsts.length * 100)}` : "–",
        unit: firsts.length ? "%" : "", note: `of the last ${plural(firsts.length, "video")}` },
      { label: "Fixed by the Animator", value: fixed, note: "failed, then passed" },
      { label: "Being made again", value: r.held.length, note: "turned down after the fixes: made again by themselves" },
      { label: "Lessons taught", value: Object.values(taught).reduce((n, t) => n + (t.advice?.length || 0), 0),
        note: r.lessons.updated_at ? `updated ${fromNow(r.lessons.updated_at)}` : "none yet" },
    ]),
    r.held.length > 0 && section({ num: "5.1", title: "Being made again", text: "Turned down after the Animator's fixes: each is made again by itself (new drawings or a new reading where it failed; from the third time a new script), until the Reviewer passes it. Nothing for you to do.",
      body: table(["Case", "Why it was turned down", "Next making"], r.held.map(x => h("tr", {},
        h("td", { class: "title-cell" }, h("a", { href: `#studio/${x.id}` }, h("b", {}, x.title || `Case #${x.id}`))),
        h("td", { class: "small" }, x.because || ""),
        h("td", { class: "small" }, `${x.remake_at ? `about ${x.remake_at}` : "next"}${x.remakes ? ` (time ${x.remakes + 1})` : ""}`)))) }),
    section({ num: "5.2", title: "What it checks", text: "On the finished video, the way a viewer sees and hears it.",
      body: h("div", { class: "card card-pad" }, h("ul", { class: "lessons" },
        h("li", {}, h("b", {}, "Words on screen: "), "captions, numbers, names and the title never on top of each other, over the Professor's face, or under YouTube's buttons and title."),
        h("li", {}, h("b", {}, "His voice: "), `faster-whisper hears the final mix; at least ${Math.round(c.min_match * 100)}% of the script must come through, and every line clearly.`),
        h("li", {}, h("b", {}, "That it's him: "), `read by a model that does his voice, and measured against the Host page's sample of it: pitch within ${-c.his_pitch[0]} semitones below and ${c.his_pitch[1]} above, the same timbre. One that isn't him is read again.`),
        h("li", {}, h("b", {}, "Pace: "), `no line faster than ${c.line_pace} words a second; the whole between ${c.pace[0]} and ${c.pace[1]}.`),
        h("li", {}, h("b", {}, "Sound: "), `loudness near ${c.loudness} LUFS (where Shorts play), no clipping, no silence where he should speak.`),
        h("li", {}, h("b", {}, "Picture: "), "no shot too dark to see, no clip standing still, 1080×1920, within the length limit."),
        h("li", {}, h("b", {}, "A look: "), `Gemini looks at ${c.frames} frames for words cut off, a broken or watermarked picture, a child or anything graphic.`))) }),
    section({ num: "5.3", title: "Lessons it has taught", text: `A problem in ${c.recurring} of the last ${c.lookback} first looks becomes a standing fix or advice.`,
      body: Object.keys(taught).length
        ? h("div", { class: "taught" }, Object.entries(taught).map(([agent, t]) => h("div", { class: "card card-pad", dataset: { agent } },
            h("span", { class: "agent-badge", dataset: { agent } }, h("i"), names[agent] || agent),
            Object.keys(t.settings || {}).length > 0 && h("div", {}, Object.entries(t.settings).map(([k, x]) => h("span", { class: "setting-chip" }, `${k}: ${x}`))),
            h("ul", {}, (t.advice || []).map(a => h("li", {}, a))))))
        : empty("Nothing yet", "Lessons appear once the same problem turns up again and again.") }),
    Object.keys(counts).length > 0 && section({ num: "5.4", title: "What it finds most", text: `In the last ${plural(firsts.length, "first look")}.`,
      body: h("div", { class: "card card-pad" }, h("div", { class: "rounds" },
        Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => h("span", { class: "tag" }, `${ISSUE_KINDS[k] || k} · ${n}`)))) }),
    section({ num: "5.5", title: "Recent reviews", text: "Newest first; each look at a case is a row.",
      body: r.history.length
        ? table([["When", { class: "col-time" }], "Case", "Look", "Result", "Problems"], r.history.slice(0, 30).map(x => h("tr", {},
            h("td", { class: "col-time small" }, fmtWhen(x.at)),
            h("td", { class: "title-cell" }, h("a", { href: `#studio/${x.video_id}` }, h("b", {}, x.title || `Case #${x.video_id}`))),
            h("td", {}, `${x.round + 1}`),
            h("td", {}, x.passed ? pill("Passed", "ok") : pill("Failed", "bad")),
            h("td", { class: "small" }, (x.kinds || []).map(k => ISSUE_KINDS[k] || k).join(", ") || "–"))))
        : empty("No reviews yet", "Every video is reviewed once it's made.") })].filter(Boolean));
}

// ------------------------------------------------------------------ 06 schedule (Agent 6)

/** What a Short's YouTube or Instagram part says beside its state, e.g. "goes public 16:00 · in 2 hours". */
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
           skipped: "it wasn't public on YouTube at its slot",
           expired: "not posted within 2 days of its slot (this PC was off)",
           cancelled: p.because || "you took it off",
           deleted: "deleted from Instagram",
           remaking: "made again for Instagram (a few minutes), then it waits for its slot" }[p.state] || "";
}

/** Why a button on a Short's YouTube or Instagram part is greyed out. */
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

/** A Short's part on YouTube or on Instagram: where it stands there, and Open, Post now and Delete (and Stop on
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
        ? h("button", { class: "btn btn-xs", type: "button", title: "Makes its video again (a few minutes), then its Reel "
                        + "waits for its slot", onclick: () => instagramAction(v, "schedule") }, "Schedule")
        : button("now", "Post now"),
      yt && button("stop", "Stop"), button("delete", "Delete", true)));
}

const partHead = (id, name) => [[icon(id, "th-ic"), name], { class: "col-part" }];
const partCell = (v, which) => h("td", { class: "col-part", "data-label": which === "youtube" ? "YouTube" : "Instagram" },
  v ? platformPart(v, which) : h("span", { class: "muted" }, "–"));

/** A slot on the Schedule page: its time, its Short, and the Short's YouTube and Instagram parts. */
function scheduleRow(s) {
  const a = state.app;
  const v = s.video;
  const [label, tone] = SLOT[a.paused && ["due", "late"].includes(s.state) ? "paused" : s.state] || [s.state, "idle"];
  return h("tr", { class: "slot-row", dataset: { state: s.state, next: s.at === a.autopilot.next?.at && !a.paused ? "1" : "0" } },
    h("td", { class: "col-time" }, h("b", {}, clockIn(s.at, scheduleTz()))),
    h("td", { class: "col-time muted" }, nyTime(s.at)),
    h("td", { class: "title-cell" }, v
      ? [h("a", { href: `#studio/${v.id}` }, h("b", {}, v.title || `Short #${v.id}`)), v.category && h("small", {}, category(v.category))]
      : [pill(label, tone), h("small", {}, s.state === "missed" ? "Nothing went out" : "Not made yet")]),
    partCell(v, "youtube"), partCell(v, "instagram"));
}

async function loadSchedule() {
  const a = state.app;
  const ap = a.autopilot;
  const data = await api("/api/schedule");
  const now = new Date();
  const shorts = [...data.slots.map(s => s.video).filter(Boolean), ...data.later];
  const ahead = shorts.filter(v => v.status === "scheduled" && v.publish_at && new Date(v.publish_at) > now).length;
  const posted = data.slots.filter(s => s.state === "posted").length;
  const reels = data.slots.filter(s => s.video?.platforms?.instagram.state === "posted").length;
  const ig = a.services.instagram || {};
  $("#view-schedule").replaceChildren(...[
    pageHead({ eyebrow: "06 · Agent 6 · Publisher", agent: "publisher", title: "Schedule",
      lede: "Agent 6 uploads each case that passed the Reviewer as private with its slot as the publish time, so YouTube "
            + "makes it public on the minute, with its sources, photo credits and the music's credit in the description, "
            + "and its thumbnail. With Instagram on, the same video goes up as a Reel when its slot comes. Beside each "
            + "Short: where it stands on YouTube and on Instagram, with Open, Post now and Delete for each (and Stop, "
            + "which keeps it private on YouTube).",
      actions: [h("a", { class: "btn", href: "#settings" }, "Change the timetable"), makeButton({ primary: true })] }),
    kpis([
      { label: "Posted today", value: posted, unit: `/ ${data.slots.length}` },
      { label: "Reels today", value: ig.connected ? reels : "–", unit: ig.connected ? `/ ${data.slots.length}` : "",
        note: ig.connected ? (ig.on ? "posted on Instagram" : "Reels are switched off") : "Instagram isn't connected" },
      { label: "Next post", value: ap.next ? clockIn(ap.next.at, scheduleTz()) : "–", note: ap.next ? fromNow(ap.next.at) : "" },
      { label: "Scheduled ahead", value: ahead, note: "uploaded, waiting to go public" },
      { label: "Next free slot", value: ap.next_open ? clockIn(ap.next_open, scheduleTz()) : "–",
        note: ap.next_open ? fromNow(ap.next_open) : "every slot this week is taken" },
    ]),
    a.services.youtube && !a.services.youtube_manage && h("div", { class: "callout banner", dataset: { tone: "warn" } },
      h("b", {}, "Post now, Stop and Delete need your OK on YouTube once. "),
      a.local !== false
        ? h("span", {}, "Google's page asks whether this app may change or delete your videos. ",
            h("button", { class: "btn btn-sm", type: "button", onclick: () => allowManaging() }, "Allow it now"))
        : "Allow it from the dashboard on your computer; until then use YouTube Studio."),
    !ig.connected && h("div", { class: "callout banner" },
      h("b", {}, "Instagram isn't connected yet, "), "so its side shows “Not for Instagram”. Connect it on the ",
      h("a", { href: "#youtube" }, "Channels page"), ": the Shorts uploaded after that get their Reels."),
    instagramDown(a),
    data.youtube.error && h("div", { class: "callout banner", dataset: { tone: "warn" } },
      h("b", {}, "YouTube didn't say how they stand just now "), `(${data.youtube.error}). The YouTube side shows what `
      + "the dashboard knows; it asks again in 2 minutes."),
    section({ num: "6.1", title: "Today's slots", text: `${plural(ap.schedule.posts_per_day, "Short")} a day, one every ${hours(ap.schedule.every_hours)} from ${ap.schedule.first_post} (${scheduleTz()}), all made in the morning run from ${ap.schedule.make_at}.`,
      body: table([["Time", { class: "col-time" }], ["New York", { class: "col-time" }], "Short",
                   partHead("ic-youtube", "YouTube"), partHead("ic-instagram", "Instagram")],
                  data.slots.map(scheduleRow), "schedule") }),
    data.later.length > 0 && section({ num: "6.2", title: "Later days", text: "Uploaded for a later day, private on YouTube until their time.",
      body: table([["Goes public", { class: "col-time" }], "Short", partHead("ic-youtube", "YouTube"), partHead("ic-instagram", "Instagram")],
        data.later.map(v => h("tr", {},
          h("td", { class: "col-time" }, onClock(v.publish_at), h("small", { class: "muted", style: "display:block" }, fromNow(v.publish_at))),
          h("td", { class: "title-cell" }, h("a", { href: `#studio/${v.id}` }, h("b", {}, v.title)), v.category && h("small", {}, category(v.category))),
          partCell(v, "youtube"), partCell(v, "instagram"))), "schedule") })].filter(Boolean));
  syncButtons();
}

// ------------------------------------------------------------------ 07 results (Agent 7)

const LIFT_KINDS = [["category", "Case type"], ["why_now", "Why now"], ["hook", "Kind of hook"], ["visuals", "Visuals used"],
                    ["length", "Length"], ["lines", "Number of lines"], ["pace", "The Professor's pace"], ["music", "Music mood"],
                    ["hashtag", "Hashtags"], ["review", "Review"], ["follow_up", "Follow-up or first case"], ["hour", "Posting time"]];

function liftCard(title, weights, names = {}) {
  const entries = Object.entries(weights || {}).sort((a, b) => b[1] - a[1]);
  return h("div", { class: "card card-pad lift" }, h("p", { class: "sub-head" }, title),
    entries.length ? h("ul", {}, entries.map(([name, x]) => {
      const pct = Math.min(Math.abs(x - 1), 1) * 50;
      return h("li", {}, h("span", { class: "lift-name", title: name }, names[name] || cap(name)),
        h("span", { class: "lift-bar" }, h("span", { class: x >= 1 ? "up" : "down", style: `width:${pct}%` })),
        h("span", { class: "lift-num" }, `${x.toFixed(2)}x`));
    })) : h("p", { class: "note" }, "Not enough cases in any group yet."));
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
    pageHead({ eyebrow: "07 · Agent 7 · Analyst", agent: "analyst", title: "Results",
      lede: "Agent 7 reads YouTube's numbers and the newest comments every day and, once a week, writes the playbook: "
            + "what does better than the channel's usual, by case type, hook, visuals, length, pace and posting time, and "
            + "a few lessons for each agent. Every agent reads its lessons each time it works; the playbook's weights are "
            + "followed three times out of four, so the channel keeps trying new things.",
      actions: [taskButton("stats", "Read the numbers now", { primary: true })] }),
    kpis([
      { label: "Cases published", value: rows.length },
      { label: "Views", value: views.reduce((a, b) => a + b, 0).toLocaleString() },
      { label: "Median views", value: median.toLocaleString(), note: "the playbook's yardstick" },
      { label: "Average watched", value: pcts.length ? Math.round(pcts.reduce((a, b) => a + b, 0) / pcts.length) : "–",
        unit: pcts.length ? "%" : "", note: "YouTube Analytics, ~2 days late" },
      { label: "Comments saved", value: r.comments, note: "for the Editor's topic ideas" },
    ]),
    section({ num: "7.1", title: "The playbook", text: book.updated_at ? `Written ${fromNow(book.updated_at)} from ${plural(book.samples, "case")}.` : "",
      body: book.samples
        ? h("div", { class: "card card-pad" }, book.summary && h("p", {}, book.summary),
            book.lessons?.length > 0 && h("ol", { class: "lessons", style: "margin-top:10px" }, book.lessons.map(l => h("li", {}, l))))
        : empty("No playbook yet", `Agent 7 writes one once ${r.min_samples} cases are at least 2 days old (${r.judged} so far).`) }),
    section({ num: "7.2", title: "What each agent has learned", text: "From the Analyst's numbers and the Reviewer's checks; each agent reads its own every time it works.",
      body: h("div", { class: "taught" }, state.app.agents.filter(a => a.key !== "analyst").map(a => {
        const t = r.taught?.[a.key] || { settings: {}, advice: [] };
        return h("div", { class: "card card-pad", dataset: { agent: a.key } },
          h("span", { class: "agent-badge", dataset: { agent: a.key } }, h("i"), `${a.number} ${a.name}`),
          Object.keys(t.settings || {}).length > 0 && h("div", {}, Object.entries(t.settings).map(([k, x]) => h("span", { class: "setting-chip" }, `${k}: ${x}`))),
          t.advice?.length ? h("ul", {}, t.advice.map(l => h("li", {}, l))) : h("p", { class: "note" }, "Nothing yet."));
      })) }),
    section({ num: "7.3", title: "What does better than usual", text: `Median views of each group against the channel's median; a group needs ${r.min_samples} cases.`,
      body: h("div", { class: "lift-grid" }, LIFT_KINDS.map(([key, title]) =>
        liftCard(title, book.weights?.[key], key === "category" ? CATEGORY : key === "why_now" ? WHY_NOW : {}))) }),
    section({ num: "7.4", title: "Follow-up candidates", text: "Cases with 1.5 times the usual views and no part 2 yet. Agent 1 may make one.",
      body: r.follow_ups.length
        ? table(["Case", ["Views vs usual", { class: "col-right" }]], r.follow_ups.map(f => h("tr", {},
            h("td", { class: "title-cell" }, h("a", { href: `#studio/${f.id}` }, h("b", {}, f.title))),
            h("td", { class: "col-right" }, `${f.views_vs_usual}x`))))
        : empty("None yet", "They appear once some cases clearly beat the channel's usual.") }),
    section({ num: "7.5", title: "Cases and their numbers", text: "Newest first.",
      body: rows.length
        ? table(["Case", ["Published", { class: "col-time" }], ["Views", { class: "col-right" }], ["Likes", { class: "col-right" }],
                 ["Comments", { class: "col-right" }], ["Watched", { class: "col-right" }]],
            [...rows].reverse().map(x => h("tr", {},
              h("td", { class: "title-cell" }, h("a", { href: `#studio/${x.id}` }, h("b", {}, x.title)),
                h("small", {}, category(x.traits.category?.[0]))),
              h("td", { class: "col-time small" }, fmtWhen(x.publish_at)),
              h("td", { class: "col-right" }, x.views.toLocaleString()),
              h("td", { class: "col-right" }, x.likes.toLocaleString()),
              h("td", { class: "col-right" }, x.comments.toLocaleString()),
              h("td", { class: "col-right" }, x.avg_view_pct !== null && x.avg_view_pct !== undefined ? `${Math.round(x.avg_view_pct)}%` : "–"))))
        : empty("No numbers yet", "They appear once cases are public and Agent 7 has read YouTube's numbers.") }));
  syncButtons();
}

// ------------------------------------------------------------------ L1 music

async function loadMusic() {
  const tracks = await api("/api/music");
  const input = h("input", { type: "file", accept: ".mp3,.m4a,.aac,.wav,.ogg,audio/*", multiple: true, hidden: true,
                             onchange: e => addTracks([...e.target.files]) });
  const zone = h("label", { class: "dropzone" }, input,
    h("b", {}, "Drop music files here, or click to choose"),
    h("small", {}, "Agent 4 picks one in the script's mood (tracks.yaml), or any at random. Use only music you may post "
                   + "on YouTube; a track that needs a credit gets its line added at upload."));
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", e => { e.preventDefault(); zone.classList.remove("over"); addTracks([...e.dataTransfer.files]); });
  const mb = tracks.reduce((sum, t) => sum + t.size, 0) / 1e6;

  $("#view-music").replaceChildren(
    pageHead({ eyebrow: "L1 · Library", title: "Music",
      lede: "The music under the Professor. It dips while he speaks and comes back in the pauses." }),
    kpis([
      { label: "Tracks", value: tracks.length, tone: tracks.length ? null : "warn", note: tracks.length ? "one per Short" : "Shorts have no music" },
      { label: "With a credit line", value: tracks.filter(t => t.credit).length, note: "added to the description at upload" },
      { label: "Library size", value: mb.toFixed(1), unit: "MB" },
    ]),
    section({ num: "L1.1", title: "Add tracks", body: zone }),
    section({ num: "L1.2", title: "Tracks", text: "Press play to listen.",
      body: tracks.length
        ? table(["Track", "Listen", ["", { class: "col-actions" }]], tracks.map(t => h("tr", {},
            h("td", { class: "title-cell" }, h("b", { title: t.name }, t.name),
              h("small", {}, `${(t.size / 1e6).toFixed(1)} MB${t.credit ? " · credit added at upload" : ""}`)),
            h("td", {}, h("audio", { src: t.url, controls: true, preload: "none" })),
            h("td", { class: "col-actions" }, h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button",
                                                            onclick: () => removeTrack(t) }, "Remove")))))
        : empty("No tracks yet", "Add a few tracks above. Until then, Shorts are made without music.") }));
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

// ------------------------------------------------------------------ L2 host

const DEEPER = [[0, "As Gemini reads it"], [1, "1 semitone deeper"], [2, "2 semitones deeper"]];

async function loadHost() {
  const d = await api("/api/host");
  const ro = !state.app.local;
  const v = d.voice;
  const field = (label, control, note) => h("label", { class: "field" }, h("span", {}, label), control, note && h("small", { class: "muted" }, note));
  const name = h("input", { class: "input", value: d.name, maxlength: 40, disabled: ro, "aria-label": "His name" });
  const size = h("select", { class: "input", disabled: ro, "aria-label": "His size" },
    Object.entries(d.sizes).map(([key, px]) => h("option", { value: key, selected: key === d.size },
      `${{ S: "Small", M: "Medium", L: "Large" }[key] || key} · ${px} px wide`)));
  const deeper = h("select", { class: "input", disabled: ro, "aria-label": "How much deeper" },
    DEEPER.map(([n, text]) => h("option", { value: n, selected: n === v.deeper }, text)));
  const style = h("textarea", { class: "input", rows: 3, disabled: ro, maxlength: LIMITS.style, "aria-label": "His persona" });
  style.value = v.style;
  const save = async changes => {
    try {
      await api("/api/host", { method: "PATCH", json: changes });
      toast("Saved. New previews use it.", "ok");
      await loadState();
      loadHost();
    } catch (e) {
      toast(e.message, "error", 7000);
    }
  };

  const voiceRows = d.voices.map(x => h("tr", { class: x.name === v.name ? "current" : "" },
    h("td", { class: "title-cell" }, h("b", {}, x.name), h("small", {}, x.label)),
    h("td", { class: "col-right" }, x.pitch ? `${Math.round(x.pitch)} Hz` : "–"),
    h("td", {}, x.sample ? h("audio", { src: x.sample, controls: true, preload: "none" })
      : h("button", { class: "btn btn-sm", type: "button", "data-needs-idle": true, disabled: ro,
                      onclick: () => runTask("host-sample", null, { voice: x.name }) }, "Record a sample")),
    h("td", { class: "col-actions" }, x.name === v.name ? pill("His voice", "ok")
      : h("button", { class: "btn btn-sm btn-ghost", type: "button", disabled: ro, onclick: () => save({ voice: x.name }) }, "Use"))));

  $("#view-host").replaceChildren(...[
    pageHead({ eyebrow: "L2 · Library", title: "Host",
      lede: `${d.name} hosts every case. He's drawn from your own character sheet, cut out and given a mouth and eyelids `
            + "that move, and floats in the lower-left corner the whole video: talking with the words, blinking, nodding as "
            + "each line starts. His voice is one of Gemini's (free), read in his persona and made a little deeper.",
      actions: [taskButton("host-test", "Make a test clip", { primary: !d.test_clip, title: "He says his line from your sheet in his current voice (one free Gemini call)" })] }),
    d.resting && h("div", { class: "callout banner", dataset: { tone: "warn" } },
      h("b", {}, "His voice is resting. "), (d.used_up
        ? `Today's ${d.daily} free readings are used up; they renew at ${d.resting}. `
        : `Gemini's free voice didn't answer, so it's asked again at ${d.resting}. `)
      + "Until then the Shorts wait for it: no other voice reads him."),
    kpis([
      { label: "Voice", value: v.name, note: (d.voices.find(x => x.name === v.name) || {}).label || "" },
      { label: "Readings left today", value: d.left, unit: `of ${d.daily}`, note: `Gemini's free voice, renewed at ${d.renews}` },
      { label: "Deeper", value: v.deeper, unit: v.deeper === 1 ? "semitone" : "semitones", note: "same timing, lower pitch" },
      { label: "Size", value: d.size, note: `${d.sizes[d.size]} px wide, lower left` },
    ]),
    section({ num: "L2.1", title: "Him", text: "Cut from your sheet's Headshot, so he always looks exactly like it.",
      body: h("div", { class: "host-grid" },
        h("article", { class: "card host-card" },
          h("div", { class: "host-figure" }, h("img", { src: d.images.base, alt: `${d.name}, cut out from the sheet` })),
          h("div", { class: "char-body" },
            h("h3", {}, d.name, h("small", {}, "the host")),
            h("p", { class: "muted small" }, "Highly intelligent, a deep thinker, a great storyteller: calm, observant, wise. "
              + "He never says his name in a video; it's only for this page."),
            field("Name", name),
            field("Size on screen", size),
            h("div", { class: "row", style: "margin-top:10px" },
              h("button", { class: "btn btn-sm btn-primary", type: "button", disabled: ro,
                            onclick: () => save({ name: name.value, size: size.value }) }, "Save")))),
        h("article", { class: "card host-card" },
          d.test_clip ? h("div", { class: "phone" }, h("video", { src: d.test_clip, controls: true, playsinline: true, preload: "metadata" }))
            : h("div", { class: "phone" }, h("div", { class: "phone-blank" }, "No test clip yet. Press “Make a test clip”: he says “Every story has a lesson… if you know how to listen.”")),
          h("div", { class: "char-body" },
            h("h3", {}, "Your sheet"),
            h("a", { href: d.images.sheet, target: "_blank", rel: "noopener" },
              h("img", { class: "sheet-thumb", src: d.images.sheet, alt: "The character sheet he's drawn from" })))))
    }),
    section({ num: "L2.2", title: "His voice", text: "Gemini's deep male voices, measured for pitch (lower is deeper). A sample is recorded once for the current depth and persona (one free call).",
      body: [
        table(["Voice", ["Pitch", { class: "col-right" }], "Sample", ["", { class: "col-actions" }]], voiceRows),
        h("div", { class: "card", style: "margin-top:14px" }, h("div", { class: "card-body" },
          h("div", { class: "inline-fields" }, field("Deeper", deeper, "a gentle pitch drop; his words keep their timing")),
          field("His persona", style, "how Gemini reads every line; each line adds its own direction"),
          h("div", { class: "row", style: "margin-top:10px" },
            h("button", { class: "btn btn-sm btn-primary", type: "button", disabled: ro,
                          onclick: () => save({ deeper: Number(deeper.value), style: style.value }) }, "Save"),
            h("span", { class: "note" }, "Changes apply to the next videos made; finished previews keep their voice."))))
      ] })].filter(Boolean));
  syncButtons();
}

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
      lede: "Where the Shorts go: YouTube, and Instagram as Reels if you like. Each needs your permission once; your "
            + "passwords never touch this software.",
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
      { label: "Reels", value: ig.on ? "On" : "Off", tone: ig.on ? "ok" : null, note: ig.on ? "each Short also goes up as a Reel" : "switch on once connected" },
      ig.connected && { label: "Posted today by API", value: ig.used_today ?? "–", unit: ig.daily_limit ? `/ ${ig.daily_limit}` : "" },
    ]),
    section({ num: "S1.2", title: "Instagram Reels (optional)",
      text: "Each Short also goes up as a Reel at its slot, with the same caption, credits and cover. Instagram's own API, free.",
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
          h("p", {}, ig.on ? "On: every Short goes up as a Reel when its slot comes (this computer must be on then)."
                           : "Off: nothing goes to Instagram."),
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
  const cs = s.cases;
  const row = (label, hint, control, forId) => h("div", { class: "form-row" },
    h("div", {}, h("label", { class: "label", for: forId }, label), hint && h("p", { class: "hint" }, hint)),
    h("div", {}, control));
  const text = (name, value) => h("input", { class: "input", id: `s-${name}`, name, value: value ?? "", disabled: ro });
  const range = (name, value, min, max, step, unit = "") => {
    const out = h("output", {}, `${value}${unit}`);
    return h("div", { class: "range-row" },
      h("input", { type: "range", id: `s-${name}`, name, min, max, step, value, disabled: ro,
                   oninput: e => { out.textContent = `${e.target.value}${unit}`; } }), out);
  };
  const toggle = (name, checked, label) => h("label", { class: "check" },
    h("input", { type: "checkbox", id: `s-${name}`, name, checked, disabled: ro }), h("span", {}, label));
  const preview = h("div", { class: "slot-preview", "aria-live": "polite" });
  const form = h("form", { class: "settings-sections", novalidate: true, onsubmit: saveSettings });
  const showSlots = () => preview.replaceChildren(...slotPreview($("#s-first_post", form).value,
    Number($("#s-every_hours", form).value), Number($("#s-posts_per_day", form).value)));
  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zones = [...new Set([sch.timezone, browserZone, ...TIMEZONES])];
  const select = (name, options, current, onchange) => h("select", { class: "input", id: `s-${name}`, name, disabled: ro, onchange },
    options.map(([value, label]) => h("option", { value, selected: String(value) === String(current) }, label)));
  const card = (id, num, title, ...rows) => h("div", { class: "card", id: `set-${id}` },
    h("div", { class: "card-head" }, h("h3", {}, h("span", { class: "muted", style: "font-family:var(--font-mono);font-weight:500;margin-right:8px" }, num), title)),
    rows);

  form.append(
    card("channel", "S2.1", "Channel",
      row("Channel name", null, text("name", s.channel.name), "s-name"),
      row("Name on the videos", "The end card says “Follow <name> for a new case every day”. Off: just “A new case every day”.",
          toggle("show_name", !!s.channel.show_name, "Show the channel's name on the end card")),
      row("Public contact email", h("span", {}, "Optional. Shown on your public ", h("a", { href: "/about", target: "_blank" }, "About"), " and ",
            h("a", { href: "/privacy", target: "_blank" }, "Privacy"), " pages, which Google asks for."),
          text("contact_email", s.channel.contact_email), "s-contact_email"),
      row("Who it's for", "The agents choose and write cases for these viewers.", text("audience", s.channel.audience), "s-audience"),
      row("Voice and rules", "The tone and limits Agents 1 and 3 follow in every case.",
          h("textarea", { class: "input", id: "s-voice", name: "voice", rows: 5, disabled: ro, value: s.channel.voice }), "s-voice")),
    card("look", "S2.2", "The look",
      row("How the Shorts look", "Changes apply to the cases written after you save; a case already written keeps its look.",
        select("look_style", [["drawn", "Drawn in his art: every scene painted like the Professor"],
                              ["footage", "Real footage: stock video, archive film and photos"]], s.look?.style || "footage"), "s-look_style"),
      row("His art", "Every drawing starts with these words (Cloudflare's FLUX draws from words alone). Keep the names of his colours and lines.",
        h("textarea", { class: "input", id: "s-art", name: "art", rows: 4, disabled: ro, value: s.look?.art || "" }), "s-art"),
      row("When Cloudflare can't draw", "Its free drawing runs out after about 7 drawn Shorts a day (renewed at 05:30 in India), or it can be down. A case already written for drawings is written again for footage, before he reads it.",
        select("look_when_out", [["footage", "Make them with real footage meanwhile: the day's Shorts still all go up"],
                                 ["wait", "Wait for Cloudflare: Shorts wait, and their slots can stay empty"]], s.look?.when_out || "footage"), "s-look_when_out"),
      row("Today's drawing", "Cloudflare's free plan: 10,000 neurons a day (about 58 a drawing, 6 to 9 drawings a Short), renewed at 05:30 in India. It stops at 9,000 and never charges.",
        h("div", { class: "drawing-status" }, s.drawing?.configured
          ? h("p", {}, `${plural(s.drawing.pictures, "drawing")} today · ${s.drawing.neurons.toLocaleString()} of ${s.drawing.budget.toLocaleString()} neurons`,
              s.drawing.resting ? h("span", { class: "warn" }, ` · resting until ${s.drawing.resting}${s.drawing.fallback ? ": Shorts are made with real footage until then" : ""}`) : "")
          : h("p", { class: "warn" }, "Cloudflare isn't connected: add CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN to .env.")))),
    card("posting", "S2.3", "Posting",
      row("Daily schedule", "The morning run makes the whole day's Shorts one after another; each goes public on the minute.",
        h("div", {},
          h("div", { class: "inline-fields" },
            h("div", { class: "field" }, h("label", { for: "s-first_post" }, "First post"),
              h("input", { class: "input", type: "time", id: "s-first_post", name: "first_post", value: sch.first_post, disabled: ro, oninput: showSlots })),
            h("div", { class: "field" }, h("label", { for: "s-every_hours" }, "Then one every"),
              select("every_hours", EVERY_HOURS.map(n => [n, hours(n)]), sch.every_hours, showSlots)),
            h("div", { class: "field" }, h("label", { for: "s-posts_per_day" }, "Shorts a day"),
              h("input", { class: "input", type: "number", id: "s-posts_per_day", name: "posts_per_day", min: 1, max: 12,
                           value: sch.posts_per_day, disabled: ro, oninput: showSlots })),
            h("div", { class: "field" }, h("label", { for: "s-make_at" }, "Morning run"),
              h("input", { class: "input", type: "time", id: "s-make_at", name: "make_at", value: sch.make_at || "07:00", disabled: ro,
                           title: "When the day's run starts: at least 30 minutes before the first post" })),
            h("div", { class: "field" }, h("label", { for: "s-timezone" }, "On the clock of"),
              select("timezone", zones.map(z => [z, z === browserZone ? `${z} (this device)` : z]), sch.timezone, showSlots))),
          preview))),
    card("cases", "S2.4", "Cases",
      row("Case types", "How often Agent 1 picks each type.",
        h("div", { class: "weight-list" }, Object.entries(s.categories_available).map(([key, label]) =>
          h("div", { class: "weight", dataset: { cat: key } },
            h("div", {}, h("b", {}, category(key)), h("small", {}, label)),
            select(`cat-${key}`, HOW_OFTEN, Number(cs.categories?.[key] ?? 0)))))),
      row("Your OK first", "These cases wait in the Studio until you approve them.",
        h("div", { style: "display:grid;gap:8px" },
          toggle("approve_trending", cs.approval?.trending !== false, "Cases about this week's news"),
          toggle("approve_politics", cs.approval?.politics !== false, "Cases that touch politics (any type)"))),
      row("Approval wait", "A case still waiting this long is discarded: news goes stale.",
          select("approval_expires_days", [1, 2, 3, 5, 7].map(n => [n, plural(n, "day")]), cs.approval_expires_days), "s-approval_expires_days"),
      row("Length", "Agent 3 aims for the target and never writes past the longest.",
        h("div", { style: "display:grid;gap:10px" },
          h("div", {}, h("span", { class: "small muted" }, "Target"), range("target_seconds", cs.target_seconds, 40, 75, 1, " s")),
          h("div", {}, h("span", { class: "small muted" }, "Longest"), range("max_seconds", cs.max_seconds, 45, 90, 1, " s")))),
      row("Ideas", null, h("div", { style: "display:grid;gap:8px" },
        toggle("follow_ups", cs.follow_ups !== false, "Part 2s: a case that did well can get a follow-up"),
        toggle("comment_requests", cs.comment_requests !== false, "Viewers' comments can suggest the next case")))),
    card("research", "S2.5", "Research",
      row("Share-alike photos", "CC BY-SA photos arguably make the whole video share-alike too, so they're off unless you allow them.",
          toggle("share_alike_images", !!s.research?.share_alike_images, "Also use CC BY-SA photos"))),
    card("reach", "S2.6", "Trends and hashtags",
      row("Trends from", "Worldwide asks every country and puts the trends shared by the most countries first.",
          select("region", [...new Set(["ALL", s.trends.region, ...REGIONS])].map(r => [r, r === "ALL" ? "All countries (worldwide)" : r]), s.trends.region),
          "s-region"),
      row("Hashtags on every Short", "Up to 4, like #shorts #casestudy. Each case adds its type's own.", text("hashtags", s.metadata.base_hashtags.join(" ")), "s-hashtags")),
    card("music", "S2.7", "Music",
      row("Music volume", "Under the voices; 0 turns music off.", range("volume", s.music.volume, 0, 1.5, 0.05), "s-volume")),
    h("div", { class: "savebar" },
      h("p", { class: "note" }, ro ? "Settings can only be changed on your computer." : "Changes apply to the next case."),
      h("button", { class: "btn btn-primary", type: "submit", disabled: ro }, "Save settings")));

  const nav = [["channel", "S2.1", "Channel"], ["look", "S2.2", "The look"], ["posting", "S2.3", "Posting"],
               ["cases", "S2.4", "Cases"], ["research", "S2.5", "Research"], ["reach", "S2.6", "Trends and hashtags"],
               ["music", "S2.7", "Music"]];
  $("#view-settings").replaceChildren(
    pageHead({ eyebrow: "S2 · Setup", title: "Settings", lede: "How the channel behaves. Saved to config/channel.yaml." }),
    h("div", { class: "settings" },
      h("nav", { class: "settings-nav", "aria-label": "Settings sections" }, nav.map(([id, num, label]) =>
        h("a", { href: "#settings", onclick: e => { e.preventDefault(); $(`#set-${id}`).scrollIntoView({ behavior: "smooth" }); } },
          h("span", {}, num), label))),
      form));
  showSlots();
}

/** The day's posting times for the settings preview; times after midnight are marked. */
function slotPreview(first, every, count) {
  if (!/^\d\d:\d\d$/.test(first || "") || !every || !(count >= 1 && count <= 12)) {
    return [h("p", { class: "hint" }, "Pick a first post time, a gap and 1 to 12 Shorts a day.")];
  }
  if ((count - 1) * every >= 24) return [h("p", { class: "hint warn" }, `${count} Shorts ${hours(every)} apart don't fit in a day.`)];
  const [hh, mm] = first.split(":").map(Number);
  return Array.from({ length: count }, (_, k) => {
    const minutes = hh * 60 + mm + Math.round(k * every * 60);
    const clock = `${String(Math.floor(minutes / 60) % 24).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
    return h("span", { class: "tag" }, clock, minutes >= 1440 && h("small", {}, "next day"));
  });
}

async function saveSettings(event) {
  event.preventDefault();
  const f = new FormData(event.target);
  const list = (value, sep = ",") => String(value || "").split(sep).map(x => x.trim()).filter(Boolean);
  const body = {
    channel: { name: f.get("name"), show_name: f.get("show_name") === "on", contact_email: f.get("contact_email"),
               audience: f.get("audience"), voice: f.get("voice") },
    schedule: { timezone: f.get("timezone"), first_post: f.get("first_post"), every_hours: Number(f.get("every_hours")),
                posts_per_day: Number(f.get("posts_per_day")), make_at: f.get("make_at") },
    cases: {
      categories: Object.fromEntries(Object.keys(CATEGORY).map(k => [k, Number(f.get(`cat-${k}`) || 0)])),
      approval: { trending: f.get("approve_trending") === "on", politics: f.get("approve_politics") === "on" },
      approval_expires_days: Number(f.get("approval_expires_days")), target_seconds: Number(f.get("target_seconds")),
      max_seconds: Number(f.get("max_seconds")),
      follow_ups: f.get("follow_ups") === "on", comment_requests: f.get("comment_requests") === "on",
    },
    research: { share_alike_images: f.get("share_alike_images") === "on" },
    look: { style: f.get("look_style"), art: f.get("art"), when_out: f.get("look_when_out") },
    trends: { region: f.get("region") },
    metadata: { base_hashtags: list(f.get("hashtags"), " ") },
    music: { volume: Number(f.get("volume")) },
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

const loaders = { overview: loadOverview, topics: loadTopics, research: loadResearch, scripts: loadScripts, studio: loadStudio,
                  review: loadReview, schedule: loadSchedule, results: loadResults, music: loadMusic, host: loadHost,
                  youtube: () => loadYouTube(),
                  settings: loadSettings, activity: loadActivity };

/** "#studio/12" -> "studio"; older page names land on their new pages. */
function currentView() {
  const view = location.hash.slice(1).split("/")[0];
  const name = { shorts: "studio", queue: "studio", trends: "topics", cast: "host", hosts: "host", channels: "youtube",
                 instagram: "youtube" }[view] || view;
  return VIEWS.includes(name) ? name : "overview";
}

let lastView = null;
async function route() {
  const view = currentView();
  if (lastView === "scripts" && view !== "scripts" && state.scripts.selected && state.dirty.has(state.scripts.selected)
      && !confirm("Leave without saving your changes to this case?")) {
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
      toast(e.target.checked ? "Autopilot on. The agents get to work: posting on time, and keeping cases ready ahead."
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
