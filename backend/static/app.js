let sim = null;              // single-mode dataset (floor map view)
let simSentinel = null;      // compare view, left column
let simFifo = null;          // compare view, right column
let t = 0;
let timer = null;
let nurseSlots = [];
let nurseSlotsSentinel = [];
let nurseSlotsFifo = [];
let currentView = "map";
let started = false; // true once Play has been pressed at least once since the last load/reset

const clockEl = document.getElementById("clock");
const playBtn = document.getElementById("playBtn");
const resetBtn = document.getElementById("resetBtn");
const applyBtn = document.getElementById("applyBtn");
const speedSelect = document.getElementById("speedSelect");
const modeSelect = document.getElementById("modeSelect");
const modeField = document.getElementById("modeField");
const nursesInput = document.getElementById("nursesInput");
const roomsInput = document.getElementById("roomsInput");
const shiftInput = document.getElementById("shiftInput");
const pingsMinInput = document.getElementById("pingsMinInput");
const pingsMaxInput = document.getElementById("pingsMaxInput");
const presetBtns = document.querySelectorAll(".preset-btn");
const nursesEl = document.getElementById("nurses");
const statsEl = document.getElementById("stats");
const totalsEl = document.getElementById("totals");
const floorEl = document.getElementById("floor");
const mapViewEl = document.getElementById("mapView");
const compareViewEl = document.getElementById("compareView");
const viewMapBtn = document.getElementById("viewMapBtn");
const viewCompareBtn = document.getElementById("viewCompareBtn");
const floorSentinelEl = document.getElementById("floorSentinel");
const floorFifoEl = document.getElementById("floorFifo");
const sentinelMetricsEl = document.getElementById("sentinelMetrics");
const sentinelMetricsHeadingEl = document.getElementById("sentinelMetricsHeading");
const sentinelMetricsCompareEl = document.getElementById("sentinelMetricsCompare");

function severityClass(sev) {
  if (sev <= 1) return "sev-low";
  if (sev <= 4) return "sev-mid";
  if (sev <= 7) return "sev-high";
  return "sev-crit";
}

function bucketFor(sev) {
  if (sev <= 1) return "1";
  if (sev <= 4) return "2-4";
  if (sev <= 7) return "5-7";
  return "8-10";
}

// assigned_min/finish_min are null for alerts still unassigned when the shift
// ended (a rush that outpaces capacity) - never coerce null in a comparison
// here, since `null <= t` is true in JS for any t >= 0.
function isWaiting(a, atTime) {
  return a.arrival_min <= atTime && (a.assigned_min === null || atTime < a.assigned_min);
}

function isInProgress(a, atTime) {
  return a.assigned_min !== null && a.assigned_min <= atTime && atTime < a.finish_min;
}

function isResolved(a, atTime) {
  return a.finish_min !== null && a.finish_min <= atTime;
}

function isProcessed(a, atTime) {
  return a.assigned_min !== null && a.assigned_min <= atTime;
}

function statsHtml(processed, highlightCritical) {
  const buckets = { "1": [], "2-4": [], "5-7": [], "8-10": [] };
  for (const a of processed) buckets[bucketFor(a.severity)].push(a.wait_min);
  const avg = xs => (xs.length ? (xs.reduce((s, v) => s + v, 0) / xs.length).toFixed(1) : "n/a");
  const overallAvg = avg(processed.map(a => a.wait_min));
  const critCls = highlightCritical ? "stat-highlight" : "";
  return `
    <div>Overall avg wait: <b>${overallAvg}${processed.length ? "m" : ""}</b></div>
    <div>Sev 1: <b>${avg(buckets["1"])}${buckets["1"].length ? "m" : ""}</b></div>
    <div>Sev 2-4: <b>${avg(buckets["2-4"])}${buckets["2-4"].length ? "m" : ""}</b></div>
    <div>Sev 5-7: <b>${avg(buckets["5-7"])}${buckets["5-7"].length ? "m" : ""}</b></div>
    <div class="${critCls}">Sev 8-10: <b>${avg(buckets["8-10"])}${buckets["8-10"].length ? "m" : ""}</b></div>
  `;
}

function sentinelMetricsHtml(simData) {
  const m = simData && simData.metrics;
  if (!m || m.active_incidents === undefined) return "";
  return `
    <div>Raw pings: <b>${m.raw_pings}</b></div>
    <div>Active incidents: <b>${m.active_incidents}</b></div>
    <div>Duplicates consolidated: <b>${m.duplicates_consolidated}</b></div>
    <div>Starvation escalations: <b>${m.starvation_escalations}</b></div>
  `;
}

