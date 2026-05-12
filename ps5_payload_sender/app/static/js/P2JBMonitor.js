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

  // Pull persisted config and current status in parallel
  const [cfg, status] = await Promise.all([
    api('/api/p2jb/config').catch(() => ({})),
    api('/api/p2jb/status').catch(() => ({ state: 'idle' })),
  ]);
  _p2jbApplyConfig(cfg || {});
  _p2jbApplyStatus(status);

  // Wire up buttons
  document.getElementById('btn-p2jb-start').addEventListener('click', startP2JB);
  document.getElementById('btn-p2jb-stop' ).addEventListener('click', stopP2JB);
  document.getElementById('p2jb-auto-run').addEventListener('change', _p2jbToggleAutoRun);
  _p2jbToggleAutoRun();

  document.getElementById('p2jb-lua-enable').addEventListener('change', _p2jbToggleLuaPort);
  _p2jbToggleLuaPort();
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
    return;
  }
  if (msg.type === 'p2jb_check') {
    const sub = document.getElementById('p2jb-status-sub');
    if (sub) {
      const cfg = _p2jbReadConfig();
      sub.textContent = `Checking port ${cfg.elf_port} · poll #${msg.poll} · ${msg.elapsed_s}s elapsed`;
    }
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

window.initP2JBMonitor = initP2JBMonitor;
window.handleP2JBEvent = handleP2JBEvent;
