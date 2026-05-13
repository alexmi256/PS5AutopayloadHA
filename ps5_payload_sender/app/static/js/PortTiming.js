'use strict';

// ── Port Timing Analysis ─────────────────────────────────────────

async function loadTimingStats() {
  const container = document.getElementById('timing-stats');
  if (!container) return;
  try {
    const { stats } = await api('/api/timing');
    const ports = Object.keys(stats);
    if (!ports.length) {
      container.innerHTML = '<p class="section-hint">No timing data yet. Run a payload or use Analyze.</p>';
      return;
    }
    container.innerHTML = ports.map(p => {
      const s = stats[p];
      const avg  = (s.avg_ms  / 1000).toFixed(1);
      const last = (s.last_ms / 1000).toFixed(1);
      const min  = (s.min_ms  / 1000).toFixed(1);
      const max  = (s.max_ms  / 1000).toFixed(1);
      return `
        <div class="timing-row">
          <span class="timing-port">Port ${s.port}</span>
          <span class="timing-stat">avg&nbsp;<b>${avg}s</b></span>
          <span class="timing-stat">last&nbsp;<b>${last}s</b></span>
          <span class="timing-stat timing-muted">min&nbsp;${min}s&nbsp;/&nbsp;max&nbsp;${max}s</span>
          <span class="timing-count">${s.count} run${s.count !== 1 ? 's' : ''}</span>
        </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = '<p class="section-hint">Could not load timing data.</p>';
  }
}

async function analyzePort() {
  const host = getHost();
  if (!host) return;
  const portEl = document.getElementById('timing-port-input');
  const port   = parseInt(portEl?.value || '9026', 10);
  const btn    = document.getElementById('btn-timing-analyze');
  if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }

  try {
    const res = await api('/api/timing/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, port, timeout: 30, interval: 0.5 }),
    });
    showToast(res.reachable
      ? `Port ${port} ready in ${(res.duration_ms / 1000).toFixed(1)}s`
      : `Port ${port} not reachable`);
    await loadTimingStats();
  } catch (e) {
    showToast('Analyze failed: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML  = icon('play') + ' Analyze'; }
  }
}

async function clearTimingStats() {
  if (!confirm('Clear all timing data?')) return;
  await api('/api/timing', { method: 'DELETE' });
  await loadTimingStats();
  showToast('Timing data cleared');
}

// Record timing from a successful port wait (called by StatusLog / ws)
async function recordPortTiming(port, durationMs, startIso, readyIso) {
  try {
    await api('/api/timing/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port, duration_ms: durationMs, start: startIso, ready: readyIso }),
    });
    await loadTimingStats();
  } catch (_) { /* non-critical */ }
}
