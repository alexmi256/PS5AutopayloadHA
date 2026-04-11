'use strict';

// ── Status Log ───────────────────────────────────────────────────
function log(msg, level = 'info') {
  const container = document.getElementById('status-log');
  const el = document.createElement('div');
  el.className = `log-entry log-${level} fade`;
  const ts = new Date().toLocaleTimeString('en-US',
    { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  const tsEl  = document.createElement('span');
  tsEl.className = 'log-ts'; tsEl.textContent = ts;
  const msgEl = document.createElement('span');
  msgEl.textContent = msg;
  el.appendChild(tsEl); el.appendChild(msgEl);
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  while (container.children.length > 300) container.removeChild(container.firstChild);
}

function clearLog() { document.getElementById('status-log').innerHTML = ''; }

// ── Port Check ───────────────────────────────────────────────────
async function checkPortOnce() {
  const host    = getHost(); if (!host) return;
  const port    = parseInt(document.getElementById('check-port').value, 10);
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
    el.className  = d.reachable ? 'res-ok' : 'res-fail';
    el.textContent = d.reachable
      ? `✓ Port ${port} is reachable`
      : `✗ Port ${port} not reachable`;
    log(el.textContent, d.reachable ? 'success' : 'warn');
  } catch (e) { log('Port check: ' + e.message, 'error'); }
}

async function waitForPort() {
  const host     = getHost(); if (!host) return;
  const port     = parseInt(document.getElementById('check-port').value, 10);
  const timeout  = parseFloat(document.getElementById('check-timeout').value) || 10;
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
    el.className   = d.reachable ? 'res-ok' : 'res-fail';
    el.textContent = d.reachable
      ? `✓ Port ${port} reachable`
      : `✗ Timeout: Port ${port} not reachable`;
  } catch (e) { log('Wait: ' + e.message, 'error'); }
}
