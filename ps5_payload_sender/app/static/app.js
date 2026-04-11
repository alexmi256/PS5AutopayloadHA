'use strict';

const BASE = (window.PS5_BASE || '').replace(/\/$/, '');

// ================================================================
// State
// ================================================================
const state = {
  ws: null,
  wsRetries: 0,
  payloads: [],
  profiles: [],
  devices: [],
  favorites: [],
  notifyEnabled: true,
};

// ================================================================
// Theme
// ================================================================
function initTheme() {
  const saved = sessionStorage.getItem('ps5_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  document.getElementById('btn-theme').textContent = saved === 'dark' ? '☀' : '🌙';
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  sessionStorage.setItem('ps5_theme', next);
  document.getElementById('btn-theme').textContent = next === 'dark' ? '☀' : '🌙';
}

// ================================================================
// WebSocket
// ================================================================
function connectWS() {
  const dot = document.getElementById('ws-indicator');
  dot.className = 'ws-dot ws-connecting';
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}${BASE}/ws`);
  state.ws = ws;

  ws.onopen = () => {
    dot.className = 'ws-dot ws-online';
    state.wsRetries = 0;
    log('Connected ✓', 'success');
    ws._ping = setInterval(() => {
      if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'ping' }));
    }, 25000);
  };

  ws.onmessage = ({ data }) => {
    try { handleWS(JSON.parse(data)); } catch (_) { /* ignore */ }
  };

  ws.onclose = () => {
    dot.className = 'ws-dot ws-offline';
    clearInterval(ws._ping);
    const delay = Math.min(1000 * Math.pow(1.5, state.wsRetries++), 20000);
    if (state.wsRetries <= 12) setTimeout(connectWS, delay);
    else log('Connection lost. Please reload the page.', 'error');
  };

  ws.onerror = () => ws.close();
}

function handleWS(msg) {
  if (msg.type === 'pong') return;
  if (msg.type === 'config') {
    const ip = document.getElementById('ps5-ip');
    if (msg.ps5_ip && !ip.value) ip.value = msg.ps5_ip;
    return;
  }
  if (msg.type === 'status') log(msg.message, msg.level || 'info');
}

// ================================================================
// API fetch
// ================================================================
async function api(path, opts = {}) {
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status} ${txt}`);
  }
  return res.json();
}

