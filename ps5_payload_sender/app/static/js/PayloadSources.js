'use strict';

// ── Payload Sources (GitHub) ─────────────────────────────────────
// _editingSourceRepo tracks which source is being edited (null = add mode)
let _editingSourceRepo = null;

function _parseRepoInput(raw) {
  let s = raw.trim();
  s = s.replace(/^https?:\/\//i, '');
  s = s.replace(/^github\.com\//i, '');
  s = s.replace(/\.git$/i, '');
  s = s.replace(/\/+$/, '');
  const parts = s.split('/').filter(Boolean);
  return parts.slice(0, 2).join('/');
}

async function refreshSources() {
  try {
    const data = await api('/api/sources');
    state.sources = data.sources || [];
    renderSourcesList();
    if (typeof updateSourcesSummary === 'function') updateSourcesSummary();
  } catch (e) { log('Load sources: ' + e.message, 'error'); }
}

function renderSourcesList() {
  const container = document.getElementById('sources-list');
  if (!container) return;
  if (!state.sources.length) {
    container.innerHTML = '<div class="empty-state">No sources added yet.</div>';
    return;
  }
  const updatesByRepo = {};
  Object.values(state.updateResults || {}).forEach(u => {
    if (!u.repo) return;
    (updatesByRepo[u.repo] = updatesByRepo[u.repo] || []).push(u);
  });
  container.innerHTML = '';
  state.sources.forEach(src => {
    const updatesForRepo = updatesByRepo[src.repo] || [];
    const el = document.createElement('div');
    el.className = 'source-item fade' + (updatesForRepo.length ? ' has-updates' : '');
    el.dataset.repo = src.repo;

    // ── Main row: info + buttons ─────────────────────────────────
    const mainRow = document.createElement('div');
    mainRow.className = 'source-main-row';

    const info = document.createElement('div');
    info.className = 'source-info';
    const nameRow = document.createElement('div');
    nameRow.className = 'source-name-row';
    const nameEl = document.createElement('span');
    nameEl.className   = 'source-repo';
    nameEl.textContent = src.display_name || src.repo;
    nameEl.title       = src.repo;
    nameRow.appendChild(nameEl);
    if (updatesForRepo.length) {
      const upBadge = document.createElement('span');
      upBadge.className = 'source-update-badge';
      upBadge.textContent = `⚠ ${updatesForRepo.length} update${updatesForRepo.length > 1 ? 's' : ''}`;
      upBadge.title = updatesForRepo
        .map(u => `${u.filename}: ${u.current_version} → ${u.latest_version}`)
        .join('\n');
      nameRow.appendChild(upBadge);
    }
    info.appendChild(nameRow);
    if (src.filter) {
      const filterEl = document.createElement('span');
      filterEl.className = 'source-filter';
      filterEl.textContent = `filter: ${src.filter}`;
      info.appendChild(filterEl);
    }

    const btns = document.createElement('div');
    btns.className = 'source-btns';

    const checkBtn = document.createElement('button');
    checkBtn.className = 'btn btn-sm source-check-btn';
    checkBtn.textContent = '↻ Check';
    checkBtn.title = 'Check for new payloads and updates';
    checkBtn.addEventListener('click', () => checkSourceUpdates(src.repo, el));

    const editBtn = document.createElement('button');
    editBtn.className = 'btn btn-sm';
    editBtn.textContent = 'Edit';
    editBtn.title = 'Edit source';
    editBtn.addEventListener('click', () => editSource(src));

    const delBtn = document.createElement('button');
    delBtn.className = 'btn btn-sm btn-danger';
    delBtn.textContent = 'Delete';
    delBtn.title = 'Remove source';
    delBtn.addEventListener('click', () => deleteSource(src.repo));

    btns.appendChild(checkBtn);
    btns.appendChild(editBtn);
    btns.appendChild(delBtn);
    mainRow.appendChild(info);
    mainRow.appendChild(btns);

    // ── Check results panel (hidden until Check clicked) ─────────
    const panel = document.createElement('div');
    panel.className = 'source-check-panel';
    panel.style.display = 'none';

    el.appendChild(mainRow);
    el.appendChild(panel);
    container.appendChild(el);
  });
}

// ── Add / Edit Source panel ───────────────────────────────────────
function toggleAddSourcePanel() {
  const panel = document.getElementById('source-add-panel');
  const isOpen = panel.style.display !== 'none';
  if (isOpen) {
    _closeSourcePanel();
  } else {
    _openSourcePanel();
  }
}

function _openSourcePanel(prefill = null) {
  _editingSourceRepo = prefill ? prefill.repo : null;

  // Pre-fill (edit mode) or clear (add mode)
  document.getElementById('source-repo-input').value    = prefill?.repo         || '';
  document.getElementById('source-display-input').value = prefill?.display_name || '';
  document.getElementById('source-filter-input').value  = prefill?.filter       || '';

  // Source type radio
  const typeVal = prefill?.source_type || 'auto';
  const radio = document.querySelector(`input[name="src-type"][value="${typeVal}"]`);
  if (radio) radio.checked = true;
  _onSourceTypeChange();

  // Folder — pre-populate with saved value
  if (prefill?.folder && typeVal === 'folder') {
    const sel = document.getElementById('source-folder-select');
    if (sel) {
      sel.innerHTML = `<option value="${prefill.folder}" selected>${prefill.folder}</option>`;
      document.getElementById('source-folder-hint').textContent = '';
    }
  }

  // Update title and button labels for edit vs add
  const titleEl  = document.getElementById('source-panel-title');
  const fetchBtn = document.getElementById('btn-source-fetch');
  const saveBtn  = document.getElementById('btn-source-save');
  if (titleEl)  titleEl.textContent  = _editingSourceRepo ? 'Edit Source' : 'Add Source';
  if (fetchBtn) fetchBtn.textContent = _editingSourceRepo ? '↻ Re-scan'   : 'Detect Payloads';
  if (saveBtn)  saveBtn.style.display = _editingSourceRepo ? '' : 'none';

  document.getElementById('source-detected').style.display = 'none';
  document.getElementById('source-add-status').textContent = '';
  document.getElementById('source-add-status').className = 'source-status';

  const panel = document.getElementById('source-add-panel');
  panel.style.display = '';
  document.getElementById('source-repo-input').focus();
}

function _closeSourcePanel() {
  _editingSourceRepo = null;
  document.getElementById('source-add-panel').style.display = 'none';
}

function editSource(src) {
  _openSourcePanel(src);
}

// ── Save source config without re-scanning ────────────────────────
async function saveSourceConfig() {
  const repo = _parseRepoInput(document.getElementById('source-repo-input').value);
  const statusEl = document.getElementById('source-add-status');
  if (!repo) {
    statusEl.textContent = 'Enter a repository'; statusEl.className = 'source-status error'; return;
  }
  const [owner, repoName] = repo.split('/');
  const sourceType = _getSourceType();
  const folder = sourceType === 'folder'
    ? (document.getElementById('source-folder-select')?.value || '') : '';
  const filter      = document.getElementById('source-filter-input').value.trim();
  const displayName = document.getElementById('source-display-input').value.trim();

  try {
    // Delete old + add updated entry
    if (_editingSourceRepo && _editingSourceRepo !== repo) {
      const [oldOwner, oldRepoName] = _editingSourceRepo.split('/');
      await api(`/api/sources/${encodeURIComponent(oldOwner)}/${encodeURIComponent(oldRepoName)}`,
        { method: 'DELETE' });
    }
    await api(`/api/sources/${encodeURIComponent(owner)}/${encodeURIComponent(repoName)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filter, source_type: sourceType, folder, display_name: displayName }),
    });
    statusEl.textContent = 'Source updated.'; statusEl.className = 'source-status ok';
    _editingSourceRepo = null;
    await refreshSources();
    setTimeout(_closeSourcePanel, 800);
  } catch (e) {
    statusEl.textContent = 'Error: ' + e.message; statusEl.className = 'source-status error';
  }
}

// ── Source-type radio toggle ─────────────────────────────────────
function _onSourceTypeChange() {
  const type = _getSourceType();
  const folderWrap = document.getElementById('source-folder-wrap');
  if (folderWrap) folderWrap.style.display = type === 'folder' ? '' : 'none';
}

function _getSourceType() {
  const el = document.querySelector('input[name="src-type"]:checked');
  return el ? el.value : 'auto';
}

// ── Fetch repo folders ────────────────────────────────────────────
async function loadRepoFolders() {
  const repoInput = document.getElementById('source-repo-input');
  const repo = _parseRepoInput(repoInput.value);
  if (!repo) {
    showToast('Enter a repository first');
    return;
  }
  const sel    = document.getElementById('source-folder-select');
  const hint   = document.getElementById('source-folder-hint');
  const btn    = document.getElementById('btn-load-folders');
  if (btn) { btn.disabled = true; btn.textContent = '⏳'; }

  try {
    const data = await api(`/api/sources/tree?repo=${encodeURIComponent(repo)}`);
    const folders = data.folders || [];
    sel.innerHTML = '<option value="">– select a folder –</option>';
    folders.forEach(f => {
      const opt = document.createElement('option');
      opt.value = f; opt.textContent = f;
      sel.appendChild(opt);
    });
    // Smart default: suggest payloads / bin / build
    const SUGGEST = ['payloads', 'bin', 'build', 'releases'];
    const suggested = folders.find(f => SUGGEST.includes(f.toLowerCase()));
    if (suggested) {
      sel.value = suggested;
      if (hint) hint.textContent = `Suggested: /${suggested}`;
    } else {
      if (hint) hint.textContent = '';
    }
    if (!folders.length) {
      sel.innerHTML = '<option value="">No sub-folders found</option>';
    }
  } catch (e) {
    showToast('Could not load folders: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Load'; }
  }
}

async function addSource() {
  const repoInput   = document.getElementById('source-repo-input');
  const filterInput = document.getElementById('source-filter-input');
  const statusEl    = document.getElementById('source-add-status');
  const repo = _parseRepoInput(repoInput.value);
  repoInput.value = repo;
  if (!repo) {
    statusEl.textContent = 'Enter a repository (e.g. ps5-payload-dev/kstuff)';
    statusEl.className = 'source-status error';
    return;
  }

  const sourceType = _getSourceType();
  const folder     = sourceType === 'folder'
    ? (document.getElementById('source-folder-select')?.value || '')
    : '';

  const scanLabel = sourceType === 'releases' ? 'releases'
    : sourceType === 'folder' ? `folder /${folder || '(root)'}`
    : 'repository';
  statusEl.textContent = `Scanning ${scanLabel}…`;
  statusEl.className   = 'source-status loading';
  document.getElementById('source-detected').style.display = 'none';

  try {
    // In edit mode: remove old entry first if the repo slug changed
    if (_editingSourceRepo && _editingSourceRepo !== repo) {
      const [oldOwner, oldRepo] = _editingSourceRepo.split('/');
      await api(`/api/sources/${encodeURIComponent(oldOwner)}/${encodeURIComponent(oldRepo)}`,
        { method: 'DELETE' });
    }

    const data = await api('/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo,
        filter:       filterInput.value.trim(),
        source_type:  sourceType,
        folder,
        display_name: document.getElementById('source-display-input').value.trim(),
      }),
    });
    const linked = data.auto_linked || [];
    const src    = data.assets[0]?.source_type === 'repo_file' ? 'repo files' : 'releases';
    const msg = linked.length
      ? `Found ${data.assets.length} payload(s) in ${src} — auto-linked: ${linked.join(', ')}`
      : `Found ${data.assets.length} payload(s) in ${src}`;
    statusEl.textContent = msg;
    statusEl.className   = 'source-status ok';
    _renderDetectedPayloads(data.repo, data.assets);
    if (linked.length) await refreshPayloads();
    await refreshSources();
    _editingSourceRepo = null;
    repoInput.value   = '';
    filterInput.value = '';
    document.getElementById('source-display-input').value = '';
  } catch (e) {
    const txt = e.message.includes('404')
      ? 'No .elf/.lua payload files found. ZIP-only releases are not supported.'
      : e.message.includes('400')
        ? 'Invalid format — use owner/repo (e.g. ps5-payload-dev/kstuff)'
        : 'Error: ' + e.message;
    statusEl.textContent = txt;
    statusEl.className   = 'source-status error';
  }
}

// ── Detected payload list ────────────────────────────────────────

function _renderDetectedPayloads(repo, assets) {
  // Group by asset_name, keep all versions
  const byAsset = {};
  assets.forEach(a => {
    if (!byAsset[a.asset_name]) byAsset[a.asset_name] = [];
    byAsset[a.asset_name].push(a);
  });

  const listEl = document.getElementById('source-detected-list');
  listEl.innerHTML = '';

  Object.entries(byAsset).forEach(([assetName, versions]) => {
    const latest = versions[0];
    const ext    = assetName.includes('.') ? assetName.slice(assetName.lastIndexOf('.')).toLowerCase() : '';

    const row = document.createElement('div');
    row.className = 'detected-row';
    row.dataset.repo           = repo;
    row.dataset.assetName      = assetName;
    row.dataset.downloadUrl    = latest.download_url;
    row.dataset.version        = latest.tag;
    row.dataset.path           = latest.path || '';
    row.dataset.publishedAt    = latest.published_at    || '';
    row.dataset.assetUpdatedAt = latest.asset_updated_at || '';
    row.dataset.assetSize      = String(latest.size       || 0);
    row.dataset.releaseId      = String(latest.release_id || 0);
    row.dataset.allVersions    = JSON.stringify(
      versions.map(v => ({ tag: v.tag, download_url: v.download_url, path: v.path || '' }))
    );

    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.className = 'p-checkbox'; cb.checked = false;
    cb.addEventListener('change', _updateDetectedSelectionUI);

    const badge = document.createElement('span');
    badge.className   = `badge ${ext === '.lua' ? 'badge-lua' : ext === '.zip' ? 'badge-zip' : 'badge-elf'}`;
    badge.textContent = ext.replace('.', '').toUpperCase() || 'FILE';

    // Top row: checkbox + badge + filename
    const rowTop = document.createElement('div');
    rowTop.className = 'detected-row-top';
    const nameEl = document.createElement('span');
    nameEl.className   = 'detected-name';
    nameEl.textContent = assetName;
    rowTop.appendChild(cb);
    rowTop.appendChild(badge);
    rowTop.appendChild(nameEl);
    row.appendChild(rowTop);

    // Sub row: version + path (if present)
    const hasVer  = latest.tag && latest.tag !== 'latest';
    const hasPath = latest.path && latest.path !== assetName;
    if (hasVer || hasPath) {
      const rowSub = document.createElement('div');
      rowSub.className = 'detected-row-sub';
      if (hasVer) {
        const verEl = document.createElement('span');
        verEl.className   = 'detected-ver';
        verEl.textContent = latest.tag;
        rowSub.appendChild(verEl);
      }
      if (hasPath) {
        const pathEl = document.createElement('span');
        pathEl.className   = 'detected-path';
        pathEl.textContent = latest.path;
        rowSub.appendChild(pathEl);
      }
      row.appendChild(rowSub);
    }

    listEl.appendChild(row);
  });

  _updateDetectedSelectionUI();
  document.getElementById('source-detected').style.display = '';
}

// ── Selection helpers ────────────────────────────────────────────

function _updateDetectedSelectionUI() {
  const cbs = document.querySelectorAll('#source-detected-list input[type=checkbox]');
  const n   = Array.from(cbs).filter(cb => cb.checked).length;
  const countEl   = document.getElementById('detected-count');
  const importBtn = document.getElementById('btn-source-import');
  if (countEl)   countEl.textContent  = n > 0 ? `${n} selected` : '';
  if (importBtn) importBtn.disabled   = n === 0;
}

function _selectAllDetected() {
  document.querySelectorAll('#source-detected-list input[type=checkbox]')
    .forEach(cb => { cb.checked = true; });
  _updateDetectedSelectionUI();
}

function _deselectAllDetected() {
  document.querySelectorAll('#source-detected-list input[type=checkbox]')
    .forEach(cb => { cb.checked = false; });
  _updateDetectedSelectionUI();
}

// ── Import selected payloads ─────────────────────────────────────

async function importSelected() {
  const rows = document.querySelectorAll('#source-detected-list .detected-row');
  const btn  = document.getElementById('btn-source-import');
  btn.disabled    = true;
  btn.textContent = 'Importing…';
  let imported = 0;

  for (const row of rows) {
    const cb = row.querySelector('input[type=checkbox]');
    if (!cb || !cb.checked) continue;
    try {
      let allVersions = [];
      try { allVersions = JSON.parse(row.dataset.allVersions || '[]'); } catch (_) {}
      await api('/api/payloads/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo:                 row.dataset.repo,
          asset_name:           row.dataset.assetName,
          download_url:         row.dataset.downloadUrl,
          version:              row.dataset.version,
          all_versions:         allVersions,
          release_published_at: row.dataset.publishedAt    || '',
          asset_updated_at:     row.dataset.assetUpdatedAt || '',
          asset_size:           parseInt(row.dataset.assetSize)  || 0,
          release_id:           parseInt(row.dataset.releaseId)  || 0,
        }),
      });
      imported++;
    } catch (e) { log(`Import '${row.dataset.assetName}': ${e.message}`, 'error'); }
  }

  btn.textContent = 'Import Selected';
  if (imported > 0) {
    showToast(`${imported} payload(s) imported`);
    document.getElementById('source-detected').style.display = 'none';
    document.getElementById('source-add-panel').style.display = 'none';
    await refreshPayloads();
  } else {
    btn.disabled = false;
    _updateDetectedSelectionUI();
  }
}

// ── Delete source ────────────────────────────────────────────────
async function deleteSource(repo) {
  if (!confirm(`Remove source '${repo}'?\n\nAlready imported payloads will NOT be deleted.`)) return;
  const [owner, repoName] = repo.split('/');
  try {
    await api(`/api/sources/${encodeURIComponent(owner)}/${encodeURIComponent(repoName)}`, { method: 'DELETE' });
    await refreshSources();
  } catch (e) { log('Remove source: ' + e.message, 'error'); }
}

// ── Check source: detect new payloads + updates ──────────────────
async function checkSourceUpdates(repo, sourceEl) {
  const el    = sourceEl || document.querySelector(`.source-item[data-repo="${CSS.escape(repo)}"]`);
  const btn   = el && el.querySelector('.source-check-btn');
  const panel = el && el.querySelector('.source-check-panel');

  if (btn) { btn.disabled = true; btn.textContent = 'Checking…'; }

  try {
    const data = await api(`/api/sources/releases?repo=${encodeURIComponent(repo)}`);

    const byAsset = {};
    data.releases.forEach(r => {
      if (!byAsset[r.asset_name]) byAsset[r.asset_name] = [];
      byAsset[r.asset_name].push(r);
    });

    // Releases come newest-first → first item's tag is the newest release.
    const newestTag = data.releases[0]?.tag || null;
    const newestReleaseAssets = data.releases.filter(r => r.tag === newestTag);

    const owned          = state.payloads.filter(p => p.source && p.source.repo === repo);
    const importedAssets = new Set(owned.map(p => p.source.asset));
    const usedAsUpdate   = new Set();

    if (!state.updateResults) state.updateResults = {};
    let updatesAvail = 0;
    // Single-payload repo with a single-asset newest release: trust the newest
    // release as the successor for the one tracked payload, regardless of
    // whether the saved asset filename still matches.
    const singlePayloadRepo = owned.length === 1 && newestReleaseAssets.length === 1;
    owned.forEach(p => {
      let vers        = byAsset[p.source.asset];
      let assetName   = p.source.asset;
      let downloadUrl = vers ? vers[0].download_url : null;

      if (singlePayloadRepo) {
        const successor = newestReleaseAssets[0];
        vers        = [successor];
        assetName   = successor.asset_name;
        downloadUrl = successor.download_url;
        usedAsUpdate.add(assetName);
      }

      if (vers && vers[0].tag !== p.source.version) {
        updatesAvail++;
        state.updateResults[p.name] = {
          filename:        p.name,
          repo:            p.source.repo,
          asset_name:      assetName,
          current_version: p.source.version,
          latest_version:  vers[0].tag,
          download_url:    downloadUrl,
        };
      }
    });

    const newAssets = Object.entries(byAsset)
      .filter(([name]) => !importedAssets.has(name) && !usedAsUpdate.has(name))
      .map(([name, vers]) => ({ name, latest: vers[0], versions: vers }));
    _renderUpdateBadge(Object.keys(state.updateResults).length);
    renderSourcesList();
    if (updatesAvail) renderPayloads();

    if (panel) {
      const repoUpdates = Object.values(state.updateResults).filter(u => u.repo === repo);
      _populateSourceCheckPanel(panel, repo, newAssets, repoUpdates, owned.length);
      panel.style.display = '';
    }

    const parts = [];
    if (newAssets.length) parts.push(`${newAssets.length} new payload(s)`);
    if (updatesAvail)     parts.push(`${updatesAvail} update(s) available`);
    if (!parts.length)    parts.push('All up to date');
    showToast(parts.join(' · '));
  } catch (e) { log('Check source: ' + e.message, 'error'); }
  finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Check'; }
  }
}

function _populateSourceCheckPanel(panel, repo, newAssets, repoUpdates, importedCount) {
  panel.innerHTML = '';
  const updatesAvail = repoUpdates.length;

  const statusLine = document.createElement('div');
  const parts = [];
  if (newAssets.length) parts.push(`${newAssets.length} new payload(s) found`);
  if (updatesAvail)     parts.push(`${updatesAvail} update(s) available`);
  if (!parts.length)    parts.push(importedCount ? '✔ All up to date' : '✔ No payloads in this release');
  const hasWarning = newAssets.length > 0 || updatesAvail > 0;
  statusLine.textContent = (hasWarning ? '⚠ ' : '') + parts.join(' · ');
  statusLine.className   = 'source-check-status ' + (hasWarning ? 'warn' : 'ok');
  panel.appendChild(statusLine);

  if (updatesAvail) {
    const hdr = document.createElement('p');
    hdr.className   = 'source-check-hdr';
    hdr.textContent = 'Updates available:';
    panel.appendChild(hdr);

    const updList = document.createElement('div');
    updList.className = 'source-check-list';

    repoUpdates.forEach(u => {
      const row = document.createElement('div');
      row.className = 'source-update-row';
      const txt = document.createElement('span');
      txt.className = 'source-update-text';
      txt.textContent = `${u.filename}: ${u.current_version} → ${u.latest_version}`;
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm btn-primary';
      btn.textContent = 'Update';
      btn.addEventListener('click', async () => {
        btn.disabled = true; btn.textContent = 'Updating…';
        try {
          await api(`/api/payloads/${encodeURIComponent(u.filename)}/switch-version`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              repo: u.repo, asset_name: u.asset_name,
              download_url: u.download_url, version: u.latest_version,
            }),
          });
          delete state.updateResults[u.filename];
          showToast(`'${u.filename}' updated to ${u.latest_version}`);
          await refreshPayloads();
          renderSourcesList();
          row.remove();
          _renderUpdateBadge(Object.keys(state.updateResults).length);
        } catch (e) {
          log(`Update '${u.filename}': ${e.message}`, 'error');
          btn.disabled = false; btn.textContent = 'Update';
        }
      });
      row.appendChild(txt); row.appendChild(btn);
      updList.appendChild(row);
    });

    panel.appendChild(updList);
  }

  if (newAssets.length) {
    const hdr = document.createElement('p');
    hdr.className   = 'source-check-hdr';
    hdr.textContent = 'New payloads available:';
    panel.appendChild(hdr);

    const list = document.createElement('div');
    list.className = 'source-check-list';

    const importBtn = document.createElement('button');
    importBtn.className   = 'btn btn-primary btn-sm';
    importBtn.textContent = 'Import Selected';
    importBtn.disabled    = true;
    importBtn.style.cssText = 'width:100%;margin-top:.4rem';

    const updatePanelCount = () => {
      const cbs = list.querySelectorAll('input[type=checkbox]');
      const n = Array.from(cbs).filter(cb => cb.checked).length;
      importBtn.disabled = n === 0;
    };

    // Select All / Deselect All bar
    const bar = document.createElement('div');
    bar.className = 'detected-select-bar detected-select-bar--inline';
    const saBtn = document.createElement('button');
    saBtn.className = 'btn btn-xs'; saBtn.textContent = 'Select All';
    saBtn.addEventListener('click', () => {
      list.querySelectorAll('input[type=checkbox]').forEach(cb => cb.checked = true);
      updatePanelCount();
    });
    const daBtn = document.createElement('button');
    daBtn.className = 'btn btn-xs'; daBtn.textContent = 'Deselect All';
    daBtn.addEventListener('click', () => {
      list.querySelectorAll('input[type=checkbox]').forEach(cb => cb.checked = false);
      updatePanelCount();
    });
    const cntEl = document.createElement('span');
    cntEl.className = 'detected-count';
    bar.appendChild(saBtn); bar.appendChild(daBtn); bar.appendChild(cntEl);
    panel.appendChild(bar);

    newAssets.forEach(asset => {
      const ext = asset.name.includes('.') ? asset.name.slice(asset.name.lastIndexOf('.')).toLowerCase() : '';
      const row = document.createElement('div');
      row.className = 'detected-row';
      row.dataset.repo           = repo;
      row.dataset.assetName      = asset.name;
      row.dataset.downloadUrl    = asset.latest.download_url;
      row.dataset.version        = asset.latest.tag;
      row.dataset.path           = asset.latest.path || '';
      row.dataset.publishedAt    = asset.latest.published_at    || '';
      row.dataset.assetUpdatedAt = asset.latest.asset_updated_at || '';
      row.dataset.allVersions    = JSON.stringify(
        asset.versions.map(v => ({ tag: v.tag, download_url: v.download_url }))
      );

      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.className = 'p-checkbox'; cb.checked = false;
      cb.addEventListener('change', updatePanelCount);

      const badge = document.createElement('span');
      badge.className   = `badge ${ext === '.lua' ? 'badge-lua' : ext === '.zip' ? 'badge-zip' : 'badge-elf'}`;
      badge.textContent = ext.replace('.', '').toUpperCase() || 'FILE';

      // Top row: checkbox + badge + filename
      const rowTop = document.createElement('div');
      rowTop.className = 'detected-row-top';
      const nameEl = document.createElement('span');
      nameEl.className = 'detected-name'; nameEl.textContent = asset.name;
      rowTop.appendChild(cb); rowTop.appendChild(badge); rowTop.appendChild(nameEl);
      row.appendChild(rowTop);

      // Sub row: version + path
      const hasVer  = asset.latest.tag && asset.latest.tag !== 'latest';
      const hasPath = asset.latest.path && asset.latest.path !== asset.name;
      if (hasVer || hasPath) {
        const rowSub = document.createElement('div');
        rowSub.className = 'detected-row-sub';
        if (hasVer) {
          const verEl = document.createElement('span');
          verEl.className = 'detected-ver'; verEl.textContent = asset.latest.tag;
          rowSub.appendChild(verEl);
        }
        if (hasPath) {
          const pathEl = document.createElement('span');
          pathEl.className = 'detected-path'; pathEl.textContent = asset.latest.path;
          rowSub.appendChild(pathEl);
        }
        row.appendChild(rowSub);
      }

      list.appendChild(row);
    });

    panel.appendChild(list);
    importBtn.addEventListener('click', () => _importFromPanel(list, importBtn, panel));
    panel.appendChild(importBtn);
  }

  const closeBtn = document.createElement('button');
  closeBtn.className   = 'btn btn-sm';
  closeBtn.textContent = '✕ Close';
  closeBtn.style.cssText = 'margin-top:.35rem;width:100%';
  closeBtn.addEventListener('click', () => { panel.style.display = 'none'; });
  panel.appendChild(closeBtn);

  panel.style.display = '';
}

async function _importFromPanel(list, btn, panel) {
  const rows = list.querySelectorAll('.detected-row');
  btn.disabled = true; btn.textContent = 'Importing…';
  let imported = 0;
  for (const row of rows) {
    const cb = row.querySelector('input[type=checkbox]');
    if (!cb || !cb.checked) continue;
    try {
      let allVersions = [];
      try { allVersions = JSON.parse(row.dataset.allVersions || '[]'); } catch (_) {}
      await api('/api/payloads/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo:                 row.dataset.repo,
          asset_name:           row.dataset.assetName,
          download_url:         row.dataset.downloadUrl,
          version:              row.dataset.version,
          all_versions:         allVersions,
          release_published_at: row.dataset.publishedAt    || '',
          asset_updated_at:     row.dataset.assetUpdatedAt || '',
          asset_size:           parseInt(row.dataset.assetSize)  || 0,
          release_id:           parseInt(row.dataset.releaseId)  || 0,
        }),
      });
      imported++;
    } catch (e) { log(`Import '${row.dataset.assetName}': ${e.message}`, 'error'); }
  }
  btn.textContent = 'Import Selected';
  if (imported > 0) {
    showToast(`${imported} payload(s) imported`);
    panel.style.display = 'none';
    await refreshPayloads();
  } else {
    btn.disabled = false;
  }
}

// ── Global update check ──────────────────────────────────────────
async function checkAllUpdates() {
  if (!state.sources.length) return;
  const btn = document.getElementById('btn-check-all-updates');
  if (btn) { btn.disabled = true; btn.textContent = 'Checking…'; }
  try {
    const data = await api('/api/sources/check-updates');
    if (!state.updateResults) state.updateResults = {};
    Object.keys(state.updateResults).forEach(k => delete state.updateResults[k]);
    data.updates.forEach(u => { state.updateResults[u.filename] = u; });
    state.updateCheckDone = true;
    _renderUpdateBadge(data.updates.length);
    renderSourcesList();
    renderPayloads();
  } catch (e) { log('Check updates: ' + e.message, 'error'); }
  finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Check Updates'; }
  }
}

function _renderUpdateBadge(count) {
  const badge = document.getElementById('update-count-badge');
  if (!badge) return;
  if (count > 0) {
    badge.textContent = `⚠ ${count} update${count > 1 ? 's' : ''} available`;
    badge.className   = 'update-count-badge warn';
    document.getElementById('btn-update-all').style.display = '';
  } else {
    badge.textContent = '✔ All up to date';
    badge.className   = 'update-count-badge ok';
    document.getElementById('btn-update-all').style.display = 'none';
  }
}

async function updateAll() {
  const updates = Object.values(state.updateResults || {});
  if (!updates.length) { showToast('Nothing to update'); return; }
  if (!confirm(`Update ${updates.length} payload(s) to latest versions?`)) return;
  const btn = document.getElementById('btn-update-all');
  if (btn) { btn.disabled = true; btn.textContent = 'Updating…'; }
  let done = 0;
  for (const u of updates) {
    try {
      await api(`/api/payloads/${encodeURIComponent(u.filename)}/switch-version`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo: u.repo, asset_name: u.asset_name,
          download_url: u.download_url, version: u.latest_version,
        }),
      });
      delete state.updateResults[u.filename];
      done++;
    } catch (e) { log(`Update '${u.filename}': ${e.message}`, 'error'); }
  }
  if (btn) { btn.disabled = false; btn.textContent = '⬆ Update All'; }
  showToast(`${done} payload(s) updated`);
  await refreshPayloads();
  await checkAllUpdates();
}
