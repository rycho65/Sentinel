let shiftId = null;
let totalBeds = 20;
let mode = "auto";
let lastState = null;

let currentView = "login";
let povNurseId = null;
const selectedGrades = {};   // eventId -> "GREEN"|"YELLOW"|"ORANGE"|"RED", picked inline on its card

let pollTimer = null;
let povTimer = null;
let queueRenderLocked = false;

// Navigating to /index.html and back (e.g. via the nav links) is a full page
// load, so these two lines are what let an in-progress shift survive that -
// otherwise every trip back to Live Product would hit the login screen again.
const SHIFT_STORAGE_KEY = "sentinel_shift_id";
const DOCTOR_STORAGE_KEY = "sentinel_doctor_name";

// ---- element refs ----

const views = {
  login: document.getElementById("loginView"),
  setup: document.getElementById("setupView"),
  command: document.getElementById("commandView"),
  pov: document.getElementById("povView"),
};

const loginBtn = document.getElementById("loginBtn");
const loginUser = document.getElementById("loginUser");
const setupBeds = document.getElementById("setupBeds");
const setupNurseCount = document.getElementById("setupNurseCount");
const nurseRows = document.getElementById("nurseRows");
const startShiftBtn = document.getElementById("startShiftBtn");

const shiftSubtitle = document.getElementById("shiftSubtitle");
const modeToggleBtn = document.getElementById("modeToggleBtn");
const injectEventBtn = document.getElementById("injectEventBtn");
const endShiftBtn = document.getElementById("endShiftBtn");
const ccNurses = document.getElementById("ccNurses");
const ccTotals = document.getElementById("ccTotals");
const ccFloor = document.getElementById("ccFloor");
const ccEvents = document.getElementById("ccEvents");
const ccQueue = document.getElementById("ccQueue");
const headerDoctorName = document.getElementById("headerDoctorName");
const summaryIncidents = document.getElementById("summaryIncidents");
const summaryNurses = document.getElementById("summaryNurses");
const summaryQueue = document.getElementById("summaryQueue");
const summaryCompleted = document.getElementById("summaryCompleted");

const povBackBtn = document.getElementById("povBackBtn");
const povName = document.getElementById("povName");
const povRole = document.getElementById("povRole");
const povNoTask = document.getElementById("povNoTask");
const povTask = document.getElementById("povTask");
const povRoom = document.getElementById("povRoom");
const povDesc = document.getElementById("povDesc");
const povGrade = document.getElementById("povGrade");
const povGoal = document.getElementById("povGoal");
const povStartBtn = document.getElementById("povStartBtn");
const povElapsedWrap = document.getElementById("povElapsedWrap");
const povElapsed = document.getElementById("povElapsed");
const povDoneBtn = document.getElementById("povDoneBtn");
const povUpNext = document.getElementById("povUpNext");
const povUpNextBody = document.getElementById("povUpNextBody");

// ---- helpers ----

const GRADE_EMOJI = { GREEN: "\u{1F7E2}", YELLOW: "\u{1F7E1}", ORANGE: "\u{1F7E0}", RED: "\u{1F534}" };
const GRADE_CLASS = { GREEN: "sev-low", YELLOW: "sev-mid", ORANGE: "sev-high", RED: "sev-crit" };

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

function showView(name) {
  currentView = name;
  for (const key of Object.keys(views)) {
    views[key].hidden = key !== name;
  }
}

// ---- LOGIN ----

loginBtn.addEventListener("click", () => {
  // Hackathon-level auth: any credentials advance. Nothing is sent to the backend.
  const name = loginUser.value.trim() || "Coordinator";
  headerDoctorName.textContent = `Dr. ${name}`;
  sessionStorage.setItem(DOCTOR_STORAGE_KEY, name);
  showView("setup");
  renderNurseRows();
});

// ---- SHIFT SETUP ----

