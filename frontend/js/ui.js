// Общие кусочки интерфейса для страниц: раскладка, фильтры, поля формы.
import { h } from './util.js';
import { icon } from './icons.js';

// Страница: основная колонка (скролл) + правая панель, как у карточки.
export function pageLayout() {
  const main = h('div', { class: 'cqa-pg-main' });
  const side = h('aside', { class: 'cqa-pg-side' });
  const el = h('div', { class: 'cqa-pg' }, main, side);
  return { el, main, side };
}

export function pageHead({ crumbs, title, count, sub, actions }) {
  return h('header', { class: 'cqa-pg-head' },
    crumbs && h('nav', { class: 'cqa-crumbs', 'aria-label': 'Навигация' },
      crumbs.flatMap((c, i) => [i > 0 && icon('arrowRight', 14), c.href ? h('a', { href: c.href }, c.label) : h('span', { class: 'cqa-here' }, c.label)])),
    h('div', { class: 'cqa-pg-title' },
      h('h1', null, title),
      count != null && h('span', { class: 'cqa-pg-count cqa-num' }, count),
      actions && h('div', { class: 'cqa-pg-actions' }, actions)),
    sub && h('p', { class: 'cqa-pg-sub' }, sub));
}

// Табы-пилюли в стиле фильтров fbroker.kz (бордер, активная — зелёная).
export function tabs(options, value, onChange, label) {
  return h('div', { class: 'cqa-tabs', role: 'group', 'aria-label': label },
    options.map(o => h('button', {
      class: 'cqa-tab', 'aria-pressed': String(o.value === value),
      onclick: () => onChange(o.value),
    }, o.label, o.count != null && h('span', { class: 'cqa-tab-n cqa-num' }, o.count))));
}

export function segmented(options, value, onChange, label) {
  return h('div', { class: 'cqa-seg-ctl', role: 'radiogroup', 'aria-label': label },
    options.map(o => h('button', {
      type: 'button', role: 'radio', 'aria-checked': String(o.value === value), title: o.hint || null,
      onclick: () => onChange(o.value),
    }, o.icon && icon(o.icon, 14), o.label)));
}

export function field(label, control, { hint, error, id } = {}) {
  return h('div', { class: `cqa-field ${error ? 'is-invalid' : ''}` },
    h('label', { class: 'cqa-label', for: id }, label),
    control,
    hint && !error && h('span', { class: 'cqa-hint' }, hint),
    error && h('span', { class: 'cqa-err' }, error));
}

export function input(props) {
  const el = h('input', { class: 'cqa-input', type: 'text', ...props });
  if (props.value != null) el.value = props.value;
  return el;
}

export function textarea(props) {
  const el = h('textarea', { class: 'cqa-textarea', ...props });
  if (props.value != null) el.value = props.value;
  return el;
}

export function toggle({ checked, onChange, label, id }) {
  return h('label', { class: 'cqa-switch', for: id },
    h('input', { type: 'checkbox', id, checked: !!checked, onchange: e => onChange(e.target.checked) }),
    h('span', { class: 'cqa-switch-ui', 'aria-hidden': 'true' }),
    h('span', null, label));
}

export function sideBlock(title, ...kids) {
  return h('section', { class: 'cqa-side-block' }, title && h('h2', null, title), kids);
}

export function stat(label, value, note) {
  return h('div', { class: 'cqa-stat' }, h('span', { class: 'cqa-stat-label' }, label), h('b', { class: 'cqa-num' }, value), note && h('span', { class: 'cqa-stat-note' }, note));
}

export function emptyState(title, text, action) {
  return h('div', { class: 'cqa-empty' }, h('span', { class: 'cqa-mark' }, icon('scan', 18)), h('h3', null, title), h('p', null, text), action);
}

export function download(filename, text, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = h('a', { href: url, download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function pickFile(accept = '.json,application/json') {
  return new Promise(resolve => {
    const inp = h('input', { type: 'file', accept, style: { display: 'none' } });
    inp.onchange = () => { resolve(inp.files[0] || null); inp.remove(); };
    document.body.append(inp); inp.click();
  });
}
