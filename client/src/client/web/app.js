const state = {
  live: null,
  history: [],
  profile: null,
  selectedId: null,
  mode: "live",
  ticks: [],
  decisions: [],
  chats: [],
  replayIndex: 0,
  playing: false,
  timer: null,
};

const SEPOLIA_CHAIN_ID = "0xaa36a7";
const AGENT_PUBLIC_KEY_TEXT_RECORD = "thelastprompt.agent_public_key";

const $ = (id) => document.getElementById(id);
const els = {
  publicKey: $("publicKey"),
  walletStatus: $("walletStatus"),
  ensNameInput: $("ensNameInput"),
  loginButton: $("loginButton"),
  storeProfileButton: $("storeProfileButton"),
  connection: $("connection"),
  refreshButton: $("refreshButton"),
  agentName: $("agentName"),
  tick: $("tick"),
  meters: $("meters"),
  inventory: $("inventory"),
  actionBudget: $("actionBudget"),
  validActions: $("validActions"),
  modeLabel: $("modeLabel"),
  simTitle: $("simTitle"),
  mapGrid: $("mapGrid"),
  thinking: $("thinking"),
  decisionMeta: $("decisionMeta"),
  chat: $("chat"),
  chatCount: $("chatCount"),
  history: $("history"),
  historyCount: $("historyCount"),
  playButton: $("playButton"),
  timeline: $("timeline"),
  timelineLabel: $("timelineLabel"),
};

els.refreshButton.addEventListener("click", refreshAll);
els.loginButton.addEventListener("click", loginWithMetaMask);
els.storeProfileButton.addEventListener("click", storeAgentKeyOnEns);
els.playButton.addEventListener("click", togglePlay);
els.timeline.addEventListener("input", () => {
  state.playing = false;
  stopTimer();
  state.replayIndex = Number(els.timeline.value);
  render();
});

refreshAll();
setInterval(refreshLive, 1200);
setInterval(refreshHistory, 7000);

async function refreshAll() {
  await Promise.all([refreshLive(), refreshHistory()]);
}

async function refreshLive() {
  try {
    state.live = await fetchJson("/api/live");
    state.profile = state.live.profile || state.profile;
    els.connection.textContent = "live";
    els.publicKey.textContent = `agent: ${profileLabel(state.profile, state.live.public_key)}`;
    renderWalletProfile();
    if (!state.selectedId && state.live.state?.sim_id) state.selectedId = state.live.state.sim_id;
    if (state.mode === "live") render();
  } catch (error) {
    els.connection.textContent = "offline";
  }
}

async function refreshHistory() {
  const payload = await fetchJson("/api/history/simulations");
  state.history = payload.simulations || [];
  renderHistory();
}

async function selectHistory(simId) {
  state.mode = "history";
  state.selectedId = simId;
  state.playing = false;
  stopTimer();
  const [ticks, decisions, chats] = await Promise.all([
    fetchJson(`/api/history/ticks?sim_id=${encodeURIComponent(simId)}`),
    fetchJson(`/api/history/decisions?sim_id=${encodeURIComponent(simId)}`),
    fetchJson(`/api/history/chats?sim_id=${encodeURIComponent(simId)}`),
  ]);
  state.ticks = ticks.ticks || [];
  state.decisions = decisions.decisions || [];
  state.chats = chats.chats || [];
  state.replayIndex = Math.max(0, state.ticks.length - 1);
  renderHistory();
  render();
}

function selectLive() {
  state.mode = "live";
  state.playing = false;
  stopTimer();
  renderHistory();
  render();
}

