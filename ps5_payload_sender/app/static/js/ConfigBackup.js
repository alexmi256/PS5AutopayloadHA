'use strict';

// ── Config Backup / Restore ──────────────────────────────────────

async function exportConfig() {
  try {
    const res = await fetch(BASE + '/api/backup');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement('a'), {
      href: url, download: 'ps5-autopayload-backup.json',
    });
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('Config exported');
  } catch (e) {
    showToast('Export failed: ' + e.message);
  }
}

async function resetConfig() {
  const ok = confirm(
    'FACTORY RESET\n\n' +
    'This will permanently delete:\n' +
    '  • All sources\n' +
    '  • All payloads\n' +
    '  • All flows / profiles\n' +
    '  • All settings and devices\n\n' +
    'A backup will be saved automatically before the reset.\n\nContinue?'
  );
  if (!ok) return;
  try {
    await api('/api/config/reset', { method: 'POST' });
    showToast('Config reset — reloading …');
    setTimeout(() => location.reload(), 1200);
  } catch (e) {
    showToast('Reset failed: ' + e.message);
  }
}

// ── Selective Import ─────────────────────────────────────────────

let _importData = null;

function importConfig() {
  const input = Object.assign(document.createElement('input'), {
    type: 'file', accept: '.json',
  });
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    let data;
    try { data = JSON.parse(await file.text()); }
    catch { showToast('Invalid JSON file'); return; }
    if (data.version !== 1) { showToast('Unrecognised backup format'); return; }
    _importData = data;
    _openImportModal(data);
  };
  input.click();
}

function _openImportModal(data) {
  // ── Populate preview ──────────────────────────────────────────
  const nSources  = (data.sources  || []).length;
  const nPayloads = Object.keys(data.payload_meta || {}).length;
  const nProfiles = Object.keys(data.profiles     || {}).length;
  const nFlows    = ((data.state || {}).builder_steps || []).length;

  document.getElementById('import-preview').innerHTML =
    `<strong>Backup contents:</strong>&nbsp; ` +
    `Sources: ${nSources} &nbsp;·&nbsp; ` +
    `Payloads: ${nPayloads} &nbsp;·&nbsp; ` +
    `Profiles: ${nProfiles} &nbsp;·&nbsp; ` +
    `Flow steps: ${nFlows}`;

  // ── Reset to defaults ─────────────────────────────────────────
  ['sources', 'payloads', 'flows', 'profiles', 'settings'].forEach(id => {
    const el = document.getElementById('imp-' + id);
    if (el) el.checked = true;
  });
  const mergeRadio = document.querySelector('input[name="imp-mode"][value="merge"]');
  if (mergeRadio) mergeRadio.checked = true;

  _validateImport();
  document.getElementById('import-modal').style.display = 'flex';
}

function _closeImportModal() {
  document.getElementById('import-modal').style.display = 'none';
  _importData = null;
}

// ── Dependency validation ─────────────────────────────────────────

function _validateImport() {
  const sel      = _getImportSections();
  const container = document.getElementById('import-warnings');
  container.innerHTML = '';

  function addWarn(msg, cls) {
    const div = document.createElement('div');
    div.className = 'import-warn ' + cls;
    div.textContent = msg;
    container.appendChild(div);
  }

  // Rule 1: Flows reference payloads — critical
  if (sel.includes('flows') && !sel.includes('payloads')) {
    addWarn(
      'Auto-Load Builder flows reference payloads. Import Payloads as well to avoid broken steps.',
      'import-warn-error'
    );
  }

  // Rule 2: Payloads without sources — soft warning
  if (sel.includes('payloads') && !sel.includes('sources')) {
    addWarn(
      'Payloads may be outdated without their sources.',
      'import-warn-info'
    );
  }

  // Rule 3: Profiles without flows — informational
  if (sel.includes('profiles') && !sel.includes('flows')) {
    addWarn(
      'Profiles were built with the Auto-Load Builder. Import Flows as well to keep them editable.',
      'import-warn-soft'
    );
  }
}

function _getImportSections() {
  return ['sources', 'payloads', 'flows', 'profiles', 'settings']
    .filter(id => {
      const el = document.getElementById('imp-' + id);
      return el && el.checked;
    });
}

function _getImportMode() {
  const el = document.querySelector('input[name="imp-mode"]:checked');
  return el ? el.value : 'merge';
}

// ── Confirm import ────────────────────────────────────────────────

async function _confirmImport() {
  if (!_importData) return;

  const sections = _getImportSections();
  if (!sections.length) { showToast('Select at least one section'); return; }

  const mode = _getImportMode();
  const btn  = document.getElementById('btn-import-confirm');
  btn.disabled = true;
  btn.textContent = 'Importing…';

  try {
    const result = await api('/api/backup/restore-selective', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        backup:   _importData,
        sections,
        mode,
        conflict: 'replace',
      }),
    });

    _closeImportModal();

    // Show broken-profiles notice if any profiles reference missing payloads
    if (result.broken_profiles && result.broken_profiles.length) {
      const names = result.broken_profiles.join(', ');
      log(
        `Import complete — broken profiles (missing payloads): ${names}`,
        'warn'
      );
      showToast('Imported with warnings — check the log', 3500);
    } else {
      showToast('Import successful');
    }

    // ── Refresh all affected UI panels ───────────────────────────
    if (sections.includes('sources'))  { await refreshSources?.();  updateSourcesSummary?.(); }
    if (sections.includes('payloads')) { await refreshPayloads?.(); updatePayloadsSummary?.(); }
    if (sections.includes('profiles')) { await refreshProfiles?.(); updateProfilesSummary?.(); }
    if (sections.includes('flows') || sections.includes('settings')) {
      await loadPersistedState?.();
      builderRenderList?.();
      updateBuilderSummary?.();
    }

  } catch (e) {
    showToast('Import failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Import';
  }
}

// ── Wire modal events ─────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btn-import-cancel') .addEventListener('click', _closeImportModal);
  document.getElementById('btn-import-confirm').addEventListener('click', _confirmImport);
  document.getElementById('import-modal').addEventListener('click', e => {
    if (e.target === e.currentTarget) _closeImportModal();
  });

  ['sources', 'payloads', 'flows', 'profiles', 'settings'].forEach(id => {
    const el = document.getElementById('imp-' + id);
    if (el) el.addEventListener('change', _validateImport);
  });
});
