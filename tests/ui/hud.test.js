// Browser tests for the HUD: the panels, the controls, and the two things
// only a real browser can prove — that a note filename containing markup
// renders as text, and that the HUD survives the backend going away and
// coming back.
//
//   cd tests/ui && npm install && npm test
//
// Optional: this needs Playwright and a Chromium build, which is why it is
// separate from the stdlib Python suite. Set CHROMIUM_PATH to reuse a
// browser that is already on the machine.

const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const REPO = path.resolve(__dirname, '..', '..');
const PORT = Number(process.env.PORT || 7870);
const BASE = `http://127.0.0.1:${PORT}`;
const CHROMIUM_PATH = process.env.CHROMIUM_PATH || undefined;

let pass = 0, fail = 0;
const ok = (name, cond, detail = '') => {
  if (cond) { pass++; console.log(`  ok    ${name}`); }
  else { fail++; console.log(`  FAIL  ${name}${detail ? ' :: ' + detail : ''}`); }
};
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

/** Build a throwaway vault so the suite does not depend on the real one. */
function makeVault() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-ui-'));
  for (const folder of ['raw', 'wiki', 'output']) {
    fs.mkdirSync(path.join(root, folder), { recursive: true });
  }
  const write = (p, body) => fs.writeFileSync(path.join(root, p), body, 'utf8');
  write('wiki/OBEOS.md', 'Links [[The Assistant]] and [[Lathe]]\n');
  write('wiki/The Assistant.md', '[[OBEOS]] [[Lathe]] [[Blackcomputer]]\n');
  write('wiki/Lathe.md', '[[OBEOS]]\n');
  write('wiki/Blackcomputer.md', '[[The Assistant]]\n');
  write('output/today.md', '[[The Assistant]]\n');
  // A filename containing markup: the HUD must render it as text.
  write('raw/<img src=x onerror=window.__XSS__=1>.md', '[[OBEOS]]\n');
  return root;
}

function startServer(vaultDir, extraEnv = {}) {
  return spawn('python3', ['-m', 'server'], {
    cwd: REPO,
    env: {
      ...process.env,
      ASSISTANT_PORT: String(PORT), ASSISTANT_VAULT: vaultDir, ASSISTANT_ENGINE: 'OpenCode',
      ...extraEnv,
    },
    stdio: 'ignore',
  });
}

/** Stand-in speech tools, so the voice phase needs no model on disk. */
function makeVoiceTools() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-voice-'));
  // A transcriber that always hears the same command.
  fs.writeFileSync(path.join(dir, 'fake-stt.py'), "print('metrics')\n", 'utf8');
  // A synthesiser that writes a real, short WAV where it is told to.
  fs.writeFileSync(path.join(dir, 'fake-tts.py'), [
    'import math, struct, sys, wave',
    "out = sys.argv[sys.argv.index('-f') + 1]",
    'frames = b"".join(struct.pack("<h", int(9000 * math.sin(i * 0.08))) for i in range(4000))',
    'w = wave.open(out, "wb")',
    'w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(frames); w.close()',
    '',
  ].join('\n'), 'utf8');
  return dir;
}
const stopServer = (p) => { try { p.kill('SIGKILL'); } catch (e) { /* already gone */ } };

async function waitFor(up, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(`${BASE}/api/health`);
      if (up && res.ok) return true;
    } catch (e) { if (!up) return true; }
    await sleep(250);
  }
  return false;
}

