// Мини-хелпер для DOM без фреймворка.
export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') for (const [sk, sv] of Object.entries(v)) sk.startsWith('--') ? el.style.setProperty(sk, sv) : (el.style[sk] = sv);
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value') el.value = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

// Чаты: "MM:SS". Звонки: ISO 8601 с таймзоной. Возвращаем секунды от начала диалога.
export function offsetsOf(transcript) {
  const raw = transcript.map(t => {
    const m = /^(\d{1,3}):(\d{2})$/.exec(t.timestamp);
    if (m) return Number(m[1]) * 60 + Number(m[2]);
    const ms = Date.parse(t.timestamp);
    return Number.isNaN(ms) ? null : ms / 1000;
  });
  const first = raw.find(x => x != null) ?? 0;
  return raw.map(x => (x == null ? null : x - first));
}

export function mmss(sec) {
  if (sec == null) return '—';
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

export function clockOf(ts) {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export const SPEAKER = { client: 'Клиент', operator: 'Оператор', bot: 'Бот', system: 'Система' };

export const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key));
    localStorage.setItem(key, JSON.stringify(value));
  } catch { return null; }
}

// replaceChildren, который понимает массивы, null и false.
export function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity)
    .filter(k => k != null && k !== false)
    .map(k => (k instanceof Node ? k : document.createTextNode(String(k)))));
  return el;
}

// Тост в духе «Corrected · Undo»: тёмная плашка снизу справа.
export function toast(text, { icon: ic = null } = {}) {
  const box = document.querySelector('.cqa-toasts');
  if (!box) return;
  const el = h('div', { class: 'cqa-toast', role: 'status' }, ic, h('span', null, text));
  box.append(el);
  setTimeout(() => { el.classList.add('is-leaving'); setTimeout(() => el.remove(), 400); }, 3600);
}