function totalsHtml(simData, processedCount) {
  const arrived = simData.alerts.filter(a => a.arrival_min <= t).length;
  const resolved = simData.alerts.filter(a => isResolved(a, t)).length;
  const interrupts = simData.alerts.filter(a => isProcessed(a, t) && a.interrupted).length;
  return `
    <div>Total alarms so far: <b>${arrived}</b> <span style="color:var(--text-dim)">/ ${simData.alerts.length}</span></div>
    <div>Assigned so far: <b>${processedCount}</b></div>
    <div>Resolved so far: <b>${resolved}</b></div>
    <div>Interrupts fired: <b>${interrupts}</b></div>
  `;
}

function placeholderTotalsHtml() {
  return `
    <div>Total alarms so far: <b>0</b></div>
    <div>Assigned so far: <b>0</b></div>
    <div>Resolved so far: <b>0</b></div>
    <div>Interrupts fired: <b>0</b></div>
  `;
}

function assignSlots(slots, inProgress) {
  const inProgressIds = new Set(inProgress.map(a => a.id));
  const next = slots.map(id => (id && inProgressIds.has(id) ? id : null));
  for (const a of inProgress) {
    if (!next.includes(a.id)) {
      const freeIdx = next.indexOf(null);
      if (freeIdx !== -1) next[freeIdx] = a.id;
    }
  }
  return next;
}

function nursesHtml(slots, simData) {
  return slots.map((id, i) => {
    const alert = id ? simData.alerts.find(a => a.id === id) : null;
    if (!alert) {
      return `<div class="nurse-card"><div class="nurse-label">NURSE ${i}</div><div class="nurse-idle">idle</div></div>`;
    }
    const cls = severityClass(alert.severity);
    const escalatedMark = alert.escalated ? ' <span class="escalated-mark" title="Escalated while waiting">&#9650;</span>' : "";
    return `<div class="nurse-card busy">
      <div class="nurse-label">NURSE ${i}</div>
      <div class="nurse-alert ${cls}">Room ${alert.room} &mdash; ${alert.alert_type} (sev ${alert.severity})${escalatedMark}</div>
    </div>`;
  }).join("");
}

function buildFloor(container, prefix, simData, compact) {
  container.innerHTML = "";
  if (compact) container.classList.add("floor-compare");
  for (const room of simData.rooms) {
    const div = document.createElement("div");
    div.className = "room";
    div.dataset.room = room;
    div.innerHTML = `<div class="room-number">${room}</div><div class="room-status">&mdash;</div>`;
    container.appendChild(div);
  }
  for (let i = 0; i < simData.nurses; i++) {
    const marker = document.createElement("div");
    marker.className = "nurse-marker";
    marker.id = `${prefix}-nurse-marker-${i}`;
    marker.textContent = `N${i}`;
    container.appendChild(marker);
  }
}

function positionNurseMarker(container, prefix, i, roomId) {
  const marker = document.getElementById(`${prefix}-nurse-marker-${i}`);
  if (!marker) return;
  if (roomId === null) {
    marker.style.left = `${20 + i * 28}px`;
    marker.style.top = `12px`;
    return;
  }
  const roomEl = container.querySelector(`.room[data-room="${roomId}"]`);
  if (!roomEl) return;
  marker.style.left = `${roomEl.offsetLeft + roomEl.offsetWidth / 2}px`;
  marker.style.top = `${roomEl.offsetTop + roomEl.offsetHeight / 2}px`;
}

function renderFloorInto(container, prefix, simData, slots, waiting, inProgress) {
  const roomStatus = {};
  for (const a of waiting) {
    const cur = roomStatus[a.room];
    if (!cur || a.severity > cur.severity) roomStatus[a.room] = { severity: a.severity, label: `waiting (sev ${a.severity})`, escalated: a.escalated };
  }
  for (const a of inProgress) {
    roomStatus[a.room] = { severity: a.severity, label: `nurse on scene (sev ${a.severity})`, escalated: a.escalated };
  }

  container.querySelectorAll(".room").forEach(roomEl => {
    const room = roomEl.dataset.room;
    const status = roomStatus[room];
    roomEl.className = "room";
    const statusEl = roomEl.querySelector(".room-status");
    if (status) {
      roomEl.classList.add(severityClass(status.severity));
      if (status.escalated) roomEl.classList.add("interrupted");
      statusEl.textContent = status.escalated ? `${status.label} ▲` : status.label;
    } else {
      statusEl.textContent = "—";
    }
  });

  slots.forEach((id, i) => {
    const alert = id ? simData.alerts.find(a => a.id === id) : null;
    positionNurseMarker(container, prefix, i, alert ? alert.room : null);
  });
}

