/* ============================================================
   Lucide icon set (MIT-licensed, https://lucide.dev).
   Only the icons actually used in this add-on are bundled.
   Each entry is the inner content of a 24×24 lucide SVG.
   Public API:
     icon(name, opts?)   → string (HTML)
     iconEl(name, opts?) → SVGElement (for builder code)
   ============================================================ */

const LUCIDE_PATHS = {
  // Theme
  sun:           '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon:          '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',

  // Navigation
  'chevron-down':  '<path d="m6 9 6 6 6-6"/>',
  'chevron-right': '<path d="m9 18 6-6-6-6"/>',

  // Actions
  plus:          '<path d="M5 12h14"/><path d="M12 5v14"/>',
  'refresh-cw':  '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  'rotate-ccw':  '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
  download:      '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  upload:        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  save:          '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/>',
  settings:      '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  pencil:        '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
  'trash-2':     '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
  x:             '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  check:         '<path d="M20 6 9 17l-5-5"/>',
  search:        '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',

  // Status
  'alert-triangle': '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  star:          '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',

  // Run / control
  play:          '<polygon points="6 3 20 12 6 21 6 3"/>',
  pause:         '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
  square:        '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>',

  // List affordances
  'more-vertical':  '<circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>',
  'grip-vertical':  '<circle cx="9" cy="12" r="1"/><circle cx="9" cy="5" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="19" r="1"/>',
};

/**
 * Return an inline SVG string for the given Lucide icon name.
 * @param {string} name   Lucide icon name (see LUCIDE_PATHS above)
 * @param {object} [opts] { size, filled, class: extraClass }
 * @returns {string}
 */
function icon(name, opts = {}) {
  const path = LUCIDE_PATHS[name];
  if (!path) {
    console.warn(`icon('${name}') is not in the bundled Lucide set`);
    return '';
  }
  const size  = opts.size  || 16;
  const fill  = opts.filled ? 'currentColor' : 'none';
  const extra = opts.class ? ` ${opts.class}` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg"`
       + ` width="${size}" height="${size}" viewBox="0 0 24 24"`
       + ` fill="${fill}" stroke="currentColor" stroke-width="2"`
       + ` stroke-linecap="round" stroke-linejoin="round"`
       + ` class="lucide lucide-${name}${extra}" aria-hidden="true">`
       + `${path}</svg>`;
}

/**
 * Return an SVGElement DOM node — convenient for builder code that
 * does `el.appendChild(iconEl('plus'))` instead of innerHTML.
 */
function iconEl(name, opts = {}) {
  const tpl = document.createElement('template');
  tpl.innerHTML = icon(name, opts).trim();
  return tpl.content.firstChild;
}

window.icon   = icon;
window.iconEl = iconEl;