function render() {
  const snapshot = currentSnapshot();
  const simState = snapshot?.sim_state || state.live?.state || null;
  const decision = currentDecision(simState);
  const chats = currentChats(simState);

  if (!simState) {
    els.simTitle.textContent = "Waiting for state";
    els.agentName.textContent = "Agent";
    els.mapGrid.innerHTML = "";
    els.validActions.innerHTML = "";
    els.thinking.textContent = "No model output yet.";
    return;
  }

  const agent = simState.agent || {};
  els.modeLabel.textContent = state.mode === "live" ? "Live Sight" : "Replay";
  els.simTitle.textContent = `${shortKey(simState.sim_id)} · ${simState.phase || "day"} · ${simState.temp}C`;
  els.agentName.textContent = agentLabel(agent);
  els.tick.textContent = `tick ${simState.tick ?? 0}`;
  els.actionBudget.textContent = `budget ${agent.action_budget ?? "?"}`;
  els.timeline.max = Math.max(0, state.mode === "history" ? state.ticks.length - 1 : simState.sim_status?.max_ticks || 0);
  els.timeline.value = state.mode === "history" ? state.replayIndex : simState.tick || 0;
  els.timeline.disabled = state.mode !== "history";
  const frame = state.mode === "history" ? state.ticks[state.replayIndex] : null;
  const frameKind = frame?.kind ? ` · ${frame.kind}` : "";
  els.timelineLabel.textContent = state.mode === "history" ? `frame ${state.replayIndex + 1}/${state.ticks.length}${frameKind}` : "now";
  els.playButton.disabled = state.mode !== "history" || state.ticks.length <= 1;
  els.playButton.textContent = state.playing ? "Pause" : "Play";

  renderMeters(agent);
  renderInventory(agent);
  renderActions(simState.valid_actions || []);
  renderMap(simState);
  renderThinking(decision, simState);
  renderChat(chats, simState);
}

function currentSnapshot() {
  if (state.mode === "live") {
    return state.live?.state ? { sim_state: state.live.state, decision: state.live.latest_decision } : null;
  }
  const frame = state.ticks[state.replayIndex];
  return frame?.snapshot || null;
}

function currentDecision(simState) {
  if (state.mode === "live") return state.live?.latest_decision || null;
  if (!simState) return null;
  const tick = Number(simState.tick || 0);
  return state.decisions.filter((decision) => Number(decision.tick) <= tick).at(-1) || null;
}

function currentChats(simState) {
  if (state.mode === "live") return state.live?.chat_log || [];
  if (!simState) return [];
  const tick = Number(simState.tick || 0);
  return state.chats.filter((chat) => Number(chat.tick) <= tick).slice(-80);
}

function renderMeters(agent) {
  els.meters.innerHTML = [
    meter("health", agent.health),
    meter("hunger", 100 - Number(agent.hunger || 0)),
    meter("thirst", 100 - Number(agent.thirst || 0)),
    meter("warmth", agent.warmth),
    meter("mental", agent.mental_health),
  ].join("");
}

function renderInventory(agent) {
  const inventory = agent.inventory || {};
  const items = Object.entries(inventory).filter(([, amount]) => Number(amount) > 0);
  els.inventory.innerHTML = [
    `<span class="pill">carry ${agent.inventory_weight ?? 0}/${agent.carry_capacity ?? "?"}</span>`,
    ...items.map(([item, amount]) => `<span class="pill">${escapeHtml(item)} ${amount}</span>`),
  ].join("");
}

function renderActions(actions) {
  els.validActions.innerHTML = actions.length ? actions.map((action) => `
    <div class="action">
      <strong>${escapeHtml(action.action)} · ${action.budget}</strong>
      <span class="muted">${escapeHtml(action.description || "")}</span>
    </div>
  `).join("") : `<div class="muted">No actions currently available.</div>`;
}

function renderMap(simState) {
  const tiles = (simState.visible_map || []).filter((tile) => Number.isInteger(tile.x) && Number.isInteger(tile.y));
  if (!tiles.length) {
    els.mapGrid.innerHTML = `<div class="muted">No visible tiles.</div>`;
    return;
  }

  const xs = tiles.map((tile) => tile.x);
  const ys = tiles.map((tile) => tile.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const byPos = new Map(tiles.map((tile) => [`${tile.x},${tile.y}`, tile]));
  els.mapGrid.style.gridTemplateColumns = `repeat(${maxX - minX + 1}, minmax(0, 1fr))`;

  const cells = [];
  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      const tile = byPos.get(`${x},${y}`);
      cells.push(tile ? tileHtml(tile, simState.agent) : `<div></div>`);
    }
  }
  els.mapGrid.innerHTML = cells.join("");
}

