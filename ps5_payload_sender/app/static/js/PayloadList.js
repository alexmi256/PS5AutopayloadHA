'use strict';

// ── Payload List ─────────────────────────────────────────────────
async function refreshPayloads() {
  try {
    const data = await api('/api/payloads');
    state.payloads = data.payloads || [];
    // Remove stale selections
    state.selectedPayloads = new Set(
      [...(state.selectedPayloads || new Set())].filter(
        n => state.payloads.some(p => p.name === n)
      )
    );
    renderPayloadFilters();
    renderPayloads();
  } catch (e) { log('Load payloads: ' + e.message, 'error'); }
}

function renderPayloads() {
  builderUpdatePayloadDropdown();
  const c        = document.getElementById('payload-list');
  c.innerHTML    = '';
  const filtered = getFilteredPayloads();
  if (!filtered.length) {
    const query = (state.payloadSearch || '').trim();
    c.innerHTML = `<div class="empty-state">${
      query
        ? 'No payloads found.'
        : state.payloadFilter === 'favorites'
          ? 'No favorites yet. Click ⭐ on a payload to add it.'
          : 'No payloads. Upload a .lua or .elf file.'
    }</div>`;
    renderBulkBar();
    return;
  }
  filtered.forEach(p => c.appendChild(buildPayloadItem(p)));
  renderBulkBar();
}

function renderBulkBar() {
  const bar = document.getElementById('bulk-action-bar');
  if (!bar) return;
  const sel = state.selectedPayloads || new Set();
  if (sel.size === 0) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = '';
  const countEl = bar.querySelector('#bulk-count');
  if (countEl) countEl.textContent = `${sel.size} selected`;
  // Sync select-all checkbox
  const allCb = document.getElementById('payload-select-all');
  if (allCb) {
    const filtered = getFilteredPayloads();
    allCb.checked = filtered.length > 0 && filtered.every(p => sel.has(p.name));
    allCb.indeterminate = sel.size > 0 && !allCb.checked;
  }
}

function buildPayloadItem(p) {
  const isFav = state.payloadFavorites.includes(p.name);
  const isSel = (state.selectedPayloads || new Set()).has(p.name);
  const el    = document.createElement('div');
  el.className = 'payload-item fade' + (isFav ? ' payload-fav' : '') + (isSel ? ' payload-selected' : '');

  // ── Row 1: checkbox + badge + name ───────────────────────────────
  const rowTop = document.createElement('div');
  rowTop.className = 'p-row-top';

  const cb = document.createElement('input');
  cb.type    = 'checkbox'; cb.className = 'p-checkbox'; cb.checked = isSel;
  cb.addEventListener('change', e => {
    e.stopPropagation();
    if (!state.selectedPayloads) state.selectedPayloads = new Set();
    if (cb.checked) state.selectedPayloads.add(p.name);
    else            state.selectedPayloads.delete(p.name);
    el.classList.toggle('payload-selected', cb.checked);
    renderBulkBar();
  });

  const badge = document.createElement('span');
  badge.className  = `badge ${p.ext === '.lua' ? 'badge-lua' : 'badge-elf'}`;
  badge.textContent = p.ext.replace('.', '').toUpperCase();

  const name = document.createElement('span');
  name.className  = 'p-name'; name.textContent = p.name;

  rowTop.appendChild(cb); rowTop.appendChild(badge); rowTop.appendChild(name);

  // ── Row 2: meta + port override + actions ────────────────────────
  const rowBot = document.createElement('div');
  rowBot.className = 'p-row-bottom';

  const meta = document.createElement('span');
  meta.className  = 'p-meta';
  meta.textContent = fmt(p.size) + (p.mtime ? '  ' + fmtDate(p.mtime) : '');

  const portInput       = document.createElement('input');
  portInput.type        = 'number';
  portInput.className   = 'p-port-input advanced-only';
  portInput.placeholder = String(p.auto_port);
  portInput.min         = '1';
  portInput.max         = '65535';
  portInput.title       = 'Override port (empty = auto)';

  const favBtn = document.createElement('button');
  favBtn.className   = 'p-fav' + (isFav ? ' p-fav-active' : '');
  favBtn.textContent = '⭐';
  favBtn.title       = isFav ? 'Remove from favorites' : 'Add to favorites';
  favBtn.addEventListener('click', e => { e.stopPropagation(); togglePayloadFavorite(p.name); });

  const sendBtn = document.createElement('button');
  sendBtn.className   = 'p-send';
  sendBtn.textContent = '▶ Send to PS5';
  sendBtn.addEventListener('click', async e => {
    e.stopPropagation();
    await sendDirect(p.name, p.auto_port, portInput, sendBtn);
  });

  const del = document.createElement('button');
  del.className   = 'p-del';
  del.textContent = '✕';
  del.title       = 'Delete';
  del.addEventListener('click', async e => {
    e.stopPropagation();
    if (!confirm(`Delete '${p.name}'?`)) return;
    try {
      await api(`/api/payloads/${encodeURIComponent(p.name)}`, { method: 'DELETE' });
      state.payloadFavorites = state.payloadFavorites.filter(f => f !== p.name);
      if (state.selectedPayloads) state.selectedPayloads.delete(p.name);
      await refreshPayloads();
      log(`'${p.name}' deleted`);
    } catch (err) { log('Delete: ' + err.message, 'error'); }
  });

  rowBot.appendChild(meta);
  rowBot.appendChild(portInput); rowBot.appendChild(favBtn);
  rowBot.appendChild(sendBtn); rowBot.appendChild(del);

  el.appendChild(rowTop);
  el.appendChild(rowBot);
  return el;
}

