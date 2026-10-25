// Control room for the cartoon channel. Plain JS, no build step; talks to dashboard/api.py.
// Every page has the same shape: a header with its actions, a row of numbers, then numbered sections.
// Pages 01-05 belong to the five agents: Casting, Writer, Animator, Publisher, Analyst.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const SVG_NS = "http://www.w3.org/2000/svg";

const EMOTIONS = ["neutral", "happy", "annoyed", "surprised", "sad", "smug"];
const ACTIONS = { talk: "Talks", gesture: "Points", shrug: "Shrugs", facepalm: "Facepalms", cross_arms: "Crosses arms",
                  think: "Thinks", wave: "Waves", cheer: "Cheers", phone: "On the phone", mug: "Holds a mug",
                  walk_in: "Walks in" };
const STATUS = { planned: ["Written", "accent"], making: ["Being made", "run"], scheduled: ["Scheduled", "run"],
                 live: ["Live", "ok"], failed: ["Failed", "bad"], vetoed: ["Vetoed", "bad"],
                 discarded: ["Discarded", "idle"], skipped: ["Skipped", "idle"] };
// What each posting slot says, by its state (see slot_board in tools/jobs.py).
const SLOT = { posted: ["Posted", "ok"], scheduled: ["Ready", "run"], making: ["Making…", "run"],
               late: ["Late · going out", "warn"], due: ["Up next", "accent"], open: ["Open", "idle"],
               missed: ["No post", "idle"], paused: ["Paused", "warn"] };
// Which agents a dashboard task puts to work (for the "Working" badge on their cards).
const TASK_AGENTS = { prepare: ["casting", "writer"], render: ["animator"], publish: ["animator", "publisher"],
                      autopilot: ["casting", "writer", "animator", "publisher"], stats: ["analyst"] };