// ================================================================
// Logging
// ================================================================
function log(msg, level = 'info') {
  const container = document.getElementById('status-log');
  const el = document.createElement('div');
  el.className = `log-entry log-${level} fade`;
  const ts = new Date().toLocaleTimeString('en-US',
    { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  const tsEl = document.createElement('span');
  tsEl.className = 'log-ts'; tsEl.textContent = ts;
  const msgEl = document.createElement('span');
  msgEl.textContent = msg;
  el.appendChild(tsEl); el.appendChild(msgEl);
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  while (container.children.length > 300) container.removeChild(container.firstChild);
}

function clearLog() { document.getElementById('status-log').innerHTML = ''; }

// ================================================================
// Helpers
// ================================================================
function getHost() {
  const h = document.getElementById('ps5-ip').value.trim();
  if (!h) { alert('Please enter PS5 IP address!'); return null; }
  return h;
}

function fmt(b) {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(2)} MB`;
}

function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) +
    ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function validateIp() {
  const val = document.getElementById('ps5-ip').value.trim();
  const warn = document.getElementById('ip-warn');
  if (!val) { warn.style.display = 'none'; return; }
  const valid = /^(\d{1,3}\.){3}\d{1,3}$/.test(val) &&
    val.split('.').every(n => parseInt(n) <= 255);
  warn.style.display = valid ? 'none' : '';
}

// ================================================================
// State persistence
// ================================================================
let _saveTimer = null;

function scheduleSave() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(persistState, 800);
}

async function persistState() {
  try {
    await api('/api/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ps5_ip: document.getElementById('ps5-ip').value.trim(),
        notify_enabled: state.notifyEnabled,
        favorites: state.favorites,
        builder_steps: builder.steps,
        builder_profile_name: document.getElementById('builder-profile-name').value,
      }),
    });
  } catch (_) { /* silent */ }
}

async function loadPersistedState() {
  try {
    const saved = await api('/api/state');
    if (saved.ps5_ip) {
      document.getElementById('ps5-ip').value = saved.ps5_ip;
      onIpChange();
    }
    if (typeof saved.notify_enabled === 'boolean') {
      state.notifyEnabled = saved.notify_enabled;
      document.getElementById('notify-toggle').checked = saved.notify_enabled;
    }
    if (Array.isArray(saved.favorites)) state.favorites = saved.favorites;
    if (Array.isArray(saved.builder_steps) && saved.builder_steps.length) {
      builder.steps = saved.builder_steps;
      builderRenderList();
    }
    if (saved.builder_profile_name)
      document.getElementById('builder-profile-name').value = saved.builder_profile_name;
  } catch (_) { /* first run */ }
}

// ================================================================
// Version display
// ================================================================
async function loadVersion() {
  try {
    const data = await api('/api/version');
    const badge = document.getElementById('version-badge');
    if (badge) badge.textContent = `v${data.version}`;
  } catch (_) { /* ignore */ }
}

// ================================================================
// Devices
// ================================================================
async function loadDevicesFromServer() {
  try {
    const data = await api('/api/devices');
    state.devices = data.devices || [];
    renderDeviceDropdown();
  } catch (e) { log('Load devices: ' + e.message, 'warn'); }
}

async function saveDevicesToServer() {
  try {
    await api('/api/devices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ devices: state.devices }),
    });
  } catch (e) { log('Save devices: ' + e.message, 'error'); }
}

function renderDeviceDropdown() {
  const sel = document.getElementById('device-select');
  const cur = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  state.devices.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d.id; opt.textContent = `${d.name}  (${d.ip})`;
    sel.appendChild(opt);
  });
  if (cur) sel.value = cur;
}

function onDeviceSelect() {
  const id = document.getElementById('device-select').value;
  if (!id) return;
  const dev = state.devices.find(d => d.id === id);
  if (dev) { document.getElementById('ps5-ip').value = dev.ip; scheduleSave(); }
}

function onIpChange() {
  const ip = document.getElementById('ps5-ip').value.trim();
  const match = state.devices.find(d => d.ip === ip);
  document.getElementById('device-select').value = match ? match.id : '';
  scheduleSave();
}

function openDeviceModal() {
  renderDeviceListModal();
  document.getElementById('device-modal').style.display = 'flex';
}

function closeDeviceModal() {
  document.getElementById('device-modal').style.display = 'none';
  document.getElementById('new-device-name').value = '';
  document.getElementById('new-device-ip').value = '';
}

function renderDeviceListModal() {
  const container = document.getElementById('device-list-modal');
  container.innerHTML = '';
  if (!state.devices.length) {
    container.innerHTML = '<div class="empty-state">No saved devices</div>';
    return;
  }
  state.devices.forEach(d => {
    const el = document.createElement('div');
    el.className = 'device-entry fade';
    const name = document.createElement('span');
    name.className = 'dev-name'; name.textContent = d.name;
    const ip = document.createElement('span');
    ip.className = 'dev-ip'; ip.textContent = d.ip;
    const selBtn = document.createElement('button');
    selBtn.className = 'btn btn-sm'; selBtn.textContent = 'Select';
    selBtn.addEventListener('click', () => {
      document.getElementById('ps5-ip').value = d.ip;
      document.getElementById('device-select').value = d.id;
      closeDeviceModal(); scheduleSave();
    });
    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-sm btn-danger'; delBtn.textContent = '✕';
    delBtn.addEventListener('click', async () => {
      state.devices = state.devices.filter(x => x.id !== d.id);
      await saveDevicesToServer();
      renderDeviceDropdown(); renderDeviceListModal();
    });
    el.appendChild(name); el.appendChild(ip);
    el.appendChild(selBtn); el.appendChild(delBtn);
    container.appendChild(el);
  });
}

async function addDevice() {
  const name = document.getElementById('new-device-name').value.trim();
  const ip = document.getElementById('new-device-ip').value.trim();
  if (!name || !ip) { alert('Enter name and IP!'); return; }
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  state.devices.push({ id, name, ip });
  await saveDevicesToServer();
  renderDeviceDropdown(); renderDeviceListModal();
  document.getElementById('new-device-name').value = '';
  document.getElementById('new-device-ip').value = '';
  log(`Device '${name}' (${ip}) saved`, 'success');
}

// ================================================================
// Payloads
// ================================================================
async function refreshPayloads() {
  try {
    const data = await api('/api/payloads');
    state.payloads = data.payloads || [];
    renderPayloads();
  } catch (e) { log('Load payloads: ' + e.message, 'error'); }
}

function renderPayloads() {
  builderUpdatePayloadDropdown();
  const c = document.getElementById('payload-list');
  c.innerHTML = '';
  if (!state.payloads.length) {
    c.innerHTML = '<div class="empty-state">No payloads. Upload a .lua or .elf file.</div>';
    return;
  }
  state.payloads.forEach(p => {
    const el = document.createElement('div');
    el.className = 'payload-item fade';

    const badge = document.createElement('span');
    badge.className = `badge ${p.ext === '.lua' ? 'badge-lua' : 'badge-elf'}`;
    badge.textContent = p.ext.replace('.', '').toUpperCase();

    const info = document.createElement('div');
    info.className = 'p-info';
    const name = document.createElement('span');
    name.className = 'p-name'; name.textContent = p.name;
    const meta = document.createElement('span');
    meta.className = 'p-meta';
    meta.textContent = fmt(p.size) + (p.mtime ? '  ' + fmtDate(p.mtime) : '');
    info.appendChild(name); info.appendChild(meta);

    const portInput = document.createElement('input');
    portInput.type = 'number'; portInput.className = 'p-port-input';
    portInput.placeholder = String(p.auto_port);
    portInput.min = '1'; portInput.max = '65535';
    portInput.title = 'Override port (empty = auto)';

    const sendBtn = document.createElement('button');
    sendBtn.className = 'p-send'; sendBtn.textContent = '▶'; sendBtn.title = 'Send';
    sendBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await sendDirect(p.name, p.auto_port, portInput, sendBtn);
    });

    const del = document.createElement('button');
    del.className = 'p-del'; del.textContent = '✕'; del.title = 'Delete';
    del.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete '${p.name}'?`)) return;
      try {
        await api(`/api/payloads/${encodeURIComponent(p.name)}`, { method: 'DELETE' });
        await refreshPayloads();
        log(`'${p.name}' deleted`);
      } catch (err) { log('Delete: ' + err.message, 'error'); }
    });

    el.appendChild(badge); el.appendChild(info);
    el.appendChild(portInput); el.appendChild(sendBtn); el.appendChild(del);
    c.appendChild(el);
  });
}

