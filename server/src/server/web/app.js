const state = {
  live: null,
  archive: [],
  selectedId: null,
  mode: "live",
  ticks: [],
  events: [],
  actions: [],
  replayIndex: 0,
  playing: false,
  timer: null,
};

const $ = (id) => document.getElementById(id);

const els = {
  serverKey: $("serverKey"),
  liveStatus: $("liveStatus"),
  queueCount: $("queueCount"),
  archiveCount: $("archiveCount"),
  liveSims: $("liveSims"),
  archiveSims: $("archiveSims"),
  simTitle: $("simTitle"),
  modeLabel: $("modeLabel"),
  mapGrid: $("mapGrid"),
  agents: $("agents"),
  events: $("events"),
  actions: $("actions"),
  agentCount: $("agentCount"),
  eventCount: $("eventCount"),
  actionCount: $("actionCount"),
  playButton: $("playButton"),
  timeline: $("timeline"),
  tickLabel: $("tickLabel"),
  refreshButton: $("refreshButton"),
};

els.refreshButton.addEventListener("click", refreshAll);
els.playButton.addEventListener("click", togglePlay);
els.timeline.addEventListener("input", () => {
  state.playing = false;
  stopTimer();
  state.replayIndex = Number(els.timeline.value);
  render();
});

refreshAll();
setInterval(refreshLive, 1500);
setInterval(refreshArchive, 8000);

async function refreshAll() {
  await Promise.all([refreshLive(), refreshArchive()]);
}

async function refreshLive() {
  try {
    state.live = await fetchJson("/api/live");
    els.liveStatus.textContent = "live";
    els.serverKey.textContent = `server: ${shortKey(state.live.server_public_key)}`;
    renderLiveList();
    if (!state.selectedId && state.live.simulations.length) {
      selectLive(state.live.simulations[0].sim_id);
    }
    if (state.mode === "live") render();
  } catch (error) {
    els.liveStatus.textContent = "offline";
  }
}

async function refreshArchive() {
  const payload = await fetchJson("/api/history/simulations");
  state.archive = payload.simulations || [];
  renderArchiveList();
}

async function selectLive(simId) {
  state.mode = "live";
  state.selectedId = simId;
  state.playing = false;
  stopTimer();
  renderLiveList();
  renderArchiveList();
  render();
}

async function selectArchive(simId) {
  state.mode = "archive";
  state.selectedId = simId;
  state.playing = false;
  stopTimer();
  const [ticks, events, actions] = await Promise.all([
    fetchJson(`/api/history/ticks?sim_id=${encodeURIComponent(simId)}`),
    fetchJson(`/api/history/events?sim_id=${encodeURIComponent(simId)}`),
    fetchJson(`/api/history/actions?sim_id=${encodeURIComponent(simId)}`),
  ]);
  state.ticks = ticks.ticks || [];
  state.events = events.events || [];
  state.actions = actions.actions || [];
  state.replayIndex = Math.max(0, state.ticks.length - 1);
  renderLiveList();
  renderArchiveList();
  render();
}

function renderLiveList() {
  const sims = state.live?.simulations || [];
  els.queueCount.textContent = `${state.live?.queue?.length || 0} queued`;
  els.liveSims.innerHTML = sims.length ? sims.map((sim) => `
    <button class="item ${state.mode === "live" && state.selectedId === sim.sim_id ? "active" : ""}" data-live="${sim.sim_id}">
      <strong>${shortKey(sim.sim_id)}</strong>
      <span class="muted">tick ${sim.tick} · ${sim.alive_count}/${sim.agents.length} alive · ${sim.temp}C</span>
    </button>
  `).join("") : `<div class="muted">No active simulations.</div>`;
  els.liveSims.querySelectorAll("[data-live]").forEach((node) => {
    node.addEventListener("click", () => selectLive(node.dataset.live));
  });
}

function renderArchiveList() {
  els.archiveCount.textContent = `${state.archive.length} sims`;
  els.archiveSims.innerHTML = state.archive.length ? state.archive.map((sim) => {
    const summary = sim.summary || {};
    return `
      <button class="item ${state.mode === "archive" && state.selectedId === sim.sim_id ? "active" : ""}" data-archive="${sim.sim_id}">
        <strong>${shortKey(sim.sim_id)}</strong>
        <span class="muted">${sim.status} · tick ${summary.tick ?? "?"} · ${new Date(sim.updated_at * 1000).toLocaleTimeString()}</span>
      </button>
    `;
  }).join("") : `<div class="muted">No stored simulations yet.</div>`;
  els.archiveSims.querySelectorAll("[data-archive]").forEach((node) => {
    node.addEventListener("click", () => selectArchive(node.dataset.archive));
  });
}