const AGENT_KEYS = ["casting", "writer", "animator", "publisher", "analyst"];
const TIMEZONES = ["Asia/Kolkata", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                   "Europe/London", "Europe/Berlin", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney", "UTC"];
const EVERY_HOURS = [1, 1.5, 2, 3, 4, 6, 8, 12];
const REGIONS = ["US", "GB", "CA", "AU", "IE", "NZ", "IN", "PH", "SG", "ZA", "DE", "FR", "ES", "BR", "MX", "JP"];
const LIMITS = { hook: 60, line: 90, title: 100 };
// The same pacing the Writer and the renderer use (agents/writer.py, tools/cartoon_render.py).
const PACE = { wordsPerSecond: 2.5, leadIn: 0.35, tail: 1.5, gap: 0.28 };
const VIEWS = ["overview", "cast", "scripts", "studio", "schedule", "results", "music", "youtube", "settings", "activity"];
// The audience is worldwide but US-heavy, so times are also shown for New York next to the schedule's own clock.
const AUDIENCE_TZ = "America/New_York";

const state = { app: null, videos: [], task: null, watching: null, dirty: new Set(),
                studio: { filter: "planned", selected: null, picked: false }, scripts: { selected: null },
                signals: null, signalsPoll: null };

// ------------------------------------------------------------------ helpers

/** Build DOM safely: text always goes in as text, never as HTML. */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
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
    throw new Error(Array.isArray(detail) ? detail.map(d => d.msg).join("; ") : detail || `${res.status} ${res.statusText}`);
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
const secs = s => s ? `${Math.round(s)} s` : "–";

/** A video the dashboard shows as "live" once its publish time has passed. */
const shownStatus = v => v.status === "scheduled" && v.publish_at && new Date(v.publish_at) <= new Date() ? "live" : v.status;

/** How long a script will run, the way the Writer estimates it. */
function estimate(beats, cast) {
  const words = beats.reduce((n, b) => n + b.line.split(/\s+/).filter(Boolean).length / (cast[b.speaker]?.speed || 1), 0);
  return words / PACE.wordsPerSecond + PACE.leadIn + PACE.tail + beats.length * PACE.gap;
}

function pill(text, tone = "idle") {
  return h("span", { class: "pill", dataset: { tone } }, text);
}

function statusPill(v) {
  const [text, tone] = STATUS[shownStatus(v)] || [v.status, "idle"];
  return pill(text, tone);
}

function avatars(cast) {
  return h("span", { class: "avatars" }, cast.map(c => c.image && h("img", { src: c.image, alt: c.name, title: `${c.name}, the ${c.role}` })));
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

function table(head, rows) {
  return h("div", { class: "card table-wrap" },
    h("table", { class: "table" },
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

/** "Make the 14:00 Short now": takes the oldest written episode (or writes one), animates and uploads it. */
function makeButton({ primary = false, sm = false } = {}) {
  const a = state.app;
  const nextOpen = a.autopilot.next_open;
  const blocked = !a.services.youtube || !nextOpen;
  return h("button", { class: `btn${primary ? " btn-primary" : ""}${sm ? " btn-sm" : ""}`, type: "button",
    "data-needs-idle": true, dataset: { blocked: blocked ? "1" : "0" },
    title: !a.services.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
         : "Takes the oldest written episode (or writes one), animates it and uploads it for that slot",
    onclick: () => {
      const when = nextOpen ? `${clockIn(nextOpen, scheduleTz())} (${fromNow(nextOpen)})` : "the next free slot";
      if (confirm(`Make a Short for ${when} now?\n\nAgent 4 takes the oldest written episode (Agents 1 and 2 write one `
                  + "if none are waiting), Agent 3 animates it, and it's uploaded as private. YouTube makes it public "
                  + "at that time.")) runTask("autopilot");
    } }, nextOpen ? `Make the ${clockIn(nextOpen, scheduleTz())} Short now` : "Make the next Short now");
}

const writeButton = (opts = {}) => taskButton("prepare", "Write a new episode",
  { title: "Agent 1 casts it, Agent 2 writes it from today's trends", ...opts });

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
  document.title = `${a.channel} · Control room`;

  const rows = [
    ["Gemini", s.gemini ? "ok" : "bad", s.gemini ? "Ready" : "Add key", null],
    ["YouTube", s.youtube ? "ok" : "warn", s.youtube ? "Connected" : "Not connected", "#youtube"],
    ["Voices", s.voices ? "ok" : "off", s.voices ? "Kokoro ready" : "Downloads on first use", null],
    ["Lip-sync", s.lipsync ? "ok" : "off", s.lipsync ? "Rhubarb ready" : "Downloads on first use", null],
    ["Music", s.music ? "ok" : "warn", s.music ? plural(s.music, "track") : "No tracks", "#music"],
    ["Database", "ok", s.database === "cloud" ? "Cloud" : "This PC", null],
    ["Telegram", s.telegram ? "ok" : "off", s.telegram ? "Alerts on" : "Optional", "#activity"],
  ];
  $("#services").replaceChildren(...rows.map(([name, tone, text, href]) => h("li", {},
    h(href ? "a" : "span", { href },
      h("span", { class: "inline" }, h("span", { class: "dot", dataset: { tone } }), name), h("small", {}, text)))));

  const agent = key => a.agents.find(x => x.key === key);
  $("#count-cast").textContent = agent("casting")?.count || "";
  $("#count-scripts").textContent = agent("writer")?.count || "";
  $("#count-schedule").textContent = agent("publisher")?.count || "";
  $("#count-music").textContent = s.music || "";

  const ap = a.autopilot;
  const on = !a.paused;
  $("#autopost").checked = on;
  $("#autopost").disabled = !a.local;
  $("#autopost-label").textContent = on ? "Autopilot on" : "Autopilot paused";
  $("#autopost-sub").textContent = !on ? "The agents wait for you"
    : ap.here ? `${plural(ap.schedule.posts_per_day, "Short")} a day from ${ap.schedule.first_post}` : "Runs in the cloud";
  $("#pause-switch").title = a.local ? "Off stops all automatic work (your own buttons keep working)"
                                     : "Change PAUSED in Vercel's environment variables";
  syncButtons();
}

function syncButtons() {
  const busy = state.task?.status === "running";
  const local = state.app?.local !== false;  // in the cloud the scheduled jobs do the work
  for (const b of $$("[data-needs-idle]")) b.disabled = busy || !local || b.dataset.blocked === "1";
}

async function runTask(kind, videoId) {
  try {
    watchTask(await api(`/api/tasks/${kind}`, { method: "POST", json: videoId ? { video_id: videoId } : {} }));
  } catch (e) {
    toast(e.message, "error", 7000);
  }
}

function watchTask(task) {
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
    state.watching = null;
    syncButtons();
    finishTask(state.task);
  };
  setTimeout(poll, 700);
}

function taskSummary(t) {
  const r = t.result || {};
  if (typeof r.skipped === "string") return `Nothing to do: ${r.skipped}.`;
  if (t.kind === "prepare") return r.planned?.length ? `New episode written: ${r.planned[0].title}` : "Done.";
  if (t.kind === "render" || r.rendered) return `Video ready (${secs(r.length)}). Press play in the Studio.`;
  if (t.kind === "publish" || t.kind === "autopilot") {
    return r.live_now ? `Posted: ${r.title}. It's live now.` : `Uploaded: ${r.title}. It goes public ${fmtWhen(r.publish_at)}.`;
  }
  if (t.kind === "stats") {
    if (r.skipped) return r.skipped;
    return `Numbers for ${plural(r.updated || 0, "Short")}.` + (r.learn?.lessons ? " The playbook is updated." : "");
  }
  if (t.kind === "connect") return `YouTube connected: ${r.channel}`;
  return "Done.";
}

async function finishTask(t) {
  if (t.status === "error") toast(t.error, "error", 9000);
  else toast(taskSummary(t), "ok", 6000);
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
  if (job === "casting" && d.names) return `${cap(d.setting || "")}: ${d.names.join(", ")}`;
  if (job === "writer" && d.premise) return d.premise;
  if (job === "animator" && d.length) return `Episode #${d.video_id}: a ${secs(d.length)} video, made in ${secs(d.seconds)}`;
  if (d.youtube_id) return `${d.live_now ? "Posted" : "Uploaded"} #${d.video_id} “${d.title}”, ${d.live_now ? "live now" : `goes public ${fmtWhen(d.publish_at)}`}`;
  if (d.planned) return d.planned.map(p => `#${p.id} ${p.title}`).join(", ") || "Nothing written";
  if (d.rendered) return d.video_id ? `Preview of #${d.video_id} rendered${d.length ? ` (${secs(d.length)})` : ""}`
                                    : `Preview rendered: ${d.title || ""}`;
  if (d.updated !== undefined) return `Numbers for ${plural(d.updated, "Short")}${d.vetoed ? `, ${d.vetoed} vetoed` : ""}`
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
  if (key === "casting" || key === "writer") return writeButton({ sm: true });
  if (key === "animator") return h("a", { class: "btn btn-sm", href: "#studio" }, "Open the Studio");
  if (key === "publisher") return makeButton({ sm: true });
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
    const [label, tone] = SLOT[a.paused && waiting ? "paused" : s.state] || [s.state, "idle"];
    const live = s.state === "posted";
    const link = v?.youtube_id && h("a", { class: "platform", dataset: { tone: live ? "ok" : "run" }, target: "_blank", rel: "noopener",
      href: live ? `https://youtube.com/shorts/${v.youtube_id}` : `https://studio.youtube.com/video/${v.youtube_id}/edit`,
      title: live ? "Watch on YouTube" : "Open in YouTube Studio" }, live ? "Watch ↗" : "Studio ↗");
    return h("tr", { class: "slot-row", dataset: { state: s.state, next: s.at === nextAt && !a.paused ? "1" : "0" } },
      h("td", { class: "col-time" }, h("b", {}, clockIn(s.at, scheduleTz()))),
      h("td", { class: "col-time muted" }, nyTime(s.at)),
      h("td", {}, pill(label, tone)),
      h("td", { class: "title-cell" }, v
        ? [h("a", { href: `#studio/${v.id}` }, h("b", {}, v.title || `Short #${v.id}`)), v.setting && h("small", {}, cap(v.setting))]
        : h("span", { class: "slot-title muted" }, s.state === "missed" ? "Nothing went out" : "Not made yet")),
      h("td", { class: "col-actions" }, link));
  });
}

function overviewLede(a) {
  const sch = a.autopilot.schedule;
  const rhythm = `${plural(sch.posts_per_day, "Short")} a day, one every ${hours(sch.every_hours)} from ${sch.first_post} (${sch.timezone})`;
  if (a.paused) return `The autopilot is paused, so the agents wait for you. Switch it on (top right) for ${rhythm}; `
                       + "on this PC they also keep episodes written and animated ahead.";
  if (!a.services.youtube) return "The autopilot is on, but YouTube isn't connected yet, so nothing can be posted.";
  return `The autopilot is on: ${rhythm}.${a.autopilot.here ? "" : " It runs in the cloud."}`;
}

async function loadOverview() {
  const a = state.app;
  const ap = a.autopilot;
  const posted = ap.slots.filter(s => s.state === "posted").length;
  const next = ap.next;
  const written = a.agents.find(x => x.key === "writer")?.count || 0;
  const previews = a.agents.find(x => x.key === "animator")?.count || 0;
  const root = $("#view-overview");
  const today = new Date(ap.slots[0].at).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", timeZone: scheduleTz() });

  root.replaceChildren(
    pageHead({ eyebrow: `00 · ${today}`, title: "Overview", lede: overviewLede(a),
      actions: [writeButton(), makeButton({ primary: true })] }),
    kpis([
      { label: "Posted today", value: posted, unit: `/ ${ap.slots.length}` },
      { label: "Next post", value: next ? clockIn(next.at, scheduleTz()) : "–",
        note: next ? `${fromNow(next.at)} · ${nyTime(next.at)} in New York` : "" },
      { label: "Episodes waiting", value: written, note: `${previews} animated, ready to watch`, tone: written ? null : "warn" },
      { label: "Characters", value: a.agents.find(x => x.key === "casting")?.count || 0, note: "created by Agent 1" },
      { label: "Autopilot", value: a.paused ? "Paused" : "On", tone: a.paused ? "warn" : "ok",
        note: ap.here ? "checks every minute on this PC" : `runs in the cloud${ap.last_check ? `, last ${fromNow(ap.last_check)}` : ""}` },
    ]),
    section({ num: "01–05", title: "The five agents", text: "In order: each one hands its work to the next.", body: pipelineSteps() }),
    h("div", { class: "grid-2-1" },
      section({ num: "A", title: "Today's schedule", text: `On the ${scheduleTz()} clock, with New York time beside it.`,
        actions: h("a", { class: "btn btn-sm", href: "#schedule" }, "Full schedule"),
        body: table([["Time", { class: "col-time" }], ["New York", { class: "col-time" }], "Status", "Short", ["", { class: "col-actions" }]],
                    slotRows(ap.slots)) }),
      section({ num: "B", title: "Coming up", text: "Holidays and world days the Writer can play on.",
        body: h("div", { class: "card card-pad" }, a.events.length
          ? h("ul", { class: "events" }, a.events.slice(0, 8).map(e => h("li", {}, h("span", {}, e.name),
              h("small", {}, e.in_days === 0 ? "today" : `in ${plural(e.in_days, "day")}`))))
          : h("p", { class: "note" }, "Nothing in the next few days.")) })),
    h("div", { id: "overview-activity", style: "margin-top:30px" }));
  syncButtons();
  const act = await api("/api/activity");
  const box = $("#overview-activity");
  if (box) box.replaceChildren(section({ num: "C", title: "Latest work", text: "What the agents did most recently.",
    actions: h("a", { class: "btn btn-sm", href: "#activity" }, "All activity"),
    body: runsTable(act.runs.slice(0, 6)) }));
}

// ------------------------------------------------------------------ 01 cast (Agent 1)

async function loadCast() {
  const chars = await api("/api/characters");
  const queued = chars.filter(c => c.episodes.some(e => e.status === "planned"));
  const voices = new Set(chars.map(c => c.voice));
  $("#view-cast").replaceChildren(
    pageHead({ eyebrow: "01 · Agent 1 · Casting", agent: "casting", title: "Cast",
      lede: "For every episode Agent 1 picks a setting and designs two or three adult characters whose personalities "
            + "clash: their look, their voice and their role in the sketch. Every character is kept here.",
      actions: [writeButton({ primary: true })] }),
    kpis([
      { label: "Characters", value: chars.length },
      { label: "In waiting episodes", value: queued.length },
      { label: "Voices used", value: voices.size, unit: "/ 20" },
      { label: "Newest", value: chars[0] ? chars[0].name : "–", note: chars[0] ? `created ${fromNow(chars[0].created_at)}` : "" },
    ]),
    section({ num: "1.1", title: "Characters", text: "Newest first. Press play to hear a character's voice (made on this PC the first time).",
      body: chars.length
        ? h("div", { class: "cast-grid" }, chars.map(c => h("article", { class: "card char-card" },
            h("img", { class: "portrait", src: c.image, alt: `${c.name}, drawn`, loading: "lazy" }),
            h("div", { class: "char-body" },
              h("h3", {}, c.name, h("small", {}, c.age)),
              h("span", { class: "role" }, cap(c.role)),
              c.personality && h("p", {}, c.personality),
              h("p", { class: "look" }, c.look.split(": ").slice(1).join(": ")),
              h("p", { class: "look" }, `Voice: ${c.voice_label}`),
              h("div", { class: "char-foot" }, h("audio", { src: c.voice_sample, controls: true, preload: "none" })),
              c.episodes.length > 0 && h("div", { class: "chips" }, c.episodes.map(e =>
                h("a", { class: "tag", href: e.status === "planned" ? `#scripts/${e.id}` : `#studio/${e.id}` }, `#${e.id}`)))))))
        : empty("No characters yet", "Press “Write a new episode”: Agent 1 casts it, Agent 2 writes the sketch.") }));
  syncButtons();
}

// ------------------------------------------------------------------ 02 scripts (Agent 2)

async function loadScripts() {
  state.videos = await api("/api/videos");
  const sub = Number(location.hash.split("/")[1]);
  if (sub) {
    state.scripts.selected = sub;
    history.replaceState(null, "", "#scripts");
  }
  renderScripts();
  loadSignals();
}

function renderScripts() {
  const root = $("#view-scripts");
  const list = state.videos.filter(v => v.status === "planned" && !v.legacy);
  if (!list.some(v => v.id === state.scripts.selected)) state.scripts.selected = list[0]?.id ?? null;
  const selected = list.find(v => v.id === state.scripts.selected);
  const avg = list.length ? list.reduce((n, v) => n + (v.estimate || 0), 0) / list.length : 0;

  root.replaceChildren(
    pageHead({ eyebrow: "02 · Agent 2 · Writer", agent: "writer", title: "Scripts",
      lede: "Agent 2 writes each sketch for its cast: a hook for the top of the screen and 3 to 6 lines that end on a "
            + "punchline, using today's trends when one fits. Edit any line before it's animated.",
      actions: [writeButton({ primary: true })] }),
    kpis([
      { label: "Waiting", value: list.length, note: "written, not posted yet", tone: list.length ? null : "warn" },
      { label: "Animated", value: list.filter(v => v.preview).length, note: "ready to watch in the Studio" },
      { label: "Average length", value: avg ? Math.round(avg) : "–", unit: avg ? "s" : "", note: "estimated from the words" },
      { label: "Using a trend", value: list.filter(v => v.trend).length, note: "the rest are evergreen" },
    ]),
    section({ num: "2.1", title: "Episodes waiting", text: "The autopilot posts these oldest first.",
      body: !list.length
        ? empty("Nothing written yet", "Press “Write a new episode”. On this PC the agents also keep a few written ahead while the autopilot is on.")
        : h("div", { class: "studio" },
            h("div", { class: "card studio-list" },
              h("div", { class: "card-head" }, h("h3", {}, plural(list.length, "episode")), h("p", {}, "oldest first")),
              h("ul", { class: "vlist" }, [...list].reverse().map(v => h("li", {},
                h("button", { class: "vrow", type: "button", "aria-current": String(v.id === state.scripts.selected),
                              onclick: () => leaveDirty(state.scripts.selected, () => { state.scripts.selected = v.id; renderScripts(); }) },
                  h("span", { class: "vid" }, `#${v.id}`),
                  h("span", { class: "vtitle" }, v.title || v.premise),
                  h("span", { class: "vmeta" }, avatars(v.cast), h("span", { class: "tag" }, cap(v.setting)),
                    h("span", {}, `~${Math.round(v.estimate || 0)} s`), v.preview && pill("Animated", "ok"))))))),
            selected && scriptEditor(selected)) }),
    h("div", { id: "signals" }));
  if (state.signals) renderSignals();
  syncButtons();
}

/** Asks before throwing away unsaved edits. */
function leaveDirty(id, go) {
  if (state.dirty.has(id) && !confirm("Leave without saving your changes to this episode?")) return;
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
  const beats = v.beats.map(b => ({ ...b }));
  const lengthNote = h("span", { class: "muted small" });
  const markDirty = () => {
    state.dirty.add(v.id);
    lengthNote.textContent = `~${Math.round(estimate(beats.filter(b => b.line.trim()), v.cast))} s when spoken`;
  };
  const select = (options, value, onchange, label) => {
    const el = h("select", { class: "input", "aria-label": label, onchange: e => { onchange(e.target.value); markDirty(); } },
      options.map(([val, text]) => h("option", { value: val, selected: String(val) === String(value) }, text)));
    return el;
  };
  const body = h("ol", { class: "beat-list" });
  const labelled = (text, control) => h("label", {}, text, control);
  const drawBeats = () => body.replaceChildren(...beats.map((b, k) => {
    const line = h("input", { class: "input", value: b.line, "aria-label": `Line ${k + 1}`,
                              oninput: e => { b.line = e.target.value; markDirty(); } });
    return h("li", { class: `beat${k + 1 === beats.length ? " punch" : ""}` },
      h("span", { class: "k" }, k + 1 === beats.length ? "★" : k + 1),
      h("div", { class: "beat-main" },
        select(v.cast.map((c, i) => [i, c.name]), b.speaker, x => { b.speaker = Number(x); }, "Who speaks"),
        h("div", {}, line, counted(line, LIMITS.line))),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", title: "Remove this line",
        disabled: beats.length <= 2, onclick: () => { beats.splice(k, 1); markDirty(); drawBeats(); } }, "✕"),
      h("div", { class: "beat-how" },
        labelled("Emotion", select(EMOTIONS.map(e => [e, cap(e)]), b.emotion, x => { b.emotion = x; }, "Their emotion")),
        labelled("Action", select(Object.entries(ACTIONS), b.action, x => { b.action = x; }, "What they do")),
        labelled("Camera", select([["wide", "Wide"], ["close", "Close-up"]], b.camera, x => { b.camera = x; }, "Camera")),
        labelled("Others react", select(EMOTIONS.map(e => [e, cap(e)]), b.listener_emotion, x => { b.listener_emotion = x; },
                                        "The others react"))));
  }));
  drawBeats();

  const hook = h("input", { class: "input", value: v.hook, oninput: markDirty, "aria-label": "Hook" });
  const title = h("input", { class: "input", value: v.title, oninput: markDirty, "aria-label": "YouTube title" });
  const description = h("textarea", { class: "input", rows: 6, oninput: markDirty, "aria-label": "Description" });
  description.value = v.description || "";
  markDirty();
  state.dirty.delete(v.id);  // measuring the length isn't an edit

  const save = async () => {
    try {
      const updated = await api(`/api/videos/${v.id}`, { method: "PATCH", json: {
        hook: hook.value, title: title.value, description: description.value,
        beats: beats.map(b => ({ ...b, speaker: Number(b.speaker) })) } });
      state.dirty.delete(v.id);
      const i = state.videos.findIndex(x => x.id === v.id);
      if (i >= 0) state.videos[i] = updated;
      renderScripts();
      toast("Saved. Agent 3 animates the new version (or press Animate in the Studio).", "ok");
    } catch (e) {
      toast(e.message, "error", 7000);
    }
  };

  root.append(
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, avatars(v.cast), h("span", { class: "tag" }, cap(v.setting)), statusPill(v),
        v.trend ? h("span", { class: "tag" }, `Trend: ${v.trend}`) : h("span", { class: "tag" }, "Evergreen"),
        h("span", { class: "muted small" }, `#${v.id} · written ${fromNow(v.created_at)}`)),
      h("h2", {}, v.premise),
      h("p", { class: "angle" }, v.cast.map(c => `${c.name} (${c.role})`).join(" · "))),
    h("div", { class: "detail-body single" },
      h("div", {},
        h("div", { class: "field" }, h("label", {}, h("span", {}, "Hook · on top of the whole video"), counted(hook, LIMITS.hook)), hook),
        h("p", { class: "sub-head" }, "The sketch · ★ is the punchline"),
        body,
        h("div", { class: "row", style: "margin-top:10px" },
          h("button", { class: "btn btn-sm", type: "button", disabled: beats.length >= 6, onclick: () => {
            const last = beats[beats.length - 1];
            beats.push({ speaker: (Number(last.speaker) + 1) % v.cast.length, line: "", emotion: "neutral", action: "talk",
                         camera: "wide", listener_emotion: "neutral" });
            markDirty();
            drawBeats();
          } }, "Add a line"),
          lengthNote),
        h("p", { class: "sub-head" }, "On YouTube"),
        h("div", { class: "field" }, h("label", {}, h("span", {}, "Title"), counted(title, LIMITS.title)), title),
        h("details", { class: "more" }, h("summary", {}, "Description & hashtags"),
          h("div", { class: "field" }, description),
          h("p", { class: "hint", style: "margin-top:8px" }, "The music's credit line is added at upload, as its licence asks.")))),
    h("div", { class: "detail-actions" },
      h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: save }, "Save changes"),
      h("a", { class: "btn btn-sm", href: `#studio/${v.id}` }, v.preview ? "Watch in the Studio" : "Animate in the Studio"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")));
  return root;
}

