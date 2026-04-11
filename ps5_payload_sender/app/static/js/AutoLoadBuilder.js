'use strict';

// ── AutoLoad Builder ─────────────────────────────────────────────
// builder object is declared in state.js

// ── Step run-status tracking ──────────────────────────────────────
// Strict single-source-of-truth using currentStepIndex:
//   idx < current  → done
//   idx === current → running
//   idx > current  → idle
const _stepRunStatus = {};  // index(str) → 'running' | 'done' | 'error'
let _currentStepIdx = -1;

function handleBuilderStepStatus(msg) {
  if (!msg || msg.type !== 'status') return;
  const m = /^\[(\d+)\/(\d+)\]/.exec(msg.message);

  if (m) {
    const idx   = parseInt(m[1], 10) - 1;  // 0-based step index
    const level = msg.level || 'info';

    if (level === 'success') {
      // Explicit step-N success confirmation
      _stepRunStatus[idx] = 'done';
      if (_currentStepIdx === idx) _currentStepIdx = idx + 1;
    } else if (level === 'error') {
      _stepRunStatus[idx] = 'error';
    } else {
      // Step N is starting: enforce strict ordering
      // All prior steps not yet marked → mark done
      for (let i = 0; i < idx; i++) {
        if (!_stepRunStatus[i] || _stepRunStatus[i] === 'running') {
          _stepRunStatus[i] = 'done';
        }
      }
      _currentStepIdx = idx;
      _stepRunStatus[idx] = 'running';
      // Clear any stale status for future steps
      for (let i = idx + 1; i < builder.steps.length; i++) {
        delete _stepRunStatus[i];
      }
    }
  } else {
    // Result message without [N/M] prefix → applies to current running step
    if (_currentStepIdx >= 0) {
      const level = msg.level || 'info';
      if (level === 'success') {
        _stepRunStatus[_currentStepIdx] = 'done';
      } else if (level === 'error') {
        _stepRunStatus[_currentStepIdx] = 'error';
      }
    }
  }

  updateStepStatusBadges();
}

function updateStepStatusBadges() {
  Object.entries(_stepRunStatus).forEach(([idx, status]) => {
    const el = document.querySelector(`.builder-step[data-step-idx="${idx}"] .step-run-status`);
    if (!el) return;
    el.className = `step-run-status step-${status}`;
    el.textContent = status === 'running' ? '⏳' : status === 'done' ? '✔' : '✗';
  });
}

function clearStepRunStatus() {
  _currentStepIdx = -1;
  Object.keys(_stepRunStatus).forEach(k => delete _stepRunStatus[k]);
  document.querySelectorAll('.step-run-status').forEach(el => {
    el.className = 'step-run-status'; el.textContent = '';
  });
}

// ── Run/Stop button state ─────────────────────────────────────────
function _setBuilderRunning(running) {
  const btn = document.getElementById('btn-builder-run');
  if (!btn) return;
  if (running) {
    btn.className = 'btn btn-danger btn-xl';
    btn.textContent = '■ Stop';
  } else {
    btn.className = 'btn btn-primary btn-xl';
    btn.textContent = '▶ Run';
  }
}

// Called from ws.js when exec_state + profile change
function handleExecState(execState, profile) {
  const active = execState === 'running' || execState === 'paused';

  // Builder run→stop button (always responds since any execution can be stopped here)
  _setBuilderRunning(active);

  // Resolve final step state before clearing
  if (!active) {
    if (execState === 'completed') {
      // Mark any still-running step as done
      Object.keys(_stepRunStatus).forEach(k => {
        if (_stepRunStatus[k] === 'running') _stepRunStatus[k] = 'done';
      });
      updateStepStatusBadges();
    } else if (execState === 'failed') {
      Object.keys(_stepRunStatus).forEach(k => {
        if (_stepRunStatus[k] === 'running') _stepRunStatus[k] = 'error';
      });
      updateStepStatusBadges();
    }
    // Delay clear so user can see final ✔/✗ briefly
    setTimeout(clearStepRunStatus, 1800);
  }

  // Sync Quick Start tiles and profile list
  if (typeof renderFavorites === 'function')      renderFavorites();
  if (typeof renderProfileList === 'function')    renderProfileList();
}

