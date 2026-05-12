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

async function initFlowNotify() {
  // History
  await _flowHistoryRefresh();
  document.getElementById('btn-flow-clear-history')
    .addEventListener('click', _flowHistoryClear);

  // Notify service validation
  const svc = document.getElementById('flow-notify-service');
  svc.addEventListener('input', _flowValidateService);

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
  return {
    loader_ready:   document.getElementById('flow-notify-ready').checked,
    flow_started:   document.getElementById('flow-notify-started').checked,
    flow_completed: document.getElementById('flow-notify-completed').checked,
    flow_failed:    document.getElementById('flow-notify-failed').checked,
    service:        document.getElementById('flow-notify-service').value.trim(),
  };
}

function flowNotifyApplyConfig(cfg) {
  cfg = cfg || {};
  document.getElementById('flow-notify-ready').checked     = cfg.loader_ready    !== false;
  document.getElementById('flow-notify-started').checked   = !!cfg.flow_started;
  document.getElementById('flow-notify-completed').checked = cfg.flow_completed  !== false;
  document.getElementById('flow-notify-failed').checked    = cfg.flow_failed     !== false;
  document.getElementById('flow-notify-service').value     = cfg.service || '';
  _flowValidateService();
}

function flowNotifyRenderHeader(cfg) {
  // Render the same `# ~notify …` header the Python parser expects.
  const parts = [
    `loader_ready=${cfg.loader_ready ? 'on' : 'off'}`,
    `flow_started=${cfg.flow_started ? 'on' : 'off'}`,
    `flow_completed=${cfg.flow_completed ? 'on' : 'off'}`,
    `flow_failed=${cfg.flow_failed ? 'on' : 'off'}`,
  ];
  if (cfg.service) parts.push(`service="${cfg.service}"`);
  return `# ~notify ${parts.join(' ')}`;
}

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
    _updateWaitLoaderLiveOverlay(msg);
    // Also push a sparse hint into the main log so the user sees activity
    // even if the builder card is scrolled off-screen.
    if (msg.poll % 10 === 1) {
      log(`Waiting for loader on port ${msg.port} — poll #${msg.poll} (${_fmtWaited(msg.elapsed_s)} elapsed)`, 'info');
    }
  }
}

function _updateWaitLoaderLiveOverlay(msg) {
  // Find the wait_for_loader step whose port matches the poll's port —
  // there's usually only one, so a name-attr lookup is enough.
  const live = document.querySelector(
    `.builder-step .step-wait-live[data-port="${msg.port}"]`,
  );
  if (!live) return;
  const elapsedTxt = _fmtWaited(msg.elapsed_s || 0);
  live.classList.add('active');
  live.classList.toggle('reachable', !!msg.ok);
  live.innerHTML = msg.ok
    ? `<span class="step-wait-icon">✅</span>
       <span class="step-wait-text">Loader reachable on port ${msg.port}
         (${elapsedTxt} elapsed, ${msg.consecutive}/${msg.consecutive || 1} stable)</span>`
    : `<span class="step-wait-icon">⏳</span>
       <span class="step-wait-text">Checking port ${msg.port}…
         <span class="step-wait-elapsed">${elapsedTxt} elapsed</span></span>`;
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
