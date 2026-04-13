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

function importConfig() {
  const input = Object.assign(document.createElement('input'), {
    type: 'file', accept: '.json',
  });
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    let data;
    try {
      data = JSON.parse(await file.text());
    } catch {
      showToast('Invalid JSON file'); return;
    }
    if (data.version !== 1) {
      showToast('Unrecognised backup format'); return;
    }
    const ok = confirm(
      'This will overwrite your current config (devices, sources, profiles, settings).\n\n' +
      'A pre-restore backup is created automatically.\n\nImport?'
    );
    if (!ok) return;
    try {
      const res = await api('/api/backup/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      showToast('Config restored – reloading …');
      setTimeout(() => location.reload(), 1200);
    } catch (e) {
      showToast('Restore failed: ' + e.message);
    }
  };
  input.click();
}
