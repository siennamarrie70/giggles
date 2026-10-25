// Control room for the Shorts channel. Plain JS, no build step; talks to dashboard/api.py.
// Every page has the same shape: a header with its actions, a row of numbers, then numbered sections.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const SVG_NS = "http://www.w3.org/2000/svg";

const FORMAT_LABEL = { punchline: "Punchline", pov: "POV", top3: "Top 3" };
const STATUS = { planned: ["Planned", "accent"], making: ["Being made", "run"], scheduled: ["Scheduled", "run"],
                 live: ["Live", "ok"], failed: ["Failed", "bad"], vetoed: ["Vetoed", "bad"],
                 discarded: ["Discarded", "idle"], skipped: ["Skipped", "idle"] };
// What each posting slot says, by its state (see slot_board in tools/jobs.py).
const SLOT = { posted: ["Posted", "ok"], scheduled: ["Ready", "run"], making: ["Making…", "run"],
               late: ["Late · going out", "warn"], due: ["Up next", "accent"], open: ["Open", "idle"],
               missed: ["No post", "idle"], paused: ["Paused", "warn"] };
const TIMEZONES = ["Asia/Kolkata", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                   "Europe/London", "Europe/Berlin", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney", "UTC"];
const EVERY_HOURS = [1, 1.5, 2, 3, 4, 6, 8, 12];
const LIMITS = { hook: 70, punchline: 55, caption: 40, title: 100 };
const VIEWS = ["overview", "shorts", "trends", "music", "youtube", "settings", "activity"];
const REGIONS = ["US", "GB", "CA", "AU", "IE", "NZ", "IN", "PH", "SG", "ZA", "DE", "FR", "ES", "BR", "MX", "JP"];
// The audience is US-centred, so times are also shown for New York next to the schedule's own clock.
const AUDIENCE_TZ = "America/New_York";

const state = { app: null, videos: [], task: null, watching: null, dirty: new Set(),
                shorts: { filter: "planned", selected: null } };

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
const nyTime = iso => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZone: AUDIENCE_TZ });
/** A moment on the schedule's clock, e.g. 16:00: slots are set in that time zone, not the browser's. */
const clockIn = (iso, tz) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: tz });
const scheduleTz = () => state.app.autopilot.schedule.timezone;

/** A video the dashboard shows as "live" once its publish time has passed. */
const shownStatus = v => v.status === "scheduled" && v.publish_at && new Date(v.publish_at) <= new Date() ? "live" : v.status;

function pill(text, tone = "idle") {
  return h("span", { class: "pill", dataset: { tone } }, text);
}

function statusPill(v) {
  const [text, tone] = STATUS[shownStatus(v)] || [v.status, "idle"];
  return pill(text, tone);
}

function fmtChip(key) {
  return h("span", { class: "fmt", dataset: { format: key } }, h("i", { "aria-hidden": "true" }), FORMAT_LABEL[key] || key);
}