// The trends Agent 2 reads: shown below the scripts. Out-of-date trends come back at once while today's
// load in the background (asking every country takes minutes), so the section checks again shortly.
async function loadSignals(refresh = false) {
  clearTimeout(state.signalsPoll);
  if (refresh) { state.signals = { ...(state.signals || {}), fetching: true }; renderSignals(); }
  try {
    state.signals = await api(`/api/trends${refresh ? "?refresh=1" : ""}`);
  } catch (e) {
    if (refresh || !state.signals) toast(e.message, "error");
  }
  if (currentView() !== "scripts") return;
  renderSignals();
  if (state.signals?.refreshing) state.signalsPoll = setTimeout(() => {
    if (currentView() === "scripts") loadSignals();
  }, 15000);
}

function renderSignals() {
  const box = $("#signals");
  const t = state.signals;
  if (!box) return;
  if (!t || !t.google_trends) {
    box.replaceChildren(section({ num: "2.2", title: "What the Writer reads today", body: h("p", { class: "loading" }, "Reading today's trends…") }));
    return;
  }
  const world = t.region === "ALL";
  const note = t.fetching ? "Asking every country for today's trends… this can take a few minutes."
    : t.refreshing ? `Showing the trends from ${t.fetched_at ? fromNow(t.fetched_at) : "before"} while today's load in the background.`
    : t.errors?.length ? `Notes: ${t.errors.join(" · ")}` : `Fetched ${t.fetched_at ? fromNow(t.fetched_at) : "–"}; reused for up to 6 hours.`;
  box.replaceChildren(section({ num: "2.2", title: "What the Writer reads today", text: note,
    actions: h("button", { class: "btn btn-sm", type: "button", disabled: !!t.fetching, onclick: () => loadSignals(true) },
      t.fetching ? "Fetching…" : "Refresh trends"),
    body: h("div", { class: "grid-2" },
      h("div", { class: "card card-pad" },
        h("p", { class: "sub-head" }, world ? `Trending searches · ${t.countries ?? "every"} countries` : `Trending searches · ${t.region}`),
        t.google_trends.length
          ? h("ol", { class: "ranked" }, t.google_trends.slice(0, 12).map(g => h("li", {}, h("span", {}, g.term),
              h("small", { title: (g.countries || []).join(", ") }, world ? `${(g.countries || []).length} ctry` : g.traffic || ""))))
          : h("p", { class: "note" }, "Nothing yet.")),
      h("div", { class: "card card-pad" },
        h("p", { class: "sub-head" }, "Popular comedy on YouTube"),
        t.youtube_popular.length
          ? h("ol", { class: "ranked" }, t.youtube_popular.slice(0, 12).map(p => h("li", {}, h("span", {}, p.title),
              h("small", {}, p.countries?.length > 1 ? `${p.countries.length} ctry` : p.views ? `${(p.views / 1e6).toFixed(1)}M` : ""))))
          : h("p", { class: "note" }, state.app.services.youtube ? "Nothing came back this time."
                                      : ["Connect YouTube to see these. ", h("a", { href: "#youtube" }, "How →")]),
        t.events?.length > 0 && [h("p", { class: "sub-head" }, "Coming up"),
          h("ul", { class: "events" }, t.events.slice(0, 5).map(e => h("li", {}, h("span", {}, e.name),
            h("small", {}, e.in_days === 0 ? "today" : `in ${plural(e.in_days, "day")}`))))])) }));
}