function maxMinutes() {
  if (currentView === "compare") {
    return Math.max(simSentinel ? simSentinel.total_minutes : 0, simFifo ? simFifo.total_minutes : 0);
  }
  return sim ? sim.total_minutes : 0;
}

function render() {
  clockEl.textContent = `t = ${t}m`;
  if (currentView === "compare") {
    renderCompare();
    return;
  }
  if (!sim) return;

  if (!started) {
    const idleSlots = new Array(sim.nurses).fill(null);
    nursesEl.innerHTML = nursesHtml(idleSlots, sim);
    totalsEl.innerHTML = placeholderTotalsHtml();
    statsEl.innerHTML = statsHtml([], false);
    renderFloorInto(floorEl, "single", sim, idleSlots, [], []);
    return;
  }

  const inProgress = sim.alerts.filter(a => isInProgress(a, t));
  const waiting = sim.alerts.filter(a => isWaiting(a, t));

  nurseSlots = assignSlots(nurseSlots, inProgress);
  nursesEl.innerHTML = nursesHtml(nurseSlots, sim);

  const processed = sim.alerts.filter(a => isProcessed(a, t));
  totalsEl.innerHTML = totalsHtml(sim, processed.length);
  statsEl.innerHTML = statsHtml(processed, false);

  renderFloorInto(floorEl, "single", sim, nurseSlots, waiting, inProgress);
}

function renderCompareColumn(simData, slotsRef, prefix, ids) {
  if (!simData) return slotsRef;

  if (!started) {
    const idleSlots = new Array(simData.nurses).fill(null);
    renderFloorInto(document.getElementById(ids.floor), prefix, simData, idleSlots, [], []);
    document.getElementById(ids.totals).innerHTML = placeholderTotalsHtml();
    document.getElementById(ids.stats).innerHTML = statsHtml([], true);
    const idleBadge = document.getElementById(ids.badge);
    idleBadge.textContent = "not started";
    idleBadge.classList.remove("complete");
    return idleSlots;
  }

  const inProgress = simData.alerts.filter(a => isInProgress(a, t));
  const waiting = simData.alerts.filter(a => isWaiting(a, t));

  const nextSlots = assignSlots(slotsRef, inProgress);
  renderFloorInto(document.getElementById(ids.floor), prefix, simData, nextSlots, waiting, inProgress);

  const processed = simData.alerts.filter(a => isProcessed(a, t));
  document.getElementById(ids.totals).innerHTML = totalsHtml(simData, processed.length);
  document.getElementById(ids.stats).innerHTML = statsHtml(processed, true);

  const done = t >= simData.total_minutes;
  const badge = document.getElementById(ids.badge);
  badge.textContent = done ? `finished at t=${simData.total_minutes}m` : "running…";
  badge.classList.toggle("complete", done);

  return nextSlots;
}

function renderCompare() {
  nurseSlotsSentinel = renderCompareColumn(simSentinel, nurseSlotsSentinel, "sentinel", {
    floor: "floorSentinel", totals: "totalsSentinel", stats: "statsSentinel", badge: "sentinelBadge",
  });
  nurseSlotsFifo = renderCompareColumn(simFifo, nurseSlotsFifo, "fifo", {
    floor: "floorFifo", totals: "totalsFifo", stats: "statsFifo", badge: "fifoBadge",
  });
}

function tick() {
  t += 1;
  if (t > maxMinutes()) {
    pause();
    return;
  }
  render();
}

function play() {
  if (timer) return;
  if (!started) {
    started = true;
    render(); // reveal the true t=0 snapshot now that playback has actually begun
  }
  playBtn.textContent = "Pause";
  timer = setInterval(tick, parseInt(speedSelect.value, 10));
}

function pause() {
  clearInterval(timer);
  timer = null;
  playBtn.textContent = "Play";
}

function resetPlayback() {
  pause();
  t = 0;
  started = false;
  if (sim) nurseSlots = new Array(sim.nurses).fill(null);
  if (simSentinel) nurseSlotsSentinel = new Array(simSentinel.nurses).fill(null);
  if (simFifo) nurseSlotsFifo = new Array(simFifo.nurses).fill(null);
  render();
}