// ── Dropdown ─────────────────────────────────────────────────────
function builderUpdatePayloadDropdown() {
  const sel = document.getElementById('panel-payload-select');
  // Clear ALL children (including optgroup) – options-only removal misses optgroups
  sel.innerHTML = '<option value="">– Select a payload –</option>';

  const searchEl = document.getElementById('builder-payload-search');
  const query    = (searchEl ? searchEl.value : '').trim().toLowerCase();
  let payloads   = state.payloads.slice();

  if (query) {
    payloads = payloads.filter(p => p.name.toLowerCase().includes(query));
    payloads.sort((a, b) => {
      const aS = a.name.toLowerCase().startsWith(query);
      const bS = b.name.toLowerCase().startsWith(query);
      return (aS && !bS) ? -1 : (!aS && bS) ? 1 : 0;
    });
  }

  const favs = payloads.filter(p =>  state.payloadFavorites.includes(p.name));
  const rest = payloads.filter(p => !state.payloadFavorites.includes(p.name));

  function addGroup(label, items) {
    if (!items.length) return;
    const grp = document.createElement('optgroup');
    grp.label = label;
    items.forEach(p => {
      const opt = document.createElement('option');
      opt.value          = p.name;
      opt.textContent    = (state.payloadFavorites.includes(p.name) ? '⭐ ' : '') + p.name;
      opt.dataset.autoPort = String(p.auto_port);
      grp.appendChild(opt);
    });
    sel.appendChild(grp);
  }

  if (favs.length) addGroup('— Favorites —', favs);
  addGroup(favs.length ? '— All Payloads —' : '— Payloads —', rest);
}

// ── Panels ───────────────────────────────────────────────────────
function builderTogglePanel(type) {
  const panels = { payload: 'panel-payload', delay: 'panel-delay', wait: 'panel-wait' };
  Object.entries(panels).forEach(([t, id]) => {
    const el = document.getElementById(id);
    el.style.display = (t === type && el.style.display === 'none') ? '' : 'none';
  });
}

// Called when user selects a payload in the dropdown (basic mode: immediate add)
function builderAddPayloadStepFromSelect() {
  const sel = document.getElementById('panel-payload-select');
  if (!sel.value) return;
  const filename = sel.value;
  const autoPort = parseInt(sel.options[sel.selectedIndex].dataset.autoPort, 10);
  builder.steps.push({ type: 'payload', filename, autoPort, portOverride: null });
  sel.value = '';                                    // reset selector
  document.getElementById('panel-payload').style.display = 'none';
  builderRenderList(); scheduleSave();
}

function builderAddPayloadStep() {
  const sel      = document.getElementById('panel-payload-select');
  const filename = sel.value;
  if (!filename) { alert('Select a payload!'); return; }
  const autoPort    = parseInt(sel.options[sel.selectedIndex].dataset.autoPort, 10);
  const portVal     = parseInt(document.getElementById('panel-payload-port').value, 10);
  const portOverride = (portVal > 0 && portVal <= 65535) ? portVal : null;
  builder.steps.push({ type: 'payload', filename, autoPort, portOverride });
  document.getElementById('panel-payload-port').value  = '';
  sel.value = '';
  document.getElementById('panel-payload').style.display = 'none';
  builderRenderList(); scheduleSave();
}

function builderAddDelayStep(ms) {
  if (!ms || ms <= 0) return;
  builder.steps.push({ type: 'delay', ms });
  builderRenderList(); scheduleSave();
}

function builderAddWaitStep() {
  const port     = parseInt(document.getElementById('panel-wait-port').value, 10);
  const timeout  = parseInt(document.getElementById('panel-wait-to').value, 10);
  const ivEl     = document.getElementById('panel-wait-interval');
  const interval = ivEl ? (parseInt(ivEl.value, 10) || 500) : 500;
  if (!port    || port < 1    || port > 65535) { alert('Invalid port!');    return; }
  if (!timeout || timeout < 1)                 { alert('Invalid timeout!'); return; }
  builder.steps.push({ type: 'wait_port', port, timeout, interval_ms: Math.max(100, interval) });
  document.getElementById('panel-wait').style.display = 'none';
  builderRenderList(); scheduleSave();
}