// ------------------------------------------------------------------ 03 studio (Agent 3)

const STUDIO_FILTERS = [
  ["planned", "Waiting", v => v.status === "planned"],
  ["coming", "Coming up", v => v.status === "making" || shownStatus(v) === "scheduled"],
  ["published", "Published", v => shownStatus(v) === "live"],
  ["stopped", "Stopped", v => ["failed", "vetoed", "discarded", "skipped"].includes(v.status)],
];
const STUDIO_TEXT = {
  planned: "Written episodes. Animate one to watch it before its turn; the autopilot posts them oldest first.",
  coming: "Uploaded as private. Each goes public at its slot; delete it in YouTube Studio before then to veto it.",
  published: "Public on YouTube.",
  stopped: "Episodes that failed, were vetoed or were discarded.",
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
    pageHead({ eyebrow: "03 · Agent 3 · Animator", agent: "animator", title: "Studio",
      lede: "Agent 3 gives every line its character's voice (Kokoro, on this PC), moves the mouths with the words "
            + "(Rhubarb), adds music in the script's mood and animates the sketch. Free and private: nothing leaves this PC.",
      actions: [makeButton()] }),
    kpis([
      { label: "Animated", value: waiting.filter(v => v.preview).length, unit: `/ ${waiting.length}`, note: "waiting episodes ready to watch" },
      { label: "Coming up", value: counts.coming, note: "uploaded, not public yet" },
      { label: "Published", value: counts.published, note: "in the last 60 Shorts" },
      { label: "Stopped", value: counts.stopped, note: "failed, vetoed or discarded" },
    ]),
    section({ num: "3.1", title: "Episodes", text: STUDIO_TEXT[filter], actions: tabs,
      body: !state.videos.length
        ? empty("No episodes yet", "Press “Write a new episode” on the Scripts page, then animate it here.")
        : !list.length ? empty(`Nothing ${STUDIO_FILTERS.find(([k]) => k === filter)[1].toLowerCase()}`, STUDIO_TEXT[filter])
        : h("div", { class: "studio" },
            h("div", { class: "card studio-list" },
              h("div", { class: "card-head" }, h("h3", {}, plural(list.length, "episode")), h("p", {}, "newest first")),
              h("ul", { class: "vlist" }, list.map(v => h("li", {},
                h("button", { class: "vrow", type: "button", "aria-current": String(v.id === state.studio.selected),
                              onclick: () => { state.studio.selected = v.id; renderStudio(); } },
                  h("span", { class: "vid" }, `#${v.id}`),
                  h("span", { class: "vtitle" }, v.title || v.premise || "A new episode"),
                  h("span", { class: "vmeta" }, avatars(v.cast), statusPill(v), v.legacy && h("span", { class: "tag" }, "Cute-animal version"),
                    v.slot && v.status !== "planned" && h("span", {}, clockIn(v.slot, scheduleTz())),
                    v.status === "planned" && !v.legacy && (v.preview ? pill("Animated", "ok") : h("span", {}, "not animated"))) ))))),
            selected && studioDetail(selected)) }));
  syncButtons();
}

