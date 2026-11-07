// Attention queue: grave errors, failed runs, appeals, low totals.
import { api } from '../api.js';
import { fmt } from '../scoring.js';
import { h, fill, store } from '../util.js';
import { icon } from '../icons.js';
import { pageLayout, pageHead, tabs, sideBlock, stat, emptyState, input, toggle } from '../ui.js';

const KIND = {
  grave: { label: 'Грубая ошибка', pill: 'cqa-pill--red', icon: 'alert' },
  failed: { label: 'Сбой оценки', pill: 'cqa-pill--red', icon: 'x' },
  appeal: { label: 'Апелляция', pill: 'cqa-pill--amber', icon: 'gavel' },
  disputed: { label: 'Модели разошлись', pill: 'cqa-pill--amber', icon: 'scan' },
  low_score: { label: 'Низкий балл', pill: 'cqa-pill--amber', icon: 'chart' },
  model_fix: { label: 'Ответ модели исправлен', pill: '', icon: 'refresh' },
};
const ORDER = ['grave', 'failed', 'appeal', 'disputed', 'low_score', 'model_fix'];

function reasonLine(r, threshold) {
  if (r.kind === 'grave') {
    return h('div', { class: 'cqa-att-line' },
      h('b', null, r.criterion_name, ': '), r.detail || 'нарушение выявлено',
      r.evidence && h('blockquote', { class: 'cqa-att-quote' }, `#${r.evidence.msg + 1} · «${r.evidence.quote}»`));
  }
  if (r.kind === 'failed') return h('div', { class: 'cqa-att-line' }, h('b', null, 'Модель не вернула оценку: '), r.detail || 'ошибка');
  if (r.kind === 'appeal') return h('div', { class: 'cqa-att-line' }, h('b', null, 'На рассмотрении: '), `${r.count} апелл.`);
  if (r.kind === 'disputed') {
    return h('div', { class: 'cqa-att-line' }, h('b', null, 'Модели разошлись: '),
      (r.criteria || []).map(x => `${x.criterion_name} (${x.answer} / ${x.second_answer})`).join(', '));
  }
  if (r.kind === 'low_score') {
    return h('div', { class: 'cqa-att-line' },
      h('b', null, `Итог ${fmt(r.total)} ниже порога ${fmt(threshold)}`),
      r.weakest?.length > 0 && ['. Слабее всего: ', r.weakest.map(w => `${w.criterion_name} (${fmt(w.points, 1)} из ${fmt(w.max_points, 1)})`).join(', ')]);
  }
  return h('div', { class: 'cqa-att-line' }, h('b', null, `${r.criterion_name}: `), r.detail);
}

function focusCrit(item) {
  const r = item.reasons.find(x => x.criterion_id) || item.reasons.find(x => x.criteria?.length)?.criteria?.[0]
    || item.reasons.find(x => x.weakest?.length)?.weakest?.[0];
  return r?.criterion_id ? `?crit=${encodeURIComponent(r.criterion_id)}` : '';
}

