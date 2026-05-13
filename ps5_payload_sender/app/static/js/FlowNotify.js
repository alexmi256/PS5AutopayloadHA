'use strict';

// ─── Flow notification config + history + Advanced test panel ────
//
// Owns three pieces of UI that live inside the Auto-Load Builder card:
//   1. The per-flow "# ~notify …" config (loader_ready / flow_started
//      / flow_completed / flow_failed + optional notify.<service>).
//      Builder writes this into the saved .txt file as a header line.
//   2. The Recent-flow-runs history list.
//   3. The Advanced test panel (5 buttons + Simulate Loader Ready +
//      "Also run flow" checkbox).

const FLOW_RESULT_LABEL = {
  completed:      { text: 'completed',       cls: 'p2jb-res-ok'   },
  loader_ready:   { text: 'loader ready',    cls: 'p2jb-res-ok'   },
  failed_timeout: { text: 'failed: timeout', cls: 'p2jb-res-err'  },
  failed:         { text: 'failed',          cls: 'p2jb-res-err'  },
  stopped:        { text: 'stopped',         cls: 'p2jb-res-warn' },
};

const _FLOW_LOADER_FIELD_IDS = [
  'flow-wait-for-loader', 'flow-notify-ready', 'flow-loader-port',
  'flow-loader-interval', 'flow-loader-timeout',
];

async function initFlowNotify() {
  // History
  await _flowHistoryRefresh();
  document.getElementById('btn-flow-clear-history')
    .addEventListener('click', _flowHistoryClear);

  // Notify service validation + persistent-row visibility
  const svc = document.getElementById('flow-notify-service');
  svc.addEventListener('input', () => {
    _flowValidateService();
    _flowUpdateLoaderUI();
  });

  // Loader-config visibility + warning are driven by the loader_ready toggle
  // and by the contents of the builder. Wire up the relevant inputs.
  _FLOW_LOADER_FIELD_IDS.forEach(id => {
    document.getElementById(id)?.addEventListener('change', _flowUpdateLoaderUI);
    document.getElementById(id)?.addEventListener('input',  _flowUpdateLoaderUI);
  });
  _flowUpdateLoaderUI();

  // Test buttons
  document.querySelectorAll('[data-flow-test]').forEach(btn => {
    btn.addEventListener('click', () => _flowTestNotification(btn.dataset.flowTest));
  });
  document.getElementById('btn-flow-simulate')
    .addEventListener('click', _flowSimulateLoaderReady);
  document.getElementById('flow-test-realflow')
    .addEventListener('change', _flowToggleRealFlowWarn);
}

// ─── Notify config read/apply (used by AutoLoadBuilder) ──────────
function flowNotifyReadConfig() {
  const intOr = (id, fallback) => {
    const v = parseInt(document.getElementById(id).value, 10);
    return Number.isFinite(v) && v > 0 ? v : fallback;
  };
  return {
    wait_for_loader_enabled: document.getElementById('flow-wait-for-loader').checked,
    loader_ready:      document.getElementById('flow-notify-ready').checked,
    flow_started:      document.getElementById('flow-notify-started').checked,
    flow_completed:    document.getElementById('flow-notify-completed').checked,
    flow_failed:       document.getElementById('flow-notify-failed').checked,
    service:           document.getElementById('flow-notify-service').value.trim(),
    persistent:        document.getElementById('flow-notify-persistent').checked,
    loader_port:       intOr('flow-loader-port',     9021),
    loader_interval_s: intOr('flow-loader-interval', 30),
    // UI stores minutes — convert here.
    loader_max_wait_s: intOr('flow-loader-timeout',  180) * 60,
  };
}

function flowNotifyApplyConfig(cfg) {
  cfg = cfg || {};
  document.getElementById('flow-wait-for-loader').checked  = !!cfg.wait_for_loader_enabled;
  document.getElementById('flow-notify-ready').checked     = cfg.loader_ready    !== false;
  document.getElementById('flow-notify-started').checked   = !!cfg.flow_started;
  document.getElementById('flow-notify-completed').checked = cfg.flow_completed  !== false;
  document.getElementById('flow-notify-failed').checked    = cfg.flow_failed     !== false;
  document.getElementById('flow-notify-service').value     = cfg.service || '';
  document.getElementById('flow-notify-persistent').checked = cfg.persistent  !== false;
  if (cfg.loader_port)       document.getElementById('flow-loader-port').value     = cfg.loader_port;
  if (cfg.loader_interval_s) document.getElementById('flow-loader-interval').value = cfg.loader_interval_s;
  if (cfg.loader_max_wait_s) document.getElementById('flow-loader-timeout').value  = Math.round(cfg.loader_max_wait_s / 60);
  _flowValidateService();
  _flowUpdateLoaderUI();
}