function scheduledBox(v) {
  const live = v.publish_at && new Date(v.publish_at) <= new Date();
  return h("div", { class: "callout", dataset: { tone: "ok" } },
    live ? "Public since " : "Goes public ", h("b", {}, fmtWhen(v.publish_at)), live ? "" : ` (${fromNow(v.publish_at)})`, ". ",
    h("a", { href: v.studio_url, target: "_blank", rel: "noopener" }, "Open in YouTube Studio ↗"),
    live && v.youtube_id ? [" · ", h("a", { href: `https://youtube.com/shorts/${v.youtube_id}`, target: "_blank", rel: "noopener" }, "Watch ↗")] : null);
}

function scriptView(v) {
  return h("ol", { class: "script" }, v.beats.map((b, k) => {
    const who = v.cast[b.speaker] || {};
    return h("li", { class: k === v.beats.length - 1 ? "punch" : "" },
      who.image ? h("img", { src: who.image, alt: "" }) : h("span"),
      h("div", {},
        h("span", { class: "who" }, who.name || "?"),
        h("p", { class: "line" }, b.line),
        h("div", { class: "how" }, h("span", { class: "tag" }, cap(b.emotion)), h("span", { class: "tag" }, ACTIONS[b.action] || b.action),
          h("span", { class: "tag" }, b.camera === "close" ? "Close-up" : "Wide"),
          h("span", { class: "tag" }, h("small", {}, "others:"), cap(b.listener_emotion)))));
  }));
}