function pageHead({ eyebrow, title, lede, actions = [] }) {
  return h("header", { class: "page-head" },
    h("div", {}, h("p", { class: "eyebrow" }, eyebrow), h("h1", {}, title), lede && h("p", { class: "lede" }, lede)),
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
  return h("div", { class: "card" }, h("div", { class: "empty" }, icon("paw"), h("h3", {}, title), text && h("p", {}, text)));
}

function taskButton(kind, label, { primary = false, sm = false, title, confirmText } = {}) {
  return h("button", { class: `btn${primary ? " btn-primary" : ""}${sm ? " btn-sm" : ""}`, type: "button",
                       "data-needs-idle": true, title,
                       onclick: () => { if (!confirmText || confirm(confirmText)) runTask(kind); } }, label);
}

/** "Make the 16:00 Short now": takes the oldest planned Short (or plans one), renders and uploads it. */
function makeButton() {
  const a = state.app;
  const nextOpen = a.autopilot.next_open;
  const blocked = !a.services.youtube || !nextOpen;
  return h("button", { class: "btn", type: "button", "data-needs-idle": true, dataset: { blocked: blocked ? "1" : "0" },
    title: !a.services.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
         : "Plans (or takes the oldest planned Short), renders and uploads it for that slot",
    onclick: () => {
      const when = nextOpen ? `${clockIn(nextOpen, scheduleTz())} (${fromNow(nextOpen)})` : "the next free slot";
      if (confirm(`Make a Short for ${when} now?\n\nIt uses the oldest planned Short (or plans a new one), renders it `
                  + "and uploads it as private. YouTube makes it public at that time.")) runTask("autopilot");
    } }, nextOpen ? `Make the ${clockIn(nextOpen, scheduleTz())} Short now` : "Make the next Short now");
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
  document.title = `${a.channel} · Control room`;

  const rows = [
    ["Gemini", s.gemini ? "ok" : "bad", s.gemini ? "Ready" : "Add key", null],
    ["Pexels", s.pexels ? "ok" : "bad", s.pexels ? "Ready" : "Add key", null],
    ["Pixabay", s.pixabay ? "ok" : "off", s.pixabay ? "Ready" : "Optional", null],
    ["YouTube", s.youtube ? "ok" : "warn", s.youtube ? "Connected" : "Not connected", "#youtube"],
    ["Music", s.music ? "ok" : "warn", s.music ? plural(s.music, "track") : "No tracks", "#music"],
    ["Database", "ok", s.database === "cloud" ? "Cloud" : "This PC", null],
    ["Telegram", s.telegram ? "ok" : "off", s.telegram ? "Alerts on" : "Optional", "#activity"],
  ];
  $("#services").replaceChildren(...rows.map(([name, tone, text, href]) => h("li", {},
    h(href ? "a" : "span", { href },
      h("span", { class: "inline" }, h("span", { class: "dot", dataset: { tone } }), name), h("small", {}, text)))));

  $("#count-shorts").textContent = a.counts?.planned || "";
  $("#count-music").textContent = s.music || "";

  const ap = a.autopilot;
  const on = !a.paused;
  $("#autopost").checked = on;
  $("#autopost").disabled = !a.local;
  $("#autopost-label").textContent = on ? "Autopilot on" : "Autopilot paused";
  $("#autopost-sub").textContent = !on ? "Nothing posts by itself"
    : ap.here ? `${plural(ap.schedule.posts_per_day, "Short")} a day from ${ap.schedule.first_post}` : "Runs in the cloud";
  $("#pause-switch").title = a.local ? "Off stops all automatic posting (your own buttons keep working)"
                                     : "Change PAUSED in Vercel's environment variables";
  syncButtons();
}

function syncButtons() {
  const busy = state.task?.status === "running";
  const local = state.app?.local !== false;  // in the cloud the hourly jobs do the work
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
  if (t.kind === "prepare") {
    return r.planned?.length ? `New Short planned: ${r.planned[0].title}`
                             : `Couldn't plan one this time: ${(r.skipped || []).join("; ") || "no suitable clips"}.`;
  }
  if (t.kind === "render") return "Preview ready. Press play on the phone.";
  if (t.kind === "publish" || t.kind === "autopilot") {
    return r.live_now ? `Posted: ${r.title}. It's live now.` : `Uploaded: ${r.title}. It goes public ${fmtWhen(r.publish_at)}.`;
  }
  if (t.kind === "stats") return `Stats updated for ${plural(r.updated || 0, "Short")}.`;
  if (t.kind === "connect") return `YouTube connected: ${r.channel}`;
  return "Done.";
}

async function finishTask(t) {
  if (t.status === "error") toast(t.error, "error", 9000);
  else toast(taskSummary(t), "ok", 6000);
  if (t.kind === "prepare" && t.result?.planned?.length) {  // show the new Short
    state.shorts = { filter: "planned", selected: t.result.planned[0].id, picked: true };
  }
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
        ? [h("a", { href: `#shorts/${v.id}` }, h("b", {}, v.title || `Short #${v.id}`)), v.format && h("small", {}, FORMAT_LABEL[v.format] || v.format)]
        : h("span", { class: "slot-title muted" }, s.state === "missed" ? "Nothing went out" : "Not made yet")),
      h("td", { class: "col-actions" }, link));
  });
}

function overviewLede(a) {
  const ap = a.autopilot;
  const sch = ap.schedule;
  const rhythm = `${plural(sch.posts_per_day, "Short")} a day, one every ${hours(sch.every_hours)} from ${sch.first_post} (${sch.timezone})`;
  if (a.paused) return `The autopilot is paused, so nothing posts by itself. Switch it on (top right) for ${rhythm}.`;
  if (!a.services.youtube) return "The autopilot is on, but YouTube isn't connected yet, so it can't post.";
  return `The autopilot is on: ${rhythm}.${ap.here ? "" : " It runs in the cloud."}`;
}

