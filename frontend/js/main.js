// Точка входа. Монтируется в один корневой элемент — так же будет в Dynamics 365 web resource.
import { h, fill, store } from './util.js';
import { icon } from './icons.js';
import { mountCard } from './views/card.js';
import { mountDialogs } from './views/dialogs.js';
import { mountChecklist } from './views/checklist.js';
import { mountAppeals } from './views/appeals.js';
import { mountAnalytics } from './views/analytics.js';
import { mountAttention } from './views/attention.js';
import { mountBot } from './views/bot.js';

const root = document.getElementById('cqa-root');
root.classList.add('cqa', 'cqa-app');

let role = store('cqa.role') || 'operator';
let view = null;
let currentHash = null;

const ROLES = [
  { id: 'operator', label: 'Оператор', icon: 'flag' },
  { id: 'reviewer', label: 'Проверяющий', icon: 'gavel' },
];
const NAV = [
  { key: 'dialogs', href: '#/dialogs', label: 'Диалоги', icon: 'chat' },
  { key: 'attention', href: '#/attention', label: 'Внимание', icon: 'alert' },
  { key: 'checklists', href: '#/checklists', label: 'Чек-лист', icon: 'list' },
  { key: 'appeals', href: '#/appeals', label: 'Апелляции', icon: 'gavel' },
  { key: 'analytics', href: '#/analytics', label: 'Аналитика', icon: 'chart' },
  { key: 'bot', href: '#/bot', label: 'Бот → оператор', icon: 'spark' },
];

const main = h('main', { class: 'cqa-main' });
const roleBox = h('div', { class: 'cqa-role', role: 'group', 'aria-label': 'Роль' });
const navBox = h('nav', { class: 'cqa-nav', 'aria-label': 'Разделы' });

function renderRoles() {
  fill(roleBox, ROLES.map(r => h('button', {
    'aria-pressed': String(role === r.id), title: r.label,
    onclick: () => { role = r.id; store('cqa.role', role); renderRoles(); view?.setRole(role); },
  }, icon(r.icon, 16), h('span', null, r.label))));
}
function renderNav(key) {
  fill(navBox, NAV.map(n => h('a', { href: n.href, 'aria-current': n.key === key ? 'page' : null, title: n.label }, icon(n.icon, 18), h('span', null, n.label))));
}
renderRoles();

fill(root,
  h('aside', { class: 'cqa-rail' },
    h('a', { class: 'cqa-brand', href: '#/dialogs' },
      h('span', { class: 'cqa-mark' }, icon('scan', 16)),
      h('span', { class: 'cqa-brand-text' }, h('b', null, 'CQA'), h('span', null, 'Контроль качества'))),
    navBox,
    h('div', { class: 'cqa-rail-foot' }, h('span', { class: 'cqa-rail-label' }, 'Роль'), roleBox),
  ),
  main,
  h('div', { class: 'cqa-toasts', 'aria-live': 'polite' }),
);

function parse(hash) {
  const [path, query = ''] = hash.replace(/^#/, '').split('?');
  const parts = path.split('/').filter(Boolean);
  return { parts, q: Object.fromEntries(new URLSearchParams(query)) };
}

async function route() {
  if (view?.canLeave && currentHash && location.hash !== currentHash && !view.canLeave()) {
    history.replaceState(null, '', currentHash);
    return;
  }
  currentHash = location.hash || '#/dialogs';
  const { parts, q } = parse(currentHash);
  const [section = 'dialogs', id] = parts;
  view?.destroy();
  view = null;
  const ctx = { role, onNavigate: next => { location.hash = `#/dialogs/${encodeURIComponent(next)}`; } };
  if (section === 'dialogs' && id) {
    renderNav('dialogs');
    view = await mountCard(main, { ...ctx, id: decodeURIComponent(id), crit: q.crit });
  } else if (section === 'checklists') {
    renderNav('checklists'); view = await mountChecklist(main, ctx);
  } else if (section === 'appeals') {
    renderNav('appeals'); view = await mountAppeals(main, ctx);
  } else if (section === 'attention') {
    renderNav('attention'); view = await mountAttention(main, ctx);
  } else if (section === 'bot') {
    renderNav('bot'); view = await mountBot(main, ctx);
  } else if (section === 'analytics') {
    renderNav('analytics'); view = await mountAnalytics(main, ctx);
  } else {
    renderNav('dialogs'); view = await mountDialogs(main, ctx);
  }
}
addEventListener('hashchange', route);
route();
