// Reviewer dashboard: plain JavaScript over the detector's JSON API.
// Every value from the API is shown with textContent, never parsed as HTML.
"use strict";

const state = {
  apiKey: readSession("riskdetect-api-key"),
  tiers: { watch_from: 0.3, review_from: 0.6, high_from: 0.85 },
  platform: "",
  queue: [],
  current: null, // { platform, actor_id }
  history: [],
};

const $ = (id) => document.getElementById(id);

// -- storage that may be unavailable (private windows, blocked site data) -----------

function readSession(key) {
  try { return sessionStorage.getItem(key) || ""; } catch { return ""; }
}
function writeSession(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* not kept; fine */ }
}
function readLocal(key) {
  try { return localStorage.getItem(key) || ""; } catch { return ""; }
}
function writeLocal(key, value) {
  try { localStorage.setItem(key, value); } catch { /* not kept; fine */ }
}

// -- API ------------------------------------------------------------------------------

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json" };
  if (state.apiKey) headers["X-API-Key"] = state.apiKey;
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  let data = {};
  try { data = await response.json(); } catch { /* empty or not JSON */ }
  if (!response.ok) {
    throw new ApiError(response.status, data.error || `request failed (${response.status})`);
  }
  return data;
}

const enc = encodeURIComponent;
const actorPath = (platform, actor) => `/actors/${enc(platform)}/${enc(actor)}`;

// -- small helpers ----------------------------------------------------------------------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function tierBadge(tier) {
  return el("span", `tier ${tier}`, tier);
}

const fmtScore = (score) => score.toFixed(2);
const fmtDate = (iso) => new Date(iso).toISOString().slice(0, 10);
const fmtDateTime = (iso) => new Date(iso).toISOString().replace("T", " ").slice(0, 16) + " UTC";
const ACTION_WORDS = {
  monitor: "keep an eye on them",
  send_to_review: "a person reviews",
  rate_limit: "slow their posting",
  hold_new_content: "hold new posts until reviewed",
};

let toastTimer = 0;
function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 3500);
}

function handleError(error) {
  if (error instanceof ApiError && error.status === 401) {
    toast("This server needs an API key.");
    openKeyDialog();
    return;
  }
  toast(error.message || "Something went wrong.");
}

// -- header: health and platforms --------------------------------------------------------

async function loadStatus() {
  const health = $("health");
  try {
    const status = await api("/health");
    if (status.tiers) state.tiers = status.tiers;
    health.textContent = `Running · ${status.models.length} models`;
    health.className = "health ok";
    const { platforms } = await api("/platforms");
    const select = $("platform");
    const keep = select.value;
    select.replaceChildren(el("option", "", "All platforms"));
    select.firstChild.value = "";
    for (const p of platforms) {
      const option = el("option", "", `${p.platform} (${p.users_tracked.toLocaleString()} users)`);
      option.value = p.platform;
      select.append(option);
    }
    select.value = keep;
    return true;
  } catch (error) {
    health.textContent = error.status === 401 ? "Needs API key" : "Not reachable";
    health.className = "health bad";
    if (error.status === 401) openKeyDialog();
    return false;
  }
}

// -- queue ----------------------------------------------------------------------------------

async function loadQueue() {
  const query = new URLSearchParams({ limit: "200" });
  if (state.platform) query.set("platform", state.platform);
  try {
    const data = await api(`/review-queue?${query}`);
    state.queue = data.items;
    $("queue-count").textContent =
      data.count > data.items.length
        ? `${data.items.length} of ${data.count.toLocaleString()}`
        : `${data.count.toLocaleString()}`;
    renderQueue();
  } catch (error) {
    handleError(error);
  }
}

// Rules read as plain sentences, so a rule's reason leads when there is one.
function mainReason(reasons) {
  const rule = reasons.find((r) => /^R\d/.test(r.code));
  return (rule || reasons[0] || { text: "No reason given" }).text;
}

function sortedReasons(reasons) {
  const isRule = (r) => (/^R\d/.test(r.code) ? 0 : 1);
  return [...reasons].sort((a, b) => isRule(a) - isRule(b));
}

function renderQueue() {
  const list = $("queue-list");
  list.replaceChildren();
  $("queue-empty").hidden = state.queue.length > 0;
  for (const item of state.queue) {
    const button = el("button", "queue-item");
    button.type = "button";
    const selected =
      state.current &&
      state.current.platform === item.platform &&
      state.current.actor_id === item.actor_id;
    button.setAttribute("aria-current", selected ? "true" : "false");
    button.append(el("span", "who", item.actor_id), el("span", "num", fmtScore(item.score)));
    const meta = el("span", "meta");
    meta.append(tierBadge(item.tier), el("span", "", item.platform));
    const why = el("span", "why", mainReason(item.reasons));
    button.append(meta, why);
    button.addEventListener("click", () => openActor(item.platform, item.actor_id));
    const row = el("li");
    row.append(button);
    list.append(row);
  }
}

