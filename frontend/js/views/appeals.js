// Очередь апелляций: проверяющий видит спорные оценки и переходит в карточку к нужному критерию.
import { api } from '../api.js';
import { h, fill } from '../util.js';
import { icon } from '../icons.js';
import { pageLayout, pageHead, tabs, sideBlock, stat, emptyState, input } from '../ui.js';

const STATUS = { open: 'На рассмотрении', confirmed: 'Подтверждена', changed: 'Оценка изменена' };
const ans = a => (a == null ? '—' : a === 'yes' ? 'Да' : a === 'no' ? 'Нет' : a === 'na' ? 'N/A' : String(a));

export async function mountAppeals(root, { role }) {
  const S = { all: [], tab: 'open', role, q: '' };
  const L = pageLayout();
  fill(root, L.el);
  fill(L.main, h('div', { class: 'cqa-loading' }, icon('refresh', 16, 'cqa-spin'), 'Загружаем апелляции…'));

  function render() {
    const by = s => S.all.filter(a => s === 'all' || (s === 'done' ? a.status !== 'open' : a.status === s));
    const q = S.q.trim().toLowerCase();
    const match = a => !q || [a.conversation_id, a.criterion_name, a.criterion_id, a.comment, a.decision?.by].some(x => x && String(x).toLowerCase().includes(q));
    const list = by(S.tab).filter(match).sort((a, b) => S.tab === 'open'
      ? a.created_at.localeCompare(b.created_at)
      : (b.decision?.decided_at || b.created_at).localeCompare(a.decision?.decided_at || a.created_at));
    fill(L.main,
      pageHead({ title: 'Апелляции', count: S.all.length, sub: 'Оператор оспаривает критерий в карточке диалога. Проверяющий изучает доказательства, подтверждает или меняет оценку, итог пересчитывается.' }),
      h('div', { class: 'cqa-filters' },
        tabs([
          { value: 'open', label: 'На рассмотрении', count: by('open').length },
          { value: 'changed', label: 'Оценка изменена', count: by('changed').length },
          { value: 'confirmed', label: 'Подтверждена', count: by('confirmed').length },
          { value: 'all', label: 'Все', count: S.all.length },
        ], S.tab, v => { S.tab = v; render(); }, 'Статус'),
        h('div', { class: 'cqa-search' }, icon('scan', 16),
          input({ placeholder: 'Диалог, критерий, проверяющий', value: S.q, 'aria-label': 'Поиск по апелляциям',
            oninput: e => { S.q = e.target.value; const pos = e.target.selectionStart; render(); const el = L.main.querySelector('.cqa-search input'); el?.focus(); el?.setSelectionRange(pos, pos); } }))),
      list.length === 0
        ? emptyState(S.tab === 'open' ? 'Открытых апелляций нет' : 'Здесь пока пусто',
            'Откройте диалог, раскройте критерий и нажмите «Оспорить оценку».',
            h('a', { class: 'cqa-btn cqa-btn--outline cqa-btn--sm', href: '#/dialogs' }, 'К диалогам', icon('arrowRight', 14)))
        : h('div', { class: 'cqa-ap-list' }, list.map(a => h('a', {
            class: 'cqa-ap', href: `#/dialogs/${encodeURIComponent(a.conversation_id)}?crit=${encodeURIComponent(a.criterion_id)}`,
          },
            h('div', { class: 'cqa-ap-top' },
              h('span', { class: `cqa-status cqa-status--${a.status}` }, STATUS[a.status]),
              h('b', { class: 'cqa-num' }, a.conversation_id),
              h('span', { class: 'cqa-muted' }, '·'),
              h('span', { class: 'cqa-ap-crit' }, a.criterion_name || a.criterion_id),
              h('span', { class: 'cqa-ap-date cqa-num' }, new Date(a.created_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }))),
            h('blockquote', null, a.comment),
            h('div', { class: 'cqa-ap-foot' },
              h('span', null, 'Исходно ', h('b', null, ans(a.original_answer))),
              a.decision && [icon('arrowRight', 14), h('span', null, 'Итог ', h('b', null, ans(a.status === 'changed' ? a.decision.answer : a.original_answer)))],
              a.decision && h('span', { class: 'cqa-muted cqa-ap-reason' }, `«${a.decision.reason}»`),
              a.decision?.by && h('span', { class: 'cqa-muted' }, `· ${a.decision.by}`),
              h('span', { class: 'cqa-ap-go' }, S.role === 'reviewer' && a.status === 'open' ? 'Рассмотреть' : 'Открыть', icon('chevronRight', 14)))))),
    );

    const open = by('open').length;
    fill(L.side, h('div', { class: 'cqa-side-inner' },
      sideBlock('Сводка', h('div', { class: 'cqa-stats' },
        stat('Самая старая', by('open').length ? new Date(by('open').map(a => a.created_at).sort()[0]).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—', 'ждёт решения'),
        stat('Открыто', open), stat('Изменено', S.all.filter(a => a.status === 'changed').length),
        stat('Подтверждено', S.all.filter(a => a.status === 'confirmed').length),
        stat('Доля изменённых', S.all.filter(a => a.status !== 'open').length ? `${Math.round((S.all.filter(a => a.status === 'changed').length / S.all.filter(a => a.status !== 'open').length) * 100)}%` : '—'))),
      sideBlock('Как это работает',
        h('ol', { class: 'cqa-steps-list' },
          h('li', null, 'Оператор раскрывает критерий в карточке и пишет комментарий.'),
          h('li', null, 'Проверяющий видит спорную оценку, комментарий и реплики-доказательства.'),
          h('li', null, 'Он подтверждает или меняет ответ и указывает причину. Исходная оценка сохраняется.')),
        S.role !== 'reviewer' && h('p', { class: 'cqa-hintbox' }, icon('gavel', 14), 'Чтобы принимать решения, переключите роль на «Проверяющий» в меню слева.')),
    ));
  }

  S.all = await api.listAppeals();
  render();
  return { setRole(r) { S.role = r; render(); }, destroy() {} };
}
