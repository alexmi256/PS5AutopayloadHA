'use strict';

// ─── P2JB / Patience monitor ─────────────────────────────────────
//
// Watches the PS5 ELF loader port and reacts when it becomes
// reachable (=jailbreak succeeded). Does *not* trigger any exploit
// itself — the user still has to start P2JB / Patience on the
// console. This card exposes Start / Stop, a live status pill,
// and a settings panel for ports, interval, auto-run, and
// notification toggles.

const P2JB_STATE_LABEL = {
  idle:         { text: 'Idle',                  cls: 'p2jb-pill-idle'    },
  waiting:      { text: 'Waiting for loader…',   cls: 'p2jb-pill-waiting' },
  loader_ready: { text: 'Loader ready',          cls: 'p2jb-pill-ok'      },
  running_flow: { text: 'Running flow…',         cls: 'p2jb-pill-running' },
  completed:    { text: 'Flow completed',        cls: 'p2jb-pill-ok'      },
  failed:       { text: 'Failed',                cls: 'p2jb-pill-err'     },
  timeout:      { text: 'Timeout',               cls: 'p2jb-pill-err'     },
  stopped:      { text: 'Stopped',               cls: 'p2jb-pill-idle'    },
};

let _p2jbActive = false;
let _p2jbPollTimer = null;

// ─── Init & refresh ──────────────────────────────────────────────
async function initP2JBMonitor() {
  // Pre-fill flow dropdown from saved profiles (refreshed on each open)
  await _p2jbRefreshFlowOptions();

  // Pull persisted config, current status, and history in parallel
  const [cfg, status, history] = await Promise.all([
    api('/api/p2jb/config').catch(() => ({})),
    api('/api/p2jb/status').catch(() => ({ state: 'idle' })),
    api('/api/p2jb/history').catch(() => ({ runs: [] })),
  ]);
  _p2jbApplyConfig(cfg || {});
  _p2jbApplyStatus(status);
  _p2jbRenderHistory(history.runs || []);

  // Wire up buttons
  document.getElementById('btn-p2jb-start').addEventListener('click', startP2JB);
  document.getElementById('btn-p2jb-stop' ).addEventListener('click', stopP2JB);
  document.getElementById('p2jb-auto-run').addEventListener('change', _p2jbToggleAutoRun);
  _p2jbToggleAutoRun();

  document.getElementById('p2jb-lua-enable').addEventListener('change', _p2jbToggleLuaPort);
  _p2jbToggleLuaPort();

  document.getElementById('btn-p2jb-clear-history')
    .addEventListener('click', _p2jbClearHistory);

  // Advanced test panel
  document.querySelectorAll('[data-p2jb-test]').forEach(btn => {
    btn.addEventListener('click', () => _p2jbTest(btn.dataset.p2jbTest));
  });
  document.getElementById('btn-p2jb-simulate')
    .addEventListener('click', _p2jbSimulate);
  document.getElementById('p2jb-test-realflow')
    .addEventListener('change', _p2jbToggleRealFlowWarn);
}

async function _p2jbRefreshFlowOptions() {
  const sel = document.getElementById('p2jb-flow');
  if (!sel) return;
  try {
    const r = await api('/api/autoload/profiles');
    const profiles = (r.profiles || []).filter(n => !n.startsWith('__'));
    const current = sel.value;
    sel.innerHTML = '<option value="">– Select a flow –</option>' +
      profiles.map(p => `<option value="${p}">${p}</option>`).join('');
    if (current && profiles.includes(current)) sel.value = current;
  } catch (_) { /* keep whatever is there */ }
}

