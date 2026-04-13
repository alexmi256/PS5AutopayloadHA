'use strict';

// ── Collapsible section manager ──────────────────────────────────
// Sections with class="collapsible" on <section> get click-to-collapse
// behaviour via their .collapse-header child.
// The .collapse-arrow child rotates 90° when the section is open.
// State persists in sessionStorage (resets on page reload / restart).

const _COLLAPSED_KEY = 'ps5_sections_collapsed';

function initCollapsible() {
  let savedState = {};
  try {
    savedState = JSON.parse(sessionStorage.getItem(_COLLAPSED_KEY) || '{}');
  } catch (_) {}

  document.querySelectorAll('.collapsible').forEach(card => {
    const header = card.querySelector('.collapse-header');
    const body   = card.querySelector('.collapse-body');
    const arrow  = card.querySelector('.collapse-arrow');
    const id     = card.id;
    if (!header || !body) return;

    // Restore saved state.  true → collapsed.
    // HTML starts with arrow.open on all sections (= open).
    if (savedState[id] === true) {
      body.classList.add('collapsed');
      if (arrow) arrow.classList.remove('open');
    }

    header.addEventListener('click', () => {
      const isNowCollapsed = body.classList.toggle('collapsed');
      if (arrow) arrow.classList.toggle('open', !isNowCollapsed);
      savedState[id] = isNowCollapsed;
      sessionStorage.setItem(_COLLAPSED_KEY, JSON.stringify(savedState));
    });
  });
}

// ── Section summary badges ───────────────────────────────────────
// Called automatically after every data refresh.

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