function tileHtml(tile, selfAgent) {
  const resources = Object.values(tile.resources || {}).reduce((sum, amount) => sum + Number(amount || 0), 0);
  const occupants = (tile.occupants || [])
    .filter((agent) => agent.alive !== false)
    .map((agent) => {
      const self = agent.id === selfAgent?.id || agent.public_key === selfAgent?.public_key;
      const label = self ? "You" : agentLabel(agent);
      return `<span class="agent-dot" title="${escapeHtml(label)}">${self ? "@" : escapeHtml(compactLabel(label))}</span>`;
    })
    .join("");
  const shelters = (tile.shelters || []).length;
  return `
    <div class="tile ${tile.type} ${tile.hazard ? "hazard" : ""}">
      <span class="coords">${tile.x},${tile.y}</span>
      <span class="shelter">${shelters ? `S${shelters}` : ""}</span>
      <span class="tile-type">${tile.type.slice(0, 1).toUpperCase()}</span>
      <span class="occupants">${occupants}</span>
      <span class="resources">${resources ? `R${resources}` : ""}</span>
    </div>
  `;
}

function renderThinking(decision, simState) {
  if (!decision) {
    els.decisionMeta.textContent = "none";
    els.thinking.textContent = "No decision recorded yet.";
    return;
  }
  const actions = decision.actions || decision.actions_json || [];
  const budgets = decision.phase_budgets || {};
  const actionBudget = Number(budgets.action_budget);
  const budgetText = Number.isFinite(actionBudget) ? ` · action ${actionBudget.toFixed(2)}` : "";
  els.decisionMeta.textContent = `tick ${decision.tick ?? "?"} · ${actions.length || 0} actions${budgetText}`;
  const reasoning = decision.reasoning || "No reasoning returned.";
  const summary = decision.talk_summary || decision.plan || "";
  const planText = summary ? `Talk summary:\n${summary}\n\n` : "";
  const actionText = actions.map((action) => `- ${decisionActionText(action, simState)}`).join("\n");
  els.thinking.textContent = `${planText}${reasoning}\n\nActions:\n${actionText || "- wait"}`;
}

function renderChat(chats, simState) {
  els.chatCount.textContent = String(chats.length);
  els.chat.innerHTML = chats.length ? chats.slice().reverse().map((chat) => `
    <div class="feed-line">
      <strong>${escapeHtml(chat.direction || "?")} · tick ${chat.tick ?? "?"}</strong>
      <span class="muted">${escapeHtml(agentLabelFromPublicKey(simState, chat.peer) || chat.peer || "?")}: ${escapeHtml(chat.message || "")}</span>
    </div>
  `).join("") : `<div class="muted">No chat yet.</div>`;
}

function renderHistory() {
  els.historyCount.textContent = `${state.history.length} sims`;
  els.history.innerHTML = [
    state.live?.state ? `<button class="history-item ${state.mode === "live" ? "active" : ""}" id="liveSelect"><strong>Live</strong><span class="muted">${shortKey(state.live.state.sim_id)} · tick ${state.live.state.tick} · ${state.live.state.phase || "day"}</span></button>` : "",
    ...state.history.map((sim) => `
      <button class="history-item ${state.mode === "history" && state.selectedId === sim.sim_id ? "active" : ""}" data-sim="${sim.sim_id}">
        <strong>${shortKey(sim.sim_id)}</strong>
        <span class="muted">${sim.status} · ${sim.summary?.phase || "day"} · ${new Date(sim.updated_at * 1000).toLocaleTimeString()}</span>
      </button>
    `),
  ].join("") || `<div class="muted">No stored states yet.</div>`;
  const live = document.getElementById("liveSelect");
  if (live) live.addEventListener("click", selectLive);
  els.history.querySelectorAll("[data-sim]").forEach((node) => {
    node.addEventListener("click", () => selectHistory(node.dataset.sim));
  });
}