function render() {
  const snapshot = currentSnapshot();
  if (!snapshot) {
    els.simTitle.textContent = "No simulation selected";
    els.modeLabel.textContent = "Waiting";
    els.mapGrid.innerHTML = "";
    els.agents.innerHTML = "";
    els.events.innerHTML = "";
    els.actions.innerHTML = "";
    return;
  }

  els.modeLabel.textContent = state.mode === "live" ? "Live View" : "Replay";
  els.simTitle.textContent = `${shortKey(snapshot.sim_id)} · tick ${snapshot.tick}`;
  els.tickLabel.textContent = `tick ${snapshot.tick}`;
  els.timeline.max = Math.max(0, state.mode === "archive" ? state.ticks.length - 1 : snapshot.max_ticks || 0);
  els.timeline.value = state.mode === "archive" ? state.replayIndex : snapshot.tick || 0;
  els.timeline.disabled = state.mode !== "archive";
  els.playButton.disabled = state.mode !== "archive" || state.ticks.length <= 1;
  els.playButton.textContent = state.playing ? "Pause" : "Play";

  renderMap(snapshot);
  renderAgents(snapshot);
  renderEvents(snapshot);
  renderActions(snapshot);
}

function currentSnapshot() {
  if (state.mode === "live") {
    return (state.live?.simulations || []).find((sim) => sim.sim_id === state.selectedId) || null;
  }
  const tick = state.ticks[state.replayIndex];
  return tick?.snapshot || null;
}

function renderMap(snapshot) {
  const rows = snapshot.map || [];
  const width = rows[0]?.length || 1;
  els.mapGrid.style.gridTemplateColumns = `repeat(${width}, minmax(0, 1fr))`;
  els.mapGrid.innerHTML = rows.flat().map((tile) => {
    const resources = Object.values(tile.resources || {}).reduce((sum, amount) => sum + Number(amount || 0), 0);
    const occupants = (tile.occupants || []).map((id) => `<span class="agent-dot">A${id}</span>`).join("");
    return `
      <div class="tile ${tile.type} ${tile.hazard ? "hazard" : ""}" title="${tile.type}${tile.hazard ? ` · ${tile.hazard}` : ""}">
        <span class="coords">${tile.x},${tile.y}</span>
        <span class="tile-type">${tile.type.slice(0, 1).toUpperCase()}</span>
        <span class="occupants">${occupants}</span>
        <span class="resources">${resources ? `R${resources}` : ""}</span>
      </div>
    `;
  }).join("");
}

function renderAgents(snapshot) {
  const agents = snapshot.agents || [];
  const alive = agents.filter((agent) => agent.alive).length;
  els.agentCount.textContent = `${alive} alive`;
  els.agents.innerHTML = agents.map((agent) => `
    <div class="agent-row ${agent.alive ? "" : "dead"}">
      <div>
        <strong>A${agent.id} ${agent.alive ? "" : "· dead"}</strong>
        <div class="muted">(${agent.pos.x},${agent.pos.y}) · ${agent.stance} · ${agent.inventory_weight}/${agent.carry_capacity} carry</div>
      </div>
      <div class="bars">
        ${bar("health", agent.health)}
        ${bar("hunger", 100 - agent.hunger)}
        ${bar("thirst", 100 - agent.thirst)}
        ${bar("warmth", agent.warmth)}
      </div>
    </div>
  `).join("");
}

function renderEvents(snapshot) {
  const events = state.mode === "archive"
    ? state.events.filter((event) => event.tick <= snapshot.tick).slice(-80)
    : snapshot.recent_events || [];
  els.eventCount.textContent = String(events.length);
  els.events.innerHTML = events.length ? events.slice().reverse().map((event) => `
    <div class="feed-line">
      <strong>${event.event_type || event.type || "event"} · tick ${event.tick}</strong>
      <span class="muted">${escapeHtml(event.message || "")}</span>
    </div>
  `).join("") : `<div class="muted">No events yet.</div>`;
}

function renderActions(snapshot) {
  const actions = state.mode === "archive"
    ? state.actions.filter((action) => action.tick <= snapshot.tick).slice(-80)
    : [];
  els.actionCount.textContent = String(actions.length);
  els.actions.innerHTML = actions.length ? actions.slice().reverse().map((entry) => {
    const action = entry.action || {};
    return `
      <div class="feed-line">
        <strong>A${entry.agent_id} · tick ${entry.tick}</strong>
        <span class="muted">${escapeHtml(action.action || "action")} ${escapeHtml(actionText(action))}</span>
      </div>
    `;
  }).join("") : `<div class="muted">Open an archived sim to inspect stored actions.</div>`;
}

function togglePlay() {
  if (state.mode !== "archive" || state.ticks.length <= 1) return;
  state.playing = !state.playing;
  if (state.playing) {
    state.timer = setInterval(() => {
      state.replayIndex = (state.replayIndex + 1) % state.ticks.length;
      render();
    }, 750);
  } else {
    stopTimer();
  }
  render();
}

function stopTimer() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

function bar(name, value) {
  const width = Math.max(0, Math.min(100, Number(value || 0)));
  return `<div class="bar ${name}" title="${name} ${Math.round(width)}"><span style="width:${width}%"></span></div>`;
}

function actionText(action) {
  if (action.target?.x !== undefined) return `(${action.target.x},${action.target.y})`;
  if (action.target?.id !== undefined) return `A${action.target.id}`;
  return [action.consumable, action.item].filter(Boolean).join(" ");
}

function shortKey(value) {
  if (!value) return "...";
  return String(value).length > 12 ? `${String(value).slice(0, 6)}...${String(value).slice(-4)}` : String(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}