async function sendDirect(filename, autoPort, portInput, btn) {
  const host = getHost(); if (!host) return;
  const portVal = parseInt(portInput.value, 10);
  const port = (portVal > 0 && portVal <= 65535) ? portVal : autoPort;
  btn.disabled = true; btn.textContent = '⏳';
  try {
    await api('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, filename, port, notify: state.notifyEnabled }),
    });
    btn.textContent = '✓'; btn.className = 'p-send ok';
  } catch (e) {
    log('Send: ' + e.message, 'error');
    btn.textContent = '✗'; btn.className = 'p-send err';
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = '▶'; btn.className = 'p-send'; }, 2200);
}

async function uploadPayloads(files) {
  if (!files || !files.length) return;
  const bar = document.getElementById('upload-bar');
  const label = document.getElementById('upload-label');
  const prog = document.getElementById('upload-progress');
  prog.style.display = 'block';
  for (let i = 0; i < files.length; i++) {
    label.textContent = `${files[i].name} (${i + 1}/${files.length})`;
    bar.style.width = `${(i / files.length) * 100}%`;
    const fd = new FormData(); fd.append('file', files[i]);
    try {
      const d = await api('/api/payloads/upload', { method: 'POST', body: fd });
      log(`'${d.filename}' uploaded (${fmt(d.size)}, port ${d.auto_port})`, 'success');
    } catch (e) { log(`Upload '${files[i].name}': ${e.message}`, 'error'); }
  }
  bar.style.width = '100%'; label.textContent = 'Done!';
  setTimeout(() => { prog.style.display = 'none'; bar.style.width = '0'; }, 2000);
  document.getElementById('payload-upload').value = '';
  await refreshPayloads();
}

// ================================================================
// Visual Builder
// ================================================================
const builder = { steps: [] };

function builderUpdatePayloadDropdown() {
  const sel = document.getElementById('panel-payload-select');
  const cur = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  state.payloads.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = `${p.name}  (:${p.auto_port})`;
    opt.dataset.autoPort = String(p.auto_port);
    sel.appendChild(opt);
  });
  if (cur) sel.value = cur;
}