// ── Drag & drop ──────────────────────────────────────────────────
function _builderMakeDragDrop(el, idx) {
  el.addEventListener('dragstart', e => {
    e.dataTransfer.setData('text/plain', String(idx));
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => el.classList.add('dragging'), 0);
  });
  el.addEventListener('dragend', () => {
    el.classList.remove('dragging');
    el.setAttribute('draggable', 'false');
  });
  el.addEventListener('dragover',  e => { e.preventDefault(); el.classList.add('drag-over'); });
  el.addEventListener('dragleave', e => {
    if (!el.contains(e.relatedTarget)) el.classList.remove('drag-over');
  });
  el.addEventListener('drop', e => {
    e.preventDefault(); el.classList.remove('drag-over');
    const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (isNaN(from) || from === idx) return;
    const moved = builder.steps.splice(from, 1)[0];
    builder.steps.splice(idx, 0, moved);
    builderRenderList(); scheduleSave();
  });
}

function _builderMakeDragHandle(stepEl) {
  const drag = document.createElement('span');
  drag.className   = 'drag-handle';
  drag.textContent = '☰';
  drag.title       = 'Drag to reorder';
  drag.addEventListener('mousedown',  () => stepEl.setAttribute('draggable', 'true'));
  drag.addEventListener('touchstart', () => stepEl.setAttribute('draggable', 'true'), { passive: true });
  return drag;
}

function _makeStepNum(idx) {
  const num = document.createElement('span');
  num.className   = 'step-num';
  num.textContent = idx + 1;
  return num;
}

function _makeStepStatusBadge(idx) {
  const badge = document.createElement('span');
  badge.className = 'step-run-status';
  const cur = _stepRunStatus[idx];
  if (cur) {
    badge.classList.add(`step-${cur}`);
    badge.textContent = cur === 'running' ? '⏳' : cur === 'done' ? '✔' : '✗';
  }
  return badge;
}

function _builderMakeOrderBtns(idx) {
  const btns   = document.createElement('div');
  btns.className = 'step-btns';
  const upBtn  = document.createElement('button');
  upBtn.className   = 'btn btn-sm'; upBtn.textContent  = '↑'; upBtn.disabled = idx === 0;
  upBtn.addEventListener('click', () => builderMoveStep(idx, -1));
  const downBtn = document.createElement('button');
  downBtn.className   = 'btn btn-sm'; downBtn.textContent = '↓';
  downBtn.disabled = idx === builder.steps.length - 1;
  downBtn.addEventListener('click', () => builderMoveStep(idx, 1));
  const delBtn = document.createElement('button');
  delBtn.className   = 'btn btn-sm btn-danger'; delBtn.textContent = '✕';
  delBtn.addEventListener('click', () => builderDeleteStep(idx));
  btns.appendChild(upBtn); btns.appendChild(downBtn); btns.appendChild(delBtn);
  return btns;
}