function studioDetail(v) {
  if (v.legacy) return legacyDetail(v);
  const editable = v.status === "planned";
  const s = state.app.services;
  const nextOpen = state.app.autopilot.next_open;
  const blocked = !s.youtube || !nextOpen;
  const phone = h("div", { class: "phone" },
    v.preview ? h("video", { src: v.preview, controls: true, playsinline: true, preload: "metadata", poster: v.cover || undefined })
      : v.cover ? [h("img", { src: v.cover, alt: "" }), h("span", { class: "phone-badge" }, "Uploaded; preview cleared")]
      : h("div", { class: "phone-blank" }, editable ? "Not animated yet. Press “Animate” below: about a minute." : "No video here."));
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, avatars(v.cast), h("span", { class: "tag" }, cap(v.setting)), statusPill(v),
        h("span", { class: "muted small" }, `#${v.id} · ${v.duration ? secs(v.duration) : `~${secs(v.estimate)}`}`
          + (v.music ? ` · ♪ ${v.music.replace(/\.[^.]+$/, "")}` : ""))),
      h("h2", {}, v.title || v.premise),
      v.hook && h("p", { class: "angle" }, `Hook: “${v.hook}”`)),
    h("div", { class: "detail-body" },
      phone,
      h("div", {},
        v.status === "making" && v.slot && h("div", { class: "callout", dataset: { tone: "warn" } }, "Being made for the ",
          h("b", {}, clockIn(v.slot, scheduleTz())), " slot right now."),
        v.status === "scheduled" && scheduledBox(v),
        v.error && h("div", { class: "callout", dataset: { tone: "bad" } }, v.error),
        h("p", { class: "sub-head" }, "The sketch"),
        scriptView(v),
        h("details", { class: "more" }, h("summary", {}, "Description, credits & hashtags"),
          h("p", { class: "desc-ro" }, v.description || ""),
          v.music_credit && h("p", { class: "desc-ro muted", style: "margin-top:8px" }, `Added at upload:\n${v.music_credit}`)))),
    editable && h("div", { class: "detail-actions" },
      h("button", { class: "btn btn-sm", type: "button", "data-needs-idle": true, onclick: () => runTask("render", v.id) },
        v.preview ? "Animate again" : "Animate"),
      h("a", { class: "btn btn-sm", href: `#scripts/${v.id}` }, "Edit the script"),
      h("button", { class: "btn btn-sm btn-primary", type: "button", "data-needs-idle": true, dataset: { blocked: blocked ? "1" : "0" },
        title: !s.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
             : `Uploads as private, scheduled for the next free slot (${clockIn(nextOpen, scheduleTz())})`,
        onclick: () => upload(v) }, "Upload & schedule"),
      h("span", { class: "spacer" }),
      !s.youtube && h("a", { class: "note", href: "#youtube" }, "Connect YouTube to upload"),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")));
}

