// Control room for the Shorts channel. Plain JS, no build step; talks to dashboard/api.py.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const SVG_NS = "http://www.w3.org/2000/svg";

const FORMAT_LABEL = { punchline: "Punchline", pov: "POV", top3: "Top 3" };
const STATUS_LABEL = { planned: "Planned", making: "Being made", scheduled: "Scheduled", live: "Live",
                       failed: "Failed", vetoed: "Vetoed", discarded: "Discarded", skipped: "Skipped" };
// What each posting slot on the line-up says, by its state (see slot_board in tools/jobs.py).
const SLOT_LABEL = { posted: "Posted", scheduled: "Ready", making: "Making…", late: "Late · going out",
                     due: "Up next", open: "", missed: "No post" };
const TIMEZONES = ["Asia/Kolkata", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                   "Europe/London", "Europe/Berlin", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney", "UTC"];
const EVERY_HOURS = [1, 1.5, 2, 3, 4, 6, 8, 12];
const LIMITS = { hook: 70, punchline: 55, caption: 40, title: 100 };
const VIEWS = ["queue", "trends", "music", "settings", "youtube", "activity"];
const REGIONS = ["US", "GB", "CA", "AU", "IE", "NZ", "IN", "PH", "SG", "ZA", "DE", "FR", "ES", "BR", "MX", "JP"];

const state = { app: null, videos: [], task: null, watching: null, dirty: new Set() };

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

function paw(cls = "", n = 0) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", `paw ${cls}`.trim());
  svg.setAttribute("aria-hidden", "true");
  svg.style.setProperty("--n", n);
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", "#paw");
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

// The audience is US-centred, so times are also shown for New York next to the viewer's own clock.
const AUDIENCE_TZ = "America/New_York";
const nyTime = date => date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZone: AUDIENCE_TZ });

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const hours = n => `${n} hour${n === 1 ? "" : "s"}`;

/** A moment on the schedule's clock, e.g. 16:00: slots are set in that time zone, not the browser's. */
const clockIn = (iso, tz) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: tz });

/** A video the dashboard shows as "live" once its publish time has passed. */
const shownStatus = v => v.status === "scheduled" && v.publish_at && new Date(v.publish_at) <= new Date() ? "live" : v.status;

// ------------------------------------------------------------------ header

async function loadState() {
  state.app = await api("/api/state");
  renderHeader();
  if (state.app.task && state.watching !== state.app.task.id) watchTask(state.app.task);
}

function renderHeader() {
  const a = state.app;
  const s = a.services;
  $("#channel-name").textContent = a.channel;
  document.title = `${a.channel} · Control room`;

  const chips = [
    ["Gemini", s.gemini ? "" : "bad", null, s.gemini ? "AI writer ready" : "Add GEMINI_API_KEY to .env"],
    ["Pexels", s.pexels ? "" : "bad", null, s.pexels ? "Stock footage ready" : "Add PEXELS_API_KEY to .env"],
    ["Pixabay", s.pixabay ? "" : "off", null, s.pixabay ? "Backup footage ready" : "Optional backup footage"],
    ["YouTube", s.youtube ? "" : "warn", "#youtube", s.youtube ? "Connected" : "Not connected yet"],
    [`Music · ${s.music}`, s.music ? "" : "warn", "#music", s.music ? `${plural(s.music, "track")}` : "No tracks: Shorts are silent"],
    [s.database === "cloud" ? "Database · cloud" : "Database · this PC", "", null, "Where plans and history are kept"],
    ["Telegram", s.telegram ? "" : "off", "#activity", s.telegram ? "Phone alerts on" : "Optional phone alerts"],
  ];
  $("#services").replaceChildren(...chips.map(([label, cls, href, title]) =>
    h("li", {}, h(href ? "a" : "span", { class: `chip ${cls}`.trim(), href, title },
      h("span", { class: "dot", "aria-hidden": "true" }), label))));

  const ap = a.autopilot;
  const sch = ap.schedule;
  const on = !a.paused;
  $("#autopost").checked = on;
  $("#autopost").disabled = !a.local;
  $("#autopost-label").textContent = on ? "Autopilot on" : "Autopilot paused";
  $("#autopost-sub").textContent = !on ? "Nothing posts by itself"
    : ap.here ? `${plural(sch.posts_per_day, "Short")} a day from ${sch.first_post}` : "Runs in the cloud";
  $("#pause-switch").classList.toggle("is-paused", !on);
  $("#pause-switch").title = a.local ? "Turn off to stop all automatic posting (your own buttons keep working)"
                                     : "Change PAUSED in Vercel's environment variables";

  $("#today-date").textContent = new Date(ap.slots[0].at).toLocaleDateString(undefined,
    { weekday: "long", day: "numeric", month: "long", timeZone: sch.timezone });
  $("#next-slot").replaceChildren(...heroLine(a));
  renderLineup();
  $("#events").replaceChildren(...a.events.slice(0, 3).map((e, i) =>
    h("li", { class: "event", style: `--tilt:${i % 2 ? 1.3 : -1.6}deg` },
      e.in_days === 0 ? `${e.name} is today` : `${e.name} in ${plural(e.in_days, "day")}`)));
  syncButtons();
}

