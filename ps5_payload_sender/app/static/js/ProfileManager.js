'use strict';

// ── Profile Manager ──────────────────────────────────────────────
async function refreshProfiles() {
  try {
    const data = await api('/api/autoload/profiles');
    state.profiles = data.profiles || [];
    renderProfileList();
    renderFavorites();
    if (typeof updateProfilesSummary === 'function') updateProfilesSummary();
    if (typeof populateFlowSelector === 'function') populateFlowSelector(state.profiles);
  } catch (e) { log('Load profiles: ' + e.message, 'error'); }
}

function renderProfileList() {
  const container = document.getElementById('profile-list');
  container.innerHTML = '';
  if (!state.profiles.length) {
    container.innerHTML = '<div class="empty-state">No flows created yet.</div>';
    return;
  }

  const isActive = state.execState === 'running' || state.execState === 'paused';
  const running  = state.runningProfile;

  state.profiles.forEach(name => {
    const item  = document.createElement('div');
    item.className = 'profile-item fade';

    const isFav      = state.favorites.includes(name);
    const isThisOne  = isActive && running === name;
    const isOtherOne = isActive && running !== name;

    // Favorite / pin button
    const favBtn = document.createElement('button');
    favBtn.className   = `btn btn-sm${isFav ? ' fav-active' : ''}`;
    favBtn.textContent = isFav ? '📌 Pinned' : 'Pin to Quick Start ⭐';
    favBtn.title       = isFav ? 'Unpin from Quick Start' : 'Pin to Quick Start';
    favBtn.addEventListener('click', () => toggleFavorite(name));

    // Display name
    const nameEl = document.createElement('span');
    nameEl.className   = 'profile-name';
    nameEl.textContent = name.replace(/\.txt$/i, '');

    // Edit button
    const editBtn = document.createElement('button');
    editBtn.className   = 'btn btn-sm'; editBtn.textContent = 'Edit';
    editBtn.title       = 'Edit in builder';
    editBtn.disabled    = isActive;
    editBtn.addEventListener('click', () => editProfile(name));

    // Run / Stop button — transforms based on global exec state
    const runBtn = document.createElement('button');
    runBtn.className   = 'btn btn-sm ' + (isThisOne ? 'btn-danger' : 'btn-primary');
    runBtn.textContent = isThisOne ? '■' : '▶';
    runBtn.title       = isThisOne ? 'Stop' : 'Run';
    runBtn.disabled    = isOtherOne;
    runBtn.addEventListener('click', () => {
      if (isActive) {
        stopAutoload();
      } else {
        runProfile(name, runBtn);
      }
    });

    // Delete button
    const delBtn = document.createElement('button');
    delBtn.className   = 'btn btn-sm btn-danger'; delBtn.textContent = '✕';
    delBtn.title       = 'Delete';
    delBtn.disabled    = isActive;
    delBtn.addEventListener('click', async () => {
      if (!confirm(`Delete profile '${name}'?`)) return;
      try {
        await api(`/api/autoload/content/${encodeURIComponent(name)}`, { method: 'DELETE' });
        state.favorites = state.favorites.filter(f => f !== name);
        await refreshProfiles();
        scheduleSave();
        log(`Profile '${name}' deleted`);
      } catch (e) { log('Delete profile: ' + e.message, 'error'); }
    });

    item.appendChild(nameEl);
    item.appendChild(favBtn); item.appendChild(editBtn);
    item.appendChild(runBtn); item.appendChild(delBtn);
    container.appendChild(item);
  });
}

function toggleFavorite(name) {
  if (state.favorites.includes(name)) {
    state.favorites = state.favorites.filter(f => f !== name);
    showToast(`Removed from Quick Start`);
  } else {
    state.favorites.push(name);
    showToast(`Added to Quick Start ⭐`);
  }
  renderProfileList(); renderFavorites(); scheduleSave();
}

async function runProfile(name, btn) {
  const host = getHost(); if (!host) return;
  if (state.execState === 'running' || state.execState === 'paused') {
    showToast('Already running'); return;
  }
  const continueOnError = document.getElementById('continue-on-error').checked;
  // Optimistic: dim button while request fires; WS exec_state re-renders properly
  if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
  state.execState = 'running'; // optimistic guard – prevents second click racing in
  try {
    await api('/api/autoload/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ host, profile: name, continue_on_error: continueOnError }),
    });
  } catch (e) {
    state.execState = 'idle'; // revert optimistic state on error
    if (e.message.includes('409')) {
      showToast('Already running');
    } else {
      log('Run: ' + e.message, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = '▶'; }
  }
  // Success: WS exec_state message drives the full UI update
}

async function editProfile(name) {
  try {
    const data = await api(`/api/autoload/parse/${encodeURIComponent(name)}`);
    if (!data.steps || !data.steps.length) {
      log(`Profile '${name}' has no parseable steps`, 'warn'); return;
    }
    builder.steps = data.steps;
    document.getElementById('builder-profile-name').value = name.replace(/\.txt$/i, '');
    builderRenderList(); scheduleSave();
    document.getElementById('builder-card').scrollIntoView({ behavior: 'smooth' });
    log(`Profile '${name}' loaded into builder`, 'success');
  } catch (e) { log('Edit profile: ' + e.message, 'error'); }
}