/** A Short made by the cute-animal version: it can still go up as it is, but the agents don't make this kind. */
function legacyDetail(v) {
  const s = state.app.services;
  const canUpload = v.status === "planned" && v.preview && s.youtube && state.app.autopilot.next_open;
  return h("article", { class: "card" },
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, statusPill(v), h("span", { class: "tag" }, "Cute-animal version"), h("span", { class: "muted small" }, `#${v.id}`)),
      h("h2", {}, v.title || v.premise || "A Short")),
    h("div", { class: "detail-body" },
      h("div", { class: "phone" }, v.preview
        ? h("video", { src: v.preview, controls: true, playsinline: true, preload: "metadata" })
        : h("div", { class: "phone-blank" }, "No video kept for this one.")),
      h("div", {},
        v.status === "scheduled" && scheduledBox(v),
        v.status === "planned" && h("div", { class: "callout", dataset: { tone: "warn" } },
          "Made by the cute-animal version, before the cartoons. It can still go up exactly as it is"
          + (v.preview ? "" : " (but its video wasn't kept)") + ", or be discarded; the agents don't make this kind any more."),
        h("details", { class: "more" }, h("summary", {}, "Description"), h("p", { class: "desc-ro" }, v.description || "")))),
    v.status === "planned" && h("div", { class: "detail-actions" },
      h("button", { class: "btn btn-sm btn-primary", type: "button", "data-needs-idle": true, dataset: { blocked: canUpload ? "0" : "1" },
        onclick: () => upload(v) }, "Upload & schedule"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard")));
}

function upload(v) {
  const slot = state.app.autopilot.next_open;
  const when = slot ? `${fmtWhen(slot)} (${fromNow(slot)})` : "at the next free slot";
  if (!confirm(`Upload “${v.title}” to YouTube?\n\nIt goes up as private and becomes public ${when}. `
             + "Until then you can still delete it in YouTube Studio.")) return;
  runTask("publish", v.id);
}

async function discard(v) {
  if (!confirm(`Discard “${v.title || v.premise}”? It won't be posted.`)) return;
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

// ------------------------------------------------------------------ 04 schedule (Agent 4)

async function loadSchedule() {
  const a = state.app;
  const ap = a.autopilot;
  state.videos = await api("/api/videos");
  const now = new Date();
  const ahead = state.videos.filter(v => v.status === "scheduled" && v.publish_at && new Date(v.publish_at) > now)
    .sort((x, y) => new Date(x.publish_at) - new Date(y.publish_at));
  const posted = ap.slots.filter(s => s.state === "posted").length;
  $("#view-schedule").replaceChildren(
    pageHead({ eyebrow: "04 · Agent 4 · Publisher", agent: "publisher", title: "Schedule",
      lede: "Agent 4 uploads each Short as private with its slot as the publish time, so YouTube makes it public on the "
            + "minute, and adds the music's credit line. Until then you can delete it in YouTube Studio: that's your veto.",
      actions: [h("a", { class: "btn", href: "#settings" }, "Change the timetable"), makeButton({ primary: true })] }),
    kpis([
      { label: "Posted today", value: posted, unit: `/ ${ap.slots.length}` },
      { label: "Next post", value: ap.next ? clockIn(ap.next.at, scheduleTz()) : "–", note: ap.next ? fromNow(ap.next.at) : "" },
      { label: "Scheduled ahead", value: ahead.length, note: "uploaded, waiting to go public" },
      { label: "Next free slot", value: ap.next_open ? clockIn(ap.next_open, scheduleTz()) : "–",
        note: ap.next_open ? fromNow(ap.next_open) : "every slot this week is taken" },
    ]),
    section({ num: "4.1", title: "Today's slots", text: `${plural(ap.schedule.posts_per_day, "Short")} a day, one every ${hours(ap.schedule.every_hours)} from ${ap.schedule.first_post} (${scheduleTz()}).`,
      body: table([["Time", { class: "col-time" }], ["New York", { class: "col-time" }], "Status", "Short", ["", { class: "col-actions" }]],
                  slotRows(ap.slots)) }),
    section({ num: "4.2", title: "Uploaded, going public soon", text: "Private on YouTube until their time.",
      body: ahead.length
        ? table([["Goes public", { class: "col-time" }], "Short", ["", { class: "col-actions" }]], ahead.map(v => h("tr", {},
            h("td", { class: "col-time" }, fmtWhen(v.publish_at), h("small", { class: "muted", style: "display:block" }, fromNow(v.publish_at))),
            h("td", { class: "title-cell" }, h("a", { href: `#studio/${v.id}` }, h("b", {}, v.title)), h("small", {}, cap(v.setting))),
            h("td", { class: "col-actions" }, v.studio_url && h("a", { class: "platform", dataset: { tone: "run" }, href: v.studio_url,
              target: "_blank", rel: "noopener" }, "Studio ↗")))))
        : empty("Nothing scheduled ahead", a.paused ? "The autopilot is paused. Switch it on, or press “Make the next Short now”."
                                                  : "The next Short is made in the hours before its slot.") }));
  syncButtons();
}

// ------------------------------------------------------------------ 05 results (Agent 5)

const LIFT_KINDS = [["setting", "Setting"], ["role", "Character role"], ["voice", "Voice"], ["outfit", "Outfit"],
                    ["length", "Length"], ["beats", "Number of lines"], ["trend", "Trend or evergreen"], ["hour", "Posting time"]];

function liftCard(title, weights) {
  const entries = Object.entries(weights || {}).sort((a, b) => b[1] - a[1]);
  return h("div", { class: "card card-pad lift" }, h("p", { class: "sub-head" }, title),
    entries.length ? h("ul", {}, entries.map(([name, x]) => {
      const pct = Math.min(Math.abs(x - 1), 1) * 50;
      return h("li", {}, h("span", { class: "lift-name", title: name }, cap(name)),
        h("span", { class: "lift-bar" }, h("span", { class: x >= 1 ? "up" : "down", style: `width:${pct}%` })),
        h("span", { class: "lift-num" }, `${x.toFixed(2)}x`));
    })) : h("p", { class: "note" }, "Not enough Shorts in any group yet."));
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
    pageHead({ eyebrow: "05 · Agent 5 · Analyst", agent: "analyst", title: "Results",
      lede: "Agent 5 reads YouTube's numbers every day and, once a week, writes the playbook: what does better than "
            + "the channel's usual, by setting, kind of character, voice, length and posting time. Agents 1 and 2 follow it "
            + "three times out of four, so the channel keeps trying new things.",
      actions: [taskButton("stats", "Read the numbers now", { primary: true })] }),
    kpis([
      { label: "Shorts published", value: rows.length },
      { label: "Views", value: views.reduce((a, b) => a + b, 0).toLocaleString() },
      { label: "Median views", value: median.toLocaleString(), note: "the playbook's yardstick" },
      { label: "Average watched", value: pcts.length ? Math.round(pcts.reduce((a, b) => a + b, 0) / pcts.length) : "–",
        unit: pcts.length ? "%" : "", note: "YouTube Analytics, ~2 days late" },
    ]),
    section({ num: "5.1", title: "The playbook", text: book.updated_at ? `Written ${fromNow(book.updated_at)} from ${plural(book.samples, "Short")}.` : "",
      body: book.samples
        ? h("div", { class: "card card-pad" }, book.summary && h("p", {}, book.summary),
            book.lessons?.length > 0 && h("ol", { class: "lessons", style: "margin-top:10px" }, book.lessons.map(l => h("li", {}, l))))
        : empty("No playbook yet", `Agent 5 writes one once ${r.min_samples} Shorts are at least 2 days old (${r.judged} so far).`) }),
    section({ num: "5.2", title: "What does better than usual", text: `Median views of each group against the channel's median; a group needs ${r.min_samples} Shorts.`,
      body: h("div", { class: "lift-grid" }, LIFT_KINDS.map(([key, title]) => liftCard(title, book.weights?.[key]))) }),
    section({ num: "5.3", title: "Shorts and their numbers", text: "Newest first.",
      body: rows.length
        ? table(["Short", ["Published", { class: "col-time" }], ["Views", { class: "col-right" }], ["Likes", { class: "col-right" }],
                 ["Comments", { class: "col-right" }], ["Watched", { class: "col-right" }]],
            [...rows].reverse().map(x => h("tr", {},
              h("td", { class: "title-cell" }, h("a", { href: `#studio/${x.id}` }, h("b", {}, x.title)),
                h("small", {}, cap(x.traits.setting?.[0] || ""))),
              h("td", { class: "col-time small" }, fmtWhen(x.publish_at)),
              h("td", { class: "col-right" }, x.views.toLocaleString()),
              h("td", { class: "col-right" }, x.likes.toLocaleString()),
              h("td", { class: "col-right" }, x.comments.toLocaleString()),
              h("td", { class: "col-right" }, x.avg_view_pct !== null && x.avg_view_pct !== undefined ? `${Math.round(x.avg_view_pct)}%` : "–"))))
        : empty("No numbers yet", "They appear once Shorts are public and Agent 5 has read YouTube's numbers.") }));
  syncButtons();
}

// ------------------------------------------------------------------ L1 music

async function loadMusic() {
  const tracks = await api("/api/music");
  const input = h("input", { type: "file", accept: ".mp3,.m4a,.aac,.wav,.ogg,audio/*", multiple: true, hidden: true,
                             onchange: e => addTracks([...e.target.files]) });
  const zone = h("label", { class: "dropzone" }, input,
    h("b", {}, "Drop music files here, or click to choose"),
    h("small", {}, "Agent 3 picks one in the script's mood (tracks.yaml), or any at random. Use only music you may post "
                   + "on YouTube; a track that needs a credit gets its line added at upload."));
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", e => { e.preventDefault(); zone.classList.remove("over"); addTracks([...e.dataTransfer.files]); });
  const mb = tracks.reduce((sum, t) => sum + t.size, 0) / 1e6;

  $("#view-music").replaceChildren(
    pageHead({ eyebrow: "L1 · Library", title: "Music",
      lede: "The music under the voices. It dips while someone speaks and comes back in the pauses." }),
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
    pageHead({ eyebrow: "S1 · Setup", title: "YouTube",
      lede: "Uploading needs your permission once. Your Google password never touches this software.",
      actions: [h("button", { class: "btn", type: "button", onclick: () => loadYouTube(true).catch(e => toast(e.message, "error")) },
                  "Check connection")] }),
    kpis([
      { label: "Channel", value: ok ? (y.channel || "Connected") : "Not connected", tone: ok ? "ok" : "warn",
        note: ok ? "uploads and stats are ready" : y.error ? `saved sign-in didn't work: ${y.error}` : "finish the steps below" },
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
                       : h("p", {}, "Connected to ", h("b", {}, y.channel || "your channel"), ". Uploads and stats are ready."))
            : h("p", {}, "A Google page opens in your browser: choose your channel and allow access."),
          h("div", { class: "row" },
            h("button", { class: "btn btn-primary btn-sm", type: "button", disabled: !y.client_file || !y.local || connecting,
                          onclick: () => runTask("connect") },
              connecting ? "Waiting for you in the browser…" : y.connected ? "Reconnect" : "Connect YouTube"),
            !y.local && h("span", { class: "note" }, "Connect from the dashboard on your computer.")))) }));
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
  const ep = s.episodes;
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
      row("Public contact email", h("span", {}, "Optional. Shown on your public ", h("a", { href: "/about", target: "_blank" }, "About"), " and ",
            h("a", { href: "/privacy", target: "_blank" }, "Privacy"), " pages, which Google asks for."),
          text("contact_email", s.channel.contact_email), "s-contact_email"),
      row("Who it's for", "Agents 1 and 2 write for these viewers.", text("audience", s.channel.audience), "s-audience"),
      row("Humour and voice", "Agents 1 and 2 follow this in every cast and every line.",
          h("textarea", { class: "input", id: "s-voice", name: "voice", rows: 4, disabled: ro, value: s.channel.voice }), "s-voice")),
    card("posting", "S2.2", "Posting",
      row("Daily schedule", "Each Short is made in the hours before its time and goes public on the minute.",
        h("div", {},
          h("div", { class: "inline-fields" },
            h("div", { class: "field" }, h("label", { for: "s-first_post" }, "First post"),
              h("input", { class: "input", type: "time", id: "s-first_post", name: "first_post", value: sch.first_post, disabled: ro, oninput: showSlots })),
            h("div", { class: "field" }, h("label", { for: "s-every_hours" }, "Then one every"),
              select("every_hours", EVERY_HOURS.map(n => [n, hours(n)]), sch.every_hours, showSlots)),
            h("div", { class: "field" }, h("label", { for: "s-posts_per_day" }, "Shorts a day"),
              h("input", { class: "input", type: "number", id: "s-posts_per_day", name: "posts_per_day", min: 1, max: 12,
                           value: sch.posts_per_day, disabled: ro, oninput: showSlots })),
            h("div", { class: "field" }, h("label", { for: "s-timezone" }, "On the clock of"),
              select("timezone", zones.map(z => [z, z === browserZone ? `${z} (this device)` : z]), sch.timezone, showSlots))),
          preview))),
    card("episodes", "S2.3", "Episodes",
      row("Where sketches happen", "Agent 1 picks one of these for each episode.",
        h("div", { class: "option-grid" }, Object.entries(s.settings_available).map(([key, label]) =>
          h("label", { class: "option" },
            h("input", { type: "checkbox", name: "settings", value: key, checked: ep.settings.includes(key), disabled: ro }),
            h("b", {}, key), h("span", {}, label))))),
      row("Characters per episode", "At most; Agent 1 casts 2 or 3.",
          select("max_cast", [[2, "Up to 2"], [3, "Up to 3"]], ep.max_cast), "s-max_cast"),
      row("Longest sketch", "Agent 2 keeps each sketch under this.", range("max_seconds", ep.max_seconds, 20, 60, 1, " s"), "s-max_seconds"),
      row("Written ahead", "While the autopilot is on, this PC keeps this many episodes written and animated, so you can watch them first.",
          select("queue", [0, 1, 2, 3, 4, 5].map(n => [n, n === 0 ? "None (write each at its slot)" : plural(n, "episode")]), ep.queue), "s-queue")),
    card("reach", "S2.4", "Trends and hashtags",
      row("Trends from", "Worldwide asks every country and puts the trends shared by the most countries first.",
          select("region", [...new Set(["ALL", s.trends.region, ...REGIONS])].map(r => [r, r === "ALL" ? "All countries (worldwide)" : r]), s.trends.region),
          "s-region"),
      row("Hashtags on every Short", "Up to 4, like #shorts #animation.", text("hashtags", s.metadata.base_hashtags.join(" ")), "s-hashtags")),
    card("music", "S2.5", "Music",
      row("Music volume", "Under the voices; 0 turns music off.", range("volume", s.music.volume, 0, 1.5, 0.05), "s-volume")),
    h("div", { class: "savebar" },
      h("p", { class: "note" }, ro ? "Settings can only be changed on your computer." : "Changes apply to the next episode."),
      h("button", { class: "btn btn-primary", type: "submit", disabled: ro }, "Save settings")));

  const nav = [["channel", "S2.1", "Channel"], ["posting", "S2.2", "Posting"], ["episodes", "S2.3", "Episodes"],
               ["reach", "S2.4", "Trends and hashtags"], ["music", "S2.5", "Music"]];
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
    channel: { name: f.get("name"), contact_email: f.get("contact_email"), audience: f.get("audience"),
               voice: f.get("voice") },
    schedule: { timezone: f.get("timezone"), first_post: f.get("first_post"), every_hours: Number(f.get("every_hours")),
                posts_per_day: Number(f.get("posts_per_day")) },
    episodes: { settings: f.getAll("settings"), max_cast: Number(f.get("max_cast")), max_seconds: Number(f.get("max_seconds")),
                queue: Number(f.get("queue")) },
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

const loaders = { overview: loadOverview, cast: loadCast, scripts: loadScripts, studio: loadStudio, schedule: loadSchedule,
                  results: loadResults, music: loadMusic, youtube: () => loadYouTube(), settings: loadSettings,
                  activity: loadActivity };

/** "#studio/12" -> "studio"; older page names land on their new pages. */
function currentView() {
  const view = location.hash.slice(1).split("/")[0];
  const name = { shorts: "studio", queue: "studio", trends: "scripts" }[view] || view;
  return VIEWS.includes(name) ? name : "overview";
}

let lastView = null;
async function route() {
  const view = currentView();
  if (lastView === "scripts" && view !== "scripts" && state.scripts.selected && state.dirty.has(state.scripts.selected)
      && !confirm("Leave without saving your changes to this episode?")) {
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

  $("#autopost").addEventListener("change", async e => {
    try {
      await api("/api/pause", { method: "POST", json: { paused: !e.target.checked } });
      toast(e.target.checked ? "Autopilot on. The agents get to work: posting on time, and writing and animating ahead."
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
    if (currentView() === "overview") loadOverview().catch(() => {});
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