// -- one user -------------------------------------------------------------------------------

async function openActor(platform, actorId) {
  state.current = { platform, actor_id: actorId };
  // Each user page has its own link: /#<platform>/<user>
  const hash = `#${enc(platform)}/${enc(actorId)}`;
  if (location.hash !== hash) history.replaceState(null, "", hash);
  renderQueue();
  try {
    const [risk, history] = await Promise.all([
      api(`${actorPath(platform, actorId)}/risk`),
      api(`${actorPath(platform, actorId)}/history`).catch((error) => {
        if (error.status === 404) return { scores: [], source: null };
        throw error;
      }),
    ]);
    renderDetail(risk, history);
    if (window.matchMedia("(max-width: 820px)").matches) {
      $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    handleError(error);
  }
}

function renderDetail(risk, history) {
  $("detail-empty").hidden = true;
  $("detail-body").hidden = false;
  $("d-platform").textContent = risk.platform;
  $("d-actor").textContent = risk.actor_id;
  $("d-score").textContent = fmtScore(risk.score);
  $("d-tier").replaceWith(Object.assign(tierBadge(risk.tier), { id: "d-tier" }));
  $("d-confidence").textContent = `${risk.confidence} confidence`;
  $("d-asof").textContent = fmtDateTime(risk.as_of);
  const actions = risk.recommended_actions.map((a) => ACTION_WORDS[a] || a);
  $("d-actions").textContent = actions.length ? actions.join(", ") : "nothing";

  const reasons = $("d-reasons");
  reasons.replaceChildren();
  if (!risk.reasons.length) reasons.append(el("li", "muted", "Nothing unusual found."));
  for (const reason of sortedReasons(risk.reasons)) {
    const item = el("li", "", reason.text);
    item.append(el("span", "code", reason.code));
    reasons.append(item);
  }

  state.history = history.scores;
  $("chart-note").textContent =
    history.source === "daily"
      ? "From the daily scoring runs."
      : history.source === "live"
        ? "From live scoring, each time the user acted."
        : "No score history recorded yet.";
  drawChart();
  fillTable();
  $("note").value = "";
}

// -- chart: one line, tier thresholds as reference lines ---------------------------------

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs, className) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (className) node.setAttribute("class", className);
  return node;
}