function togglePayloadFavorite(filename) {
  if (state.payloadFavorites.includes(filename)) {
    state.payloadFavorites = state.payloadFavorites.filter(f => f !== filename);
  } else {
    state.payloadFavorites.push(filename);
  }
  renderPayloads();
  scheduleSave();
}

async function sendDirect(filename, autoPort, portInput, btn) {
  const host    = getHost(); if (!host) return;
  const portVal = parseInt(portInput.value, 10);
  const port    = (portVal > 0 && portVal <= 65535) ? portVal : autoPort;
  btn.disabled  = true; btn.textContent = 'Sending…';
  try {
    await api('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, filename, port }),
    });
    btn.textContent = 'Sent ✔'; btn.className = 'p-send ok';
  } catch (e) {
    log('Send: ' + e.message, 'error');
    btn.textContent = 'Failed ❌'; btn.className = 'p-send err';
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = '▶ Send to PS5'; btn.className = 'p-send'; }, 2500);
}

async function bulkDeleteSelected() {
  const sel = state.selectedPayloads;
  if (!sel || sel.size === 0) return;
  if (!confirm(`Delete ${sel.size} payload(s)? This cannot be undone.`)) return;
  const names = [...sel];
  let deleted = 0;
  for (const name of names) {
    try {
      await api(`/api/payloads/${encodeURIComponent(name)}`, { method: 'DELETE' });
      state.payloadFavorites = state.payloadFavorites.filter(f => f !== name);
      deleted++;
    } catch (e) { log(`Delete '${name}': ${e.message}`, 'error'); }
  }
  state.selectedPayloads = new Set();
  await refreshPayloads();
  if (deleted > 0) { log(`${deleted} payload(s) deleted`, 'success'); showToast(`${deleted} payload(s) deleted`); }
}

async function uploadPayloads(files) {
  if (!files || !files.length) return;
  const bar   = document.getElementById('upload-bar');
  const label = document.getElementById('upload-label');
  const prog  = document.getElementById('upload-progress');
  prog.style.display = 'block';
  for (let i = 0; i < files.length; i++) {
    label.textContent   = `${files[i].name} (${i + 1}/${files.length})`;
    bar.style.width     = `${(i / files.length) * 100}%`;
    const fd = new FormData(); fd.append('file', files[i]);
    try {
      const d = await api('/api/payloads/upload', { method: 'POST', body: fd });
      log(`'${d.filename}' uploaded (${fmt(d.size)}, port ${d.auto_port})`, 'success');
    } catch (e) { log(`Upload '${files[i].name}': ${e.message}`, 'error'); }
  }
  bar.style.width   = '100%';
  label.textContent = 'Done!';
  setTimeout(() => { prog.style.display = 'none'; bar.style.width = '0'; }, 2000);
  document.getElementById('payload-upload').value = '';
  await refreshPayloads();
}