function heroLine(a) {
  const ap = a.autopilot;
  const sch = ap.schedule;
  const rhythm = `${plural(sch.posts_per_day, "Short")} a day, one every ${hours(sch.every_hours)} from ${sch.first_post}`;
  if (a.paused) {
    return ["The autopilot is ", h("strong", {}, "paused"), `, so nothing posts by itself. Switch it on (top right) for ${rhythm}.`];
  }
  if (!a.services.youtube) return ["Autopilot is on, but ", h("a", { href: "#youtube" }, "connect YouTube"), " before it can post."];
  const next = ap.next;
  const parts = [`Autopilot is on: ${rhythm}. `];
  if (next) {
    parts.push("Next post ", h("strong", {}, clockIn(next.at, sch.timezone)),
               ` (${fromNow(next.at)}), that's ${nyTime(new Date(next.at))} in New York.`);
  }
  if (!ap.here) parts.push(` It runs in the cloud${ap.last_check ? ` and last checked in ${fromNow(ap.last_check)}` : ""}.`);
  return parts;
}

function renderLineup() {
  const a = state.app;
  const ap = a.autopilot;
  const tz = ap.schedule.timezone;
  const nextAt = ap.next?.at;
  const n = ap.slots.length;
  $("#lineup").style.setProperty("--cols", n <= 6 ? n : Math.ceil(n / 2));  // one row, or two even ones
  $("#lineup").replaceChildren(...ap.slots.map((s, i) => {
    const v = s.video;
    const waiting = ["due", "late"].includes(s.state);
    const label = a.paused && waiting ? "Paused" : SLOT_LABEL[s.state];
    const link = !v?.youtube_id ? null : s.state === "posted" ? `https://youtube.com/shorts/${v.youtube_id}`
                                                               : `https://studio.youtube.com/video/${v.youtube_id}/edit`;
    const tip = v?.title ? `${v.title}${link ? (s.state === "posted" ? " · watch on YouTube" : " · open in YouTube Studio") : ""}` : null;
    return h("li", { style: `--i:${i}` },
      h(link ? "a" : "div", { class: "slot", href: link, target: link && "_blank", rel: link && "noopener", title: tip,
                              dataset: { state: a.paused && waiting ? "paused" : s.state } },
        s.at === nextAt && !a.paused && h("span", { class: "slot-next" }, "next"),
        h("b", { class: "slot-time" }, clockIn(s.at, tz)),
        h("span", { class: "slot-state" }, s.state === "making" && paw("slot-paw"), label),
        v?.title && h("span", { class: "slot-title" }, v.title)));
  }));
}

function syncButtons() {
  const busy = state.task?.status === "running";
  const local = state.app?.local !== false;  // in the cloud the hourly jobs do the work
  const youtube = !!state.app?.services.youtube;
  const nextOpen = state.app?.autopilot.next_open;
  $("#plan-btn").disabled = busy || !local;
  $("#plan-btn").title = !local ? "Runs from the dashboard on your computer" : "";
  const make = $("#make-btn");
  make.disabled = busy || !local || !youtube || !nextOpen;
  make.textContent = nextOpen ? `Make the ${clockIn(nextOpen, state.app.autopilot.schedule.timezone)} Short now`
                              : "Make the next Short now";
  make.title = !local ? "Runs from the dashboard on your computer" : !youtube ? "Connect YouTube first"
             : "Plans (or takes the oldest planned Short), renders and uploads it for that slot";
  $("#stats-btn").disabled = busy || !local;
  for (const b of $$("[data-needs-idle]")) b.disabled = busy || !local || b.dataset.blocked === "1";
}

// ------------------------------------------------------------------ tasks

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
  await loadState().catch(() => {});
  const view = currentView();
  if (view === "queue") loadQueue().catch(() => {});
  if (view === "youtube") loadYouTube().catch(() => {});
  if (view === "activity") loadActivity().catch(() => {});
}

function renderTask() {
  const t = state.task;
  const box = $("#task");
  if (!t) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.className = `task ${t.status}`;
  const title = t.status === "running" ? `${t.label}…` : t.status === "done" ? `${t.label}: done` : `${t.label}: didn't work`;
  box.replaceChildren(
    h("div", { class: "task-head" },
      t.status === "running"
        ? h("div", { class: "trail" }, [0, 1, 2, 3, 4].map(i => paw("", i)))
        : h("span", { class: "task-icon", "aria-hidden": "true" }, t.status === "done" ? "✓" : "!"),
      h("p", { class: "task-title" }, title),
      t.status !== "running" && h("button", { class: "btn btn-sm btn-ghost", type: "button",
        onclick: () => { state.task = null; renderTask(); } }, "Dismiss")),
    t.steps.length > 0 && h("ol", { class: "task-steps" }, t.steps.map(s =>
      h("li", {}, h("span", { class: "t" }, `${Math.round(s.at)}s`), h("span", {}, s.text)))),
    t.error && h("p", { class: "task-error" }, t.error));
}