function flowNotifyRenderHeader(cfg) {
  // Render the same `# ~notify …` header the Python parser expects.
  // Only include loader-config keys that differ from the defaults so
  // simple flows stay tidy.
  const parts = [
    `loader_ready=${cfg.loader_ready ? 'on' : 'off'}`,
    `flow_started=${cfg.flow_started ? 'on' : 'off'}`,
    `flow_completed=${cfg.flow_completed ? 'on' : 'off'}`,
    `flow_failed=${cfg.flow_failed ? 'on' : 'off'}`,
  ];
  if (cfg.wait_for_loader_enabled) parts.push('wait_for_loader_enabled=on');
  if ((cfg.loader_port       || 9021)  !== 9021)  parts.push(`loader_port=${cfg.loader_port}`);
  if ((cfg.loader_interval_s || 30)    !== 30)    parts.push(`loader_interval_s=${cfg.loader_interval_s}`);
  if ((cfg.loader_max_wait_s || 10800) !== 10800) parts.push(`loader_max_wait_s=${cfg.loader_max_wait_s}`);
  if (cfg.persistent === false) parts.push('persistent=off');
  if (cfg.service) parts.push(`service="${cfg.service}"`);
  return `# ~notify ${parts.join(' ')}`;
}

// Show/hide the loader-related block based on the master "Wait for loader"
// toggle, and the persistent-notification row based on whether a service
// is configured. There's no "must add a ?? step" warning anymore — the
// WAIT FOR LOADER step type is gone; the master toggle IS the trigger.
function _flowUpdateLoaderUI() {
  const master = document.getElementById('flow-wait-for-loader');
  if (!master) return;
  const show = master.checked;
  document.querySelectorAll('.flow-loader-only').forEach(el => {
    el.style.display = show ? '' : 'none';
  });

  // Persistent-notification toggle only matters when a notify.<service>
  // target is set — otherwise persistent is the only channel anyway.
  const svc  = document.getElementById('flow-notify-service').value.trim();
  const row  = document.getElementById('flow-notify-persistent-row');
  if (row) row.style.display = svc ? '' : 'none';
}

// Builder calls this after re-rendering. Kept for back-compat with the
// existing call site even though the warning logic is gone.
window.flowNotifyRefreshWarn = _flowUpdateLoaderUI;

// ─── Validation ──────────────────────────────────────────────────
function _flowValidateService() {
  const inp  = document.getElementById('flow-notify-service');
  const err  = document.getElementById('flow-notify-service-err');
  const val  = inp.value.trim();
  const bad  = !!val && !val.startsWith('notify.');
  if (err) err.style.display = bad ? '' : 'none';
  inp.classList.toggle('input-error', bad);
  return !bad;
}

// ─── WS event handler ────────────────────────────────────────────
function handleFlowNotifyEvent(msg) {
  if (msg.type === 'flow_simulation') {
    log(`Loader-ready simulation: ${msg.host || '?'}:${msg.port || '?'}`, 'info');
    return;
  }
  if (msg.type === 'flow_wait_check') {
    // Sparse progress log so the user sees the flow is alive even when
    // the builder card is scrolled out of view. The in-card live
    // overlay was removed along with the wait_for_loader step type —
    // there is no longer a step in the DOM to update.
    if (msg.poll % 10 === 1) {
      log(`Waiting for loader on port ${msg.port} — poll #${msg.poll} (${_fmtWaited(msg.elapsed_s)} elapsed)`, 'info');
    }
  }
}

// ─── Test buttons ────────────────────────────────────────────────
function _flowTestBody(extra = {}) {
  const builderName = (document.getElementById('builder-profile-name')?.value || '').trim();
  const hostEl = document.getElementById('ps5-ip');
  return {
    notify: flowNotifyReadConfig(),
    // Read IP directly — getHost() would alert() if empty, but the test
    // buttons don't need an IP to validate notification routing.
    host:   (hostEl?.value || '').trim(),
    port:   9021,
    flow_name: builderName,
    ...extra,
  };
}