async function loginWithMetaMask() {
  if (!window.ethereum) {
    els.walletStatus.textContent = "wallet: MetaMask not found";
    return;
  }
  if (!window.ethers) {
    els.walletStatus.textContent = "wallet: ethers.js unavailable";
    return;
  }

  try {
    els.walletStatus.textContent = "wallet: connecting";
    await ensureSepolia();
    const challenge = await fetchJson("/api/profile/challenge");
    const provider = new ethers.BrowserProvider(window.ethereum);
    const signer = await provider.getSigner();
    const walletAddress = await signer.getAddress();
    const signature = await window.ethereum.request({
      method: "personal_sign",
      params: [challenge.message, walletAddress],
    });
    const recovered = ethers.verifyMessage(challenge.message, signature);
    if (!sameAddress(recovered, walletAddress)) throw new Error("signature mismatch");
    const ens = await resolveWalletEns(provider, walletAddress, els.ensNameInput.value);
    const profile = {
      agent_public_key: challenge.agent_public_key,
      wallet_address: walletAddress,
      ens_name: ens.name,
      chain_id: challenge.chain_id,
      signature,
      login_message: challenge.message,
      resolver_address: ens.resolverAddress,
      profile_text_key: AGENT_PUBLIC_KEY_TEXT_RECORD,
      profile_text_value: ens.agentPublicKey || "",
      connected_at: new Date().toISOString(),
    };
    const saved = await postJson("/api/profile", profile);
    state.profile = saved.profile || profile;
    renderWalletProfile();
  } catch (error) {
    els.walletStatus.textContent = `wallet: ${error.message || "login failed"}`;
  }
}

async function storeAgentKeyOnEns() {
  if (!state.profile?.ens_name || !state.live?.public_key || !window.ethereum || !window.ethers) return;

  try {
    els.walletStatus.textContent = "wallet: waiting for tx";
    await ensureSepolia();
    const provider = new ethers.BrowserProvider(window.ethereum);
    const signer = await provider.getSigner();
    const resolver = await provider.getResolver(state.profile.ens_name);
    const address = getResolverAddress(resolver);
    if (!address) throw new Error("ENS resolver not found");

    const contract = new ethers.Contract(
      address,
      ["function setText(bytes32 node,string key,string value)"],
      signer,
    );
    const tx = await contract.setText(
      ethers.namehash(state.profile.ens_name),
      AGENT_PUBLIC_KEY_TEXT_RECORD,
      state.live.public_key,
    );
    els.walletStatus.textContent = "wallet: tx sent";
    if (tx.wait) await tx.wait();
    let confirmedValue = state.live.public_key;
    try {
      const refreshedResolver = await provider.getResolver(state.profile.ens_name);
      confirmedValue = await refreshedResolver.getText(AGENT_PUBLIC_KEY_TEXT_RECORD) || confirmedValue;
    } catch (error) {
      confirmedValue = state.live.public_key;
    }
    const saved = await postJson("/api/profile", {
      ...state.profile,
      resolver_address: address,
      profile_text_key: AGENT_PUBLIC_KEY_TEXT_RECORD,
      profile_text_value: confirmedValue,
      profile_tx_hash: tx.hash,
    });
    state.profile = saved.profile || state.profile;
    renderWalletProfile();
  } catch (error) {
    els.walletStatus.textContent = `wallet: ${error.message || "tx failed"}`;
  }
}

async function ensureSepolia() {
  const chainId = await window.ethereum.request({ method: "eth_chainId" });
  if (String(chainId).toLowerCase() === SEPOLIA_CHAIN_ID) return;
  try {
    await window.ethereum.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: SEPOLIA_CHAIN_ID }],
    });
  } catch (error) {
    if (error.code !== 4902) throw error;
    await window.ethereum.request({
      method: "wallet_addEthereumChain",
      params: [{
        chainId: SEPOLIA_CHAIN_ID,
        chainName: "Sepolia",
        nativeCurrency: { name: "Sepolia Ether", symbol: "ETH", decimals: 18 },
        rpcUrls: ["https://rpc.sepolia.org"],
        blockExplorerUrls: ["https://sepolia.etherscan.io"],
      }],
    });
  }
}

async function resolveWalletEns(provider, walletAddress, preferredName = "") {
  const result = { name: "", resolverAddress: "", agentPublicKey: "" };
  let name = String(preferredName || "").trim().replace(/\.$/, "");
  if (name) {
    let preferredForward = "";
    try {
      preferredForward = await provider.resolveName(name);
    } catch (error) {
      return result;
    }
    if (!sameAddress(preferredForward, walletAddress)) return result;
  } else {
    try {
      name = await provider.lookupAddress(walletAddress);
    } catch (error) {
      return result;
    }
  }
  if (!name) return result;

  let forward = "";
  try {
    forward = await provider.resolveName(name);
  } catch (error) {
    return result;
  }
  if (!sameAddress(forward, walletAddress)) return result;

  result.name = name;
  let resolver = null;
  try {
    resolver = await provider.getResolver(name);
  } catch (error) {
    return result;
  }
  result.resolverAddress = getResolverAddress(resolver) || "";
  if (resolver) {
    try {
      result.agentPublicKey = await resolver.getText(AGENT_PUBLIC_KEY_TEXT_RECORD) || "";
    } catch (error) {
      result.agentPublicKey = "";
    }
  }
  return result;
}