// ── WorkflowStep renderers ────────────────────────────────────────
function _buildPayloadStep(step, idx, stepEl, mainRow, btns) {
  const isLua = step.filename.toLowerCase().endsWith('.lua');
  const badge = document.createElement('span');
  badge.className   = `payload-label ${isLua ? 'lua' : 'elf'}`;
  badge.textContent = 'Payload';

  const fnEl = document.createElement('span');
  fnEl.className   = 'step-filename';
  fnEl.textContent = step.filename;
  fnEl.title       = step.filename;
  fnEl.addEventListener('click', e => {
    e.stopPropagation();
    fnEl.classList.toggle('expanded');
  });

  const portHint = document.createElement('span');
  portHint.className   = 'step-autoport advanced-only';
  portHint.textContent = `:${step.portOverride || step.autoPort}`;

  mainRow.appendChild(_builderMakeDragHandle(stepEl));
  mainRow.appendChild(_makeStepNum(idx));
  mainRow.appendChild(badge);
  mainRow.appendChild(fnEl);
  mainRow.appendChild(portHint);
  mainRow.appendChild(_makeStepStatusBadge(idx));
  mainRow.appendChild(btns);

  // Port details row (advanced only)
  const details   = document.createElement('div');
  details.className = 'step-details advanced-only';
  const portField = document.createElement('div');
  portField.className = 'step-field';
  const portLabel = document.createElement('span');
  portLabel.className = 'step-field-label'; portLabel.textContent = 'Port';
  const portInp = document.createElement('input');
  portInp.type        = 'number'; portInp.className = 'step-input';
  portInp.placeholder = String(step.autoPort); portInp.min = '1'; portInp.max = '65535';
  if (step.portOverride) portInp.value = step.portOverride;
  portInp.addEventListener('input', e => {
    const v = parseInt(e.target.value, 10);
    builder.steps[idx].portOverride = (v > 0 && v <= 65535) ? v : null;
    portHint.textContent = `:${builder.steps[idx].portOverride || step.autoPort}`;
    scheduleSave();
  });
  portField.appendChild(portLabel); portField.appendChild(portInp);
  details.appendChild(portField);
  stepEl.appendChild(mainRow);
  stepEl.appendChild(details);
}

function _buildDelayStep(step, idx, stepEl, mainRow, btns) {
  const badge = document.createElement('span');
  badge.className = 'step-type step-delay'; badge.textContent = 'DELAY';
  const spacer = document.createElement('span'); spacer.style.flex = '1';
  const msInp  = document.createElement('input');
  msInp.type = 'number'; msInp.className = 'step-input';
  msInp.value = step.ms; msInp.min = '1';
  msInp.addEventListener('input', e => {
    const v = parseInt(e.target.value, 10);
    if (v > 0) { builder.steps[idx].ms = v; scheduleSave(); }
  });
  const msUnit = document.createElement('span');
  msUnit.className = 'step-unit'; msUnit.textContent = 'ms';
  mainRow.appendChild(_builderMakeDragHandle(stepEl));
  mainRow.appendChild(_makeStepNum(idx));
  mainRow.appendChild(badge); mainRow.appendChild(spacer);
  mainRow.appendChild(msInp); mainRow.appendChild(msUnit);
  mainRow.appendChild(_makeStepStatusBadge(idx));
  mainRow.appendChild(btns);
  stepEl.appendChild(mainRow);
}

function _buildWaitStep(step, idx, stepEl, mainRow, btns) {
  const badge = document.createElement('span');
  badge.className = 'step-type step-wait'; badge.textContent = 'WAIT';
  const spacer = document.createElement('span'); spacer.style.flex = '1';

  mainRow.appendChild(_builderMakeDragHandle(stepEl));
  mainRow.appendChild(_makeStepNum(idx));
  mainRow.appendChild(badge);
  mainRow.appendChild(spacer);
  mainRow.appendChild(_makeStepStatusBadge(idx));
  mainRow.appendChild(btns);

  // Inputs in a details row (avoids horizontal overflow on mobile)
  const details = document.createElement('div');
  details.className = 'step-details';

  function makeField(labelText, value, min, max, unit, onChange) {
    const field = document.createElement('div');
    field.className = 'step-field';
    const lbl = document.createElement('span');
    lbl.className = 'step-field-label'; lbl.textContent = labelText;
    const inp = document.createElement('input');
    inp.type = 'number'; inp.className = 'step-input';
    inp.value = value; inp.min = String(min);
    if (max) inp.max = String(max);
    inp.addEventListener('input', e => onChange(parseInt(e.target.value, 10)));
    const u = document.createElement('span');
    u.className = 'step-unit'; u.textContent = unit;
    field.appendChild(lbl); field.appendChild(inp); field.appendChild(u);
    return field;
  }

  details.appendChild(makeField('Port', step.port, 1, 65535, '', v => {
    if (v > 0 && v <= 65535) { builder.steps[idx].port = v; scheduleSave(); }
  }));
  details.appendChild(makeField('Timeout', step.timeout, 1, null, 's', v => {
    if (v > 0) { builder.steps[idx].timeout = v; scheduleSave(); }
  }));
  details.appendChild(makeField('Interval', step.interval_ms || 500, 100, null, 'ms', v => {
    if (v >= 100) { builder.steps[idx].interval_ms = v; scheduleSave(); }
  }));

  stepEl.appendChild(mainRow);
  stepEl.appendChild(details);
}