// ------------------------------------------------------------------ queue

async function loadQueue() {
  state.videos = await api("/api/videos");
  renderQueue();
}

function renderQueue() {
  const root = $("#queue");
  if (!state.videos.length) {
    root.replaceChildren(h("div", { class: "empty" }, paw(),
      h("h3", {}, "No Shorts yet"),
      h("p", {}, "Press “Plan a new Short”. The planner reads today’s trends, finds free stock clips, checks them and writes the captions.")));
    return;
  }
  const coming = v => v.status === "making" || shownStatus(v) === "scheduled";
  const groups = [
    ["Planned", v => v.status === "planned",
      "The autopilot posts these first, oldest first. Watch the preview and tweak the words before their turn, "
      + "or upload one yourself into the next free slot."],
    ["Coming up", coming,
      "Uploaded as private. Each goes public at its slot; delete it in YouTube Studio before then to veto it."],
    ["History", v => v.status !== "planned" && !coming(v), null],
  ];
  let index = 0;
  root.replaceChildren(...groups.flatMap(([title, test, sub]) => {
    const items = state.videos.filter(test);
    if (!items.length) return [];
    const heading = h("h3", { class: "group-title" }, title, h("span", { class: "count" }, items.length));
    const list = h("div", { class: "cards" }, items.map(v => card(v, index++)));
    if (!sub) return [h("details", { class: "history" }, h("summary", {}, heading), list)];
    return [heading, h("p", { class: "group-sub" }, sub), list];
  }));
  syncButtons();
}

function card(v, i) {
  const editable = v.status === "planned";
  const el = h("article", { class: "card", style: `--i:${Math.min(i, 6)}`, dataset: { id: v.id } });
  const screen = h("div", { class: "phone-screen" });
  el.append(
    h("div", { class: "phone" }, h("span", { class: "phone-notch", "aria-hidden": "true" }), screen),
    h("div", { class: "card-body" },
      h("div", { class: "card-head" },
        h("span", { class: "sticker", dataset: { format: v.format } }, FORMAT_LABEL[v.format] || v.format),
        h("span", { class: "status", dataset: { status: shownStatus(v) } }, STATUS_LABEL[shownStatus(v)] || v.status),
        h("span", { class: "meta" }, `#${v.id}${v.duration ? ` · ${v.duration.toFixed(1)}s` : ""}`)),
      h("h3", { class: "theme" }, v.theme || { making: "A new Short", skipped: "Not made" }[v.status] || "Untitled"),
      v.angle && h("p", { class: "angle" }, v.angle),
      v.trend && h("p", { class: "trend-tag" }, paw(), `Rides on ${v.trend}`),
      v.status === "making" && v.slot && h("div", { class: "box" }, "Being made for the ",
        h("strong", {}, clockIn(v.slot, state.app.autopilot.schedule.timezone)), " slot right now."),
      v.status === "scheduled" && scheduledBox(v),
      v.error && h("div", { class: "box box-error" }, v.error),
      editable ? editor(v, el) : readOnly(v),
      clipStrip(v),
      editable && actions(v, el)));
  drawScreen(screen, v, el);
  return el;
}

function scheduledBox(v) {
  const live = v.publish_at && new Date(v.publish_at) <= new Date();
  return h("div", { class: "box box-ok" },
    live ? "Public since " : "Goes public ", h("strong", {}, fmtWhen(v.publish_at)),
    live ? "" : ` (${fromNow(v.publish_at)})`, ". ",
    h("a", { href: v.studio_url, target: "_blank", rel: "noopener" }, "Open in YouTube Studio ↗"),
    live && v.youtube_id ? [" · ", h("a", { href: `https://youtube.com/shorts/${v.youtube_id}`, target: "_blank",
                                         rel: "noopener" }, "Watch ↗")] : null);
}

/** What the captions say right now: the edit fields if the card has them, else the saved text. */
function captionText(v, cardEl) {
  const field = name => cardEl && $(`[name="${name}"]`, cardEl);
  const read = (name, fallback) => (field(name) ? field(name).value : fallback) || "";
  const captions = v.metadata.captions || [];
  return {
    hook: read("hook", v.metadata.hook),
    bottom: v.format === "punchline" ? read("punchline", v.metadata.punchline)
          : v.format === "top3" ? (k => k ? `3. ${k}` : "#3")(read("caption0", captions[0])) : "",
  };
}

