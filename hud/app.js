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

const JOB_POLL_MS = 1000;
const JOB_MAX_POLLS = 300;   // five minutes; a local model can be slow.

/** Follow a running skill job to its end, reporting what actually happened. */
async function followJob(jobId){
  for(let i = 0; i < JOB_MAX_POLLS; i++){
    await new Promise(r => setTimeout(r, JOB_POLL_MS));
    let job;
    try{
      job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    }catch(e){
      logLine("ASSISTANT", "lost contact with the backend while the skill was running.");
      return;
    }
    if(job.status === "running") continue;

    if(job.status === "failed"){
      logLine("ASSISTANT", `run failed — ${job.error || "no reason given"}`);
      return;
    }
    (job.reply || "").split("\n").filter(line => line.trim()).forEach(line => {
      logLine("ASSISTANT", line);
    });
    speak(job.reply);
    if(job.output){
      logLine("SYS", `written to vault: ${job.output}`);
    }else if(job.error){
      // The skill ran even though the note did not land; do not imply it did.
      logLine("SYS", job.error);
    }
    refreshVault().catch(() => {});
    return;
  }
  logLine("ASSISTANT", "still running after five minutes — check /api/jobs.");
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
    const reply = data.reply || "command complete";
    logLine("ASSISTANT", reply);
    if(data.job_id){
      // The run's own answer is worth speaking; the routing line is not.
      followJob(data.job_id);
    }else{
      speak(reply);
    }
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

function renderRuntime(cfg, health, voiceData){
  const list = $("runtimeList");
  clear(list);
  const checks = (health && health.checks) || {};
  const engine = (cfg.engine && cfg.engine.name) || UNKNOWN;

  // "CONFIGURED" rather than "READY": config names the engine, but the
  // server does not probe whether that agent is actually running. When
  // execution is on, say that much and no more — a run can still fail.
  const executes = !!(cfg.engine && cfg.engine.execution && cfg.engine.execution.enabled);
  list.appendChild(serviceRow(engine, executes ? "EXECUTION ON" : "CONFIGURED", "", "ok"));
  list.appendChild(serviceRow(
    "Obsidian Vault",
    checks.vault ? "RW" : "MISSING",
    checks.vault ? "" : "warn",
    checks.vault ? "ok" : "warn"
  ));
  // Voice reports what config actually turned on. "ON" means an adapter
  // is configured, not that the tool behind it has been proven to work.
  const stt = (voiceData && voiceData.stt) || {};
  const tts = (voiceData && voiceData.tts) || {};
  list.appendChild(serviceRow(
    "Local STT",
    stt.enabled ? `ON · ${String(stt.adapter).toUpperCase()}` : "NOT WIRED",
    stt.enabled ? "" : "off",
    stt.enabled ? "ok" : ""
  ));
  list.appendChild(serviceRow(
    "Local TTS",
    tts.enabled ? `ON · ${String(tts.adapter).toUpperCase()}` : "NOT WIRED",
    tts.enabled ? "" : "off",
    tts.enabled ? "ok" : ""
  ));
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

function renderFreshness(snapshot){
  // A prepared value with no age is a number you cannot trust, so the
  // panel says how old the snapshot behind it is.
  const node = $("vaultFreshness");
  const age = snapshot && snapshot.age_ms;
  const motto = "IF IT ISN'T IN THE VAULT, IT DIDN'T HAPPEN";
  if(age === null || age === undefined){
    node.textContent = motto;
    node.title = "";
    return;
  }
  const seconds = age / 1000;
  const label = seconds < 1 ? "JUST NOW" : `${Math.round(seconds)}s AGO`;
  node.textContent = `SNAPSHOT ${label} · ${motto}`;
  node.title = snapshot.built_at ? `snapshot built ${snapshot.built_at}` : "";
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
  renderFreshness(null);
  // Voice state came from the API too, so it is unknown now.
  renderVoice(null);
  setAudioState(UNKNOWN, "dim");
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
  const [cfg, health, skillData, voiceData] = await Promise.all([
    api("/api/config"), api("/api/health").catch(e => null), api("/api/skills"),
    api("/api/voice").catch(e => null)
  ]);
  renderConfig(cfg);
  renderVoice(voiceData);
  renderRuntime(cfg, health, voiceData);
  renderSkills(skillData);
  await refreshVault();

  clear(terminal);
  logLine("SYS", "boot sequence complete.");
  logLine("SYS", "vault mounted: /raw /wiki /output");
  logLine("SYS", `${skillData.count} skills indexed, ${skillData.command_count} commands. No database attached.`);
  logLine("SYS", `engine: ${cfg.engine.name} · runtime: ${cfg.engine.runtime}`);
  if(voiceData && voiceData.error) logLine("SYS", `voice config: ${voiceData.error}`);
  logLine("SYS", voiceLine(voiceData));
  setAudioState("IDLE", "ok");
  logLine("ASSISTANT", "ready.");
  logLine("SYS", sttOn()
    ? "Hold SPACE to speak or enter a command."
    : "Enter a command. Voice is off — see README to wire local STT.");
}

async function refreshVault(){
  const [stats, activity, graph] = await Promise.all([
    api("/api/vault/stats"), api("/api/vault/activity"), api("/api/vault/graph")
  ]);
  renderVaultStats(stats);
  renderFeed(activity.rows || []);
  renderGraph(graph);
  renderFreshness(stats);
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

/* ---------- voice ---------- */

// The level meters show measured amplitude and nothing else. A bar that
// moves when no audio is flowing would be decoration dressed as data.
const LEVEL_BARS = 22;
const REST_PX = 2;
const PEAK_PX = 20;

function buildLevels(id){
  const host = $(id);
  clear(host);
  const bars = [];
  for(let i = 0; i < LEVEL_BARS; i++){
    const bar = document.createElement("i");
    bar.style.height = `${REST_PX}px`;
    host.appendChild(bar);
    bars.push(bar);
  }
  return bars;
}

const micBars = buildLevels("micLevel");
const ttsBars = buildLevels("ttsLevel");
const micLevels = new Array(LEVEL_BARS).fill(0);
const ttsLevels = new Array(LEVEL_BARS).fill(0);

/** Scroll one real reading onto a meter, oldest falling off the left. */
function pushLevel(bars, values, level){
  values.push(Math.max(0, Math.min(1, level || 0)));
  values.shift();
  for(let i = 0; i < bars.length; i++){
    bars[i].style.height = `${REST_PX + values[i] * PEAK_PX}px`;
  }
}

function restLevels(bars, values){
  values.fill(0);
  bars.forEach(bar => { bar.style.height = `${REST_PX}px`; });
}

function setAudioState(label, cls){
  audioState.textContent = label;
  audioState.className = cls || "";
}

// Null until /api/voice answers. Nothing here claims a capability the
// server has not reported.
let voiceState = null;
let muted = false;
try{ muted = localStorage.getItem("assistant.muted") === "1"; }catch(e){ /* private mode */ }

const STT_RATE = 16000;        // what transcribers expect
const MAX_RECORD_MS = 120000;  // keeps a clip inside the server's upload limit
const MIME_CHOICES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];

let micStream = null, recorder = null, chunks = [];
let meterCtx = null, meterTimer = null, recordTimer = null;

function sttOn(){ return !!(voiceState && voiceState.stt && voiceState.stt.enabled); }

/* --- microphone --- */

async function openMic(){
  if(micStream) return micStream;
  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
    // Browsers expose capture only in a secure context, which over plain
    // HTTP means localhost and nothing else.
    throw new Error("no microphone API here — browsers expose one only over https or on localhost");
  }
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}
  });
  return micStream;
}

