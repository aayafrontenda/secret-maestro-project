// Аналитика по оценённым диалогам + экспорт результатов в CSV.
import { api } from '../api.js';
import { computeScore, finalAnswersOf, fraction, fmt } from '../scoring.js';
import { h, fill } from '../util.js';
import { icon } from '../icons.js';
import { pageLayout, pageHead, sideBlock, stat, emptyState, download, segmented } from '../ui.js';

export async function mountAnalytics(root) {
  const L = pageLayout();
  fill(root, L.el);
  fill(L.main, h('div', { class: 'cqa-loading' }, icon('refresh', 16, 'cqa-spin'), 'Считаем…'));

  const [rows, appeals, active] = await Promise.all([api.listDialogs(), api.listAppeals(), api.getActiveChecklist()]);
  const done = rows.filter(r => r.evaluation === 'done');
  const evals = (await Promise.all(done.map(r => api.getEvaluation(r.conversation_id)))).filter(Boolean);
  const S = { view: 'chart' };

  // агрегаты по активному чек-листу (оценки по старым версиям считаются по своим критериям)
  const items = evals.map(ev => {
    const cl = ev.checklist || active;
    const ans = finalAnswersOf(ev, appeals);
    return { ev, cl, ans, sc: computeScore(cl, ans), row: rows.find(r => r.conversation_id === ev.conversation_id) };
  });
  const totals = items.map(i => i.sc.total).filter(x => x != null);
  const avg = totals.length ? totals.reduce((a, b) => a + b, 0) / totals.length : null;

  const perCrit = active.criteria.map(c => {
    let applicable = 0, sum = 0, na = 0, n = 0;
    for (const it of items) {
      const a = it.ans[c.id];
      if (a == null) continue;
      n++;
      if (c.type === 'flag') { applicable++; sum += a === 'yes' ? 1 : 0; continue; }
      if (a === 'na') { na++; continue; }
      applicable++; sum += fraction(c, a) ?? 0;
    }
    return { c, n, rate: applicable ? sum / applicable : null, naRate: n ? na / n : null };
  });
  const byLang = ['RU', 'KZ', 'EN'].map(l => {
    const t = items.filter(i => i.row?.language === l).map(i => i.sc.total).filter(x => x != null);
    return { label: l, value: t.length ? t.reduce((a, b) => a + b, 0) / t.length : null, n: t.length };
  });
  const bins = Array.from({ length: 10 }, (_, k) => ({ from: k * 10, to: k * 10 + 10, n: 0 }));
  totals.forEach(t => { bins[Math.min(9, Math.floor(t / 10))].n++; });
  const maxBin = Math.max(1, ...bins.map(b => b.n));

  // всплывающая подсказка у столбиков
  const tip = h('div', { class: 'cqa-tip', role: 'tooltip' });
  const showTip = (e, text) => { tip.textContent = text; tip.style.opacity = '1'; const r = L.main.getBoundingClientRect(); tip.style.transform = `translate(${e.clientX - r.left + 12}px, ${e.clientY - r.top + L.main.scrollTop - 34}px)`; };
  const hideTip = () => { tip.style.opacity = '0'; };
  const hov = text => ({ onmousemove: e => showTip(e, text), onmouseleave: hideTip, onfocus: e => { const b = e.target.getBoundingClientRect(); showTip({ clientX: b.left, clientY: b.top }, text); }, onblur: hideTip, tabindex: 0 });

  function hbar(label, value, valueText, sub, tipText) {
    return h('div', { class: 'cqa-hbar', ...hov(tipText) },
      h('span', { class: 'cqa-hbar-label' }, label, sub && h('small', null, sub)),
      h('span', { class: 'cqa-hbar-track' }, value != null && h('i', { style: { width: `${Math.max(0, Math.min(100, value * 100))}%` } })),
      h('span', { class: 'cqa-hbar-val cqa-num' }, valueText));
  }

  function render() {
    if (!items.length) {
      fill(L.main, pageHead({ title: 'Аналитика' }), emptyState('Пока нечего считать', 'Оцените диалоги на странице «Диалоги», и здесь появится сводка по критериям и языкам.',
        h('a', { class: 'cqa-btn cqa-btn--primary cqa-btn--sm', href: '#/dialogs' }, icon('spark', 14), 'К диалогам')));
      fill(L.side);
      return;
    }
    const scored = perCrit.filter(p => p.c.type !== 'flag');
    const flags = perCrit.filter(p => p.c.type === 'flag');
    fill(L.main,
      pageHead({ title: 'Аналитика', count: items.length, sub: `По ${items.length} оценённым диалогам с учётом решений по апелляциям.` }),
      tip,
      h('section', { class: 'cqa-chart' },
        h('div', { class: 'cqa-chart-head' }, h('h2', null, 'Выполнение критериев'),
          h('span', { class: 'cqa-muted' }, 'доля от максимума среди применимых, N/A исключены'),
          segmented([{ value: 'chart', label: 'График' }, { value: 'table', label: 'Таблица' }], S.view, v => { S.view = v; render(); }, 'Вид')),
        S.view === 'chart'
          ? h('div', { class: 'cqa-hbars' }, scored.map(p => hbar(`${p.c.code} · ${p.c.name}`, p.rate, p.rate == null ? '—' : `${Math.round(p.rate * 100)}%`,
              p.naRate ? `N/A в ${Math.round(p.naRate * 100)}%` : null,
              `${p.c.name}: ${p.rate == null ? 'нет применимых' : `${Math.round(p.rate * 100)}%`} · оценок ${p.n}${p.naRate ? ` · N/A ${Math.round(p.naRate * 100)}%` : ''}`)))
          : h('table', { class: 'cqa-dtable' },
              h('thead', null, h('tr', null, ['Критерий', 'Оценок', 'Выполнение', 'N/A'].map(t => h('th', null, t)))),
              h('tbody', null, perCrit.map(p => h('tr', null,
                h('td', null, `${p.c.code} · ${p.c.name}`), h('td', { class: 'cqa-num' }, p.n),
                h('td', { class: 'cqa-num' }, p.c.type === 'flag' ? `выявлено в ${Math.round((p.rate || 0) * 100)}%` : p.rate == null ? '—' : `${Math.round(p.rate * 100)}%`),
                h('td', { class: 'cqa-num' }, p.naRate == null ? '—' : `${Math.round(p.naRate * 100)}%`)))))),

      h('div', { class: 'cqa-chart-row' },
        h('section', { class: 'cqa-chart' },
          h('div', { class: 'cqa-chart-head' }, h('h2', null, 'Распределение итогов'), h('span', { class: 'cqa-muted' }, 'диалогов в диапазоне')),
          h('div', { class: 'cqa-hist' }, bins.map(b => h('div', { class: 'cqa-hist-col', ...hov(`${b.from}–${b.to}: ${b.n} диал.`) },
            h('span', { class: 'cqa-hist-n cqa-num' }, b.n || ''),
            h('span', { class: 'cqa-hist-bar' }, h('i', { style: { height: `${(b.n / maxBin) * 100}%` } })),
            h('span', { class: 'cqa-hist-x cqa-num' }, b.from))))),
        h('section', { class: 'cqa-chart' },
          h('div', { class: 'cqa-chart-head' }, h('h2', null, 'Средний итог по языкам')),
          h('div', { class: 'cqa-hbars' }, byLang.map(l => hbar(l.label, l.value == null ? null : l.value / 100, l.value == null ? '—' : fmt(l.value, 1), `${l.n} диал.`, `${l.label}: ${l.value == null ? 'нет оценок' : fmt(l.value)} · ${l.n} диал.`))),
          flags.map(p => h('p', { class: 'cqa-muted', style: { marginTop: '14px' } }, `${p.c.name}: выявлены в ${Math.round((p.rate || 0) * 100)}% диалогов.`)))),
    );

    const changed = appeals.filter(a => a.status === 'changed').length;
    fill(L.side, h('div', { class: 'cqa-side-inner' },
      h('div', { class: 'cqa-overall' }, h('span', { class: 'cqa-overall-label' }, 'Средний итог'), h('span', { class: 'cqa-total' }, avg == null ? '—' : fmt(avg))),
      sideBlock(null, h('div', { class: 'cqa-stats' },
        stat('Оценено', `${items.length} / ${rows.length}`),
        stat('Грубые ошибки', items.filter(i => i.sc.grossErrors.length).length),
        stat('Апелляций', appeals.length, `изменено ${changed}`),
        stat('Устарели', items.filter(i => i.ev.checklist_version !== active.version).length, `не v${active.version}`))),
      sideBlock('Экспорт',
        h('p', { class: 'cqa-muted' }, 'Ответы по каждому критерию и итог: удобно сверять с эталоном.'),
        h('button', { class: 'cqa-btn cqa-btn--outline cqa-btn--block', onclick: exportCsv }, icon('external', 16), 'Скачать CSV'),
        h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', onclick: exportJson }, icon('layers', 14), 'Скачать JSON')),
    ));
  }

  function exportCsv() {
    const crit = active.criteria;
    const esc = v => { const s = v == null ? '' : String(v); return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const head = ['conversation_id', 'language', 'channel', 'checklist_version', 'total', 'gross_error', ...crit.map(c => `${c.code}_${c.id}`)];
    const lines = items.map(i => [i.ev.conversation_id, i.row?.language, i.row?.channel, i.ev.checklist_version, i.sc.total ?? '', i.sc.grossErrors.length ? 1 : 0, ...crit.map(c => i.ans[c.id] ?? '')].map(esc).join(','));
    download('cqa-results.csv', '﻿' + [head.join(','), ...lines].join('\n'), 'text/csv;charset=utf-8');
  }
  function exportJson() {
    download('cqa-results.json', JSON.stringify(items.map(i => ({ conversation_id: i.ev.conversation_id, total: i.sc.total, gross_errors: i.sc.grossErrors, checklist_version: i.ev.checklist_version, model: i.ev.model, answers: i.ans, results: i.ev.results })), null, 2));
  }

  render();
  return { setRole() {}, destroy() {} };
}