function drawScreen(screen, v, cardEl) {
  const dirty = state.dirty.has(v.id);
  if (v.preview && !dirty) {
    screen.dataset.mode = "video";
    screen.replaceChildren(h("video", { src: v.preview, controls: true, playsinline: true, loop: true,
                                        preload: "metadata", poster: v.clips[0]?.thumb }));
    return;
  }
  const text = captionText(v, cardEl);
  screen.dataset.mode = "live";
  screen.replaceChildren(
    v.clips[0]?.thumb ? h("img", { class: "poster", src: v.clips[0].thumb, alt: "" }) : h("div", { class: "phone-blank" }),
    h("p", { class: "cap cap-top" }, text.hook),
    h("p", { class: "cap cap-bottom" }, text.bottom),
    v.status === "planned" && h("span", { class: `phone-badge${dirty ? " live" : ""}` },
      dirty ? "Live preview of your edits" : "Not rendered yet"),
    v.status === "making" && h("span", { class: "phone-badge" }, "Being made…"));
}

function editor(v, cardEl) {
  const m = v.metadata;
  const onEdit = () => {
    state.dirty.add(v.id);
    cardEl.classList.add("is-dirty");
    const screen = $(".phone-screen", cardEl);
    if (screen.dataset.mode !== "live" || !$(".phone-badge.live", screen)) return drawScreen(screen, v, cardEl);
    const text = captionText(v, cardEl);
    $(".cap-top", screen).textContent = text.hook;
    $(".cap-bottom", screen).textContent = text.bottom;
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
    field("description", "Description", m.description, null, { multiline: true })));
  return h("div", { class: "fields" }, fields);
}

function readOnly(v) {
  if (!v.metadata.title) return null;  // still being planned
  return h("div", { class: "fields" },
    h("p", { class: "readonly-title" }, v.metadata.title),
    h("details", { class: "more" }, h("summary", {}, "Description, credits & hashtags"),
      h("p", { class: "desc-ro" }, v.metadata.description)));
}

function clipStrip(v) {
  if (!v.clips.length) return null;
  const site = { pexels: "Pexels", pixabay: "Pixabay" };
  return h("div", { class: "clips" }, v.clips.map(c => h("div", { class: "clip" },
    c.thumb ? h("img", { src: c.thumb, alt: "", loading: "lazy" }) : h("img", { alt: "" }),
    h("div", {},
      h("p", {}, c.score !== null && c.score !== undefined && h("span", { class: "score", title: "Clip check score" }, `${c.score}/10`),
        c.what || "Stock clip"),
      h("p", { class: "credit" }, "by ", h("a", { href: c.page_url, target: "_blank", rel: "noopener" }, c.credit_name),
        ` on ${site[c.source] || c.source}`)))));
}

function actions(v, cardEl) {
  const s = state.app?.services || {};
  const nextOpen = state.app?.autopilot.next_open;
  const blocked = !s.youtube || !nextOpen;
  return h("div", { class: "card-actions" },
    h("button", { class: "btn btn-sm btn-save", type: "button", onclick: () => saveEdits(v, cardEl) }, "Save changes"),
    h("button", { class: "btn btn-sm", type: "button", "data-needs-idle": true, onclick: () => renderPreview(v) },
      v.preview ? "Re-render preview" : "Render preview"),
    h("button", { class: "btn btn-sm btn-primary", type: "button", "data-needs-idle": true,
      dataset: { blocked: blocked ? "1" : "0" },
      title: !s.youtube ? "Connect YouTube first" : !nextOpen ? "No free slot in the next week"
           : `Uploads as private, scheduled for the next free slot (${clockIn(nextOpen, state.app.autopilot.schedule.timezone)})`,
      onclick: () => upload(v) }, "Upload & schedule"),
    h("span", { class: "spacer" }),
    !s.youtube && h("a", { class: "note", href: "#youtube" }, "Connect YouTube to upload"),
    h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => discard(v) }, "Discard"));
}

function readEdits(v, cardEl) {
  const val = name => $(`[name="${name}"]`, cardEl)?.value ?? "";
  const edits = { hook: val("hook"), title: val("title"), description: val("description") };
  if (v.format === "punchline") edits.punchline = val("punchline");
  if (v.format === "top3") edits.captions = [0, 1, 2].map(k => val(`caption${k}`));
  return edits;
}

async function saveEdits(v, cardEl) {
  try {
    const updated = await api(`/api/videos/${v.id}`, { method: "PATCH", json: readEdits(v, cardEl) });
    state.dirty.delete(v.id);
    replaceCard(updated);
    toast("Saved. Render a new preview to see the change on the video.", "ok");
  } catch (e) {
    toast(e.message, "error", 7000);
  }
}

function replaceCard(v) {
  const i = state.videos.findIndex(x => x.id === v.id);
  if (i >= 0) state.videos[i] = v;
  const old = $(`.card[data-id="${v.id}"]`);
  if (!old) return;
  const fresh = card(v, 0);
  fresh.style.animation = "none";
  old.replaceWith(fresh);
  syncButtons();
}

function renderPreview(v) {
  if (state.dirty.has(v.id)) return toast("Save your changes first, then render.", "error");
  runTask("render", v.id);
}