// ─── Apply persisted config to form ──────────────────────────────
function _p2jbApplyConfig(cfg) {
  const $ = id => document.getElementById(id);
  if (cfg.host)            $('p2jb-host').value           = cfg.host;
  if (cfg.elf_port)        $('p2jb-elf-port').value       = cfg.elf_port;
  if (cfg.lua_port) {
    $('p2jb-lua-enable').checked = true;
    $('p2jb-lua-port').value     = cfg.lua_port;
  }
  if (cfg.check_interval)  $('p2jb-interval').value       = cfg.check_interval;
  if (cfg.max_wait)        $('p2jb-max-wait').value       = Math.round(cfg.max_wait / 60);
  $('p2jb-auto-run').checked          = !!cfg.auto_run;
  if (cfg.flow_name)       $('p2jb-flow').value           = cfg.flow_name.replace(/\.txt$/i, '');
  $('p2jb-notify-ready').checked     = cfg.notify_loader_ready    !== false;
  $('p2jb-notify-started').checked   = !!cfg.notify_flow_started;
  $('p2jb-notify-completed').checked = cfg.notify_flow_completed !== false;
  $('p2jb-notify-failed').checked    = cfg.notify_flow_failed    !== false;
  if (cfg.notify_service)  $('p2jb-notify-service').value = cfg.notify_service;
  _p2jbToggleAutoRun();
  _p2jbToggleLuaPort();
}

// ─── Read form → config object ───────────────────────────────────
function _p2jbReadConfig() {
  const $ = id => document.getElementById(id);
  const ip = ($('p2jb-host').value || document.getElementById('ps5-ip').value || '').trim();
  const cfg = {
    host:                  ip,
    elf_port:              parseInt($('p2jb-elf-port').value, 10) || 9021,
    lua_port:              $('p2jb-lua-enable').checked
                              ? (parseInt($('p2jb-lua-port').value, 10) || 9026)
                              : null,
    check_interval:        parseFloat($('p2jb-interval').value) || 30,
    max_wait:              (parseFloat($('p2jb-max-wait').value) || 180) * 60,
    auto_run:              $('p2jb-auto-run').checked,
    flow_name:             $('p2jb-auto-run').checked ? ($('p2jb-flow').value || null) : null,
    notify_loader_ready:   $('p2jb-notify-ready').checked,
    notify_flow_started:   $('p2jb-notify-started').checked,
    notify_flow_completed: $('p2jb-notify-completed').checked,
    notify_flow_failed:    $('p2jb-notify-failed').checked,
    notify_service:        $('p2jb-notify-service').value.trim() || null,
  };
  return cfg;
}

function _p2jbToggleAutoRun() {
  const on = document.getElementById('p2jb-auto-run').checked;
  document.getElementById('p2jb-flow-row').style.display = on ? '' : 'none';
}

function _p2jbToggleLuaPort() {
  const on = document.getElementById('p2jb-lua-enable').checked;
  document.getElementById('p2jb-lua-port').disabled = !on;
}

// ─── Start / Stop ────────────────────────────────────────────────
async function startP2JB() {
  await _p2jbRefreshFlowOptions();
  const cfg = _p2jbReadConfig();
  if (!cfg.host) {
    log('Enter a PS5 IP first', 'error');
    return;
  }
  if (cfg.auto_run && !cfg.flow_name) {
    log('Select a flow for auto-run', 'error');
    return;
  }
  try {
    const status = await api('/api/p2jb/start', { method: 'POST', body: cfg });
    _p2jbApplyStatus(status);
    log('P2JB monitor started — waiting for loader…', 'info');
  } catch (e) {
    log('Monitor start failed: ' + e.message, 'error');
  }
}

async function stopP2JB() {
  try {
    const status = await api('/api/p2jb/stop', { method: 'POST' });
    _p2jbApplyStatus(status);
    log('Monitor stopped', 'warn');
  } catch (e) {
    log('Monitor stop failed: ' + e.message, 'error');
  }
}