function builderTogglePanel(type) {
  const panels = { payload: 'panel-payload', delay: 'panel-delay', wait: 'panel-wait' };
  Object.entries(panels).forEach(([t, id]) => {
    const el = document.getElementById(id);
    el.style.display = (t === type && el.style.display === 'none') ? '' : 'none';
  });
}

function builderAddPayloadStep() {
  const sel = document.getElementById('panel-payload-select');
  const filename = sel.value;
  if (!filename) { alert('Select a payload!'); return; }
  const autoPort = parseInt(sel.options[sel.selectedIndex].dataset.autoPort, 10);
  const portVal = parseInt(document.getElementById('panel-payload-port').value, 10);
  const portOverride = (portVal > 0 && portVal <= 65535) ? portVal : null;
  builder.steps.push({ type: 'payload', filename, autoPort, portOverride });
  document.getElementById('panel-payload-port').value = '';
  document.getElementById('panel-payload').style.display = 'none';
  builderRenderList(); scheduleSave();
}

function builderAddDelayStep(ms) {
  if (!ms || ms <= 0) return;
  builder.steps.push({ type: 'delay', ms });
  builderRenderList(); scheduleSave();
}

function builderAddWaitStep() {
  const port = parseInt(document.getElementById('panel-wait-port').value, 10);
  const timeout = parseInt(document.getElementById('panel-wait-to').value, 10);
  if (!port || port < 1 || port > 65535) { alert('Invalid port!'); return; }
  if (!timeout || timeout < 1) { alert('Invalid timeout!'); return; }
  builder.steps.push({ type: 'wait_port', port, timeout });
  document.getElementById('panel-wait').style.display = 'none';
  builderRenderList(); scheduleSave();
}

function _builderMakeDragDrop(el, idx) {
  el.addEventListener('dragstart', (e) => {
    e.dataTransfer.setData('text/plain', String(idx));
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => el.classList.add('dragging'), 0);
  });
  el.addEventListener('dragend', () => {
    el.classList.remove('dragging');
    el.setAttribute('draggable', 'false');
  });
  el.addEventListener('dragover', (e) => { e.preventDefault(); el.classList.add('drag-over'); });
  el.addEventListener('dragleave', (e) => {
    if (!el.contains(e.relatedTarget)) el.classList.remove('drag-over');
  });
  el.addEventListener('drop', (e) => {
    e.preventDefault(); el.classList.remove('drag-over');
    const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (isNaN(from) || from === idx) return;
    const moved = builder.steps.splice(from, 1)[0];
    builder.steps.splice(idx, 0, moved);
    builderRenderList(); scheduleSave();
  });
}

function _builderMakeDragHandle(el) {
  const drag = document.createElement('span');
  drag.className = 'drag-handle'; drag.textContent = '☰';
  drag.title = 'Drag to reorder';
  drag.addEventListener('mousedown', () => el.setAttribute('draggable', 'true'));
  drag.addEventListener('touchstart', () => el.setAttribute('draggable', 'true'), { passive: true });
  return drag;
}

function _builderMakeOrderBtns(idx) {
  const btns = document.createElement('div');
  btns.className = 'step-btns';
  const upBtn = document.createElement('button');
  upBtn.className = 'btn btn-sm'; upBtn.textContent = '↑'; upBtn.disabled = idx === 0;
  upBtn.addEventListener('click', () => builderMoveStep(idx, -1));
  const downBtn = document.createElement('button');
  downBtn.className = 'btn btn-sm'; downBtn.textContent = '↓';
  downBtn.disabled = idx === builder.steps.length - 1;
  downBtn.addEventListener('click', () => builderMoveStep(idx, 1));
  const delBtn = document.createElement('button');
  delBtn.className = 'btn btn-sm btn-danger'; delBtn.textContent = '✕';
  delBtn.addEventListener('click', () => builderDeleteStep(idx));
  btns.appendChild(upBtn); btns.appendChild(downBtn); btns.appendChild(delBtn);
  return btns;
}