async function loadOverview() {
  const a = state.app;
  const ap = a.autopilot;
  const posted = ap.slots.filter(s => s.state === "posted").length;
  const next = ap.next;
  const planned = a.counts?.planned || 0;
  const root = $("#view-overview");
  const today = new Date(ap.slots[0].at).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", timeZone: scheduleTz() });

  root.replaceChildren(
    pageHead({ eyebrow: `00 · ${today}`, title: "Overview", lede: overviewLede(a),
      actions: [taskButton("stats", "Refresh stats"), makeButton(), taskButton("prepare", "Plan a new Short", { primary: true })] }),
    kpis([
      { label: "Posted today", value: posted, unit: `/ ${ap.slots.length}` },
      { label: "Next post", value: next ? clockIn(next.at, scheduleTz()) : "–",
        note: next ? `${fromNow(next.at)} · ${nyTime(next.at)} in New York` : "" },
      { label: "Shorts planned", value: planned, note: planned ? "the autopilot posts these first" : "press “Plan a new Short”",
        tone: planned ? null : "warn" },
      { label: "Music", value: a.services.music, unit: "tracks", note: a.services.music ? "one picked at random" : "Shorts are silent",
        tone: a.services.music ? null : "warn" },
      { label: "Autopilot", value: a.paused ? "Paused" : "On", tone: a.paused ? "warn" : "ok",
        note: ap.here ? "checks every minute on this PC" : `runs in the cloud${ap.last_check ? `, last ${fromNow(ap.last_check)}` : ""}` },
    ]),
    h("div", { class: "grid-2-1" },
      section({ num: "01", title: "Today's schedule", text: `On the ${scheduleTz()} clock, with New York time beside it.`,
        body: table([["Time", { class: "col-time" }], ["New York", { class: "col-time" }], "Status", "Short", ["", { class: "col-actions" }]],
                    slotRows(ap.slots)) }),
      section({ num: "02", title: "Coming up", text: "Pet days and holidays the planner themes Shorts around.",
        body: h("div", { class: "card card-pad" }, a.events.length
          ? h("ul", { class: "events" }, a.events.slice(0, 8).map(e => h("li", {}, h("span", {}, e.name),
              h("small", {}, e.in_days === 0 ? "today" : `in ${plural(e.in_days, "day")}`))))
          : h("p", { class: "note" }, "Nothing in the next few days.")) })),
    h("div", { id: "overview-activity", style: "margin-top:30px" }));
  syncButtons();
  const act = await api("/api/activity");
  const box = $("#overview-activity");
  if (box) box.replaceChildren(section({ num: "03", title: "Latest work", text: "What ran most recently.",
    actions: h("a", { class: "btn btn-sm", href: "#activity" }, "All activity"),
    body: runsTable(act.runs.slice(0, 6)) }));
}

// ------------------------------------------------------------------ 01 shorts

const SHORT_FILTERS = [
  ["planned", "Planned", v => v.status === "planned"],
  ["coming", "Coming up", v => v.status === "making" || shownStatus(v) === "scheduled"],
  ["published", "Published", v => shownStatus(v) === "live"],
  ["stopped", "Stopped", v => ["failed", "vetoed", "discarded", "skipped"].includes(v.status)],
];
const FILTER_TEXT = {
  planned: "The autopilot posts these first, oldest first. Watch the preview and tweak the words before their turn, "
           + "or upload one yourself into the next free slot.",
  coming: "Uploaded as private. Each goes public at its slot; delete it in YouTube Studio before then to veto it.",
  published: "Public on YouTube.",
  stopped: "Shorts that failed, were vetoed or were discarded. Their clips aren't used again.",
};

async function loadShorts() {
  state.videos = await api("/api/videos");
  const sub = Number(location.hash.split("/")[1]);
  if (sub) {  // a link like #shorts/12 opens that Short on its tab
    const v = state.videos.find(x => x.id === sub);
    if (v) state.shorts = { filter: SHORT_FILTERS.find(([, , test]) => test(v))?.[0] || "planned", selected: v.id, picked: true };
    history.replaceState(null, "", "#shorts");  // done with the link; later reloads keep what you pick
  } else if (!state.shorts.picked) {  // until you pick a tab, open on the first one with Shorts in it
    const first = SHORT_FILTERS.find(([, , test]) => state.videos.some(test));
    if (first) state.shorts.filter = first[0];
  }
  renderShorts();
}

function renderShorts() {
  const root = $("#view-shorts");
  const { filter } = state.shorts;
  const counts = Object.fromEntries(SHORT_FILTERS.map(([key, , test]) => [key, state.videos.filter(test).length]));
  const list = state.videos.filter(SHORT_FILTERS.find(([key]) => key === filter)[2]);
  if (!list.some(v => v.id === state.shorts.selected)) state.shorts.selected = list[0]?.id ?? null;
  const selected = list.find(v => v.id === state.shorts.selected);

  const tabs = h("div", { class: "segmented", role: "tablist" }, SHORT_FILTERS.map(([key, label]) =>
    h("button", { type: "button", role: "tab", "aria-selected": String(key === filter),
                  onclick: () => leaveDirty(() => { state.shorts = { filter: key, selected: null, picked: true }; renderShorts(); }) },
      label, h("span", { class: "n" }, counts[key]))));

  root.replaceChildren(
    pageHead({ eyebrow: "01 · Make", title: "Shorts",
      lede: "Each Short is planned from today's trends: free stock clips, checked by the AI, with captions written for them.",
      actions: [makeButton(), taskButton("prepare", "Plan a new Short", { primary: true })] }),
    kpis([
      { label: "Planned", value: counts.planned, note: "waiting for a slot", tone: counts.planned ? null : "warn" },
      { label: "Coming up", value: counts.coming, note: "uploaded, not public yet" },
      { label: "Published", value: counts.published, note: "in the last 40 Shorts" },
      { label: "Stopped", value: counts.stopped, note: "failed, vetoed or discarded" },
    ]),
    section({ num: "1.1", title: "Shorts", text: FILTER_TEXT[filter], actions: tabs,
      body: !state.videos.length
        ? empty("No Shorts yet", "Press “Plan a new Short”. The planner reads today’s trends, finds free stock clips, checks them and writes the captions.")
        : !list.length ? empty(`Nothing ${SHORT_FILTERS.find(([k]) => k === filter)[1].toLowerCase()}`, FILTER_TEXT[filter])
        : h("div", { class: "studio" },
            h("div", { class: "card studio-list" },
              h("div", { class: "card-head" }, h("h3", {}, plural(list.length, "Short")), h("p", {}, "newest first")),
              h("ul", { class: "vlist" }, list.map(v => h("li", {},
                h("button", { class: "vrow", type: "button", "aria-current": String(v.id === state.shorts.selected),
                              onclick: () => leaveDirty(() => { state.shorts.selected = v.id; renderShorts(); }) },
                  h("span", { class: "vid" }, `#${v.id}`),
                  h("span", { class: "vtitle" }, v.metadata.title || v.theme || "A new Short"),
                  h("span", { class: "vmeta" }, fmtChip(v.format), statusPill(v),
                    v.slot && v.status !== "planned" && h("span", {}, clockIn(v.slot, scheduleTz())))))))),
            selected && detail(selected)) }));
  syncButtons();
}