// ─── Live updates from WebSocket ─────────────────────────────────
function handleP2JBEvent(msg) {
  if (msg.type === 'p2jb_state') {
    _p2jbApplyStatus(msg);
    // After a terminal transition, refresh the history list.
    if (['completed','failed','timeout','stopped','loader_ready'].includes(msg.state)) {
      _p2jbRefreshHistory();
    }
    return;
  }
  if (msg.type === 'p2jb_check') {
    const sub = document.getElementById('p2jb-status-sub');
    if (sub) {
      const cfg = _p2jbReadConfig();
      sub.textContent = `Checking port ${cfg.elf_port} · poll #${msg.poll} · ${msg.elapsed_s}s elapsed`;
    }
    return;
  }
  if (msg.type === 'p2jb_simulation') {
    const sub = document.getElementById('p2jb-status-sub');
    if (sub) sub.textContent = `Loader ready simulation · ${msg.host}:${msg.port}`;
    const pill = document.getElementById('p2jb-status-pill');
    const label = document.getElementById('p2jb-status-label');
    if (pill && label) {
      pill.className = 'p2jb-pill p2jb-pill-ok';
      label.textContent = 'Loader ready (sim)';
    }
    // Auto-revert after 4s so the real status reappears
    setTimeout(() => api('/api/p2jb/status').then(_p2jbApplyStatus), 4000);
  }
}

function _p2jbApplyStatus(status) {
  const pill   = document.getElementById('p2jb-status-pill');
  const label  = document.getElementById('p2jb-status-label');
  const sub    = document.getElementById('p2jb-status-sub');
  const btnGo  = document.getElementById('btn-p2jb-start');
  const btnStop= document.getElementById('btn-p2jb-stop');
  if (!pill || !label) return;

  const meta = P2JB_STATE_LABEL[status.state] || P2JB_STATE_LABEL.idle;
  pill.className = 'p2jb-pill ' + meta.cls;
  label.textContent = meta.text;

  // Sub-line: depends on state
  const cfg = status.config || {};
  if (status.state === 'waiting') {
    sub.textContent = `Polling ${cfg.host || '?'}:${cfg.elf_port || '?'} every ${cfg.check_interval || '?'}s`;
  } else if (status.state === 'loader_ready') {
    sub.textContent = `Loader reachable on ${cfg.host}:${cfg.elf_port}`;
  } else if (status.state === 'running_flow') {
    sub.textContent = `Flow: ${cfg.flow_name || ''}`;
  } else if (status.state === 'completed') {
    sub.textContent = `Flow ${cfg.flow_name || ''} completed`;
  } else if (status.state === 'failed' || status.state === 'timeout') {
    sub.textContent = status.last_error || 'unknown error';
  } else {
    sub.textContent = '';
  }

  _p2jbActive = !!status.active;
  btnGo.style.display   = _p2jbActive ? 'none' : '';
  btnStop.style.display = _p2jbActive ? ''     : 'none';
}

// ─── History list ────────────────────────────────────────────────
const P2JB_RESULT_LABEL = {
  completed:    { text: 'completed',    cls: 'p2jb-res-ok'   },
  loader_ready: { text: 'loader ready', cls: 'p2jb-res-ok'   },
  failed:       { text: 'failed',       cls: 'p2jb-res-err'  },
  timeout:      { text: 'timeout',      cls: 'p2jb-res-err'  },
  stopped:      { text: 'stopped',      cls: 'p2jb-res-warn' },
};