function builderRenderList() {
  const container = document.getElementById('builder-steps');
  container.innerHTML = '';
  if (!builder.steps.length) {
    container.innerHTML = '<div class="empty-state">No steps yet. Choose a step type above.</div>';
    return;
  }
  builder.steps.forEach((step, idx) => {
    const el = document.createElement('div');
    el.className = 'builder-step fade';
    _builderMakeDragDrop(el, idx);
    const mainRow = document.createElement('div');
    mainRow.className = 'step-main';
    const drag = _builderMakeDragHandle(el);
    const num = document.createElement('span');
    num.className = 'step-num'; num.textContent = idx + 1;
    const badge = document.createElement('span');
    const btns = _builderMakeOrderBtns(idx);

    if (step.type === 'payload') {
      const isLua = step.filename.toLowerCase().endsWith('.lua');
      badge.className = `payload-label ${isLua ? 'lua' : 'elf'}`;
      badge.textContent = 'Payload';
      const fnEl = document.createElement('span');
      fnEl.className = 'step-filename'; fnEl.textContent = step.filename;
      const portHint = document.createElement('span');
      portHint.className = 'step-autoport';
      portHint.textContent = `:${step.portOverride || step.autoPort}`;
      mainRow.appendChild(drag); mainRow.appendChild(num); mainRow.appendChild(badge);
      mainRow.appendChild(fnEl); mainRow.appendChild(portHint); mainRow.appendChild(btns);
      const details = document.createElement('div');
      details.className = 'step-details';
      const portField = document.createElement('div');
      portField.className = 'step-field';
      const portLabel = document.createElement('span');
      portLabel.className = 'step-field-label'; portLabel.textContent = 'Port';
      const portInp = document.createElement('input');
      portInp.type = 'number'; portInp.className = 'step-input';
      portInp.placeholder = String(step.autoPort); portInp.min = '1'; portInp.max = '65535';
      if (step.portOverride) portInp.value = step.portOverride;
      portInp.addEventListener('input', e => {
        const v = parseInt(e.target.value, 10);
        builder.steps[idx].portOverride = (v > 0 && v <= 65535) ? v : null;
        portHint.textContent = `:${builder.steps[idx].portOverride || step.autoPort}`;
        scheduleSave();
      });
      portField.appendChild(portLabel); portField.appendChild(portInp);
      details.appendChild(portField);
      el.appendChild(mainRow); el.appendChild(details);

    } else if (step.type === 'delay') {
      badge.className = 'step-type step-delay'; badge.textContent = 'DELAY';
      const spacer = document.createElement('span'); spacer.style.flex = '1';
      const msInp = document.createElement('input');
      msInp.type = 'number'; msInp.className = 'step-input';
      msInp.value = step.ms; msInp.min = '1';
      msInp.addEventListener('input', e => {
        const v = parseInt(e.target.value, 10);
        if (v > 0) { builder.steps[idx].ms = v; scheduleSave(); }
      });
      const msUnit = document.createElement('span');
      msUnit.className = 'step-unit'; msUnit.textContent = 'ms';
      mainRow.appendChild(drag); mainRow.appendChild(num); mainRow.appendChild(badge);
      mainRow.appendChild(spacer); mainRow.appendChild(msInp);
      mainRow.appendChild(msUnit); mainRow.appendChild(btns);
      el.appendChild(mainRow);

    } else { // wait_port
      badge.className = 'step-type step-wait'; badge.textContent = 'WAIT';
      const spacer = document.createElement('span'); spacer.style.flex = '1';
      const portInp = document.createElement('input');
      portInp.type = 'number'; portInp.className = 'step-input';
      portInp.value = step.port; portInp.min = '1'; portInp.max = '65535';
      portInp.title = 'Port';
      portInp.addEventListener('input', e => {
        const v = parseInt(e.target.value, 10);
        if (v > 0 && v <= 65535) { builder.steps[idx].port = v; scheduleSave(); }
      });
      const sep = document.createElement('span');
      sep.className = 'step-unit'; sep.textContent = '/';
      const toInp = document.createElement('input');
      toInp.type = 'number'; toInp.className = 'step-input';
      toInp.value = step.timeout; toInp.min = '1'; toInp.title = 'Timeout (s)';
      toInp.addEventListener('input', e => {
        const v = parseInt(e.target.value, 10);
        if (v > 0) { builder.steps[idx].timeout = v; scheduleSave(); }
      });
      const toUnit = document.createElement('span');
      toUnit.className = 'step-unit'; toUnit.textContent = 's';
      mainRow.appendChild(drag); mainRow.appendChild(num); mainRow.appendChild(badge);
      mainRow.appendChild(spacer); mainRow.appendChild(portInp);
      mainRow.appendChild(sep); mainRow.appendChild(toInp);
      mainRow.appendChild(toUnit); mainRow.appendChild(btns);
      el.appendChild(mainRow);
    }
    container.appendChild(el);
  });
}