/** Asks before throwing away unsaved caption edits. */
function leaveDirty(go) {
  const id = state.shorts.selected;
  if (state.dirty.has(id) && !confirm("Leave without saving your changes to this Short?")) return;
  state.dirty.delete(id);
  go();
}

function detail(v) {
  const editable = v.status === "planned";
  const el = h("article", { class: "card", dataset: { id: v.id } });
  const phone = h("div", { class: "phone" });
  el.append(
    h("div", { class: "detail-head" },
      h("div", { class: "row" }, fmtChip(v.format), statusPill(v),
        v.animal && h("span", { class: "tag" }, v.animal),
        v.music && h("span", { class: "tag", title: "Background music" }, `♪ ${v.music.replace(/\.[^.]+$/, "")}`),
        h("span", { class: "muted small" }, `#${v.id}${v.duration ? ` · ${v.duration.toFixed(1)}s` : ""} · planned ${fromNow(v.created_at)}`)),
      h("h2", {}, v.theme || { making: "A new Short", skipped: "Not made" }[v.status] || "Untitled"),
      v.angle && h("p", { class: "angle" }, v.angle),
      v.trend && h("p", { class: "angle" }, `Rides on the trend “${v.trend}”`)),
    h("div", { class: "detail-body" },
      phone,
      h("div", {},
        v.status === "making" && v.slot && h("div", { class: "callout", dataset: { tone: "warn" } }, "Being made for the ",
          h("b", {}, clockIn(v.slot, scheduleTz())), " slot right now."),
        v.status === "scheduled" && scheduledBox(v),
        v.error && h("div", { class: "callout", dataset: { tone: "bad" } }, v.error),
        editable ? editor(v, el) : readOnly(v),
        v.clips.length > 0 && [h("p", { class: "sub-head" }, `Clips · ${v.clips.length}`), clipList(v)])),
    editable && actions(v, el));
  drawScreen(phone, v, el);
  return el;
}

function scheduledBox(v) {
  const live = v.publish_at && new Date(v.publish_at) <= new Date();
  return h("div", { class: "callout", dataset: { tone: "ok" } },
    live ? "Public since " : "Goes public ", h("b", {}, fmtWhen(v.publish_at)), live ? "" : ` (${fromNow(v.publish_at)})`, ". ",
    h("a", { href: v.studio_url, target: "_blank", rel: "noopener" }, "Open in YouTube Studio ↗"),
    live && v.youtube_id ? [" · ", h("a", { href: `https://youtube.com/shorts/${v.youtube_id}`, target: "_blank", rel: "noopener" }, "Watch ↗")] : null);
}

/** What the captions say right now: the edit fields if they exist, else the saved text. */
function captionText(v, root) {
  const field = name => root && $(`[name="${name}"]`, root);
  const read = (name, fallback) => (field(name) ? field(name).value : fallback) || "";
  const captions = v.metadata.captions || [];
  return {
    hook: read("hook", v.metadata.hook),
    bottom: v.format === "punchline" ? read("punchline", v.metadata.punchline)
          : v.format === "top3" ? (k => k ? `3. ${k}` : "#3")(read("caption0", captions[0])) : "",
  };
}

function drawScreen(phone, v, root) {
  const dirty = state.dirty.has(v.id);
  if (v.preview && !dirty) {
    phone.dataset.mode = "video";
    phone.replaceChildren(h("video", { src: v.preview, controls: true, playsinline: true, loop: true,
                                       preload: "metadata", poster: v.clips[0]?.thumb }));
    return;
  }
  const text = captionText(v, root);
  phone.dataset.mode = "live";
  phone.replaceChildren(
    v.clips[0]?.thumb ? h("img", { class: "poster", src: v.clips[0].thumb, alt: "" }) : h("div", { class: "phone-blank" }),
    h("p", { class: "cap cap-top" }, text.hook),
    h("p", { class: "cap cap-bottom" }, text.bottom),
    v.status === "planned" && h("span", { class: `phone-badge${dirty ? " live" : ""}` },
      dirty ? "Live preview of your edits" : "Not rendered yet"),
    v.status === "making" && h("span", { class: "phone-badge" }, "Being made…"));
}