function setView(view) {
  currentView = view;
  mapViewEl.style.display = view === "map" ? "grid" : "none";
  compareViewEl.style.display = view === "compare" ? "grid" : "none";
  modeField.style.display = view === "compare" ? "none" : "flex";

  viewMapBtn.classList.toggle("active", view === "map");
  viewCompareBtn.classList.toggle("active", view === "compare");

  if (view === "compare" && (!simSentinel || !simFifo)) {
    loadCompare();
  } else {
    render();
  }
}

playBtn.addEventListener("click", () => (timer ? pause() : play()));
resetBtn.addEventListener("click", resetPlayback);
speedSelect.addEventListener("change", () => {
  if (timer) {
    pause();
    play();
  }
});
viewMapBtn.addEventListener("click", () => setView("map"));
viewCompareBtn.addEventListener("click", () => setView("compare"));
applyBtn.addEventListener("click", () => (currentView === "compare" ? loadCompare() : loadSimulation()));
window.addEventListener("resize", () => render());

function clampInt(input, lo, hi, fallback) {
  const v = Math.max(lo, Math.min(hi, parseInt(input.value, 10) || fallback));
  input.value = v;
  return v;
}

function nursesParam() { return clampInt(nursesInput, 1, 20, 5); }
function roomsParam() { return clampInt(roomsInput, 5, 300, 100); }
function shiftParam() { return clampInt(shiftInput, 1, 12, 5); }
function pingsMinParam() { return clampInt(pingsMinInput, 1, 200, 20); }
function pingsMaxParam() { return clampInt(pingsMaxInput, 1, 200, 30); }

function scenarioQuery(mode) {
  const nurses = nursesParam();
  const rooms = roomsParam();
  const shift = shiftParam();
  const pingsMin = pingsMinParam();
  const pingsMax = pingsMaxParam();
  return `mode=${mode}&nurses=${nurses}&rooms=${rooms}&shift_hours=${shift}&pings_min=${pingsMin}&pings_max=${pingsMax}`;
}

const PRESETS = {
  slow: { rooms: 40, nurses: 4, shift: 6, pingsMin: 3, pingsMax: 8 },
  normal: { rooms: 100, nurses: 5, shift: 5, pingsMin: 12, pingsMax: 18 },
  rush: { rooms: 100, nurses: 5, shift: 5, pingsMin: 20, pingsMax: 30 },
};

function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  roomsInput.value = p.rooms;
  nursesInput.value = p.nurses;
  shiftInput.value = p.shift;
  pingsMinInput.value = p.pingsMin;
  pingsMaxInput.value = p.pingsMax;
  presetBtns.forEach(b => b.classList.toggle("active", b.dataset.preset === name));
  currentView === "compare" ? loadCompare() : loadSimulation();
}

presetBtns.forEach(btn => btn.addEventListener("click", () => applyPreset(btn.dataset.preset)));

async function loadSimulation() {
  pause();
  const mode = modeSelect.value;
  const res = await fetch(`/api/simulation?${scenarioQuery(mode)}`);
  sim = await res.json();
  t = 0;
  started = false;
  nurseSlots = new Array(sim.nurses).fill(null);
  buildFloor(floorEl, "single", sim, false);
  const isSentinel = sim.metrics && sim.metrics.active_incidents !== undefined;
  sentinelMetricsHeadingEl.style.display = isSentinel ? "block" : "none";
  sentinelMetricsEl.innerHTML = isSentinel ? sentinelMetricsHtml(sim) : "";
  render();
}

async function loadCompare() {
  pause();
  const [sentinelRes, fifoRes] = await Promise.all([
    fetch(`/api/simulation?${scenarioQuery("sentinel")}`),
    fetch(`/api/simulation?${scenarioQuery("fifo")}`),
  ]);
  simSentinel = await sentinelRes.json();
  simFifo = await fifoRes.json();
  t = 0;
  started = false;
  nurseSlotsSentinel = new Array(simSentinel.nurses).fill(null);
  nurseSlotsFifo = new Array(simFifo.nurses).fill(null);
  buildFloor(floorSentinelEl, "sentinel", simSentinel, true);
  buildFloor(floorFifoEl, "fifo", simFifo, true);
  sentinelMetricsCompareEl.innerHTML = sentinelMetricsHtml(simSentinel);
  render();
}

loadSimulation();