// ================================================================
// Builder – actions, generate, save, run
// ================================================================
function builderMoveStep(idx, dir) {
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= builder.steps.length) return;
  [builder.steps[idx], builder.steps[newIdx]] = [builder.steps[newIdx], builder.steps[idx]];
  builderRenderList(); scheduleSave();
}

function builderDeleteStep(idx) {
  builder.steps.splice(idx, 1);
  builderRenderList(); scheduleSave();
}

function builderGenerate() {
  return builder.steps.map(step => {
    if (step.type === 'payload')
      return step.portOverride ? `${step.filename} ${step.portOverride}` : step.filename;
    if (step.type === 'delay') return `!${step.ms}`;
    return `?${step.port} ${step.timeout}`;
  }).join('\n');
}

async function builderSave() {
  if (!builder.steps.length) { alert('No steps to save!'); return; }
  const raw = document.getElementById('builder-profile-name').value.trim();
  if (!raw) { alert('Enter a profile name!'); return; }
  const safe = raw.replace(/[^a-zA-Z0-9_\-.]/g, '_');
  const filename = safe.endsWith('.txt') ? safe : `${safe}.txt`;
  const content = `# Created by Visual Builder\n${builderGenerate()}\n`;
  try {
    await api('/api/autoload/content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: filename, content }),
    });
    log(`Profile '${filename}' saved`, 'success');
    const favToggle = document.getElementById('builder-fav-toggle');
    if (favToggle.checked && !state.favorites.includes(filename)) {
      state.favorites.push(filename);
    } else if (!favToggle.checked) {
      state.favorites = state.favorites.filter(f => f !== filename);
    }
    await refreshProfiles();
    scheduleSave();
  } catch (e) { log('Save: ' + e.message, 'error'); }
}

async function builderRunDirect() {
  if (!builder.steps.length) { alert('No steps to run!'); return; }
  const host = getHost(); if (!host) return;
  const tmpProfile = '_builder_run.txt';
  const content = `# Builder direct run\n${builderGenerate()}\n`;
  try {
    await api('/api/autoload/content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: tmpProfile, content }),
    });
    await api('/api/autoload/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, profile: tmpProfile, continue_on_error: false, notify: state.notifyEnabled }),
    });
  } catch (e) { log('Run: ' + e.message, 'error'); }
}

// ================================================================
// Developer Update
// ================================================================
async function devUpdate() {
  log('Checking version …', 'info');
  try {
    const check = await api('/api/version/check');
    if (check.up_to_date) {
      log(`Already up to date (v${check.current})`, 'success');
      return;
    }
    const msg = check.remote
      ? `Update available: v${check.current} → v${check.remote}. Proceed?`
      : 'Update from GitHub and restart add-on?';
    if (!confirm(msg)) return;
  } catch (_) {
    if (!confirm('Update from GitHub and restart add-on?')) return;
  }
  log('⬇ Starting update …', 'info');
  try {
    await api('/api/update', { method: 'POST' });
    log('Update started. Restarting …', 'info');
  } catch (e) { log('Update failed: ' + e.message, 'error'); }
}

// ================================================================
// Saved profiles
// ================================================================
async function refreshProfiles() {
  try {
    const data = await api('/api/autoload/profiles');
    state.profiles = data.profiles || [];
    renderProfileList();
    renderFavorites();
  } catch (e) { log('Load profiles: ' + e.message, 'error'); }
}