function closeMic(){
  // Released after every utterance so the operating system's microphone
  // indicator goes out when nothing is being said.
  if(micStream){
    micStream.getTracks().forEach(track => track.stop());
    micStream = null;
  }
}

function rms(analyser, buffer){
  analyser.getByteTimeDomainData(buffer);
  let sum = 0;
  for(let i = 0; i < buffer.length; i++){
    const sample = (buffer[i] - 128) / 128;
    sum += sample * sample;
  }
  return Math.sqrt(sum / buffer.length);
}

function startMeter(stream){
  stopMeter();
  try{
    meterCtx = new (window.AudioContext || window.webkitAudioContext)();
    const analyser = meterCtx.createAnalyser();
    analyser.fftSize = 512;
    meterCtx.createMediaStreamSource(stream).connect(analyser);
    const buffer = new Uint8Array(analyser.fftSize);
    meterTimer = setInterval(() => pushLevel(micBars, micLevels, rms(analyser, buffer)), 60);
  }catch(e){
    // No meter beats a meter showing numbers it never measured.
    stopMeter();
  }
}

function stopMeter(){
  if(meterTimer){ clearInterval(meterTimer); meterTimer = null; }
  if(meterCtx){ meterCtx.close().catch(() => {}); meterCtx = null; }
  restLevels(micBars, micLevels);
}

