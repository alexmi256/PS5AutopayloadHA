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

  // ── Row 3: source info + version (always rendered) ──────────────
  {
    const rowSrc = document.createElement('div');
    rowSrc.className = 'p-row-source';

    if (p.source) {
      // GitHub-sourced payload
      const srcBadge = document.createElement('span');
      srcBadge.className   = 'source-badge';
      srcBadge.textContent = '⎔ ' + p.source.repo;
      srcBadge.title       = p.source.repo;
      rowSrc.appendChild(srcBadge);

      const verLabel = document.createElement('span');
      verLabel.className   = 'p-ver-label';
      verLabel.textContent = 'Version:';
      rowSrc.appendChild(verLabel);

      const versions = Array.isArray(p.source.versions) ? p.source.versions : [];
      if (versions.length > 0) {
        const verSel = document.createElement('select');
        verSel.className = 'p-ver-select';
        versions.forEach((v, i) => {
          const opt = document.createElement('option');
          opt.value               = v.tag;
          opt.textContent         = v.tag === p.source.latest_version ? `${v.tag} (latest)` : v.tag;
          opt.dataset.downloadUrl = v.download_url;
          if (v.tag === p.source.version) opt.selected = true;
          verSel.appendChild(opt);
        });
        verSel.addEventListener('change', async () => {
          const newVer = verSel.value;
          if (newVer === p.source.version) return;
          const opt = verSel.options[verSel.selectedIndex];
          // Lazy usage check
          let usedIn = [];
          try {
            const usage = await api(`/api/payloads/${encodeURIComponent(p.name)}/usage`);
            usedIn = usage.used_in || [];
          } catch (_) {}
          if (builder.steps.some(s => s.type === 'payload' && s.filename === p.name)) usedIn.push('Builder');
          if (usedIn.length && !confirm(`'${p.name}' is used in: ${usedIn.join(', ')}.\nSwitch to ${newVer}?`)) {
            verSel.value = p.source.version; return;
          }
          verSel.disabled = true;
          try {
            await api(`/api/payloads/${encodeURIComponent(p.name)}/switch-version`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                repo: p.source.repo, asset_name: p.source.asset,
                download_url: opt.dataset.downloadUrl, version: newVer,
              }),
            });
            p.source.version = newVer;
            if (state.updateResults) delete state.updateResults[p.name];
            showToast(`Switched to ${newVer}`);
            await refreshPayloads();
          } catch (e) {
            log('Switch version: ' + e.message, 'error');
            verSel.value = p.source.version;
            verSel.disabled = false;
          }
        });
        rowSrc.appendChild(verSel);
      } else {
        // No version history — show disabled dropdown with appropriate message
        const verSel = document.createElement('select');
        verSel.className = 'p-ver-select';
        verSel.disabled  = true;
        const opt = document.createElement('option');
        opt.textContent = p.source.version || 'No versions available';
        if (p.source.version) opt.value = p.source.version;
        opt.selected = true;
        verSel.appendChild(opt);
        rowSrc.appendChild(verSel);
      }
    } else {
      // Local payload — no source control
      const localBadge = document.createElement('span');
      localBadge.className   = 'p-local-file';
      localBadge.textContent = 'Local file · No version control';
      rowSrc.appendChild(localBadge);
    }

    // ── Update / up-to-date indicator (sourced payloads only) ────────
    const updateInfo = p.source ? (state.updateResults || {})[p.name] : null;
    if (p.source && updateInfo) {
      // New version available
      const warnEl = document.createElement('span');
      warnEl.className   = 'payload-update-warn';
      warnEl.textContent = `⚠ ${updateInfo.latest_version}`;
      warnEl.title       = 'New version available on GitHub';
      const updBtn = document.createElement('button');
      updBtn.className   = 'btn btn-sm source-update-btn';
      updBtn.textContent = 'Update';
      updBtn.addEventListener('click', async ev => {
        ev.stopPropagation();
        // Workflow check before updating
        let usedIn = [];
        try { const u = await api(`/api/payloads/${encodeURIComponent(p.name)}/usage`); usedIn = u.used_in || []; } catch (_) {}
        if (builder.steps.some(s => s.type === 'payload' && s.filename === p.name)) usedIn.push('Builder');
        if (usedIn.length && !confirm(`'${p.name}' is used in: ${usedIn.join(', ')}.\nUpdate to ${updateInfo.latest_version}?`)) return;
        updBtn.disabled = true; updBtn.textContent = 'Updating…';
        try {
          await api(`/api/payloads/${encodeURIComponent(p.name)}/switch-version`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              repo: updateInfo.repo, asset_name: updateInfo.asset_name,
              download_url: updateInfo.download_url, version: updateInfo.latest_version,
            }),
          });
          delete state.updateResults[p.name];
          showToast(`Updated to ${updateInfo.latest_version}`);
          await refreshPayloads();
          if (typeof checkAllUpdates === 'function') checkAllUpdates();
        } catch (e) {
          log('Update: ' + e.message, 'error');
          updBtn.disabled = false; updBtn.textContent = 'Update';
        }
      });
      rowSrc.appendChild(warnEl);
      rowSrc.appendChild(updBtn);
    } else if (p.source && state.updateCheckDone) {
      // Check has run and this payload is current
      const upToDate = document.createElement('span');
      upToDate.className   = 'payload-uptodate';
      upToDate.textContent = '✔ Up to date';
      rowSrc.appendChild(upToDate);
    }

    // ── Builder usage warning ────────────────────────────────────────
    const builderUses = builder.steps.filter(s => s.type === 'payload' && s.filename === p.name).length;
    if (builderUses) {
      const usedWarn = document.createElement('span');
      usedWarn.className   = 'payload-used-warn';
      usedWarn.textContent = `⚠ In builder`;
      usedWarn.title       = `Used in ${builderUses} builder step${builderUses > 1 ? 's' : ''}`;
      rowSrc.appendChild(usedWarn);
    }

    // Rollback button if backup exists (sourced payloads only)
    if (p.source && p.source.backup_version) {
      const rbBtn = document.createElement('button');
      rbBtn.className   = 'btn btn-sm';
      rbBtn.textContent = `↩ ${p.source.backup_version}`;
      rbBtn.title       = 'Rollback to previous version';
      rbBtn.style.marginLeft = 'auto';
      rbBtn.addEventListener('click', async ev => {
        ev.stopPropagation();
        if (!confirm(`Roll back '${p.name}' to ${p.source.backup_version}?`)) return;
        rbBtn.disabled = true; rbBtn.textContent = 'Rolling back…';
        try {
          await api(`/api/payloads/${encodeURIComponent(p.name)}/rollback`, { method: 'POST' });
          showToast(`Rolled back to ${p.source.backup_version}`);
          await refreshPayloads();
        } catch (e) {
          log('Rollback: ' + e.message, 'error');
          rbBtn.disabled = false; rbBtn.textContent = `↩ ${p.source.backup_version}`;
        }
      });
      rowSrc.appendChild(rbBtn);
    }

    el.appendChild(rowSrc);
  }

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