function upload(v) {
  if (state.dirty.has(v.id)) return toast("Save your changes first.", "error");
  const slot = state.app?.autopilot.next_open;
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
    loadQueue();
    loadState();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ------------------------------------------------------------------ trends

/** Where a trend comes from: "14 countries" (hover to list them), or the one country. */
function whereFrom(countries) {
  if (!countries?.length) return null;
  return h("small", { title: countries.join(", ") }, countries.length > 1 ? `${countries.length} countries` : countries[0]);
}

async function loadTrends(refresh = false) {
  const root = $("#trends-body");
  root.replaceChildren(h("p", { class: "loading" }, refresh
    ? "Asking for today’s trends again. Worldwide that’s every country, so it can take a minute…"
    : "Reading today’s trends…"));
  const t = await api(`/api/trends${refresh ? "?refresh=1" : ""}`);
  const world = t.region === "ALL";
  const tilt = [-2, 1.5, -1, 2.2];
  root.replaceChildren(
    h("div", { class: "panel", style: "--i:0" },
      h("h3", {}, "Coming up"),
      h("p", { class: "sub" }, "Pet days and holidays. The planner themes Shorts around them a few days early."),
      t.events.length
        ? h("div", { class: "countdowns" }, t.events.map((e, i) =>
            h("div", { class: "countdown", style: `--tilt:${tilt[i % 4]}deg` },
              h("b", {}, e.in_days === 0 ? "Today" : e.in_days),
              h("span", {}, e.in_days === 0 ? e.name : `${e.in_days === 1 ? "day" : "days"} to ${e.name}`))))
        : h("p", { class: "note" }, "Nothing in the next 10 days.")),
    h("div", { class: "grid-2" },
      h("div", { class: "panel", style: "--i:1" },
        h("h3", {}, "Today’s mood"),
        h("p", { class: "sub" }, "Everyday hooks the planner can lean on."),
        h("div", { class: "mood" },
          t.season && h("span", { class: "sticker" }, t.season),
          t.weekday_vibe && h("span", { class: "sticker" }, t.weekday_vibe),
          h("span", { class: "sticker", style: "background:var(--card)" }, t.weekday))),
      h("div", { class: "panel", style: "--i:2" },
        h("h3", {}, world ? "Trending searches · worldwide" : `Trending searches · ${t.region}`),
        h("p", { class: "sub" }, world
          ? `From ${t.countries} countries, the most widespread first. Used only when they fit cute animals; news, sport and celebrities are skipped.`
          : "Used only when they fit cute animals. News, sport and celebrities are skipped."),
        t.google_trends.length
          ? h("div", { class: "pills" }, t.google_trends.map(g =>
              h("span", { class: "pill" }, g.term, world ? whereFrom(g.countries) : g.traffic && h("small", {}, g.traffic))))
          : h("p", { class: "note" }, "Google Trends didn't answer this time."))),
    h("div", { class: "panel", style: "--i:3" },
      h("h3", {}, world ? "Popular animal videos worldwide" : "Popular animal videos on YouTube"),
      h("p", { class: "sub" }, world ? "YouTube’s Pets & Animals charts from every country, the most widespread first."
                                     : "What’s doing well in Pets & Animals right now."),
      t.youtube_popular.length
        ? h("ul", { class: "list-plain" }, t.youtube_popular.slice(0, 12).map(p =>
            h("li", {}, p.title, p.views ? h("small", {}, ` · ${p.views.toLocaleString()} views`) : null,
              world && p.countries?.length > 1 ? h("small", { title: p.countries.join(", ") }, ` · ${p.countries.length} countries`) : null)))
        : h("p", { class: "note" }, state.app?.services.youtube ? "Nothing came back this time."
                                    : ["Connect YouTube to see these. ", h("a", { href: "#youtube" }, "How →")])),
    h("p", { class: "note" }, t.fetched_at ? `Fetched ${fromNow(t.fetched_at)}. The planner reuses these for up to 6 hours. ` : "",
      t.errors.length ? `Notes: ${t.errors.join(" · ")}` : ""));
}

// ------------------------------------------------------------------ music

async function loadMusic() {
  const tracks = await api("/api/music");
  $("#music-empty").hidden = tracks.length > 0;
  $("#tracks").replaceChildren(...tracks.map(t => h("li", { class: "track" },
    h("span", { class: "track-icon", "aria-hidden": "true" }, "♪"),
    h("div", { class: "track-name" }, h("b", { title: t.name }, t.name), h("small", {}, `${(t.size / 1e6).toFixed(1)} MB`)),
    h("audio", { src: t.url, controls: true, preload: "none" }),
    h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", onclick: () => removeTrack(t) }, "Remove"))));
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
  await loadMusic();
  loadState();
}

async function removeTrack(t) {
  if (!confirm(`Remove ${t.name}?`)) return;
  try {
    await api(`/api/music/${encodeURIComponent(t.name)}`, { method: "DELETE" });
    await loadMusic();
    loadState();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ------------------------------------------------------------------ settings

async function loadSettings() {
  const s = await api("/api/settings");
  const form = $("#settings-form");
  const ro = !s.editable;
  const text = (name, label, value, hint) => h("div", { class: "field" },
    h("label", { for: `s-${name}` }, label),
    h("input", { class: "input", id: `s-${name}`, name, value: value ?? "", disabled: ro }),
    hint && h("p", { class: "hint" }, hint));
  const range = (name, label, value, min, max, step, hint) => {
    const out = h("output", {}, value);
    const input = h("input", { type: "range", id: `s-${name}`, name, min, max, step, value, disabled: ro,
      oninput: e => { out.textContent = e.target.value; } });
    return h("div", { class: "field" }, h("label", { for: `s-${name}` }, label),
      h("div", { class: "range-row" }, input, out), hint && h("p", { class: "hint" }, hint));
  };
  const sch = s.schedule;
  const preview = h("div", { class: "slot-preview", "aria-live": "polite" });
  const showSlots = () => preview.replaceChildren(...slotPreview($("#s-first_post", form).value,
    Number($("#s-every_hours", form).value), Number($("#s-posts_per_day", form).value)));
  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zones = [...new Set([sch.timezone, browserZone, ...TIMEZONES])];
  const select = (name, label, options) => h("div", { class: "field" },
    h("label", { for: `s-${name}` }, label),
    h("select", { class: "input", id: `s-${name}`, name, disabled: ro, onchange: showSlots },
      options.map(([value, text]) => h("option", { value, selected: String(value) === String(sch[name]) }, text))));

  form.replaceChildren(
    h("div", { class: "panel", style: "--i:0" },
      h("h3", {}, "Channel"),
      text("name", "Channel name", s.channel.name),
      text("contact_email", "Public contact email (optional)", s.channel.contact_email,
        h("span", {}, "Shown on your public ", h("a", { href: "/about", target: "_blank" }, "About"), " and ",
          h("a", { href: "/privacy", target: "_blank" }, "Privacy"), " pages, which Google asks for.")),
      text("audience", "Who it's for", s.channel.audience),
      h("div", { class: "field" }, h("label", { for: "s-voice" }, "Humour and voice"),
        h("textarea", { class: "input", id: "s-voice", name: "voice", rows: 4, disabled: ro, value: s.channel.voice }),
        h("p", { class: "hint" }, "The writer follows this for every caption and title."))),
    h("div", { class: "panel", style: "--i:1" },
      h("h3", {}, "Posting"),
      h("div", { class: "times" },
        h("div", { class: "field" }, h("label", { for: "s-first_post" }, "First post of the day"),
          h("input", { class: "input", type: "time", id: "s-first_post", name: "first_post", value: sch.first_post,
                       disabled: ro, oninput: showSlots })),
        select("every_hours", "Then one every", EVERY_HOURS.map(n => [n, hours(n)])),
        h("div", { class: "field" }, h("label", { for: "s-posts_per_day" }, "Shorts a day"),
          h("input", { class: "input", type: "number", id: "s-posts_per_day", name: "posts_per_day", min: 1, max: 12,
                       value: sch.posts_per_day, disabled: ro, oninput: showSlots })),
        select("timezone", "On the clock of", zones.map(z => [z, z === browserZone ? `${z} (this device)` : z]))),
      preview,
      h("p", { class: "hint" }, "Each Short is made in the two hours before its time and goes public on the minute. "
        + "Up to 12 a day fit Vercel's free plan."),
      text("rotation", "Format rotation", s.formats.rotation.join(", "),
        `In order, one per Short. Choose from: ${s.formats_available.join(", ")}.`),
      text("hashtags", "Hashtags on every Short", s.metadata.base_hashtags.join(" "), "Up to 4, like #shorts #cuteanimals."),
      range("volume", "Music volume", s.music.volume, 0, 1.5, 0.05)),
    h("div", { class: "panel wide", style: "--i:2" },
      h("h3", {}, "Content rules"),
      h("div", { class: "field" }, h("label", { for: "s-animals" }, "Animals the planner may choose"),
        h("textarea", { class: "input compact", id: "s-animals", name: "animals", rows: 2, disabled: ro,
                        value: s.content.animals.join(", ") }),
        h("p", { class: "hint" }, "Comma-separated.")),
      h("div", { class: "grid-2" },
        range("score", "Minimum clip score", s.content.min_check_score, 0, 10, 1,
          "Clips the checker scores below this are skipped."),
        range("seconds", "Longest Short (seconds)", s.content.max_short_seconds, 10, 60, 1)),
      h("div", { class: "field" }, h("label", { for: "s-region" }, "Trends from"),
        h("select", { class: "input", id: "s-region", name: "region", disabled: ro },
          [...new Set(["ALL", s.trends.region, ...REGIONS])].map(r =>
            h("option", { value: r, selected: r === s.trends.region }, r === "ALL" ? "All countries (worldwide)" : r))),
        h("p", { class: "hint" }, "Worldwide asks every country and puts the trends shared by the most countries first.")),
      h("label", { class: "check" },
        h("input", { type: "checkbox", name: "allow_people", checked: s.content.allow_people, disabled: ro }),
        h("span", {}, "Allow adults in clips. Children are always rejected, whatever this says."))),
    h("div", { class: "savebar wide" },
      h("p", { class: "note" }, ro ? "Settings can only be changed on your computer." : "Changes apply to the next Short."),
      h("button", { class: "btn btn-primary", type: "submit", disabled: ro }, "Save settings")));
  showSlots();
}

/** The day's posting times for the settings preview, as chips; times after midnight are marked. */
function slotPreview(first, every, count) {
  if (!/^\d\d:\d\d$/.test(first || "") || !every || !(count >= 1 && count <= 12)) {
    return [h("p", { class: "hint" }, "Pick a first post time, a gap and 1 to 12 Shorts a day.")];
  }
  if ((count - 1) * every >= 24) return [h("p", { class: "hint warn" }, `${count} Shorts ${hours(every)} apart don't fit in a day.`)];
  const [hh, mm] = first.split(":").map(Number);
  return Array.from({ length: count }, (_, k) => {
    const minutes = hh * 60 + mm + Math.round(k * every * 60);
    const clock = `${String(Math.floor(minutes / 60) % 24).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
    return h("span", { class: "pill" }, clock, minutes >= 1440 && h("small", {}, "next day"));
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

// ------------------------------------------------------------------ YouTube

async function loadYouTube(refresh = false) {
  const root = $("#youtube-body");
  const y = await api(`/api/youtube${refresh ? "?refresh=1" : ""}`);
  const connecting = state.task?.kind === "connect" && state.task.status === "running";
  const fileInput = h("input", { type: "file", accept: ".json,application/json", hidden: true,
                                 onchange: e => e.target.files[0] && saveClientFile(e.target.files[0]) });
  root.replaceChildren(
    h("div", { class: "panel why", style: "--i:0" },
      h("h3", {}, "Why does this need a Google Cloud project?"),
      h("ul", {},
        h("li", {}, "YouTube only lets software upload through its official API, and every app using it must be registered in Google Cloud. That registration is the “project”."),
        h("li", {}, "It’s free: no billing, no card. YouTube uploads don’t cost anything."),
        h("li", {}, "The project gives you an OAuth client file. With it, you sign in once and allow this app to upload to your channel. Your Google password never touches this software."),
        h("li", {}, "You can revoke access any time at ", h("a", { href: "https://myaccount.google.com/permissions", target: "_blank", rel: "noopener" }, "myaccount.google.com/permissions"), "."))),
    h("div", { class: "steps" },
      h("div", { class: `step${y.client_file || y.connected ? " done" : ""}`, style: "--i:1" },
        h("h3", {}, "Create the project (about 10 minutes)"),
        h("ol", {},
          h("li", {}, "Open ", h("a", { href: "https://console.cloud.google.com/projectcreate", target: "_blank", rel: "noopener" }, "Google Cloud: new project"), " with the Google account that owns your channel. Any name works."),
          h("li", {}, h("b", {}, "APIs & Services → Library"), ": enable ", h("b", {}, "YouTube Data API v3"), " and ", h("b", {}, "YouTube Analytics API"), "."),
          h("li", {}, h("b", {}, "Google Auth Platform → Branding"), ": app name, support email and developer email. Skip the logo (uploading one forces Google’s verification review)."),
          h("li", {}, h("b", {}, "Audience"), ": choose ", h("b", {}, "External"), " and add your own Gmail under ", h("b", {}, "Test users"), ". Leave it in ", h("b", {}, "Testing"), " for now: it works today, but the sign-in lasts 7 days (press Reconnect below). To make it permanent later, put your site’s ",
            h("a", { href: "/about", target: "_blank" }, "/about"), " and ", h("a", { href: "/privacy", target: "_blank" }, "/privacy"), " links (once it’s on Vercel) into Branding and press ", h("b", {}, "Publish app"), "."),
          h("li", {}, h("b", {}, "Clients → Create client → Desktop app"), ", then download its JSON file."))),
      h("div", { class: `step${y.client_file ? " done" : ""}`, style: "--i:2" },
        h("h3", {}, "Add the OAuth client file"),
        h("p", {}, y.client_file ? "Client file saved (credentials.json). You can replace it if needed."
                                 : "Choose the JSON file you just downloaded. It stays on this computer."),
        h("div", { class: "row" }, fileInput,
          h("button", { class: "btn btn-sm", type: "button", disabled: !y.local, onclick: () => fileInput.click() },
            y.client_file ? "Replace client file" : "Choose client file"))),
      h("div", { class: `step${y.connected && !y.error ? " done" : ""}`, style: "--i:3" },
        h("h3", {}, "Connect your channel"),
        y.connected
          ? (y.error ? h("div", { class: "box box-error" }, `Saved sign-in didn't work: ${y.error}`)
                     : h("p", {}, "Connected to ", h("b", {}, y.channel || "your channel"), ". Uploads and stats are ready."))
          : h("p", {}, "A Google page opens in your browser: choose your channel and allow access."),
        h("div", { class: "row" },
          h("button", { class: "btn btn-primary", type: "button", disabled: !y.client_file || !y.local || connecting,
                        onclick: () => runTask("connect") },
            connecting ? "Waiting for you in the browser…" : y.connected ? "Reconnect" : "Connect YouTube"),
          !y.local && h("p", { class: "note" }, "Connect from the dashboard on your computer.")))));
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

// ------------------------------------------------------------------ activity

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

async function loadActivity() {
  const a = await api("/api/activity");
  $("#activity-body").replaceChildren(
    h("div", { class: "panel", style: "--i:0" },
      h("h3", {}, "Job runs"),
      h("p", { class: "sub" }, "Every Short the autopilot made, the cloud's daily stats, and the buttons you press here."),
      a.runs.length
        ? h("ul", { class: "log" }, a.runs.map(r => h("li", {},
            h("span", { class: "when" }, fmtWhen(r.started_at)),
            h("span", { class: `badge${r.ok === 0 ? " fail" : r.ok === null ? " run" : ""}` },
              r.job, r.ok === 0 ? " · failed" : ""),
            h("span", { class: "what" }, runSummary(r)))))
        : h("p", { class: "note" }, "Nothing has run yet.")),
    h("div", { class: "grid-2" },
      h("div", { class: "panel", style: "--i:1" },
        h("h3", {}, "Alerts"),
        h("p", { class: "sub" }, a.telegram ? "Also sent to your phone through Telegram." : "Shown here; add Telegram to get them on your phone."),
        a.alerts.length
          ? h("ul", { class: "list-plain" }, a.alerts.map(n =>
              h("li", {}, h("small", {}, `${fmtWhen(n.at)}${n.sent ? " · sent" : ""} `), h("div", {}, n.text))))
          : h("p", { class: "note" }, "No alerts since the server started.")),
      h("div", { class: "panel", style: "--i:2" },
        h("h3", {}, "Phone alerts"),
        a.telegram
          ? h("p", { class: "sub" }, "Telegram is set up. Send yourself a test.")
          : h("p", { class: "sub" }, "Optional: create a bot with @BotFather, then add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env and restart."),
        h("button", { class: "btn btn-sm", type: "button", disabled: !a.telegram, onclick: async () => {
          try { await api("/api/notify/test", { method: "POST" }); toast("Sent. Check Telegram.", "ok"); }
          catch (e) { toast(e.message, "error", 7000); }
        } }, "Send test message"))));
}

// ------------------------------------------------------------------ routing

const loaders = { queue: loadQueue, trends: loadTrends, music: loadMusic, settings: loadSettings,
                  youtube: loadYouTube, activity: loadActivity };

function currentView() {
  const view = location.hash.slice(1);
  return VIEWS.includes(view) ? view : "queue";
}

async function route() {
  const view = currentView();
  for (const v of VIEWS) $(`#view-${v}`).hidden = v !== view;
  for (const a of $$(".tabs a")) {
    a.classList.toggle("active", a.dataset.view === view);
    if (a.dataset.view === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  try {
    await loadState();
    await loaders[view]();
  } catch (e) {
    toast(e.message, "error", 7000);
  }
}

function init() {
  $("#plan-btn").addEventListener("click", () => runTask("prepare"));
  $("#make-btn").addEventListener("click", () => {
    const slot = state.app?.autopilot.next_open;
    const when = slot ? `${clockIn(slot, state.app.autopilot.schedule.timezone)} (${fromNow(slot)})` : "the next free slot";
    if (confirm(`Make a Short for ${when} now?\n\nIt uses the oldest planned Short (or plans a new one), renders it `
                + "and uploads it as private. YouTube makes it public at that time.")) runTask("autopilot");
  });
  $("#stats-btn").addEventListener("click", () => runTask("stats"));
  $("#trends-refresh").addEventListener("click", () => loadTrends(true).catch(e => toast(e.message, "error")));
  $("#youtube-refresh").addEventListener("click", () => loadYouTube(true).catch(e => toast(e.message, "error")));
  $("#settings-form").addEventListener("submit", saveSettings);

  $("#autopost").addEventListener("change", async e => {
    try {
      await api("/api/pause", { method: "POST", json: { paused: !e.target.checked } });
      toast(e.target.checked ? "Autopilot on. It makes the next Short when its slot is due."
                             : "Autopilot paused. Nothing posts by itself; your own buttons still work.", "ok");
    } catch (err) {
      e.target.checked = !e.target.checked;
      toast(err.message, "error");
    }
    loadState();
    if (currentView() === "queue") renderQueue();
  });

  const zone = $("#dropzone");
  $("#music-input").addEventListener("change", e => addTracks([...e.target.files]));
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("over");
    addTracks([...e.dataTransfer.files]);
  });

  // Keep the line-up current and notice when the autopilot starts a Short by itself.
  setInterval(() => {
    if (!document.hidden && !state.watching) loadState().catch(() => {});
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