function renderProfileList() {
  const container = document.getElementById('profile-list');
  container.innerHTML = '';
  if (!state.profiles.length) {
    container.innerHTML = '<div class="empty-state">No profiles saved.</div>';
    return;
  }
  state.profiles.forEach(name => {
    const item = document.createElement('div');
    item.className = 'profile-item fade';
    const isFav = state.favorites.includes(name);

    const favBtn = document.createElement('button');
    favBtn.className = `btn btn-sm${isFav ? ' fav-active' : ''}`;
    favBtn.textContent = '⭐';
    favBtn.title = isFav ? 'Remove from favorites' : 'Add to favorites';
    favBtn.addEventListener('click', () => toggleFavorite(name));

    const nameEl = document.createElement('span');
    nameEl.className = 'profile-name'; nameEl.textContent = name;

    const editBtn = document.createElement('button');
    editBtn.className = 'btn btn-sm'; editBtn.textContent = '✏';
    editBtn.title = 'Edit in builder';
    editBtn.addEventListener('click', () => editProfile(name));

    const runBtn = document.createElement('button');
    runBtn.className = 'btn btn-sm btn-primary'; runBtn.textContent = '▶';
    runBtn.title = 'Run';
    runBtn.addEventListener('click', () => runProfile(name, runBtn));

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-sm btn-danger'; delBtn.textContent = '✕';
    delBtn.title = 'Delete';
    delBtn.addEventListener('click', async () => {
      if (!confirm(`Delete profile '${name}'?`)) return;
      try {
        await api(`/api/autoload/content/${encodeURIComponent(name)}`, { method: 'DELETE' });
        state.favorites = state.favorites.filter(f => f !== name);
        await refreshProfiles();
        scheduleSave();
        log(`Profile '${name}' deleted`);
      } catch (e) { log('Delete profile: ' + e.message, 'error'); }
    });

    item.appendChild(favBtn); item.appendChild(nameEl);
    item.appendChild(editBtn); item.appendChild(runBtn); item.appendChild(delBtn);
    container.appendChild(item);
  });
}

function renderFavorites() {
  const card = document.getElementById('favorites-card');
  const list = document.getElementById('favorites-list');
  const valid = state.favorites.filter(f => state.profiles.includes(f));
  if (!valid.length) { card.style.display = 'none'; return; }
  card.style.display = '';
  list.innerHTML = '';
  valid.forEach(name => {
    const btn = document.createElement('button');
    btn.className = 'btn fav-btn';
    btn.textContent = name.replace(/\.txt$/i, '');
    btn.title = `Run ${name}`;
    btn.addEventListener('click', () => runProfile(name, btn));
    list.appendChild(btn);
  });
}

function toggleFavorite(name) {
  if (state.favorites.includes(name)) {
    state.favorites = state.favorites.filter(f => f !== name);
  } else {
    state.favorites.push(name);
  }
  renderProfileList(); renderFavorites(); scheduleSave();
}

async function runProfile(name, btn) {
  const host = getHost(); if (!host) return;
  const continueOnError = document.getElementById('continue-on-error').checked;
  if (btn) btn.disabled = true;
  try {
    await api('/api/autoload/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, profile: name, continue_on_error: continueOnError, notify: state.notifyEnabled }),
    });
  } catch (e) { log('Run: ' + e.message, 'error'); }
  if (btn) btn.disabled = false;
}

async function editProfile(name) {
  try {
    const data = await api(`/api/autoload/parse/${encodeURIComponent(name)}`);
    if (!data.steps || !data.steps.length) {
      log(`Profile '${name}' has no parseable steps`, 'warn'); return;
    }
    builder.steps = data.steps;
    document.getElementById('builder-profile-name').value = name.replace(/\.txt$/i, '');
    document.getElementById('builder-fav-toggle').checked = state.favorites.includes(name);
    builderRenderList(); scheduleSave();
    document.getElementById('builder-card').scrollIntoView({ behavior: 'smooth' });
    log(`Profile '${name}' loaded into builder`, 'success');
  } catch (e) { log('Edit profile: ' + e.message, 'error'); }
}

// ================================================================
// Port check
// ================================================================
async function checkPortOnce() {
  const host = getHost(); if (!host) return;
  const port = parseInt(document.getElementById('check-port').value, 10);
  const timeout = parseFloat(document.getElementById('check-timeout').value) || 5;
  if (!port || port < 1 || port > 65535) { alert('Invalid port!'); return; }
  const el = document.getElementById('port-check-result');
  el.style.display = 'none'; el.className = '';
  log(`Checking port ${port} on ${host} …`);
  try {
    const d = await api('/api/port/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, port, timeout }),
    });
    el.style.display = 'block';
    el.className = d.reachable ? 'res-ok' : 'res-fail';
    el.textContent = d.reachable ? `✓ Port ${port} is reachable` : `✗ Port ${port} not reachable`;
    log(el.textContent, d.reachable ? 'success' : 'warn');
  } catch (e) { log('Port check: ' + e.message, 'error'); }
}

