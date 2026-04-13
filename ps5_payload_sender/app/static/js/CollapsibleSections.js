'use strict';

// ── Collapsible section manager ──────────────────────────────────
// Sections marked with class="collapsible" on their <section> element
// get click-to-collapse behaviour on their .collapse-toggle header row.
// Collapsed state persists in sessionStorage (resets on page reload).

const _COLLAPSED_KEY = 'ps5_sections_collapsed';

function initCollapsible() {
  let savedState = {};
  try {
    savedState = JSON.parse(sessionStorage.getItem(_COLLAPSED_KEY) || '{}');
  } catch (_) {}

  document.querySelectorAll('.collapsible').forEach(card => {
    const toggle = card.querySelector('.collapse-toggle');
    const body   = card.querySelector('.collapse-body');
    const icon   = card.querySelector('.collapse-icon');
    const id     = card.id;
    if (!toggle || !body) return;

    // Restore saved state
    if (savedState[id]) {
      body.classList.add('collapsed');
      if (icon) icon.textContent = '▼';
    }

    toggle.addEventListener('click', e => {
      // Don't collapse when clicking an interactive element inside the header
      if (e.target.closest('button, a, input, select, label')) return;
      const isNowCollapsed = body.classList.toggle('collapsed');
      if (icon) icon.textContent = isNowCollapsed ? '▼' : '▲';
      savedState[id] = isNowCollapsed;
      sessionStorage.setItem(_COLLAPSED_KEY, JSON.stringify(savedState));
    });
  });
}

// ── Section summary updaters ─────────────────────────────────────
// Call these whenever the underlying data changes.

function updateSourcesSummary() {
  const el = document.getElementById('summary-sources');
  if (!el) return;
  const n = (state.sources || []).length;
  el.textContent = n ? `${n} source${n !== 1 ? 's' : ''}` : '';
}

function updatePayloadsSummary() {
  const el = document.getElementById('summary-payloads');
  if (!el) return;
  const n = (state.payloads || []).length;
  el.textContent = n ? `${n} payload${n !== 1 ? 's' : ''}` : '';
}

function updateBuilderSummary() {
  const el = document.getElementById('summary-builder');
  if (!el) return;
  const n = builder.steps.length;
  el.textContent = n ? `${n} step${n !== 1 ? 's' : ''}` : '';
}

function updateProfilesSummary() {
  const el = document.getElementById('summary-profiles');
  if (!el) return;
  const n = (state.profiles || []).length;
  el.textContent = n ? `${n} profile${n !== 1 ? 's' : ''}` : '';
}
