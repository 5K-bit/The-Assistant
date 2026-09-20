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

function startServer(vaultDir) {
  return spawn('python3', ['-m', 'server'], {
    cwd: REPO,
    env: { ...process.env, ASSISTANT_PORT: String(PORT), ASSISTANT_VAULT: vaultDir, ASSISTANT_ENGINE: 'OpenCode' },
    stdio: 'ignore',
  });
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

  console.log('\n[5] push-to-talk');
  await page.click('body');
  await page.keyboard.down('Space');
  await page.waitForTimeout(200);
  ok('PTT goes live on space', (await page.getAttribute('#ptt', 'class')).includes('live'));
  ok('audio state LISTENING', (await page.textContent('#audioState')) === 'LISTENING');
  ok('PTT admits STT not wired', (await page.textContent('#terminal')).includes('not wired'));
  await page.keyboard.up('Space');
  await page.waitForTimeout(200);
  ok('PTT resets on release', !(await page.getAttribute('#ptt', 'class')).includes('live'));

  console.log('\n[6] space inside the prompt does not trigger PTT');
  await page.click('#promptInput');
  await page.keyboard.type('plan today');
  ok('space typed into input', (await page.inputValue('#promptInput')) === 'plan today');
  ok('PTT stayed idle while typing', !(await page.getAttribute('#ptt', 'class')).includes('live'));
  await page.fill('#promptInput', '');

  console.log('\n[7] backend goes away');
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

  console.log('\n[8] backend comes back');
  server = startServer(vaultDir);
  await waitFor(true);
  await page.waitForFunction(() => document.getElementById('skillList').children.length > 0, { timeout: 30000 });
  ok('footer back to CONNECTED', (await page.textContent('#footerStatus')).includes('CONNECTED'));
  ok('skills re-rendered', (await page.locator('#skillList .service').count()) === 25);
  ok('engine badge restored', (await page.textContent('#engineBadge')) === 'ENGINE: OPENCODE');
  ok('vault stats restored', (await page.textContent('#statNotes')) === '6');
  ok('cpu reading restored', /^\d+(\.\d+)?%$/.test(await page.textContent('#cpuText')));

  console.log('\n[9] console health');
  ok('no uncaught JS exceptions', pageErrors.length === 0, pageErrors.join(' | '));
  const expected = /ERR_CONNECTION_REFUSED|Failed to fetch/;
  const unexpected = consoleErrors.filter(t => !expected.test(t));
  ok('no console errors beyond the deliberate outage', unexpected.length === 0, unexpected.join(' | '));

  await browser.close();
  stopServer(server);
  fs.rmSync(vaultDir, { recursive: true, force: true });

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('harness error:', e); process.exit(2); });