function drawChart() {
  const box = $("chart");
  box.replaceChildren();
  const points = state.history.map((h) => ({ t: new Date(h.as_of).getTime(), ...h }));
  if (!points.length) return;

  const width = box.clientWidth || 600;
  const height = box.clientHeight || 220;
  const m = { top: 10, right: 58, bottom: 24, left: 34 };
  const w = width - m.left - m.right;
  const h = height - m.top - m.bottom;
  const t0 = points[0].t;
  const t1 = Math.max(points[points.length - 1].t, t0 + 1);
  const x = (t) => m.left + ((t - t0) / (t1 - t0)) * w;
  const y = (s) => m.top + (1 - s) * h;

  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none" });
  for (const s of [0, 0.5, 1]) {
    root.append(svg("line", { x1: m.left, x2: m.left + w, y1: y(s), y2: y(s) }, s === 0 ? "axis" : "grid"));
    const label = svg("text", { x: m.left - 6, y: y(s) + 4, "text-anchor": "end" }, "tick");
    label.textContent = s.toFixed(1);
    root.append(label);
  }
  const lines = [
    [state.tiers.watch_from, "WATCH"],
    [state.tiers.review_from, "REVIEW"],
    [state.tiers.high_from, "HIGH"],
  ];
  for (const [value, name] of lines) {
    root.append(svg("line", { x1: m.left, x2: m.left + w, y1: y(value), y2: y(value) }, "threshold"));
    const label = svg("text", { x: m.left + w + 6, y: y(value) + 4 }, "threshold-label");
    label.textContent = name;
    root.append(label);
  }
  for (const t of [t0, t1]) {
    const label = svg("text", { x: x(t), y: height - 6, "text-anchor": t === t0 ? "start" : "end" }, "tick");
    label.textContent = fmtDate(new Date(t).toISOString());
    root.append(label);
  }

  const path = points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.score).toFixed(1)}`).join("");
  root.append(svg("path", { d: path }, "line"));
  const last = points[points.length - 1];
  root.append(svg("circle", { cx: x(last.t), cy: y(last.score), r: 4 }, "dot"));

  // Hover: a crosshair snaps to the nearest score; the tooltip shows date, score, tier.
  const cross = svg("line", { x1: 0, x2: 0, y1: m.top, y2: m.top + h }, "crosshair");
  const marker = svg("circle", { cx: 0, cy: 0, r: 4 }, "dot");
  cross.setAttribute("visibility", "hidden");
  marker.setAttribute("visibility", "hidden");
  const hit = svg("rect", { x: m.left, y: 0, width: w, height }, "hit");
  root.append(cross, marker, hit);

  const tip = $("tooltip");
  const show = (clientX, clientY) => {
    const rect = root.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * width;
    let best = points[0];
    for (const p of points) if (Math.abs(x(p.t) - px) < Math.abs(x(best.t) - px)) best = p;
    for (const node of [cross, marker]) node.setAttribute("visibility", "visible");
    cross.setAttribute("x1", x(best.t));
    cross.setAttribute("x2", x(best.t));
    marker.setAttribute("cx", x(best.t));
    marker.setAttribute("cy", y(best.score));
    tip.replaceChildren(el("strong", "", fmtScore(best.score)), document.createTextNode(" "));
    tip.append(tierBadge(best.tier), el("div", "muted small", fmtDateTime(best.as_of)));
    tip.hidden = false;
    tip.style.left = `${Math.min(clientX + 14, window.innerWidth - 180)}px`;
    tip.style.top = `${clientY + 14}px`;
  };
  const hide = () => {
    tip.hidden = true;
    for (const node of [cross, marker]) node.setAttribute("visibility", "hidden");
  };
  hit.addEventListener("pointermove", (e) => show(e.clientX, e.clientY));
  hit.addEventListener("pointerleave", hide);
  box.append(root);
  box.setAttribute(
    "aria-label",
    `Risk score over time: ${points.length} scores, latest ${fmtScore(last.score)} (${last.tier}).`,
  );
}

function fillTable() {
  const body = $("history-table");
  body.replaceChildren();
  for (const h of [...state.history].reverse()) {
    const row = el("tr");
    const tier = el("td");
    tier.append(tierBadge(h.tier));
    row.append(el("td", "", fmtDateTime(h.as_of)), el("td", "", fmtScore(h.score)), tier);
    body.append(row);
  }
}

// -- decisions ----------------------------------------------------------------------------------

async function decide(decision, button) {
  if (!state.current) return;
  const { platform, actor_id: actorId } = state.current;
  const reviewer = $("reviewer").value.trim();
  writeLocal("riskdetect-reviewer", reviewer);
  const buttons = [...document.querySelectorAll("#decisions button")];
  buttons.forEach((b) => { b.disabled = true; });
  try {
    await api(`${actorPath(platform, actorId)}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, reviewer: reviewer || null, note: $("note").value.trim() || null }),
    });
    toast(`Saved: ${actorId} marked as ${button.textContent.toLowerCase()}.`);
    const index = state.queue.findIndex((q) => q.platform === platform && q.actor_id === actorId);
    await loadQueue();
    const next = state.queue[Math.min(Math.max(index, 0), state.queue.length - 1)];
    if (next) openActor(next.platform, next.actor_id);
    else {
      state.current = null;
      $("detail-body").hidden = true;
      $("detail-empty").hidden = false;
    }
  } catch (error) {
    handleError(error);
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}

// -- API key dialog --------------------------------------------------------------------------------

function openKeyDialog() {
  const dialog = $("key-dialog");
  if (dialog.open) return;
  $("key-input").value = state.apiKey;
  dialog.showModal();
}

// -- wiring ---------------------------------------------------------------------------------------------

function start() {
  $("reviewer").value = readLocal("riskdetect-reviewer");
  $("platform").addEventListener("change", (e) => {
    state.platform = e.target.value;
    loadQueue();
  });
  $("lookup").addEventListener("submit", (e) => {
    e.preventDefault();
    const id = $("lookup-id").value.trim();
    const platform = state.platform || (state.queue[0] && state.queue[0].platform) || $("platform").options[1]?.value;
    if (!id || !platform) {
      toast("Pick a platform first.");
      return;
    }
    openActor(platform, id);
  });
  $("decisions").addEventListener("click", (e) => {
    const button = e.target.closest("button[data-decision]");
    if (button) decide(button.dataset.decision, button);
  });
  $("toggle-table").addEventListener("click", (e) => {
    const wrap = $("history-table-wrap");
    wrap.hidden = !wrap.hidden;
    e.target.setAttribute("aria-pressed", String(!wrap.hidden));
    e.target.textContent = wrap.hidden ? "Show as table" : "Hide table";
  });
  $("key-button").addEventListener("click", openKeyDialog);
  $("key-dialog").addEventListener("close", async () => {
    if ($("key-dialog").returnValue !== "save") return;
    state.apiKey = $("key-input").value.trim();
    writeSession("riskdetect-api-key", state.apiKey);
    if (await loadStatus()) loadQueue();
  });
  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawChart, 150);
  });
  loadStatus().then(async (ok) => {
    if (!ok) return;
    await loadQueue();
    openFromLink();
  });
  window.addEventListener("hashchange", openFromLink);
}

function openFromLink() {
  const match = /^#([^/]+)\/(.+)$/.exec(location.hash);
  if (!match) return;
  try {
    openActor(decodeURIComponent(match[1]), decodeURIComponent(match[2]));
  } catch {
    toast("That link is not a valid user link.");
  }
}

start();