function renderNurseRows() {
  const count = Math.max(1, Math.min(20, parseInt(setupNurseCount.value, 10) || 1));
  const sampleNames = ["Sarah Kim", "James Lee", "Maya Patel", "Alex Chen", "Priya Rao", "Devon Ward"];
  const rows = [];
  for (let i = 0; i < count; i++) {
    rows.push(`
      <div class="nurse-row">
        <input type="text" class="nurse-name" placeholder="Name" value="${sampleNames[i % sampleNames.length]}">
        <input type="text" class="nurse-role" placeholder="Role" value="RN">
      </div>
    `);
  }
  nurseRows.innerHTML = rows.join("");
}

setupNurseCount.addEventListener("change", renderNurseRows);

startShiftBtn.addEventListener("click", async () => {
  totalBeds = Math.max(1, Math.min(300, parseInt(setupBeds.value, 10) || 20));
  const names = [...nurseRows.querySelectorAll(".nurse-name")].map(el => el.value.trim() || "Nurse");
  const roles = [...nurseRows.querySelectorAll(".nurse-role")].map(el => el.value.trim() || "RN");
  const nurses = names.map((name, i) => ({ name, role: roles[i] }));

  const shift = await postJSON("/api/live/shift", { total_beds: totalBeds, nurses });
  shiftId = shift.shift_id;
  sessionStorage.setItem(SHIFT_STORAGE_KEY, shiftId);
  mode = shift.mode;
  modeToggleBtn.textContent = mode.toUpperCase();
  shiftSubtitle.textContent = `${totalBeds} beds · ${nurses.length} nurses`;

  buildFloor();
  showView("command");
  startPolling();
});

// ---- COMMAND CENTER ----

function buildFloor() {
  ccFloor.innerHTML = "";
  for (let i = 0; i < totalBeds; i++) {
    const room = String(101 + i);
    const div = document.createElement("div");
    div.className = "room";
    div.dataset.room = room;
    div.innerHTML = `<div class="room-number">${room}</div><div class="room-status">&mdash;</div>`;
    ccFloor.appendChild(div);
  }
}

function severityClass(sev) {
  if (sev <= 1) return "sev-low";
  if (sev <= 4) return "sev-mid";
  if (sev <= 7) return "sev-high";
  return "sev-crit";
}

function renderFloor(queue) {
  const byRoom = {};
  for (const task of queue) {
    const cur = byRoom[task.room];
    if (!cur || task.severity > cur.severity) byRoom[task.room] = task;
  }
  ccFloor.querySelectorAll(".room").forEach(roomEl => {
    const task = byRoom[roomEl.dataset.room];
    roomEl.className = "room";
    const statusEl = roomEl.querySelector(".room-status");
    if (task) {
      roomEl.classList.add(severityClass(task.severity));
      if (task.escalated) roomEl.classList.add("interrupted");
      statusEl.textContent = `${task.status === "in_progress" ? "nurse on scene" : "waiting"} (sev ${task.severity})`;
    } else {
      statusEl.textContent = "—";
    }
  });

  // nurse markers, positioned over whichever room they're actively in
  ccFloor.querySelectorAll(".nurse-marker").forEach(m => m.remove());
  (lastState ? lastState.nurses : []).forEach((nurse, i) => {
    const marker = document.createElement("div");
    marker.className = "nurse-marker";
    marker.textContent = nurse.name.split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase();
    ccFloor.appendChild(marker);
    if (nurse.current_room) {
      const roomEl = ccFloor.querySelector(`.room[data-room="${nurse.current_room}"]`);
      if (roomEl) {
        marker.style.left = `${roomEl.offsetLeft + roomEl.offsetWidth / 2}px`;
        marker.style.top = `${roomEl.offsetTop + roomEl.offsetHeight / 2}px`;
        return;
      }
    }
    marker.style.left = `${20 + i * 26}px`;
    marker.style.top = "12px";
  });
}

function renderNurses(nurses) {
  ccNurses.innerHTML = nurses.map(n => `
    <div class="nurse-card ${n.status !== 'available' ? 'busy' : ''}" data-nurse-id="${n.id}">
      <div class="nurse-label">${n.name.toUpperCase()} <span class="nurse-status-tag status-${n.status}">${n.status}</span></div>
      ${n.task
        ? `<div class="nurse-alert ${severityClass(n.task.severity)}">Room ${n.task.room} &mdash; ${n.task.description}</div>`
        : `<div class="nurse-idle">idle</div>`}
    </div>
  `).join("");
  ccNurses.querySelectorAll(".nurse-card").forEach(el => {
    el.addEventListener("click", () => openPov(el.dataset.nurseId));
  });
}

