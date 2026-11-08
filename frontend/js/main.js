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
import { LANGS, lang, setLang, startI18n } from './i18n.js';

const root = document.getElementById('cqa-root');
root.classList.add('cqa', 'cqa-app');

let role = store('cqa.role') || 'operator';
// Rail: expanded shows the section names, collapsed shows icons with tooltips. The choice is remembered;
// until the user picks, it opens on wide screens as before.
let railOpen = store('cqa.rail');
if (typeof railOpen !== 'boolean') railOpen = innerWidth >= 1600;
root.classList.toggle('is-rail-open', railOpen);
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
    class: 'cqa-has-tip', 'aria-pressed': String(role === r.id), 'aria-label': r.label,
    onclick: () => { role = r.id; store('cqa.role', role); renderRoles(); view?.setRole(role); },
  }, icon(r.icon, 16), h('span', null, r.label))));
}
function renderNav(key) {
  fill(navBox, NAV.map(n => h('a', { class: 'cqa-has-tip', href: n.href, 'aria-current': n.key === key ? 'page' : null, 'aria-label': n.label }, icon(n.icon, 18), h('span', null, n.label))));
}
const railToggle = h('button', { class: 'cqa-rail-toggle cqa-has-tip', type: 'button', onclick: () => setRail(!railOpen) });
function renderRailToggle() {
  railToggle.setAttribute('aria-expanded', String(railOpen));
  railToggle.setAttribute('aria-label', railOpen ? 'Свернуть меню' : 'Развернуть меню');
  fill(railToggle, icon(railOpen ? 'chevronLeft' : 'chevronRight', 16), h('span', null, 'Свернуть'));
}
function setRail(open) {
  railOpen = open;
  store('cqa.rail', open);
  root.classList.toggle('is-rail-open', open);
  renderRailToggle();
}
renderRailToggle();
renderRoles();

fill(root,
  h('aside', { class: 'cqa-rail' },
    h('a', { class: 'cqa-brand', href: '#/dialogs' },
      h('span', { class: 'cqa-mark' }, icon('scan', 16)),
      h('span', { class: 'cqa-brand-text' }, h('b', null, 'CQA'), h('span', null, 'Контроль качества'))),
    railToggle,
    navBox,
    h('div', { class: 'cqa-rail-foot' },
      h('button', {
        class: 'cqa-lang-btn cqa-has-tip', 'aria-label': 'Язык интерфейса',
        onclick: () => { const i = LANGS.findIndex(l => l.id === lang()); setLang(LANGS[(i + 1) % LANGS.length].id); },
      }, icon('globe', 14), h('span', null, LANGS.find(l => l.id === lang()).label)),
      h('span', { class: 'cqa-rail-label' }, 'Роль'), roleBox),
  ),
  main,
  h('div', { class: 'cqa-toasts', 'aria-live': 'polite' }),
);
startI18n();

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
