// The Assistant — HUD runtime.
//
// Every panel renders from the backend on :7777. When the backend is not
// running the HUD stays up and shows unknown values as "—": it never
// falls back to invented numbers.

const API_BASE = window.ASSISTANT_API_BASE
  || (location.protocol === "file:" ? "http://127.0.0.1:7777" : "");

const $ = (id) => document.getElementById(id);
const terminal = $("terminal");
const promptInput = $("promptInput");
const ptt = $("ptt");
const audioState = $("audioState");

const UNKNOWN = "—";
const SVG_NS = "http://www.w3.org/2000/svg";

let online = null; // null until the first probe resolves.

/* ---------- helpers ---------- */

function nowTime(){
  return new Date().toLocaleTimeString([], {hour12:false});
}

async function api(path, options){
  const res = await fetch(`${API_BASE}${path}`, options);
  if(!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function el(tag, className, text){
  const node = document.createElement(tag);
  if(className) node.className = className;
  if(text !== undefined) node.textContent = text;
  return node;
}

function clear(node){
  while(node.firstChild) node.removeChild(node.firstChild);
}

function compact(n){
  if(n === null || n === undefined) return UNKNOWN;
  if(n < 1000) return String(n);
  if(n < 1e6) return `${(n/1000).toFixed(1).replace(/\.0$/,"")}K`;
  return `${(n/1e6).toFixed(1).replace(/\.0$/,"")}M`;
}

function bytes(n){
  if(n === null || n === undefined) return UNKNOWN;
  const units = ["B","KB","MB","GB","TB"];
  let value = n, i = 0;
  while(value >= 1024 && i < units.length-1){ value /= 1024; i++; }
  return `${value < 10 && i > 0 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
}

/* ---------- terminal ---------- */

function logLine(role, text){
  const cls = role === "YOU" ? "user" : role === "ASSISTANT" ? "assistant" : "sys";
  const row = el("div", "line");
  row.appendChild(el("span", "time", `[${nowTime()}]`));
  row.appendChild(document.createTextNode(" "));
  row.appendChild(el("span", cls, role));
  row.appendChild(document.createTextNode(` ${text}`));
  terminal.appendChild(row);
  terminal.scrollTop = terminal.scrollHeight;
}

async function runCommand(command){
  if(!command.trim()) return;
  logLine("YOU", command);
  promptInput.value = "";
  try{
    const data = await api("/api/command", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({command})
    });
    logLine("ASSISTANT", data.reply || "command complete");
  }catch(e){
    logLine("ASSISTANT", `backend unreachable — '${command}' not routed.`);
  }
}

/* ---------- panels ---------- */

function renderConfig(cfg){
  const engine = cfg.engine || {};
  $("engineBadge").textContent = `ENGINE: ${(engine.name || UNKNOWN).toUpperCase()}`;
  $("engineBadge").title = engine.runtime ? `runtime: ${engine.runtime}` : "";

  const list = $("scheduleList");
  clear(list);
  (cfg.schedule || []).forEach(item => {
    const row = el("div", "schedule-item");
    row.appendChild(el("div", "schedule-time", item.time || ""));
    const text = el("div", "schedule-text", item.title || "");
    text.appendChild(el("small", null, item.detail || ""));
    row.appendChild(text);
    list.appendChild(row);
  });
}

function serviceRow(label, state, dotClass, stateClass){
  const row = el("div", "service");
  const left = el("span");
  left.appendChild(el("i", dotClass ? `dot ${dotClass}` : "dot"));
  left.appendChild(document.createTextNode(label));
  row.appendChild(left);
  row.appendChild(el("span", stateClass || "", state));
  return row;
}

function renderRuntime(cfg, health){
  const list = $("runtimeList");
  clear(list);
  const checks = (health && health.checks) || {};
  const engine = (cfg.engine && cfg.engine.name) || UNKNOWN;

  // "CONFIGURED" rather than "READY": config names the engine, but the
  // server does not probe whether that agent is actually running.
  list.appendChild(serviceRow(engine, "CONFIGURED", "", "ok"));
  list.appendChild(serviceRow(
    "Obsidian Vault",
    checks.vault ? "RW" : "MISSING",
    checks.vault ? "" : "warn",
    checks.vault ? "ok" : "warn"
  ));
  // Voice is not implemented yet; say so instead of showing it armed.
  list.appendChild(serviceRow("Local STT", "NOT WIRED", "off", ""));
  list.appendChild(serviceRow("Local TTS", "NOT WIRED", "off", ""));
  list.appendChild(serviceRow("OBEOS Link", "STANDBY", "warn", "warn"));
}

function renderSkills(data){
  const list = $("skillList");
  clear(list);
  $("skillCount").textContent = `${data.count} loaded`;
  $("statSkills").textContent = compact(data.count);
  (data.skills || []).forEach(skill => {
    const row = el("div", "service");
    row.appendChild(el("span", null, skill.file));
    row.appendChild(el("span", skill.loaded ? "ok" : "warn", skill.loaded ? "✓" : "!"));
    if(skill.description) row.title = skill.description;
    list.appendChild(row);
  });
  const collisions = Object.keys(data.collisions || {});
  if(collisions.length){
    logLine("SYS", `command collision: ${collisions.join(", ")}`);
  }
}

function setBar(name, value){
  const text = $(`${name}Text`);
  const bar = $(`${name}Bar`);
  if(value === null || value === undefined){
    text.textContent = UNKNOWN;
    bar.style.width = "0%";
    return;
  }
  const n = Math.max(0, Math.min(100, Number(value) || 0));
  text.textContent = `${n}%`;
  bar.style.width = `${n}%`;
  bar.className = `fill${n >= 90 ? " red" : n >= 70 ? " amber" : ""}`;
}

function renderVitals(v){
  setBar("cpu", v.cpu);
  setBar("ram", v.ram);
  setBar("disk", v.disk);
  $("uptime").textContent = v.uptime || UNKNOWN;
}

function renderVaultStats(stats){
  $("vaultSize").textContent = bytes(stats.bytes);
  $("vaultNotes").textContent = compact(stats.notes);
  $("vaultLinks").textContent = compact(stats.links);
  $("statNotes").textContent = compact(stats.notes);
  $("statLinks").textContent = compact(stats.links);
  $("statRaw").textContent = compact(stats.raw);
  $("statWiki").textContent = compact(stats.wiki);
  $("statOutput").textContent = compact(stats.output);
}

function renderFeed(rows){
  const feed = $("vaultFeed");
  clear(feed);
  if(!rows.length){
    feed.appendChild(el("div", "feed-row empty", "no notes in the vault yet."));
    return;
  }
  rows.forEach(row => {
    const line = el("div", "feed-row");
    line.appendChild(el("span", "time", row.time));
    line.appendChild(el("span", "type", row.type));
    const path = el("span", "path", row.path);
    path.title = row.path;
    line.appendChild(path);
    feed.appendChild(line);
  });
}

function renderGraph(graph){
  const svg = $("vaultGraph");
  clear(svg);
  const nodes = graph.nodes || [];
  if(!nodes.length){
    const empty = document.createElementNS(SVG_NS, "text");
    empty.setAttribute("class", "graph-label");
    empty.setAttribute("x", "165");
    empty.setAttribute("y", "88");
    empty.setAttribute("text-anchor", "middle");
    empty.textContent = "no linked notes yet";
    svg.appendChild(empty);
    return;
  }

  // Radial layout: most-connected note centred, neighbours on a ring.
  const cx = 165, cy = 85, radius = 58;
  const positions = {};
  nodes.forEach((node, i) => {
    if(i === 0){
      positions[node.id] = {x: cx, y: cy};
    }else{
      const angle = (2 * Math.PI * (i - 1)) / Math.max(1, nodes.length - 1) - Math.PI / 2;
      positions[node.id] = {
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * (radius * 0.72)
      };
    }
  });

  (graph.edges || []).forEach(edge => {
    const a = positions[edge.source], b = positions[edge.target];
    if(!a || !b) return;
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("class", "edge");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    svg.appendChild(line);
  });

  nodes.forEach((node, i) => {
    const pos = positions[node.id];
    const circle = document.createElementNS(SVG_NS, "circle");
    const folder = node.folder === "raw" ? " raw" : node.folder === "output" ? " output" : "";
    circle.setAttribute("class", `node${folder}`);
    circle.setAttribute("cx", pos.x);
    circle.setAttribute("cy", pos.y);
    circle.setAttribute("r", i === 0 ? 9 : 7);
    svg.appendChild(circle);

    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("class", "graph-label");
    if(i === 0){
      // The centred node has neighbours on both sides, so its label sits
      // below it rather than colliding with one of them.
      label.setAttribute("x", pos.x);
      label.setAttribute("y", pos.y + 20);
      label.setAttribute("text-anchor", "middle");
    }else{
      const toLeft = pos.x > cx + 1;
      label.setAttribute("x", pos.x + (toLeft ? 11 : -11));
      label.setAttribute("y", pos.y + 2);
      label.setAttribute("text-anchor", toLeft ? "start" : "end");
    }
    label.textContent = node.id.length > 20 ? `${node.id.slice(0, 19)}…` : node.id;
    label.appendChild(document.createElementNS(SVG_NS, "title")).textContent = node.id;
    svg.appendChild(label);
  });
}

function blankPanels(){
  ["cpu","ram","disk"].forEach(name => setBar(name, null));
  ["uptime","vaultSize","vaultNotes","vaultLinks",
   "statNotes","statLinks","statRaw","statWiki","statOutput","statSkills"]
    .forEach(id => { $(id).textContent = UNKNOWN; });
  // The engine name comes from the API too, so it is unknown while the
  // backend is unreachable — showing the last value would imply it was
  // still confirmed.
  $("engineBadge").textContent = `ENGINE: ${UNKNOWN}`;
  $("engineBadge").title = "";
  $("skillCount").textContent = UNKNOWN;
  clear($("skillList"));
  clear($("runtimeList"));
  $("runtimeList").appendChild(serviceRow("Backend", "OFFLINE", "off", "warn"));
}

/* ---------- lifecycle ---------- */

function setOnline(state, detail){
  if(online === state) return;
  online = state;
  $("footerStatus").textContent = state
    ? `API: CONNECTED · VAULT: LOCAL · DB: NONE`
    : `API: FALLBACK MODE · VAULT: LOCAL · DB: NONE`;
  if(!state){
    blankPanels();
    logLine("SYS", detail || `backend unreachable at ${API_BASE || location.origin}.`);
  }
}

async function boot(){
  const [cfg, health, skillData] = await Promise.all([
    api("/api/config"), api("/api/health").catch(e => null), api("/api/skills")
  ]);
  renderConfig(cfg);
  renderRuntime(cfg, health);
  renderSkills(skillData);
  await refreshVault();

  clear(terminal);
  logLine("SYS", "boot sequence complete.");
  logLine("SYS", "vault mounted: /raw /wiki /output");
  logLine("SYS", `${skillData.count} skills indexed, ${skillData.command_count} commands. No database attached.`);
  logLine("SYS", `engine: ${cfg.engine.name} · runtime: ${cfg.engine.runtime}`);
  logLine("ASSISTANT", "ready.");
  logLine("SYS", "Hold SPACE to speak or enter a command.");
}

async function refreshVault(){
  const [stats, activity, graph] = await Promise.all([
    api("/api/vault/stats"), api("/api/vault/activity"), api("/api/vault/graph")
  ]);
  renderVaultStats(stats);
  renderFeed(activity.rows || []);
  renderGraph(graph);
}

async function refreshVitals(){
  try{
    renderVitals(await api("/api/vitals"));
    if(online !== true){
      setOnline(true);
      await boot();
    }
  }catch(e){
    setOnline(false);
  }
}

/* ---------- input ---------- */

document.querySelectorAll(".cmd").forEach(btn => {
  btn.addEventListener("click", () => runCommand(btn.dataset.command));
});
$("promptForm").addEventListener("submit", e => {
  e.preventDefault();
  runCommand(promptInput.value);
});

let pttActive = false;
function setPTT(active){
  pttActive = active;
  ptt.classList.toggle("live", active);
  ptt.textContent = active ? "LISTENING // RELEASE SPACE TO ROUTE" : "HOLD SPACE // PUSH TO TALK";
  audioState.textContent = active ? "LISTENING" : "IDLE";
  audioState.className = active ? "warn" : "ok";
}
window.addEventListener("keydown", e => {
  if(e.code === "Space" && document.activeElement !== promptInput && !pttActive){
    e.preventDefault();
    setPTT(true);
    logLine("SYS", "PTT open — local STT not wired; no audio captured.");
  }
});
window.addEventListener("keyup", e => {
  if(e.code === "Space" && pttActive){
    e.preventDefault();
    setPTT(false);
  }
});

function buildLevels(id, phase=0){
  const el = $(id);
  for(let i=0;i<22;i++){
    const bar = document.createElement("i");
    bar.style.height = `${4 + Math.abs(Math.sin((i+phase)*.72))*17}px`;
    el.appendChild(bar);
  }
}
buildLevels("micLevel");
buildLevels("ttsLevel",4);

function tick(){
  $("clock").textContent = nowTime();
  $("dateLabel").textContent = new Date()
    .toLocaleDateString([], {weekday:"short", day:"2-digit", month:"short"}).toUpperCase();
}
setInterval(tick,1000); tick();

setInterval(refreshVitals,5000);
setInterval(() => { if(online) refreshVault().catch(() => setOnline(false)); }, 30000);
refreshVitals();