async function waitForPort() {
  const host = getHost(); if (!host) return;
  const port = parseInt(document.getElementById('check-port').value, 10);
  const timeout = parseFloat(document.getElementById('check-timeout').value) || 10;
  const interval = parseFloat(document.getElementById('check-interval').value) / 1000 || 0.5;
  if (!port || port < 1 || port > 65535) { alert('Invalid port!'); return; }
  const el = document.getElementById('port-check-result');
  el.style.display = 'none'; el.className = '';
  try {
    const d = await api('/api/port/wait', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, port, timeout, interval }),
    });
    el.style.display = 'block';
    el.className = d.reachable ? 'res-ok' : 'res-fail';
    el.textContent = d.reachable ? `✓ Port ${port} reachable` : `✗ Timeout: Port ${port} not reachable`;
  } catch (e) { log('Wait: ' + e.message, 'error'); }
}

// ================================================================
// Init
// ================================================================
async function init() {
  initTheme();
  document.getElementById('btn-theme').addEventListener('click', toggleTheme);
  document.getElementById('btn-dev-update').addEventListener('click', devUpdate);

  // Connection
  document.getElementById('device-select').addEventListener('change', onDeviceSelect);
  document.getElementById('ps5-ip').addEventListener('input', onIpChange);
  document.getElementById('ps5-ip').addEventListener('blur', validateIp);
  document.getElementById('btn-manage-devices').addEventListener('click', openDeviceModal);

  // Notifications
  document.getElementById('notify-toggle').addEventListener('change', e => {
    state.notifyEnabled = e.target.checked; scheduleSave();
  });

  // Payloads
  document.getElementById('btn-refresh-payloads').addEventListener('click', refreshPayloads);
  document.getElementById('payload-upload').addEventListener('change', e => uploadPayloads(e.target.files));

  // Builder panels
  document.getElementById('btn-add-payload').addEventListener('click', () => builderTogglePanel('payload'));
  document.getElementById('btn-add-delay').addEventListener('click', () => builderTogglePanel('delay'));
  document.getElementById('btn-add-wait').addEventListener('click', () => builderTogglePanel('wait'));
  document.getElementById('btn-panel-payload-ok').addEventListener('click', builderAddPayloadStep);
  document.getElementById('btn-panel-payload-x').addEventListener('click', () => builderTogglePanel('payload'));
  document.getElementById('btn-panel-delay-ok').addEventListener('click', () => {
    const ms = parseInt(document.getElementById('panel-delay-ms').value, 10);
    if (ms > 0) { builderAddDelayStep(ms); document.getElementById('panel-delay-ms').value = ''; }
    else alert('Enter valid milliseconds!');
  });
  document.getElementById('btn-panel-delay-x').addEventListener('click', () => builderTogglePanel('delay'));
  document.querySelectorAll('.delay-preset').forEach(btn =>
    btn.addEventListener('click', () => builderAddDelayStep(parseInt(btn.dataset.ms, 10))));
  document.getElementById('btn-panel-wait-ok').addEventListener('click', builderAddWaitStep);
  document.getElementById('btn-panel-wait-x').addEventListener('click', () => builderTogglePanel('wait'));

  // Builder save/run
  document.getElementById('btn-builder-save').addEventListener('click', builderSave);
  document.getElementById('btn-builder-run').addEventListener('click', builderRunDirect);
  document.getElementById('builder-profile-name').addEventListener('input', scheduleSave);

  // Profiles
  document.getElementById('btn-refresh-profiles').addEventListener('click', refreshProfiles);

  // Port check
  document.getElementById('btn-check-once').addEventListener('click', checkPortOnce);
  document.getElementById('btn-wait-port').addEventListener('click', waitForPort);

  // Log
  document.getElementById('btn-clear-log').addEventListener('click', clearLog);

  // Device modal
  document.getElementById('btn-add-device').addEventListener('click', addDevice);
  document.getElementById('btn-close-device-modal').addEventListener('click', closeDeviceModal);
  document.getElementById('device-modal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeDeviceModal();
  });
  document.getElementById('new-device-ip').addEventListener('keydown', e => {
    if (e.key === 'Enter') addDevice();
  });

  // Boot sequence
  await loadDevicesFromServer();
  await loadPersistedState();
  try {
    const cfg = await api('/api/config');
    const ip = document.getElementById('ps5-ip');
    if (cfg.ps5_ip && !ip.value) { ip.value = cfg.ps5_ip; onIpChange(); }
  } catch (_) { /* optional */ }
  await loadVersion();
  await refreshPayloads();
  await refreshProfiles();
  connectWS();
}

document.addEventListener('DOMContentLoaded', init);
