const API_BASE = window.ASSISTANT_API_BASE || "http://127.0.0.1:7777";

const $ = (id) => document.getElementById(id);
const terminal = $("terminal");
const promptInput = $("promptInput");
const ptt = $("ptt");
const audioState = $("audioState");

function nowTime(){
  return new Date().toLocaleTimeString([], {hour12:false});
}
function logLine(role, text){
  const cls = role === "YOU" ? "user" : role === "ASSISTANT" ? "assistant" : "sys";
  const row = document.createElement("div");
  row.className = "line";
  row.innerHTML = `<span class="time">[${nowTime()}]</span> <span class="${cls}">${role}</span> ${escapeHtml(text)}`;
  terminal.appendChild(row);
  terminal.scrollTop = terminal.scrollHeight;
}
function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
}

async function runCommand(command){
  if(!command.trim()) return;
  logLine("YOU", command);
  promptInput.value = "";
  try{
    const res = await fetch(`${API_BASE}/api/command`, {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({command})
    });
    if(!res.ok) throw new Error("offline");
    const data = await res.json();
    logLine("ASSISTANT", data.reply || "command complete");
  }catch(e){
    logLine("ASSISTANT", `[local shell] ${command} queued. Backend endpoint: POST /api/command`);
  }
}

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
    logLine("SYS", "PTT open — local STT capture started.");
  }
});
window.addEventListener("keyup", e => {
  if(e.code === "Space" && pttActive){
    e.preventDefault();
    setPTT(false);
    logLine("SYS", "PTT closed — route transcript to command engine.");
  }
});

function buildLevels(id, phase=0){
  const el = $(id);
  for(let i=0;i<22;i++){
    const bar = document.createElement("i");
    const h = 4 + Math.abs(Math.sin((i+phase)*.72))*17;
    bar.style.height = `${h}px`;
    el.appendChild(bar);
  }
}
buildLevels("micLevel");
buildLevels("ttsLevel",4);

function tick(){
  $("clock").textContent = nowTime();
  const d = new Date();
  $("dateLabel").textContent = d.toLocaleDateString([], {weekday:"short", day:"2-digit", month:"short"}).toUpperCase();
}
setInterval(tick,1000); tick();

async function refreshVitals(){
  try{
    const res = await fetch(`${API_BASE}/api/vitals`);
    if(!res.ok) throw new Error();
    const v = await res.json();
    [["cpu",v.cpu],["ram",v.ram],["disk",v.disk]].forEach(([name,val])=>{
      const n = Math.max(0,Math.min(100,Number(val)||0));
      $(`${name}Text`).textContent = `${n}%`;
      $(`${name}Bar`).style.width = `${n}%`;
    });
    $("footerStatus").textContent = "API: CONNECTED · VAULT: LOCAL · DB: NONE";
  }catch(e){
    // Fallback mode intentionally preserves the shell when the backend is not running.
  }
}
setInterval(refreshVitals,5000);
refreshVitals();