// ── List render ───────────────────────────────────────────────────
function builderRenderList() {
  const container = document.getElementById('builder-steps');
  container.innerHTML = '';
  if (!builder.steps.length) {
    container.innerHTML = '<div class="empty-state">Add your first payload to start.</div>';
    return;
  }
  builder.steps.forEach((step, idx) => {
    const stepEl  = document.createElement('div');
    stepEl.className = 'builder-step fade';
    stepEl.dataset.stepIdx = String(idx);
    _builderMakeDragDrop(stepEl, idx);
    const mainRow = document.createElement('div');
    mainRow.className = 'step-main';
    const btns = _builderMakeOrderBtns(idx);

    if      (step.type === 'payload') _buildPayloadStep(step, idx, stepEl, mainRow, btns);
    else if (step.type === 'delay')   _buildDelayStep(step,   idx, stepEl, mainRow, btns);
    else                              _buildWaitStep(step,    idx, stepEl, mainRow, btns);

    container.appendChild(stepEl);
  });
}

function builderMoveStep(idx, dir) {
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= builder.steps.length) return;
  [builder.steps[idx], builder.steps[newIdx]] = [builder.steps[newIdx], builder.steps[idx]];
  builderRenderList(); scheduleSave();
}

function builderDeleteStep(idx) {
  builder.steps.splice(idx, 1);
  builderRenderList(); scheduleSave();
}

function builderGenerate() {
  return builder.steps.map(step => {
    if (step.type === 'payload')
      return step.portOverride ? `${step.filename} ${step.portOverride}` : step.filename;
    if (step.type === 'delay') return `!${step.ms}`;
    // wait_port: ?port timeout interval_ms
    const intervalMs = step.interval_ms || 500;
    return `?${step.port} ${step.timeout} ${intervalMs}`;
  }).join('\n');
}

async function builderSave() {
  if (!builder.steps.length) { alert('No steps to save!'); return; }
  const raw = document.getElementById('builder-profile-name').value.trim();
  if (!raw) { alert('Enter a profile name!'); return; }
  const safe     = raw.replace(/[^a-zA-Z0-9_\-.]/g, '_');
  const filename = safe.endsWith('.txt') ? safe : `${safe}.txt`;
  const content  = `# Created by Auto-Load Builder\n${builderGenerate()}\n`;
  try {
    await api('/api/autoload/content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: filename, content }),
    });
    log(`Profile '${filename}' saved`, 'success');
    await refreshProfiles();
    scheduleSave();
  } catch (e) { log('Save: ' + e.message, 'error'); }
}

async function stopAutoload() {
  try {
    await api('/api/autoload/stop', { method: 'POST' });
  } catch (e) { log('Stop: ' + e.message, 'error'); }
}

async function builderRunDirect() {
  if (!builder.steps.length) { alert('No steps to run!'); return; }
  const host = getHost(); if (!host) return;
  const tmpProfile = '_builder_run.txt';
  const content    = `# Auto-Load Builder direct run\n${builderGenerate()}\n`;
  clearStepRunStatus();
  _setBuilderRunning(true);
  try {
    await api('/api/autoload/content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: tmpProfile, content }),
    });
    await api('/api/autoload/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host, profile: tmpProfile,
        continue_on_error: false,
      }),
    });
  } catch (e) { log('Run: ' + e.message, 'error'); }
  finally {
    _setBuilderRunning(false);
  }
}