function editor(v, root) {
  const m = v.metadata;
  const onEdit = () => {
    state.dirty.add(v.id);
    const phone = $(".phone", root);
    if (phone.dataset.mode !== "live" || !$(".phone-badge.live", phone)) return drawScreen(phone, v, root);
    const text = captionText(v, root);
    $(".cap-top", phone).textContent = text.hook;
    $(".cap-bottom", phone).textContent = text.bottom;
  };
  const field = (name, label, value, limit, { caption = false, multiline = false } = {}) => {
    const id = `f-${v.id}-${name}`;
    const counter = limit ? h("span", { class: "counter", "aria-live": "polite" }) : null;
    const input = multiline ? h("textarea", { class: "input", id, name, rows: 8 })
                            : h("input", { class: `input${caption ? " caption" : ""}`, id, name, autocomplete: "off" });
    input.value = value || "";
    const count = () => {
      if (!counter) return;
      const left = limit - input.value.length;
      counter.textContent = left >= 0 ? `${left} left` : `${-left} too long`;
      counter.classList.toggle("over", left < 0);
    };
    input.addEventListener("input", () => { count(); onEdit(); });
    count();
    return h("div", { class: "field" }, h("label", { for: id }, h("span", {}, label), counter), input);
  };

  const fields = [field("hook", v.format === "pov" ? "On-screen caption" : "Top caption", m.hook, LIMITS.hook, { caption: true })];
  if (v.format === "punchline") {
    fields.push(field("punchline", "Punchline · appears halfway", m.punchline, LIMITS.punchline, { caption: true }));
  }
  if (v.format === "top3") {
    (m.captions?.length ? m.captions : ["", "", ""]).forEach((c, k) =>
      fields.push(field(`caption${k}`, `Clip ${k + 1} · shown as #${3 - k}`, c, LIMITS.caption, { caption: true })));
  }
  fields.push(field("title", "YouTube title", m.title, LIMITS.title));
  fields.push(h("details", { class: "more" }, h("summary", {}, "Description, credits & hashtags"),
    field("description", "Description", m.description, null, { multiline: true }),
    h("p", { class: "hint", style: "margin-top:8px;white-space:pre-line" }, v.music_credit
      ? `Added at upload, as the music's licence asks:\n${v.music_credit}`
      : v.music ? "This track needs no credit line." : "The music is picked when the video is rendered; its credit line is added at upload.")));
  return h("div", { class: "fields" }, fields);
}

function readOnly(v) {
  const m = v.metadata;
  if (!m.title) return null;  // still being planned
  return h("div", {},
    h("dl", { class: "dl" },
      h("dt", {}, "YouTube title"), h("dd", {}, m.title),
      m.hook && [h("dt", {}, "Top caption"), h("dd", {}, m.hook)],
      m.punchline && [h("dt", {}, "Punchline"), h("dd", {}, m.punchline)],
      m.captions?.length > 0 && [h("dt", {}, "Clip captions"), h("dd", {}, m.captions.join(" · "))]),
    h("details", { class: "more" }, h("summary", {}, "Description, credits & hashtags"),
      h("p", { class: "desc-ro" }, m.description)));
}

function clipList(v) {
  const site = { pexels: "Pexels", pixabay: "Pixabay" };
  return h("div", { class: "clips" }, v.clips.map(c => h("div", { class: "clip" },
    c.thumb ? h("img", { src: c.thumb, alt: "", loading: "lazy" }) : h("img", { alt: "" }),
    h("div", {},
      h("p", {}, c.score !== null && c.score !== undefined && h("span", { class: "score", title: "Clip check score" }, `${c.score}/10`),
        c.what || "Stock clip"),
      h("p", { class: "credit" }, "by ", h("a", { href: c.page_url, target: "_blank", rel: "noopener" }, c.credit_name),
        ` on ${site[c.source] || c.source}`)))));
}