/* --- recording, encoded to what transcribers read --- */

function pickMime(){
  if(!window.MediaRecorder || !MediaRecorder.isTypeSupported) return null;
  return MIME_CHOICES.find(type => MediaRecorder.isTypeSupported(type)) || null;
}

async function startRecording(){
  const stream = await openMic();
  if(!window.MediaRecorder) throw new Error("this browser cannot record audio");
  chunks = [];
  const mime = pickMime();
  recorder = new MediaRecorder(stream, mime ? {mimeType: mime} : undefined);
  recorder.ondataavailable = e => { if(e.data && e.data.size) chunks.push(e.data); };
  recorder.start();
  startMeter(stream);
}

function stopRecording(){
  return new Promise((resolve, reject) => {
    if(!recorder || recorder.state === "inactive"){ resolve(null); return; }
    recorder.onstop = () => resolve(new Blob(chunks, {type: recorder.mimeType || "audio/webm"}));
    recorder.onerror = e => reject((e && e.error) || new Error("recorder failed"));
    try{ recorder.stop(); }catch(e){ reject(e); }
  });
}

/** Re-encode the recording as the 16 kHz mono WAV transcribers expect,
 *  so the server needs no audio tooling of its own. */
async function toWav(blob){
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  let decoded;
  try{
    decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  }finally{
    ctx.close().catch(() => {});
  }
  const frames = Math.max(1, Math.round(decoded.duration * STT_RATE));
  const offline = new OfflineAudioContext(1, frames, STT_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  return encodeWav((await offline.startRendering()).getChannelData(0), STT_RATE);
}

/** 16-bit PCM in a RIFF container: 44 bytes of header, then samples. */
function encodeWav(samples, rate){
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const ascii = (at, chars) => {
    for(let i = 0; i < chars.length; i++) view.setUint8(at + i, chars.charCodeAt(i));
  };
  ascii(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  ascii(8, "WAVEfmt ");
  view.setUint32(16, 16, true);        // fmt chunk length
  view.setUint16(20, 1, true);         // PCM
  view.setUint16(22, 1, true);         // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);  // bytes per second
  view.setUint16(32, 2, true);         // bytes per frame
  view.setUint16(34, 16, true);        // bits per sample
  ascii(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let at = 44;
  for(let i = 0; i < samples.length; i++, at += 2){
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(at, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return new Blob([buffer], {type: "audio/wav"});
}

/* --- push to talk --- */

let pttActive = false;

function pttIdle(){
  if(!voiceState) return "HOLD SPACE // VOICE STATE UNKNOWN";
  return sttOn() ? "HOLD SPACE // PUSH TO TALK" : "HOLD SPACE // STT NOT WIRED";
}

/** One line for the boot log about what voice can actually do. */
function voiceLine(state){
  if(!state) return "voice: state unknown — /api/voice did not answer.";
  const stt = state.stt || {};
  const tts = state.tts || {};
  return [
    "voice",
    stt.enabled ? `stt: ${stt.adapter}` : "stt: off",
    !tts.enabled ? "tts: off"
      : tts.mode === "browser" ? "tts: browser voices" : `tts: ${tts.adapter}`
  ].join(" · ");
}

function setPTT(active){
  pttActive = active;
  ptt.classList.toggle("live", active);
  ptt.textContent = active ? "LISTENING // RELEASE SPACE TO ROUTE" : pttIdle();
}

async function beginTalking(){
  if(pttActive) return;
  if(!voiceState){
    logLine("SYS", "space held, but the backend has not reported voice state.");
    return;
  }
  if(!sttOn()){
    logLine("SYS", "space held, but local STT is not wired — no audio was captured.");
    return;
  }
  pttActive = true;   // claimed before awaiting, so a key repeat cannot double-start
  setPTT(true);
  setAudioState("LISTENING", "warn");
  try{
    await startRecording();
    recordTimer = setTimeout(() => {
      if(pttActive){
        logLine("SYS", "two minutes is the recording limit; routing what was captured.");
        endTalking();
      }
    }, MAX_RECORD_MS);
  }catch(e){
    setPTT(false);
    setAudioState("MIC BLOCKED", "warn");
    logLine("SYS", `microphone unavailable — ${e.message || e}`);
    closeMic();
  }
}

async function endTalking(){
  if(!pttActive) return;
  setPTT(false);
  if(recordTimer){ clearTimeout(recordTimer); recordTimer = null; }
  stopMeter();

  let blob = null;
  try{
    blob = await stopRecording();
  }catch(e){
    setAudioState("IDLE", "ok");
    logLine("SYS", `recording failed — ${e.message || e}`);
    closeMic();
    return;
  }
  closeMic();
  if(!blob || blob.size < 1024){
    setAudioState("IDLE", "ok");
    logLine("SYS", "nothing captured — hold SPACE a moment longer.");
    return;
  }

  setAudioState("TRANSCRIBING", "warn");
  try{
    const wav = await toWav(blob);
    const res = await fetch(`${API_BASE}/api/voice/stt`, {
      method: "POST",
      headers: {"Content-Type": "audio/wav"},
      body: wav
    });
    const data = await res.json().catch(() => ({}));
    if(!res.ok){
      setAudioState("STT FAILED", "warn");
      logLine("SYS", `transcription failed — ${data.error || res.status}`);
      return;
    }
    setAudioState("IDLE", "ok");
    runCommand(data.text);
  }catch(e){
    setAudioState("STT FAILED", "warn");
    logLine("SYS", `transcription failed — ${e.message || e}`);
  }
}

window.addEventListener("keydown", e => {
  if(e.code === "Space" && document.activeElement !== promptInput && !pttActive){
    e.preventDefault();
    beginTalking();
  }
});
window.addEventListener("keyup", e => {
  if(e.code === "Space" && pttActive){
    e.preventDefault();
    endTalking();
  }
});
ptt.addEventListener("mousedown", e => { e.preventDefault(); beginTalking(); });
window.addEventListener("mouseup", () => { if(pttActive) endTalking(); });

/* --- speech out --- */

/** Real amplitude envelope of the audio about to play, so the output
 *  meter shows the signal instead of an animation. */
async function envelope(blob){
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  try{
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    const data = decoded.getChannelData(0);
    const perSecond = 20;
    const slots = Math.max(1, Math.round(decoded.duration * perSecond));
    const span = Math.max(1, Math.floor(data.length / slots));
    const levels = new Array(slots);
    for(let i = 0; i < slots; i++){
      let sum = 0;
      const end = Math.min(data.length, (i + 1) * span);
      for(let j = i * span; j < end; j++) sum += data[j] * data[j];
      levels[i] = Math.min(1, Math.sqrt(sum / span) * 3);
    }
    return {levels, perSecond};
  }finally{
    ctx.close().catch(() => {});
  }
}

async function playWav(blob){
  let env = null;
  try{ env = await envelope(blob); }catch(e){ /* the meter is optional */ }
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  let timer = null;
  const finish = () => {
    if(timer){ clearInterval(timer); timer = null; }
    URL.revokeObjectURL(url);
    restLevels(ttsBars, ttsLevels);
    setAudioState("IDLE", "ok");
  };
  setAudioState("SPEAKING", "ok");
  await new Promise(resolve => {
    audio.onended = () => { finish(); resolve(); };
    audio.onerror = () => { finish(); resolve(); };
    if(env){
      timer = setInterval(() => {
        pushLevel(ttsBars, ttsLevels, env.levels[Math.floor(audio.currentTime * env.perSecond)]);
      }, 1000 / env.perSecond);
    }
    audio.play().catch(e => {
      logLine("SYS", `could not play speech — ${e.message || e}`);
      finish();
      resolve();
    });
  });
}

/** Browser synthesis, restricted to voices the browser calls on-device.
 *  A remote voice would ship the reply off this machine, which is the
 *  opposite of the point. */
function speakInBrowser(text){
  if(!window.speechSynthesis){
    logLine("SYS", "this browser has no speech synthesis.");
    return;
  }
  const local = speechSynthesis.getVoices().filter(v => v.localService);
  if(!local.length){
    logLine("SYS", "no on-device voice available; not speaking through a remote one.");
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = local[0];
  // speechSynthesis hands back no audio signal, so the output meter stays
  // at rest here rather than showing a level nothing measured.
  setAudioState("SPEAKING", "ok");
  utterance.onend = utterance.onerror = () => setAudioState("IDLE", "ok");
  speechSynthesis.speak(utterance);
}

async function speak(text){
  const tts = voiceState && voiceState.tts;
  if(!tts || !tts.enabled || muted || !tts.speak_replies || !text) return;
  if(tts.mode === "browser") return speakInBrowser(text);
  try{
    const res = await fetch(`${API_BASE}/api/voice/speak`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text})
    });
    if(!res.ok){
      const data = await res.json().catch(() => ({}));
      logLine("SYS", `speech failed — ${data.error || res.status}`);
      return;
    }
    await playWav(await res.blob());
  }catch(e){
    logLine("SYS", `speech failed — ${e.message || e}`);
  }
}

/* --- the audio panel, painted from what the server reports --- */

function renderVoice(state){
  voiceState = state;
  const stt = (state && state.stt) || {};
  const tts = (state && state.tts) || {};

  $("sttLabel").textContent = !state ? UNKNOWN : stt.enabled ? "LOCAL MIC" : "NOT WIRED";
  $("ttsLabel").textContent = !state ? UNKNOWN
    : !tts.enabled ? "NOT WIRED"
    : muted ? "MUTED"
    : tts.mode === "browser" ? "BROWSER VOICE" : "LOCAL VOICE";

  // Audio only ever goes to this HUD's own origin, so the route is a fact
  // about where that is — not a claim about the network as a whole.
  const host = location.hostname;
  const loopback = !host || host === "127.0.0.1" || host === "localhost" || host === "[::1]";
  const inBrowserOnly = tts.mode === "browser" && !stt.enabled;
  const live = !!(stt.enabled || tts.enabled);

  const route = $("audioRoute");
  const network = $("networkAudio");
  if(!state || !live){
    route.textContent = UNKNOWN;
    network.textContent = UNKNOWN;
    route.className = "dim";
    network.className = "dim";
  }else{
    route.textContent = inBrowserOnly ? "IN BROWSER" : loopback ? "ON-DEVICE" : `VIA ${host}`;
    route.className = inBrowserOnly || loopback ? "ok" : "warn";
    network.textContent = inBrowserOnly ? "NONE SENT"
      : loopback ? "LOOPBACK ONLY" : `SENT TO ${host}`;
    network.className = inBrowserOnly || loopback ? "ok" : "warn";
  }

  const btn = $("muteBtn");
  btn.textContent = !state ? UNKNOWN : !tts.enabled ? "NO TTS" : muted ? "MUTED" : "ON";
  btn.disabled = !(state && tts.enabled);
  // Refresh the idle label only. Repainting the panel mid-utterance — the
  // backend dropping, say — must not quietly clear the recording flag and
  // strand an open microphone.
  if(!pttActive) ptt.textContent = pttIdle();
}

$("muteBtn").addEventListener("click", () => {
  muted = !muted;
  try{ localStorage.setItem("assistant.muted", muted ? "1" : "0"); }catch(e){ /* private mode */ }
  if(muted && window.speechSynthesis) speechSynthesis.cancel();
  renderVoice(voiceState);
  logLine("SYS", muted ? "spoken replies muted." : "spoken replies on.");
});

function tick(){
  $("clock").textContent = nowTime();
  $("dateLabel").textContent = new Date()
    .toLocaleDateString([], {weekday:"short", day:"2-digit", month:"short"}).toUpperCase();
}
setInterval(tick,1000); tick();

setInterval(refreshVitals,5000);
setInterval(() => { if(online) refreshVault().catch(() => setOnline(false)); }, 30000);
refreshVitals();