export async function mountAttention(root) {
  const S = { data: null, error: null, tab: 'all', threshold: store('cqa.attention.threshold') ?? null, withReviewed: false };
  const L = pageLayout();
  fill(root, L.el);
  fill(L.main, h('div', { class: 'cqa-loading' }, icon('refresh', 16, 'cqa-spin'), 'Собираем очередь…'));

  async function load() {
    try { S.data = await api.getAttention(S.threshold ?? undefined, S.withReviewed); S.error = null; }
    catch (e) { S.error = e.message; }
  }

  function render() {
    const d = S.data || { items: [], counts: {}, threshold: 60 };
    const list = d.items.filter(i => S.tab === 'all' || i.reasons.some(r => r.kind === S.tab));
    fill(L.main,
      pageHead({ title: 'Требуют внимания', count: d.counts.total ?? 0, sub: 'Сначала грубые ошибки, затем сбои оценки, открытые апелляции, низкие баллы и ответы модели, которые бэкенду пришлось исправить. По каждому диалогу — последняя оценка; проверенные скрыты.' }),
      h('div', { class: 'cqa-filters' },
        tabs([{ value: 'all', label: 'Все', count: d.counts.total ?? 0 },
          ...ORDER.map(k => ({ value: k, label: KIND[k].label, count: d.counts[k] ?? 0 })).filter(o => o.count > 0 || S.tab === o.value)],
        S.tab, v => { S.tab = v; render(); }, 'Причина')),
      S.error ? h('div', { class: 'cqa-error' }, `Не удалось загрузить очередь: ${S.error}`)
        : list.length === 0
          ? emptyState(d.items.length ? 'Под фильтр ничего не подходит' : 'Всё спокойно',
              d.items.length ? 'Выберите другую причину.' : 'Оцените диалоги — сюда попадут те, что требуют проверки.',
              h('a', { class: 'cqa-btn cqa-btn--outline cqa-btn--sm', href: '#/dialogs' }, 'К диалогам', icon('arrowRight', 14)))
          : h('div', { class: 'cqa-ap-list' }, list.map(item => h('a', {
              class: `cqa-ap cqa-att ${item.reasons.some(r => r.kind === 'grave') ? 'is-grave' : ''}`,
              href: `#/dialogs/${encodeURIComponent(item.conversation_id)}${focusCrit(item)}`,
            },
              h('div', { class: 'cqa-ap-top' },
                [...new Set(item.reasons.map(r => r.kind))].map(k => h('span', { class: `cqa-pill ${KIND[k].pill}` }, icon(KIND[k].icon, 12), KIND[k].label)),
                h('b', { class: 'cqa-num' }, item.conversation_id),
                h('span', { class: 'cqa-muted' }, `${item.channel === 'voice call' ? 'Звонок' : 'Чат'} · ${item.language}`),
                h('span', { class: 'cqa-ap-date cqa-num' }, item.total == null ? '—' : h('b', null, fmt(item.total)))),
              item.reasons.map(r => reasonLine(r, d.threshold)),
              item.reviewed_at && h('span', { class: 'cqa-muted' }, icon('check', 12), ` Проверено${item.reviewed_by ? ` · ${item.reviewed_by}` : ''}`),
              h('div', { class: 'cqa-ap-foot' }, h('span', { class: 'cqa-ap-go' }, 'Открыть', icon('chevronRight', 14)))))),
    );

    const thr = input({ type: 'number', min: 0, max: 100, step: 1, value: d.threshold, 'aria-label': 'Порог балла',
      onkeydown: e => e.key === 'Enter' && apply(e.target.value) });
    async function apply(v) {
      const n = Math.max(0, Math.min(100, Number(v)));
      if (!Number.isFinite(n)) return;
      S.threshold = n; store('cqa.attention.threshold', n);
      await load(); render();
    }
    fill(L.side, h('div', { class: 'cqa-side-inner' },
      sideBlock('Сводка', h('div', { class: 'cqa-stats' },
        stat('Грубые ошибки', d.counts.grave ?? 0), stat('Сбои оценки', d.counts.failed ?? 0),
        stat('Апелляции', d.counts.appeal ?? 0), stat('Ниже порога', d.counts.low_score ?? 0))),
      sideBlock('Порог низкого балла',
        h('div', { class: 'cqa-inline' }, thr,
          h('button', { class: 'cqa-btn cqa-btn--outline cqa-btn--sm', onclick: () => apply(thr.value) }, 'Применить')),
        h('p', { class: 'cqa-muted' }, 'Диалоги с итогом ниже порога попадают в очередь вместе с двумя самыми слабыми критериями.'),
        toggle({ id: 'cqa-att-reviewed', checked: S.withReviewed, label: 'Показывать проверенные', onChange: async v => { S.withReviewed = v; await load(); render(); } })),
      sideBlock('Порядок',
        h('ol', { class: 'cqa-steps-list' },
          h('li', null, 'Грубая ошибка: оскорбление, услуга в обход компании, утечка данных.'),
          h('li', null, 'Сбой оценки: модель не ответила, диалог нужно переоценить.'),
          h('li', null, 'Открытая апелляция ждёт решения проверяющего.'),
          h('li', null, 'Низкий балл: чем ниже итог, тем выше в списке.'),
          h('li', null, 'Бэкенд исправил недопустимый ответ модели — стоит перепроверить.'))),
    ));
  }

  await load();
  render();
  return { setRole() {}, destroy() {} };
}