async function _flowTestNotification(event) {
  if (!_flowValidateService()) {
    log('Fix the notify service (must start with notify.)', 'error');
    return;
  }
  try {
    const r = await api('/api/flow/test_notification', {
      method: 'POST',
      body: _flowTestBody({ event }),
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

async function _flowSimulateLoaderReady() {
  if (!_flowValidateService()) {
    log('Fix the notify service (must start with notify.)', 'error');
    return;
  }
  const runReal = document.getElementById('flow-test-realflow').checked;
  const flowName = (document.getElementById('builder-profile-name')?.value || '').trim();
  if (runReal) {
    if (!flowName) {
      log('Enter a saved flow name before enabling real-flow simulation', 'error');
      return;
    }
    if (!confirm('This will run the saved flow FOR REAL against the configured PS5 IP. Continue?')) {
      return;
    }
  }
  try {
    const r = await api('/api/flow/test_notification', {
      method: 'POST',
      body: _flowTestBody({
        event: 'simulate_loader_ready',
        run_flow: runReal,
        flow_name: flowName,
      }),
    });
    if (r.success) {
      log(r.ran_flow
            ? `Simulated loader ready + ran flow '${flowName}'`
            : 'Loader-ready simulation sent', 'success');
    } else {
      log(`Simulation failed: ${r.error || r.event}`, 'error');
    }
  } catch (e) {
    log('Simulation failed: ' + e.message, 'error');
  }
}

function _flowToggleRealFlowWarn() {
  const on = document.getElementById('flow-test-realflow').checked;
  document.getElementById('flow-test-realflow-warn').style.display = on ? '' : 'none';
}

// ─── History list ────────────────────────────────────────────────
function _fmtTimestamp(unix_s) {
  if (!unix_s) return '?';
  const d = new Date(unix_s * 1000);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} `
       + `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function _fmtWaited(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h ${String(m).padStart(2,'0')}m`;
  if (m) return `${m}m ${String(sec).padStart(2,'0')}s`;
  return `${sec}s`;
}

function _flowHistoryRender(runs) {
  const list = document.getElementById('flow-history-list');
  if (!list) return;
  if (!runs || !runs.length) {
    list.innerHTML = '<li class="p2jb-history-empty">No runs yet.</li>';
    return;
  }
  list.innerHTML = runs.map(r => {
    const res    = FLOW_RESULT_LABEL[r.result] || { text: r.result, cls: '' };
    const name   = r.ps5_name ? `${r.ps5_name} (${r.host})` : r.host;
    const waited = r.loader_waited_s != null
      ? `loader ${_fmtWaited(r.loader_waited_s)}` : _fmtWaited(r.waited_s);
    const errTxt = r.error ? ` — ${r.error}` : '';
    return `<li class="p2jb-history-item">
      <span class="p2jb-history-date">${_fmtTimestamp(r.started_at)}</span>
      <span class="p2jb-history-waited">${waited}</span>
      <span class="p2jb-history-result ${res.cls}">${res.text}</span>
      <span class="p2jb-history-flow">${r.flow_name || '(unnamed)'}</span>
      <span class="p2jb-history-host" title="${name}">${name}</span>
      ${errTxt ? `<span class="p2jb-history-err">${errTxt}</span>` : ''}
    </li>`;
  }).join('');
}

async function _flowHistoryRefresh() {
  try {
    const r = await api('/api/flow/history');
    _flowHistoryRender(r.runs || []);
  } catch (_) { /* ignore */ }
}

async function _flowHistoryClear() {
  if (!confirm('Clear flow history?')) return;
  try {
    await api('/api/flow/history', { method: 'DELETE' });
    _flowHistoryRender([]);
    log('Flow history cleared', 'info');
  } catch (e) {
    log('Could not clear history: ' + e.message, 'error');
  }
}

window.initFlowNotify          = initFlowNotify;
window.handleFlowNotifyEvent   = handleFlowNotifyEvent;
window.flowNotifyReadConfig    = flowNotifyReadConfig;
window.flowNotifyApplyConfig   = flowNotifyApplyConfig;
window.flowNotifyRenderHeader  = flowNotifyRenderHeader;
window.flowHistoryRefresh      = _flowHistoryRefresh;