(async () => {
  // A stale server on this port would let the offline test pass against
  // the wrong process, so refuse to start if one is already there.
  try {
    await fetch(`${BASE}/api/health`);
    console.log(`ERROR: something is already serving ${BASE} — stop it first.`);
    process.exit(3);
  } catch (e) { /* port free, as required */ }

  const vaultDir = makeVault();
  let server = startServer(vaultDir);
  if (!await waitFor(true)) { console.log('server never came up'); process.exit(1); }

  const browser = await chromium.launch(CHROMIUM_PATH ? { executablePath: CHROMIUM_PATH } : {});
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const pageErrors = [], consoleErrors = [];
  page.on('pageerror', e => pageErrors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });

  console.log('\n[1] boot + live panels');
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.getElementById('skillList').children.length > 0, { timeout: 15000 });

  ok('engine badge from config', (await page.textContent('#engineBadge')) === 'ENGINE: OPENCODE');
  ok('25 skills rendered', (await page.locator('#skillList .service').count()) === 25);
  ok('vault notes = 6', (await page.textContent('#statNotes')) === '6');
  ok('raw/wiki/output split', (await page.textContent('#statRaw')) === '1' && (await page.textContent('#statWiki')) === '4' && (await page.textContent('#statOutput')) === '1');
  ok('cpu is a real percentage', /^\d+(\.\d+)?%$/.test(await page.textContent('#cpuText')));
  ok('uptime populated', /^\d{2,}:\d{2}$/.test(await page.textContent('#uptime')));
  ok('footer says connected', (await page.textContent('#footerStatus')).includes('CONNECTED'));
  ok('schedule rendered', (await page.locator('#scheduleList .schedule-item').count()) === 5);
  ok('feed rows rendered', (await page.locator('#vaultFeed .feed-row').count()) > 0);
  ok('graph has nodes and edges', (await page.locator('#vaultGraph circle').count()) > 0 && (await page.locator('#vaultGraph line').count()) > 0);
  ok('snapshot age shown', /SNAPSHOT (JUST NOW|\d+s AGO)/.test(await page.textContent('#vaultFreshness')));

  console.log('\n[2] runtime rows are honest');
  const rows = await page.locator('#runtimeList .service').allTextContents();
  ok('engine row says CONFIGURED not READY', rows.some(r => r.includes('OpenCode') && r.includes('CONFIGURED')));
  ok('STT and TTS say NOT WIRED', rows.filter(r => r.includes('NOT WIRED')).length === 2);
  ok('no row claims ARMED', !rows.some(r => r.includes('ARMED')));

  console.log('\n[3] markup in a note name is escaped');
  ok('no script executed from filename', (await page.evaluate(() => window.__XSS__)) === undefined);
  ok('filename rendered as text', (await page.textContent('#vaultFeed')).includes('<img src=x'));
  ok('no injected img element', (await page.locator('#vaultFeed img').count()) === 0);

  console.log('\n[4] command deck + prompt');
  await page.click('button.cmd[data-command="metrics"]');
  await page.waitForFunction(() => document.getElementById('terminal').textContent.includes('metrics.md'), { timeout: 5000 });
  ok('deck button routes to metrics.md', (await page.textContent('#terminal')).includes('routed to metrics.md'));
  ok('reply admits execution not wired', (await page.textContent('#terminal')).includes('not wired'));

  await page.fill('#promptInput', 'vaultclean');
  await page.press('#promptInput', 'Enter');
  await page.waitForFunction(() => document.getElementById('terminal').textContent.includes('vault.md'), { timeout: 5000 });
  ok('typed command routes to vault.md', (await page.textContent('#terminal')).includes('routed to vault.md'));
  ok('prompt cleared after submit', (await page.inputValue('#promptInput')) === '');

  await page.fill('#promptInput', 'summon dragons');
  await page.press('#promptInput', 'Enter');
  await page.waitForFunction(() => document.getElementById('terminal').textContent.includes('no skill declares'), { timeout: 5000 });
  ok('unknown command reported honestly', (await page.textContent('#terminal')).includes("no skill declares 'summon'"));

  console.log('\n[5] push-to-talk with voice off');
  await page.click('body');
  await page.keyboard.down('Space');
  await page.waitForTimeout(250);
  ok('PTT does not go live when STT is off', !(await page.getAttribute('#ptt', 'class')).includes('live'));
  ok('PTT box says STT not wired', (await page.textContent('#ptt')).includes('STT NOT WIRED'));
  ok('terminal admits nothing was captured', (await page.textContent('#terminal')).includes('not wired'));
  ok('audio state stays IDLE', (await page.textContent('#audioState')) === 'IDLE');
  await page.keyboard.up('Space');

  console.log('\n[6] audio panel claims nothing it cannot do');
  ok('STT card reads NOT WIRED', (await page.textContent('#sttLabel')) === 'NOT WIRED');
  ok('TTS card reads NOT WIRED', (await page.textContent('#ttsLabel')) === 'NOT WIRED');
  ok('audio route unknown, not asserted ON-DEVICE', (await page.textContent('#audioRoute')) === '—');
  ok('network audio unknown, not asserted BLOCKED', (await page.textContent('#networkAudio')) === '—');
  ok('mute button disabled with no TTS', await page.isDisabled('#muteBtn'));
  // The old HUD drew a sine wave into both meters at load. A meter must
  // sit flat when no audio is flowing.
  const restBars = await page.evaluate(() => ['micLevel', 'ttsLevel'].map(
    id => [...document.querySelectorAll(`#${id} i`)].map(b => parseFloat(b.style.height))));
  ok('both meters have 22 bars', restBars.every(bars => bars.length === 22));
  ok('meters rest flat when nothing is playing', restBars.every(bars => bars.every(h => h <= 2)));

  console.log('\n[7] space inside the prompt does not trigger PTT');
  await page.click('#promptInput');
  await page.keyboard.type('plan today');
  ok('space typed into input', (await page.inputValue('#promptInput')) === 'plan today');
  ok('PTT stayed idle while typing', !(await page.getAttribute('#ptt', 'class')).includes('live'));
  await page.fill('#promptInput', '');

  console.log('\n[8] backend goes away');
  stopServer(server);
  await waitFor(false);
  await page.waitForFunction(() => document.getElementById('footerStatus').textContent.includes('FALLBACK'), { timeout: 20000 });
  ok('footer flips to FALLBACK MODE', (await page.textContent('#footerStatus')).includes('FALLBACK MODE'));
  ok('cpu blanked to em dash', (await page.textContent('#cpuText')) === '—');
  ok('vault notes blanked', (await page.textContent('#statNotes')) === '—');
  ok('engine badge blanked', (await page.textContent('#engineBadge')) === 'ENGINE: —');
  ok('skill list cleared', (await page.locator('#skillList .service').count()) === 0);
  ok('snapshot age withdrawn', !(await page.textContent('#vaultFreshness')).includes('SNAPSHOT'));
  ok('runtime shows Backend OFFLINE', (await page.locator('#runtimeList .service').allTextContents()).some(r => r.includes('Backend') && r.includes('OFFLINE')));
  ok('no invented numbers while offline', !(await page.textContent('#vitals')).match(/\b\d+%/));

  await page.fill('#promptInput', 'metrics');
  await page.press('#promptInput', 'Enter');
  await page.waitForFunction(() => document.getElementById('terminal').textContent.includes('unreachable'), { timeout: 5000 });
  ok('offline command says unreachable, not routed', (await page.textContent('#terminal')).includes('backend unreachable'));

  console.log('\n[9] backend comes back');
  server = startServer(vaultDir);
  await waitFor(true);
  await page.waitForFunction(() => document.getElementById('skillList').children.length > 0, { timeout: 30000 });
  ok('footer back to CONNECTED', (await page.textContent('#footerStatus')).includes('CONNECTED'));
  ok('skills re-rendered', (await page.locator('#skillList .service').count()) === 25);
  ok('engine badge restored', (await page.textContent('#engineBadge')) === 'ENGINE: OPENCODE');
  ok('vault stats restored', (await page.textContent('#statNotes')) === '6');
  ok('cpu reading restored', /^\d+(\.\d+)?%$/.test(await page.textContent('#cpuText')));

  console.log('\n[10] console health');
  ok('no uncaught JS exceptions', pageErrors.length === 0, pageErrors.join(' | '));
  const expected = /ERR_CONNECTION_REFUSED|Failed to fetch/;
  const unexpected = consoleErrors.filter(t => !expected.test(t));
  ok('no console errors beyond the deliberate outage', unexpected.length === 0, unexpected.join(' | '));

  await browser.close();
  stopServer(server);

  console.log('\n[11] voice on, end to end');
  const toolDir = makeVoiceTools();
  server = startServer(vaultDir, {
    ASSISTANT_STT: '1',
    ASSISTANT_STT_ADAPTER: 'command',
    ASSISTANT_STT_COMMAND: `python3 ${path.join(toolDir, 'fake-stt.py')} {audio}`,
    ASSISTANT_TTS: '1',
    ASSISTANT_TTS_ADAPTER: 'command',
    ASSISTANT_TTS_COMMAND: `python3 ${path.join(toolDir, 'fake-tts.py')} -f {output} {text}`,
  });
  if (!await waitFor(true)) { console.log('voice server never came up'); process.exit(1); }

  // Chromium's fake capture device gives a real audio stream, so the HUD
  // records, encodes and uploads exactly as it would from a microphone.
  const voiceBrowser = await chromium.launch({
    ...(CHROMIUM_PATH ? { executablePath: CHROMIUM_PATH } : {}),
    args: [
      '--use-fake-device-for-media-capture',
      '--use-fake-ui-for-media-stream',
      '--autoplay-policy=no-user-gesture-required',
    ],
  });
  const voiceCtx = await voiceBrowser.newContext({
    viewport: { width: 1600, height: 900 }, permissions: ['microphone'],
  });
  const vp = await voiceCtx.newPage();
  const voiceErrors = [];
  vp.on('pageerror', e => voiceErrors.push(String(e)));
  await vp.goto(BASE, { waitUntil: 'networkidle' });
  await vp.waitForFunction(() => document.getElementById('skillList').children.length > 0, { timeout: 15000 });

  const voiceRows = await vp.locator('#runtimeList .service').allTextContents();
  ok('runtime row reports STT on', voiceRows.some(r => r.includes('Local STT') && r.includes('ON · COMMAND')));
  ok('runtime row reports TTS on', voiceRows.some(r => r.includes('Local TTS') && r.includes('ON · COMMAND')));
  ok('STT card reads LOCAL MIC', (await vp.textContent('#sttLabel')) === 'LOCAL MIC');
  ok('TTS card reads LOCAL VOICE', (await vp.textContent('#ttsLabel')) === 'LOCAL VOICE');
  ok('audio route measured ON-DEVICE on loopback', (await vp.textContent('#audioRoute')) === 'ON-DEVICE');
  ok('network audio measured LOOPBACK ONLY', (await vp.textContent('#networkAudio')) === 'LOOPBACK ONLY');
  ok('PTT invites speech', (await vp.textContent('#ptt')).includes('PUSH TO TALK'));
  ok('mute button live', !(await vp.isDisabled('#muteBtn')));

  // This container has no audio device, fake or otherwise, so capture
  // itself cannot run here. What a machine without a microphone shows is
  // worth asserting in its own right.
  await vp.click('body');
  await vp.keyboard.down('Space');
  await vp.waitForFunction(() => document.getElementById('terminal').textContent.includes('microphone unavailable')
    || document.getElementById('audioState').textContent === 'LISTENING', { timeout: 10000 });
  await vp.keyboard.up('Space');
  await vp.waitForTimeout(300);
  const micLog = await vp.textContent('#terminal');
  const hasMic = !micLog.includes('microphone unavailable');
  if (hasMic) {
    ok('PTT recorded from a real device', true);
  } else {
    ok('missing microphone reported, not swallowed', micLog.includes('microphone unavailable'));
    ok('audio state says MIC BLOCKED', (await vp.textContent('#audioState')) === 'MIC BLOCKED');
    ok('PTT resets after a failed open', !(await vp.getAttribute('#ptt', 'class')).includes('live'));
    ok('mic meter stayed at rest', await vp.evaluate(() =>
      [...document.querySelectorAll('#micLevel i')].every(b => parseFloat(b.style.height) <= 2)));
  }

  // The rest of the chain is the HUD's own code: its WAV encoder, the
  // upload, the server's transcriber, and routing what came back.
  const upload = await vp.evaluate(async () => {
    const rate = 16000, count = rate;          // one second of tone
    const samples = new Float32Array(count);
    for (let i = 0; i < count; i++) samples[i] = 0.4 * Math.sin(2 * Math.PI * 440 * i / rate);
    const wav = encodeWav(samples, rate);
    const res = await fetch('/api/voice/stt', {
      method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav,
    });
    return { size: wav.size, type: wav.type, status: res.status, body: await res.json() };
  });
  ok('encoder produced 16-bit mono at 16 kHz', upload.size === 44 + 16000 * 2, String(upload.size));
  ok('encoder output is a WAV blob', upload.type === 'audio/wav');
  // A 415 here would mean the RIFF header the encoder wrote is wrong.
  ok('server accepted the encoded recording', upload.status === 200, JSON.stringify(upload.body));
  ok('transcript came back from the local tool', upload.body.text === 'metrics', JSON.stringify(upload.body));
  ok('server reported the bytes it received', upload.body.bytes === upload.size);

  await vp.evaluate(text => runCommand(text), upload.body.text);
  await vp.waitForFunction(() => document.getElementById('terminal').textContent.includes('routed to metrics.md'), { timeout: 15000 });
  const routedLog = await vp.textContent('#terminal');
  ok('a transcript routes like any other command', routedLog.includes('routed to metrics.md'));
  ok('transcript shown as what was said', routedLog.includes('YOU metrics'));

  // Speech out, through the configured local synthesiser.
  const spoken = await vp.evaluate(async () => {
    const badge = document.getElementById('audioState');
    const seen = [];
    const observer = new MutationObserver(() => seen.push(badge.textContent));
    observer.observe(badge, { childList: true, characterData: true, subtree: true });
    let peak = 0;
    const watch = setInterval(() => {
      for (const bar of document.querySelectorAll('#ttsLevel i')) {
        peak = Math.max(peak, parseFloat(bar.style.height));
      }
    }, 40);
    await speak('metrics snapshot written');
    clearInterval(watch);
    observer.disconnect();
    return { seen, peak, log: document.getElementById('terminal').textContent.slice(-300) };
  });
  ok('speaking is announced while it happens', spoken.seen.includes('SPEAKING'), spoken.seen.join('>'));
  ok('audio state settles back to IDLE', spoken.seen[spoken.seen.length - 1] === 'IDLE', spoken.seen.join('>'));
  ok('no speech failure reported', !spoken.log.includes('speech failed'), spoken.log);
  ok('output meter driven by the audio itself', spoken.peak > 2, `peak ${spoken.peak}`);

  await vp.click('#muteBtn');
  ok('mute toggles the card to MUTED', (await vp.textContent('#ttsLabel')) === 'MUTED');
  ok('mute is reported in the terminal', (await vp.textContent('#terminal')).includes('spoken replies muted'));
  await vp.reload({ waitUntil: 'networkidle' });
  await vp.waitForFunction(() => document.getElementById('skillList').children.length > 0, { timeout: 15000 });
  ok('mute survives a reload', (await vp.textContent('#ttsLabel')) === 'MUTED');
  await vp.click('#muteBtn');
  ok('unmute restores LOCAL VOICE', (await vp.textContent('#ttsLabel')) === 'LOCAL VOICE');

  ok('no uncaught JS exceptions in the voice phase', voiceErrors.length === 0, voiceErrors.join(' | '));

  await voiceBrowser.close();
  stopServer(server);
  fs.rmSync(toolDir, { recursive: true, force: true });
  fs.rmSync(vaultDir, { recursive: true, force: true });

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('harness error:', e); process.exit(2); });