function renderEvents(events) {
  // Drop grade selections for events that are no longer pending (confirmed/gone).
  const stillPending = new Set(events.map(e => e.id));
  for (const id of Object.keys(selectedGrades)) {
    if (!stillPending.has(id)) delete selectedGrades[id];
  }

  if (!events.length) {
    ccEvents.innerHTML = `<div class="nurse-idle">No pending events</div>`;
    return;
  }

  ccEvents.innerHTML = events.map(e => {
    // Auto Mode: Sentinel's own suggestion is pre-selected - CONFIRM alone
    // accepts it. Manual Mode: nothing is pre-selected, the coordinator
    // must pick a grade themselves. Either way this is a click ON THE
    // CARD ITSELF - no separate "open a review" step first.
    if (mode === "auto" && e.suggested_grade && !(e.id in selectedGrades)) {
      selectedGrades[e.id] = e.suggested_grade;
    }
    const selected = selectedGrades[e.id] || null;

    return `
    <div class="event-card">
      <div class="event-room">NEW &mdash; ROOM ${e.room}</div>
      ${e.technical
        ? `<div class="event-vitals">Sensor disconnected</div>`
        : `<div class="event-vitals">SpO&#8322;: ${e.vitals.oxygen_saturation}% &nbsp; HR: ${e.vitals.heart_rate}</div>`}
      ${mode === "auto" && e.suggested_grade
        ? `<div class="event-note">SENTINEL suggests: ${GRADE_EMOJI[e.suggested_grade]} ${e.suggested_grade} &mdash; ${e.suggested_description}</div>`
        : ""}
      <div class="grade-buttons">
        ${["GREEN", "YELLOW", "ORANGE", "RED"].map(g => `
          <button class="grade-btn grade-${g} ${selected === g ? "selected" : ""}" data-event-id="${e.id}" data-grade="${g}">${GRADE_EMOJI[g]}</button>
        `).join("")}
      </div>
      <button class="btn btn-accent confirm-btn" data-event-id="${e.id}" ${selected ? "" : "disabled"}>CONFIRM</button>
    </div>
  `;
  }).join("");

  ccEvents.querySelectorAll(".grade-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      selectedGrades[btn.dataset.eventId] = btn.dataset.grade;
      renderEvents(events);
    });
  });
  ccEvents.querySelectorAll(".confirm-btn").forEach(btn => {
    btn.addEventListener("click", () => confirmEvent(events.find(e => e.id === btn.dataset.eventId)));
  });
}

async function confirmEvent(event) {
  const grade = selectedGrades[event.id];
  if (!grade) return; // must pick a grade first (manual mode has no default)

  // Accepting Sentinel's own suggestion as-is -> omit severity_grade so the
  // backend uses its own precise computed severity/incident_type (not the
  // coarse GREEN/YELLOW/ORANGE/RED bucket). Picking a different grade is
  // always an explicit override, auto or manual.
  const body = (mode === "auto" && grade === event.suggested_grade) ? {} : { severity_grade: grade };

  await postJSON(`/api/live/events/${event.id}/confirm?shift_id=${shiftId}`, body);
  delete selectedGrades[event.id];
  refreshState();
}

// Populates the summary-card row from data the app already computes each
// refresh (state.nurses / state.queue / the same totals renderTotals uses) -
// no new backend metrics, just a compact restatement for the top of the page.
function renderSummaryCards(state) {
  const available = state.nurses.filter(n => n.status === "available").length;
  summaryIncidents.textContent = state.active_incidents_total;
  summaryNurses.textContent = `${available} / ${state.nurses.length}`;
  summaryQueue.textContent = state.queue.length;
  summaryCompleted.textContent = state.completed_count;
}

function renderTotals(state) {
  ccTotals.innerHTML = `
    <div>Raw pings: <b>${state.raw_pings_total}</b></div>
    <div>Active incidents: <b>${state.active_incidents_total}</b></div>
    <div>Completed: <b>${state.completed_count}</b></div>
    <div>Queue: <b>${state.queue.length}</b></div>
  `;
}

// Unassigned waiting tasks. Auto Mode: Sentinel claims these itself via
// tick() - nothing for the coordinator to do here, so the same cards render
// without assignment controls. Manual Mode: these sit untouched until the
// coordinator explicitly assigns a nurse - that's the whole point of Manual
// Mode, full control over who goes where.
function renderQueue(state) {
  const unclaimed = state.queue.filter(t => !t.nurse_id);

  if (!unclaimed.length) {
    ccQueue.innerHTML = `<div class="nurse-idle">Queue empty</div>`;
    return;
  }

  if (mode === "auto") {
    ccQueue.innerHTML = unclaimed.map(t => `
      <div class="event-card">
        <div class="event-room">${GRADE_EMOJI[t.grade]} ROOM ${t.room}</div>
        <div class="event-vitals">${t.description}</div>
        <div class="event-note">Sentinel is assigning a nurse&hellip;</div>
      </div>
    `).join("");
    return;
  }

  const availableNurses = state.nurses.filter(n => n.status === "available");

  ccQueue.innerHTML = unclaimed.map(t => `
    <div class="event-card">
      <div class="event-room">${GRADE_EMOJI[t.grade]} ROOM ${t.room}</div>
      <div class="event-vitals">${t.description}</div>
      <select class="btn nurse-select" data-task-id="${t.id}" ${availableNurses.length ? "" : "disabled"}>
        <option value="">Assign to&hellip;</option>
        ${availableNurses.map(n => `<option value="${n.id}">${n.name}</option>`).join("")}
      </select>
      <button class="btn btn-accent assign-btn" data-task-id="${t.id}" ${availableNurses.length ? "" : "disabled"}>ASSIGN</button>
    </div>
  `).join("");

  ccQueue.querySelectorAll(".assign-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const taskId = btn.dataset.taskId;
      const select = ccQueue.querySelector(`.nurse-select[data-task-id="${taskId}"]`);
      if (!select.value) return; // must actually pick a nurse first
      await postJSON(`/api/live/nurses/${select.value}/assign?shift_id=${shiftId}`, { incident_id: taskId });
      refreshState();
    });
  });

  // The 2s poll below rebuilds this whole panel's innerHTML, which - if it
  // fires while a native <select> dropdown is open - tears the element out
  // from under the open popup and dismisses it before a nurse can be picked.
  // Suppress rebuilds while a select actually has focus. Don't force an
  // immediate rebuild on blur either: blur fires the instant the user's
  // mouse moves focus onto the ASSIGN button (before its click lands), and
  // on localhost the refresh can resolve and rebuild the DOM in that same
  // few-millisecond gap, yanking the button out from under the click. Just
  // release the lock and let the next poll tick (or the assign click's own
  // refreshState() call once it posts) pick up the rebuild.
  ccQueue.querySelectorAll(".nurse-select").forEach(select => {
    select.addEventListener("focus", () => { queueRenderLocked = true; });
    select.addEventListener("blur", () => { queueRenderLocked = false; });
  });
}

async function refreshState() {
  if (!shiftId) return;
  const state = await getJSON(`/api/live/state?shift_id=${shiftId}`);
  lastState = state;
  mode = state.mode;
  modeToggleBtn.textContent = mode.toUpperCase();
  renderNurses(state.nurses);
  renderFloor(state.queue);
  renderEvents(state.pending_events);
  if (!queueRenderLocked) renderQueue(state);
  renderTotals(state);
  renderSummaryCards(state);
}

function startPolling() {
  stopPolling();
  refreshState();
  pollTimer = setInterval(refreshState, 2000);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

modeToggleBtn.addEventListener("click", async () => {
  const next = mode === "auto" ? "manual" : "auto";
  await postJSON(`/api/live/mode?shift_id=${shiftId}`, { mode: next });
  mode = next;
  modeToggleBtn.textContent = mode.toUpperCase();
  refreshState();
});

injectEventBtn.addEventListener("click", async () => {
  const room = String(101 + Math.floor(Math.random() * totalBeds));
  const technical = Math.random() < 0.15;
  await postJSON(`/api/live/events?shift_id=${shiftId}`, { room, technical });
  refreshState();
});

endShiftBtn.addEventListener("click", () => {
  stopPolling();
  shiftId = null;
  lastState = null;
  sessionStorage.removeItem(SHIFT_STORAGE_KEY);
  sessionStorage.removeItem(DOCTOR_STORAGE_KEY);
  showView("login");
});

// ---- NURSE POV ----

function openPov(nurseId) {
  povNurseId = nurseId;
  stopPolling();
  showView("pov");
  refreshPov();
  povTimer = setInterval(refreshPov, 1000);
}

povBackBtn.addEventListener("click", () => {
  if (povTimer) clearInterval(povTimer);
  povTimer = null;
  povNurseId = null;
  showView("command");
  startPolling();
});

async function refreshPov() {
  if (!povNurseId) return;
  const data = await getJSON(`/api/live/nurses/${povNurseId}?shift_id=${shiftId}`);
  const nurse = data.nurse;
  povName.textContent = nurse.name;
  povRole.textContent = nurse.role;

  if (!nurse.task) {
    povNoTask.hidden = false;
    povTask.hidden = true;
  } else {
    povNoTask.hidden = true;
    povTask.hidden = false;
    povRoom.textContent = `Room ${nurse.task.room}`;
    povDesc.textContent = nurse.task.description;
    povGrade.textContent = `${GRADE_EMOJI[nurse.task.grade]} ${nurse.task.grade}`;

    if (nurse.task.status === "waiting") {
      povGoal.textContent = "";
      povStartBtn.hidden = false;
      povElapsedWrap.hidden = true;
    } else {
      povGoal.textContent = nurse.task.goal_minutes ? `Goal: ${nurse.task.goal_minutes} minutes` : "";
      povStartBtn.hidden = true;
      povElapsedWrap.hidden = false;
      const startedAt = new Date(nurse.task.dispatched_at);
      const elapsedSec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      const mm = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
      const ss = String(elapsedSec % 60).padStart(2, "0");
      povElapsed.textContent = `${mm}:${ss}`;
    }
  }

  if (data.up_next) {
    povUpNext.hidden = false;
    povUpNextBody.innerHTML = `<div>Room ${data.up_next.room}</div><div>${data.up_next.description}</div><div>${GRADE_EMOJI[data.up_next.grade]} ${data.up_next.grade}</div>`;
  } else {
    povUpNext.hidden = true;
  }
}

povStartBtn.addEventListener("click", async () => {
  await postJSON(`/api/live/nurses/${povNurseId}/start?shift_id=${shiftId}`);
  refreshPov();
});

povDoneBtn.addEventListener("click", async () => {
  await postJSON(`/api/live/nurses/${povNurseId}/done?shift_id=${shiftId}`);
  refreshPov();
});

// ---- init ----

// If a shift was already started earlier in this browser session (e.g. the
// coordinator navigated away to the Simulation Benchmark page and came back
// via the nav link), reconnect to it instead of asking them to log in again.
// Falls back to the normal login screen if there's nothing to restore, or
// the stored shift no longer exists on the server (e.g. after a restart).
async function restoreSession() {
  const storedName = sessionStorage.getItem(DOCTOR_STORAGE_KEY);
  if (storedName) headerDoctorName.textContent = `Dr. ${storedName}`;

  const storedShiftId = sessionStorage.getItem(SHIFT_STORAGE_KEY);
  if (!storedShiftId) {
    showView("login");
    return;
  }

  try {
    const state = await getJSON(`/api/live/state?shift_id=${storedShiftId}`);
    shiftId = storedShiftId;
    totalBeds = state.total_beds;
    mode = state.mode;
    modeToggleBtn.textContent = mode.toUpperCase();
    shiftSubtitle.textContent = `${state.total_beds} beds · ${state.nurses.length} nurses`;
    buildFloor();
    showView("command");
    startPolling();
  } catch (err) {
    sessionStorage.removeItem(SHIFT_STORAGE_KEY);
    showView("login");
  }
}

restoreSession();