function actions(v, root) {
  const s = state.app.services;
  const nextOpen = state.app.autopilot.next_open;
  const blocked = !s.youtube || !nextOpen;
  return h("div", { class: "detail-actions" },
    h("button", { class: "btn btn-sm", type: "button", onclick: () => saveEdits(v, root) }, "Save changes"),
    h("button", { class: "btn btn-sm", type: "button", "data-needs-idle": true, onclick: () => renderPreview(v) },
      v.preview ? "Re-render preview" : "Render preview"),
    h("button", { class: "btn btn-sm btn-primary", type: "button", "data-needs-idle": true,
      dataset: { blocked: blocked ? "1" : "0" },
      title: !s.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
           : `Uploads as private, scheduled for the next free slot (${clockIn(nextOpen, scheduleTz())})`,
      onclick: () => upload(v) }, "Upload & schedule"),
    h("span", { class: "spacer" }),
    !s.youtube && h("a", { class: "note", href: "#youtube" }, "Connect YouTube to upload"),
    h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard"));
}

function readEdits(v, root) {
  const val = name => $(`[name="${name}"]`, root)?.value ?? "";
  const edits = { hook: val("hook"), title: val("title"), description: val("description") };
  if (v.format === "punchline") edits.punchline = val("punchline");
  if (v.format === "top3") edits.captions = [0, 1, 2].map(k => val(`caption${k}`));
  return edits;
}

async function saveEdits(v, root) {
  try {
    const updated = await api(`/api/videos/${v.id}`, { method: "PATCH", json: readEdits(v, root) });
    state.dirty.delete(v.id);
    const i = state.videos.findIndex(x => x.id === v.id);
    if (i >= 0) state.videos[i] = updated;
    renderShorts();
    toast("Saved. Render a new preview to see the change on the video.", "ok");
  } catch (e) {
    toast(e.message, "error", 7000);
  }
}

function renderPreview(v) {
  if (state.dirty.has(v.id)) return toast("Save your changes first, then render.", "error");
  runTask("render", v.id);
}

function upload(v) {
  if (state.dirty.has(v.id)) return toast("Save your changes first.", "error");
  const slot = state.app.autopilot.next_open;
  const when = slot ? `${fmtWhen(slot)} (${fromNow(slot)})` : "at the next free slot";
  if (!confirm(`Upload “${v.metadata.title}” to YouTube?\n\nIt goes up as private and becomes public ${when}. `
             + "Until then you can still delete it in YouTube Studio.")) return;
  runTask("publish", v.id);
}

async function discard(v) {
  if (!confirm(`Discard “${v.theme}”? Its clips won't be used again.`)) return;
  try {
    await api(`/api/videos/${v.id}`, { method: "DELETE" });
    state.dirty.delete(v.id);
    toast("Discarded.");
    await loadState();
    loadShorts();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ------------------------------------------------------------------ 02 trends

/** Where a trend comes from: "14 ctry" (hover to list them), or the one country. */
function whereFrom(countries) {
  if (!countries?.length) return null;
  return h("small", { title: countries.join(", ") }, countries.length > 1 ? `${countries.length} ctry` : countries[0]);
}

async function loadTrends(refresh = false) {
  const root = $("#view-trends");
  const head = pageHead({ eyebrow: "02 · Make", title: "Trends",
    lede: "What the planner reads before each Short: searches trending around the world, popular animal videos, and the "
          + "days coming up. It only uses what fits cute animals; news, sport and celebrities are skipped.",
    actions: [h("button", { class: "btn", type: "button", onclick: () => loadTrends(true).catch(e => toast(e.message, "error")) },
                "Refresh trends")] });
  root.replaceChildren(head, h("p", { class: "loading" }, refresh
    ? "Asking for today’s trends again. Worldwide that’s every country, so it can take a minute…"
    : "Reading today’s trends… if they’re older than 6 hours this asks every country again, up to a minute."));
  const t = await api(`/api/trends${refresh ? "?refresh=1" : ""}`);
  const world = t.region === "ALL";
  root.replaceChildren(head,
    kpis([
      { label: "Trends from", value: world ? (t.countries ?? "–") : t.region, unit: world ? "countries" : "",
        note: t.fetched_at ? `fetched ${fromNow(t.fetched_at)}` : "not fetched yet" },
      { label: "Trending searches", value: t.google_trends.length },
      { label: "Popular animal videos", value: t.youtube_popular.length },
      { label: "Today", value: t.weekday, note: [t.season, t.weekday_vibe].filter(Boolean).join(" · ") },
    ]),
    h("div", { class: "grid-2" },
      section({ num: "2.1", title: world ? "Trending searches · worldwide" : `Trending searches · ${t.region}`,
        text: world ? "Searches trending in the most countries first." : "Google's trending searches.",
        body: h("div", { class: "card card-pad" }, t.google_trends.length
          ? h("ol", { class: "ranked" }, t.google_trends.slice(0, 20).map(g => h("li", {}, h("span", {}, g.term),
              world ? whereFrom(g.countries) : h("small", {}, g.traffic || ""))))
          : h("p", { class: "note" }, "Google Trends didn't answer this time.")) }),
      section({ num: "2.2", title: "Popular animal videos",
        text: world ? "YouTube's Pets & Animals charts from every country." : "Doing well in Pets & Animals now.",
        body: h("div", { class: "card card-pad" }, t.youtube_popular.length
          ? h("ol", { class: "ranked" }, t.youtube_popular.slice(0, 20).map(p => h("li", {}, h("span", {}, p.title),
              world && p.countries?.length > 1 ? whereFrom(p.countries)
                    : h("small", {}, p.views ? `${(p.views / 1e6).toFixed(1)}M views` : ""))))
          : h("p", { class: "note" }, state.app.services.youtube ? "Nothing came back this time."
                                      : ["Connect YouTube to see these. ", h("a", { href: "#youtube" }, "How →")])) })),
    section({ num: "2.3", title: "Coming up", text: "Pet days and holidays. The planner themes Shorts around them a few days early.",
      body: t.events.length
        ? table(["Day", "Date", ["In", { class: "col-time" }]], t.events.map(e => h("tr", {},
            h("td", {}, h("b", {}, e.name)),
            h("td", { class: "muted" }, new Date(`${e.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })),
            h("td", { class: "col-time" }, e.in_days === 0 ? "today" : plural(e.in_days, "day")))))
        : empty("Nothing coming up", "No pet days or holidays in the next few days.") }),
    t.errors.length > 0 && h("p", { class: "note", style: "margin-top:16px" }, `Notes: ${t.errors.join(" · ")}`));
}

// ------------------------------------------------------------------ L1 music

async function loadMusic() {
  const tracks = await api("/api/music");
  const input = h("input", { type: "file", accept: ".mp3,.m4a,.aac,.wav,.ogg,audio/*", multiple: true, hidden: true,
                             onchange: e => addTracks([...e.target.files]) });
  const zone = h("label", { class: "dropzone" }, input, icon("paw"),
    h("b", {}, "Drop music files here, or click to choose"),
    h("small", {}, "Each Short picks one of these at random. Free, safe tracks: YouTube Studio → Audio Library → "
                   + "“Attribution not required”, or Pixabay Music."));
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", e => { e.preventDefault(); zone.classList.remove("over"); addTracks([...e.dataTransfer.files]); });
  const mb = tracks.reduce((sum, t) => sum + t.size, 0) / 1e6;

  $("#view-music").replaceChildren(
    pageHead({ eyebrow: "L1 · Library", title: "Music",
      lede: "Background tracks for the Shorts. Use only music you're allowed to post on YouTube." }),
    kpis([
      { label: "Tracks", value: tracks.length, tone: tracks.length ? null : "warn", note: tracks.length ? "one per Short, at random" : "Shorts are silent" },
      { label: "Library size", value: mb.toFixed(1), unit: "MB" },
    ]),
    section({ num: "L1.1", title: "Add tracks", body: zone }),
    section({ num: "L1.2", title: "Tracks", text: "Press play to listen.",
      body: tracks.length
        ? table(["Track", "Listen", ["", { class: "col-actions" }]], tracks.map(t => h("tr", {},
            h("td", { class: "title-cell" }, h("b", { title: t.name }, t.name), h("small", {}, `${(t.size / 1e6).toFixed(1)} MB`)),
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
            !y.local && h("span", { class: "note" }, "Connect from the dashboard on your computer.")))) }),
    section({ num: "S1.2", title: "Why a Google Cloud project?",
      body: h("div", { class: "card card-pad" }, h("ul", { class: "events" },
        h("li", {}, "YouTube only lets software upload through its official API, and every app using it must be registered in Google Cloud. That registration is the “project”."),
        h("li", {}, "It’s free: no billing, no card. YouTube uploads don’t cost anything."),
        h("li", {}, "The project gives you an OAuth client file. With it, you sign in once and allow this app to upload to your channel."),
        h("li", {}, h("span", {}, "You can revoke access any time at ", link("https://myaccount.google.com/permissions", "myaccount.google.com/permissions"), ".")))) }));
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
  const text = (name, value, attrs = {}) => h("input", { class: "input", id: `s-${name}`, name, value: value ?? "", disabled: ro, ...attrs });
  const range = (name, value, min, max, step) => {
    const out = h("output", {}, value);
    return h("div", { class: "range-row" },
      h("input", { type: "range", id: `s-${name}`, name, min, max, step, value, disabled: ro,
                   oninput: e => { out.textContent = e.target.value; } }), out);
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
      row("Who it's for", null, text("audience", s.channel.audience), "s-audience"),
      row("Humour and voice", "The writer follows this for every caption and title.",
          h("textarea", { class: "input", id: "s-voice", name: "voice", rows: 4, disabled: ro, value: s.channel.voice }), "s-voice")),
    card("posting", "S2.2", "Posting",
      row("Daily schedule", "Each Short is made in the two hours before its time and goes public on the minute. Up to 12 a day fit Vercel's free plan.",
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
          preview)),
      row("Format rotation", `In order, one per Short. Choose from: ${s.formats_available.join(", ")}.`,
          text("rotation", s.formats.rotation.join(", ")), "s-rotation"),
      row("Hashtags on every Short", "Up to 4, like #shorts #cuteanimals.", text("hashtags", s.metadata.base_hashtags.join(" ")), "s-hashtags"),
      row("Music volume", null, range("volume", s.music.volume, 0, 1.5, 0.05), "s-volume")),
    card("content", "S2.3", "Content rules",
      row("Animals the planner may choose", "Comma-separated.",
          h("textarea", { class: "input", id: "s-animals", name: "animals", rows: 2, disabled: ro, value: s.content.animals.join(", ") }), "s-animals"),
      row("Minimum clip score", "Clips the checker scores below this are skipped.", range("score", s.content.min_check_score, 0, 10, 1), "s-score"),
      row("Longest Short", "In seconds.", range("seconds", s.content.max_short_seconds, 10, 60, 1), "s-seconds"),
      row("People in clips", "Children are always rejected, whatever this says.",
          h("label", { class: "check" }, h("input", { type: "checkbox", name: "allow_people", checked: s.content.allow_people, disabled: ro }),
            h("span", {}, "Allow adults in clips")))),
    card("trends", "S2.4", "Trends",
      row("Trends from", "Worldwide asks every country and puts the trends shared by the most countries first.",
          select("region", [...new Set(["ALL", s.trends.region, ...REGIONS])].map(r => [r, r === "ALL" ? "All countries (worldwide)" : r]), s.trends.region),
          "s-region")),
    h("div", { class: "savebar" },
      h("p", { class: "note" }, ro ? "Settings can only be changed on your computer." : "Changes apply to the next Short."),
      h("button", { class: "btn btn-primary", type: "submit", disabled: ro }, "Save settings")));

  const nav = [["channel", "S2.1", "Channel"], ["posting", "S2.2", "Posting"], ["content", "S2.3", "Content rules"], ["trends", "S2.4", "Trends"]];
  $("#view-settings").replaceChildren(
    pageHead({ eyebrow: "S2 · Setup", title: "Settings", lede: "How the channel behaves. Saved to config/channel.yaml." }),
    h("div", { class: "settings" },
      h("nav", { class: "settings-nav", "aria-label": "Settings sections" }, nav.map(([id, num, label]) =>
        h("a", { href: `#settings`, onclick: e => { e.preventDefault(); $(`#set-${id}`).scrollIntoView({ behavior: "smooth" }); } },
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
    formats: { rotation: list(f.get("rotation")) },
    content: { animals: list(f.get("animals")), allow_people: f.get("allow_people") === "on",
               min_check_score: Number(f.get("score")), max_short_seconds: Number(f.get("seconds")) },
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

function runSummary(r) {
  const d = r.detail || {};
  if (r.ok === null) return "Running…";
  if (d.error) return d.error;
  if (typeof d.skipped === "string") return `Skipped: ${d.skipped}`;
  if (d.planned) {
    const made = d.planned.map(p => `#${p.id} ${p.title}`).join(", ");
    return made || `Nothing planned: ${(d.skipped || []).join("; ")}`;
  }
  if (d.youtube_id && d.live_now) return `Posted #${d.video_id} “${d.title}”, live since ${fmtWhen(d.publish_at)}`;
  if (d.youtube_id) return `Uploaded #${d.video_id} “${d.title}”, goes public ${fmtWhen(d.publish_at)}`;
  if (d.rendered) return `Preview rendered: ${d.title}`;
  if (d.updated !== undefined) return `Stats for ${plural(d.updated, "Short")}${d.vetoed ? `, ${d.vetoed} vetoed` : ""}`;
  return d.text || "Done";
}

function runsTable(runs) {
  if (!runs.length) return empty("Nothing has run yet", "Plans, uploads and stats appear here as they happen.");
  return table([["When", { class: "col-time" }], "Job", "Result", "What happened"], runs.map(r => h("tr", {},
    h("td", { class: "col-time small" }, fmtWhen(r.started_at)),
    h("td", {}, h("span", { class: "tag" }, r.job)),
    h("td", {}, r.ok === null ? pill("Running", "run") : r.ok === 0 ? pill("Failed", "bad") : pill("Done", "ok")),
    h("td", { class: "log-what" }, runSummary(r)))));
}

async function loadActivity() {
  const a = await api("/api/activity");
  const failed = a.runs.filter(r => r.ok === 0).length;
  $("#view-activity").replaceChildren(
    pageHead({ eyebrow: "S3 · Setup", title: "Activity",
      lede: "Every Short the autopilot made, the daily stats, and the buttons you press here." }),
    kpis([
      { label: "Job runs", value: a.runs.length, note: "most recent first" },
      { label: "Failed", value: failed, tone: failed ? "bad" : null },
      { label: "Alerts", value: a.alerts.length, note: "since the server started" },
      { label: "Phone alerts", value: a.telegram ? "On" : "Off", tone: a.telegram ? "ok" : null, note: "through Telegram" },
    ]),
    section({ num: "S3.1", title: "Job runs", body: runsTable(a.runs) }),
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

const loaders = { overview: loadOverview, shorts: loadShorts, trends: () => loadTrends(), music: loadMusic,
                  youtube: () => loadYouTube(), settings: loadSettings, activity: loadActivity };

/** "#shorts/12" -> "shorts"; the old tab names (#queue) land on their new pages. */
function currentView() {
  const view = location.hash.slice(1).split("/")[0];
  const name = { queue: "shorts" }[view] || view;
  return VIEWS.includes(name) ? name : "overview";
}

let lastView = null;
async function route() {
  const view = currentView();
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
      toast(e.target.checked ? "Autopilot on. It makes the next Short when its slot is due."
                             : "Autopilot paused. Nothing posts by itself; your own buttons still work.", "ok");
    } catch (err) {
      e.target.checked = !e.target.checked;
      toast(err.message, "error");
    }
    await loadState().catch(() => {});
    if (currentView() === "overview") loadOverview().catch(() => {});
  });

  // Keep the schedule current and notice when the autopilot starts a Short by itself.
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