function _p2jbFmtTimestamp(unix_s) {
  if (!unix_s) return '?';
  const d = new Date(unix_s * 1000);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} `
       + `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function _p2jbFmtWaited(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h ${String(m).padStart(2,'0')}m`;
  if (m) return `${m}m ${String(sec).padStart(2,'0')}s`;
  return `${sec}s`;
}

function _p2jbRenderHistory(runs) {
  const list = document.getElementById('p2jb-history-list');
  if (!list) return;
  if (!runs || !runs.length) {
    list.innerHTML = '<li class="p2jb-history-empty">No runs yet.</li>';
    return;
  }
  list.innerHTML = runs.map(r => {
    const res    = P2JB_RESULT_LABEL[r.result] || { text: r.result, cls: '' };
    const name   = r.ps5_name ? `${r.ps5_name} (${r.host})` : r.host;
    const flow   = r.flow_name || (r.auto_run ? '(no flow)' : 'notify only');
    const errTxt = r.error ? ` — ${r.error}` : '';
    return `<li class="p2jb-history-item">
      <span class="p2jb-history-date">${_p2jbFmtTimestamp(r.started_at)}</span>
      <span class="p2jb-history-waited">${_p2jbFmtWaited(r.waited_s)}</span>
      <span class="p2jb-history-result ${res.cls}">${res.text}</span>
      <span class="p2jb-history-flow">${flow}</span>
      <span class="p2jb-history-host" title="${name}">${name}</span>
      ${errTxt ? `<span class="p2jb-history-err">${errTxt}</span>` : ''}
    </li>`;
  }).join('');
}

async function _p2jbRefreshHistory() {
  try {
    const r = await api('/api/p2jb/history');
    _p2jbRenderHistory(r.runs || []);
  } catch (_) { /* ignore */ }
}

async function _p2jbClearHistory() {
  if (!confirm('Clear monitor run history?')) return;
  try {
    await api('/api/p2jb/history', { method: 'DELETE' });
    _p2jbRenderHistory([]);
    log('P2JB monitor history cleared', 'info');
  } catch (e) {
    log('Could not clear history: ' + e.message, 'error');
  }
}

// ─── Advanced — test buttons / simulation ────────────────────────
function _p2jbTestBody(extra = {}) {
  const cfg = _p2jbReadConfig();
  return {
    host:                  cfg.host,
    elf_port:              cfg.elf_port,
    flow_name:             cfg.flow_name || null,
    notify_service:        cfg.notify_service || null,
    notify_loader_ready:   cfg.notify_loader_ready,
    notify_flow_started:   cfg.notify_flow_started,
    notify_flow_completed: cfg.notify_flow_completed,
    notify_flow_failed:    cfg.notify_flow_failed,
    ...extra,
  };
}

async function _p2jbTest(event) {
  try {
    const r = await api('/api/p2jb/test', {
      method: 'POST',
      body: _p2jbTestBody({ event }),
    });
    if (r.success) {
      log(`Test notification sent successfully (${event})`, 'success');
    } else {
      log(`Notification test failed. Check notify service. ${r.error || ''}`, 'error');
    }
  } catch (e) {
    log('Test notification failed: ' + e.message, 'error');
  }
}

async function _p2jbSimulate() {
  const runReal = document.getElementById('p2jb-test-realflow').checked;
  const cfg = _p2jbReadConfig();
  if (runReal) {
    if (!cfg.flow_name) {
      log('Select a flow before enabling real-flow simulation', 'error');
      return;
    }
    if (!confirm('This will run the selected flow FOR REAL against '
               + cfg.host + '. Continue?')) {
      return;
    }
  }
  try {
    const r = await api('/api/p2jb/test', {
      method: 'POST',
      body: _p2jbTestBody({ event: 'simulate_loader_ready', run_real_flow: runReal }),
    });
    if (r.success) {
      log(r.ran_flow
            ? `Simulated loader ready + ran flow (${r.event})`
            : 'Loader-ready simulation sent', 'success');
    } else {
      log(`Simulation failed: ${r.error || r.event}`, 'error');
    }
  } catch (e) {
    log('Simulation failed: ' + e.message, 'error');
  }
}

function _p2jbToggleRealFlowWarn() {
  const on = document.getElementById('p2jb-test-realflow').checked;
  document.getElementById('p2jb-test-realflow-warn').style.display = on ? '' : 'none';
}

window.initP2JBMonitor = initP2JBMonitor;
window.handleP2JBEvent = handleP2JBEvent;
