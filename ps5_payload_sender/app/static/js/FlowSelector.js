'use strict';

// ── Global Flow Selector + Action Bar ────────────────────────────
// Provides a persistent flow dropdown (inside the sticky header)
// that drives Builder view, Run target, and Analyze target from
// a single source of truth.
//
// Public API called by other modules:
//   populateFlowSelector(profiles)  – sync dropdown after profiles refresh
//   setFlowRunning(running)         – lock/unlock during execution
//   globalRun()                     – run the selected flow
//   globalAnalyze()                 – load flow into builder then analyze
//   globalStop()                    – stop current execution

const _FS_KEY = 'ps5_active_flow';

// ── Init ─────────────────────────────────────────────────────────

function initFlowSelector() {
  const sel = document.getElementById('global-flow-select');
  if (!sel) return;

  sel.addEventListener('change', () => {
    const name = sel.value;
    localStorage.setItem(_FS_KEY, name);
    _syncActionBar();
    if (name) _loadFlowIntoBuilder(name);
  });
}

// ── Populate ─────────────────────────────────────────────────────
// Called from refreshProfiles() with the full profiles array.

function populateFlowSelector(profiles) {
  const sel = document.getElementById('global-flow-select');
  if (!sel) return;

  const prev = sel.value || localStorage.getItem(_FS_KEY) || '';
  sel.innerHTML = '<option value="">– Select flow –</option>';

  profiles.forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name.replace(/\.txt$/i, '');
    sel.appendChild(opt);
  });

  // Restore: last-used → first favourite → first profile
  let restore = '';
  if (profiles.includes(prev)) {
    restore = prev;
  } else if (state.favorites && state.favorites.length && profiles.includes(state.favorites[0])) {
    restore = state.favorites[0];
  } else if (profiles.length) {
    restore = profiles[0];
  }

  sel.value = restore;
  if (restore) localStorage.setItem(_FS_KEY, restore);
  _syncActionBar();
}

// ── State sync ───────────────────────────────────────────────────

function _syncActionBar() {
  const sel     = document.getElementById('global-flow-select');
  const btnRun  = document.getElementById('btn-global-run');
  const btnAna  = document.getElementById('btn-global-analyze');
  const btnStop = document.getElementById('btn-global-stop');
  if (!sel) return;

  const hasFlow  = !!sel.value;
  const isActive = state.execState === 'running' || state.execState === 'paused';

  if (btnRun)  btnRun.disabled  = !hasFlow || isActive;
  if (btnAna)  btnAna.disabled  = !hasFlow || isActive;
  if (btnStop) btnStop.style.display = isActive ? '' : 'none';
}

// Called from handleExecState() in AutoLoadBuilder.js
function setFlowRunning(running) {
  const sel = document.getElementById('global-flow-select');
  if (sel) sel.disabled = running;
  _syncActionBar();
}

// ── Actions ───────────────────────────────────────────────────────

async function globalRun() {
  const name = document.getElementById('global-flow-select')?.value;
  if (!name) return;
  await runProfile(name, document.getElementById('btn-global-run'));
}

async function globalAnalyze() {
  const name = document.getElementById('global-flow-select')?.value;
  if (!name) return;
  await _loadFlowIntoBuilder(name);
  await startFlowAnalysis();
}

function globalStop() {
  stopAutoload();
}

// ── Helpers ───────────────────────────────────────────────────────

async function _loadFlowIntoBuilder(name) {
  try {
    const data = await api(`/api/autoload/parse/${encodeURIComponent(name)}`);
    if (data.steps && data.steps.length) {
      builder.steps = data.steps;
      document.getElementById('builder-profile-name').value = name.replace(/\.txt$/i, '');
      builderRenderList();
      scheduleSave();
    }
  } catch (e) {
    log('Load flow: ' + e.message, 'error');
  }
}
