'use strict';

// ── Flow & Port Analysis ─────────────────────────────────────────

async function startFlowAnalysis() {
  const host = getHost();
  if (!host) return;
  if (!builder.steps.length) { showToast('No steps in builder'); return; }

  const safeMode = document.getElementById('flow-safe-mode').checked;
  const btn      = document.getElementById('btn-global-analyze');
  const timelineEl = document.getElementById('flow-timeline');

  if (btn) { btn.disabled = true; btn.textContent = '⏳ Analyzing…'; }
  timelineEl.innerHTML = '<div class="flow-tl-row"><span class="flow-tl-ts">[00:00]</span><span class="flow-tl-msg">Flow started…</span></div>';

  try {
    const res = await api('/api/flow/analyze', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ host, steps: builder.steps, safe_mode: safeMode }),
    });
    renderFlowTimeline(res.run);
    _refreshFlowSectionSummary();
  } catch (e) {
    showToast('Analysis failed: ' + e.message);
    log('Flow analysis: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '📊 Analyze'; }
  }
}

// ── Timeline renderer ────────────────────────────────────────────

function renderFlowTimeline(run) {
  const el = document.getElementById('flow-timeline');
  if (!run || !run.steps) {
    el.innerHTML = '<p class="section-hint">No run data.</p>';
    return;
  }

  const ts  = s => '[' +
    String(Math.floor(s / 60)).padStart(2, '0') + ':' +
    String(Math.floor(s % 60)).padStart(2, '0') + ']';

  const lines = [];
  lines.push({ t: 0, msg: 'Flow started' + (run.safe_mode ? ' (Safe Mode)' : ''), lvl: 'info' });

  run.steps.forEach(step => {
    const t = step.offset_s || 0;
    if (step.type === 'wait_port') {
      lines.push({ t, msg: `WAIT port ${step.port}`, lvl: 'info' });
      const endT = t + (step.duration_ms / 1000);
      if (step.reached) {
        lines.push({ t: endT, msg: `Port ${step.port} ready (${(step.duration_ms / 1000).toFixed(1)}s)`, lvl: 'success' });
      } else {
        lines.push({ t: endT, msg: `Port ${step.port} not reachable (timeout)`, lvl: 'error' });
      }
    } else if (step.type === 'delay') {
      lines.push({ t, msg: `DELAY ${step.ms}ms`, lvl: 'info' });
      lines.push({ t: t + step.ms / 1000, msg: `Delay done`, lvl: 'info' });
    } else if (step.type === 'payload') {
      if (step.safe_mode) {
        lines.push({ t, msg: `[SAFE] ${step.filename} → port ${step.port} (skipped)`, lvl: 'warn' });
      } else {
        const dur = step.duration_ms ? ` (${(step.duration_ms / 1000).toFixed(2)}s)` : '';
        lines.push({ t, msg: `${step.filename} sent${dur}`, lvl: step.success ? 'success' : 'error' });
      }
    }
  });

  const total = (run.total_ms || 0) / 1000;
  lines.push({ t: total, msg: `Flow finished — total ${total.toFixed(1)}s`, lvl: 'success' });

  el.innerHTML = lines.map(l =>
    `<div class="flow-tl-row flow-tl-${l.lvl}">` +
    `<span class="flow-tl-ts">${ts(l.t)}</span>` +
    `<span class="flow-tl-msg">${l.msg}</span>` +
    `</div>`
  ).join('');

  // Inefficiency hints
  const hints = _detectInefficiencies(run.steps);
  if (hints.length) {
    el.innerHTML +=
      '<div class="flow-hints">' +
      hints.map(h => `<div class="flow-hint">💡 ${h}</div>`).join('') +
      '</div>';
  }
}

function _detectInefficiencies(steps) {
  const hints = [];
  for (let i = 0; i < steps.length - 1; i++) {
    const s    = steps[i];
    const next = steps[i + 1];
    if (s.type === 'wait_port' && s.reached && next.type === 'delay') {
      const portMs  = s.duration_ms;
      const delayMs = next.ms;
      if (delayMs > portMs) {
        hints.push(
          `Delay ${delayMs}ms after Wait port ${s.port} — port was ready in ` +
          `${(portMs / 1000).toFixed(1)}s, delay may be reducible`
        );
      }
    }
  }
  return hints;
}

// ── Load + display stored runs ───────────────────────────────────

async function loadFlowRuns() {
  try {
    const data = await api('/api/flow/runs');
    if (data.runs && data.runs.length) {
      renderFlowTimeline(data.runs[0]);
    }
    _refreshFlowSectionSummary();
  } catch (_) {}
}

async function clearFlowRuns() {
  if (!confirm('Clear all flow run history?')) return;
  await api('/api/flow/runs', { method: 'DELETE' });
  const el = document.getElementById('flow-timeline');
  if (el) el.innerHTML = '<p class="section-hint">Run Analyze Flow to see step-by-step timing.</p>';
  _refreshFlowSectionSummary();
  showToast('Flow history cleared');
}

function _refreshFlowSectionSummary() {
  api('/api/flow/runs').then(data => {
    const el   = document.getElementById('summary-analysis');
    if (!el) return;
    const runs = data.runs || [];
    if (!runs.length) { el.textContent = ''; return; }
    el.textContent = `last run: ${(runs[0].total_ms / 1000).toFixed(1)}s`;
  }).catch(() => {});
}