function renderWalletProfile() {
  const profile = state.profile || {};
  const name = profileLabel(profile, state.live?.public_key);
  const wallet = profile.wallet_address ? shortKey(profile.wallet_address) : "disconnected";
  const textRecord = profile.profile_text_value === state.live?.public_key ? "stored" : "not stored";
  els.walletStatus.textContent = profile.wallet_address
    ? `wallet: ${name} · ${wallet} · ${textRecord}`
    : "wallet: disconnected";
  if (profile.ens_name && els.ensNameInput.value !== profile.ens_name) {
    els.ensNameInput.value = profile.ens_name;
  }
  els.storeProfileButton.hidden = !profile.ens_name || !state.live?.public_key;
}

function togglePlay() {
  if (state.mode !== "history" || state.ticks.length <= 1) return;
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

function meter(name, value) {
  const width = Math.max(0, Math.min(100, Number(value || 0)));
  return `
    <div class="meter">
      <label><span>${name}</span><span>${Math.round(width)}</span></label>
      <div class="bar ${name}"><span style="width:${width}%"></span></div>
    </div>
  `;
}

function shortKey(value) {
  if (!value) return "...";
  return String(value).length > 14 ? `${String(value).slice(0, 7)}...${String(value).slice(-4)}` : String(value);
}

function profileLabel(profile, fallbackPublicKey) {
  if (profile?.ens_name) return profile.ens_name;
  if (profile?.wallet_address) return shortKey(profile.wallet_address);
  return shortKey(fallbackPublicKey);
}

function agentLabel(agent) {
  if (!agent) return "A?";
  if (typeof agent !== "object") return `A${agent}`;
  if (agent.name) return String(agent.name);
  if (agent.ens_name) return String(agent.ens_name);
  if (agent.profile?.ens_name) return String(agent.profile.ens_name);
  if (agent.id !== undefined && agent.id !== null) return `A${agent.id}`;
  return shortKey(agent.public_key || "");
}

function compactLabel(label) {
  const text = String(label || "?");
  if (text.length <= 10) return text;
  const first = text.split(".")[0];
  if (first.length <= 10) return first;
  return `${first.slice(0, 7)}...`;
}

function agentLabelFromPublicKey(simState, publicKey) {
  if (!publicKey) return "";
  for (const agent of knownAgents(simState)) {
    if (agent.public_key === publicKey) return agentLabel(agent);
  }
  return shortKey(publicKey);
}

function decisionActionText(action, simState) {
  const name = action.action || JSON.stringify(action);
  const target = action.target;
  if (target?.x !== undefined) return `${name} (${target.x},${target.y})`;
  if (target?.name) return `${name} ${target.name}`;
  if (target?.ens_name) return `${name} ${target.ens_name}`;
  if (target?.public_key) return `${name} ${agentLabelFromPublicKey(simState, target.public_key)}`;
  if (typeof target === "string") {
    const label = agentLabelFromPublicKey(simState, target);
    return label ? `${name} ${label}` : name;
  }
  return name;
}

function knownAgents(simState) {
  const agents = [];
  if (simState?.agent) agents.push(simState.agent);
  for (const row of simState?.scoreboard || []) {
    agents.push({
      id: row.agent_id,
      name: row.name || row.ens_name,
      ens_name: row.ens_name,
      public_key: row.public_key,
      profile: row.profile,
    });
  }
  for (const tile of simState?.visible_map || []) {
    for (const occupant of tile.occupants || []) {
      if (occupant && typeof occupant === "object") agents.push(occupant);
    }
  }
  return agents;
}

function getResolverAddress(resolver) {
  return resolver?.address || resolver?.resolverAddress || "";
}

function sameAddress(a, b) {
  return Boolean(a && b && String(a).toLowerCase() === String(b).toLowerCase());
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

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}
