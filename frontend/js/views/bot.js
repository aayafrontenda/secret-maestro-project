// Bot -> operator handoffs: where AIM gives up and what it should learn.
import { api } from '../api.js';
import { fmt } from '../scoring.js';
import { h, fill, mmss, toast } from '../util.js';
import { icon } from '../icons.js';
import { pageLayout, pageHead, tabs, sideBlock, stat, emptyState } from '../ui.js';

export const REASON = {
  account_check: 'Нужна проверка счёта',
  incomplete_answer: 'Ответ бота слишком общий',
  clarification: 'Бот переспросил вместо ответа',
  human_requested: 'Клиент сразу просил человека',
  complaint: 'Жалоба или раздражение',
  other: 'Другое',
};
const pct = (a, b) => (b ? `${Math.round((a / b) * 100)}%` : '—');

export async function mountBot(root) {
  const S = { data: null, error: null, topic: 'all', reason: 'all', timer: null, destroyed: false };
  const L = pageLayout();
  fill(root, L.el);
  fill(L.main, h('div', { class: 'cqa-loading' }, icon('refresh', 16, 'cqa-spin'), 'Разбираем передачи…'));

  async function load() {
    try { S.data = await api.getHandoffs(); S.error = null; }
    catch (e) { S.error = e.message; }
  }

  function poll() {
    clearTimeout(S.timer);
    if (S.destroyed || !S.data?.job?.running) return;
    S.timer = setTimeout(async () => {
      await load();
      render();
      if (!S.data?.job?.running) toast(`LLM разобрала передачи: ${S.data.job.done} из ${S.data.job.total}`);
      poll();
    }, 2000);
  }

  async function analyze(force) {
    try {
      await api.analyzeHandoffs(force);
      await load(); render(); poll();
    } catch (e) { toast(e.message); }
  }

  function hbars(rows, total) {
    const max = Math.max(1, ...rows.map(r => r.count));
    return h('div', { class: 'cqa-hbars' }, rows.map(r => h('div', { class: 'cqa-hbar', title: r.title || '' },
      h('span', { class: 'cqa-hbar-label' }, r.label, r.sub && h('small', null, r.sub)),
      h('span', { class: 'cqa-hbar-track' }, h('i', { style: { width: `${(r.count / max) * 100}%` } })),
      h('span', { class: 'cqa-hbar-val cqa-num' }, `${r.count} · ${pct(r.count, total)}`))));
  }

  function render() {
    if (S.error || !S.data) {
      fill(L.main, pageHead({ title: 'Бот → оператор' }), h('div', { class: 'cqa-error' }, S.error || 'Нет данных'));
      fill(L.side, null);
      return;
    }
    const d = S.data;
    const items = d.items.filter(i => (S.topic === 'all' || i.topic === S.topic) && (S.reason === 'all' || i.reason === S.reason));
    const llm = d.llm_analysed > 0;

    fill(L.main,
      pageHead({ title: 'Бот → оператор', count: d.escalated, sub: 'Где бот AIM передаёт клиента живому оператору: темы, причины, ожидание и ответ, который бот мог бы дать сам. Это список того, чему научить бота дальше.' }),
      d.escalated === 0
        ? emptyState('Передач пока нет', 'Импортируйте диалоги: передача определяется по системной строке «Эскалация на оператора».')
        : [
            h('div', { class: 'cqa-bot-grid' },
              h('section', { class: 'cqa-panel' }, h('h2', null, 'Темы'),
                hbars(d.by_topic.map(t => ({
                  label: t.topic, count: t.count,
                  sub: [t.avg_wait_s != null && `ожидание ${mmss(t.avg_wait_s)}`, llm && t.automatable && `автоматизируемо: ${t.automatable}`].filter(Boolean).join(' · '),
                })), d.escalated)),
              h('section', { class: 'cqa-panel' }, h('h2', null, 'Почему бот не справился'),
                hbars(d.by_reason.map(r => ({ label: REASON[r.reason] || r.reason, count: r.count })), d.escalated),
                h('p', { class: 'cqa-muted' }, llm ? `Разобрано LLM: ${d.llm_analysed} из ${d.escalated}.` : 'Сейчас причины определены правилами. Разбор LLM уточнит их и предложит ответ для бота.'))),
            h('div', { class: 'cqa-filters' },
              tabs([{ value: 'all', label: 'Все темы', count: d.escalated }, ...d.by_topic.map(t => ({ value: t.topic, label: t.topic, count: t.count }))],
                S.topic, v => { S.topic = v; render(); }, 'Тема'),
              tabs([{ value: 'all', label: 'Любая причина' }, ...d.by_reason.map(r => ({ value: r.reason, label: REASON[r.reason] || r.reason, count: r.count }))],
                S.reason, v => { S.reason = v; render(); }, 'Причина')),
            h('div', { class: 'cqa-ap-list' }, items.map(i => h('a', { class: 'cqa-ap cqa-bot', href: `#/dialogs/${encodeURIComponent(i.conversation_id)}` },
              h('div', { class: 'cqa-ap-top' },
                h('span', { class: 'cqa-pill' }, i.topic || 'Другое'),
                h('span', { class: 'cqa-pill cqa-pill--amber' }, REASON[i.reason] || i.reason || '—'),
                i.automatable && h('span', { class: 'cqa-pill cqa-pill--green' }, icon('spark', 12), 'Бот справится'),
                h('b', { class: 'cqa-num' }, i.conversation_id),
                h('span', { class: 'cqa-muted' }, i.language),
                h('span', { class: 'cqa-ap-date cqa-num' }, i.wait_s != null ? `ждал ${mmss(i.wait_s)}` : '', i.total != null && [' · ', h('b', null, fmt(i.total))])),
              h('dl', { class: 'cqa-qa' },
                i.question && [h('dt', null, 'Клиент'), h('dd', null, i.question)],
                i.bot_answer && [h('dt', null, 'Бот'), h('dd', null, i.bot_answer)],
                i.operator_answer && [h('dt', null, 'Оператор'), h('dd', null, i.operator_answer)],
                i.suggested_bot_answer && [h('dt', { class: 'is-new' }, 'Бот мог бы'), h('dd', { class: 'is-new' }, i.suggested_bot_answer)]),
              i.bot_gap && h('p', { class: 'cqa-muted' }, icon('spark', 12), ' ', i.bot_gap)))),
          ],
    );

    const job = d.job || {};
    fill(L.side, h('div', { class: 'cqa-side-inner' },
      sideBlock('Сводка', h('div', { class: 'cqa-stats' },
        stat('С ботом', d.with_bot, `из ${d.dialogs}`),
        stat('Передано людям', d.escalated, pct(d.escalated, d.with_bot)),
        stat('Ожидание оператора', d.avg_wait_s == null ? '—' : mmss(d.avg_wait_s), d.median_wait_s == null ? null : `медиана ${mmss(d.median_wait_s)}`),
        stat('Бот справился бы', llm ? d.automatable : '—', llm ? pct(d.automatable, d.llm_analysed) : 'после разбора LLM'))),
      sideBlock('Разбор LLM',
        !job.available
          ? h('p', { class: 'cqa-hintbox' }, icon('spark', 14), 'Добавьте OPENAI_API_KEY в backend/.env и перезапустите бэкенд. Персональные данные маскируются перед отправкой.')
          : job.running
            ? h('div', { class: 'cqa-progress' },
                h('span', null, icon('refresh', 14, 'cqa-spin'), ` ${job.done} из ${job.total}`),
                h('span', { class: 'cqa-progress-bar' }, h('i', { style: { width: `${job.total ? (job.done / job.total) * 100 : 0}%` } })))
            : [
                h('button', { class: 'cqa-btn cqa-btn--primary cqa-btn--sm', onclick: () => analyze(false) }, icon('spark', 14),
                  d.llm_analysed < d.escalated ? `Разобрать ${d.escalated - d.llm_analysed}` : 'Всё разобрано'),
                d.llm_analysed > 0 && h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', onclick: () => analyze(true) }, icon('refresh', 14), 'Разобрать заново'),
              ],
        job.available && h('p', { class: 'cqa-muted' }, `Модель ${job.model}. Тема, причина, чего не хватило боту и черновик ответа для него.`, job.cost_usd ? [' ', h('span', null, `Потрачено $${job.cost_usd.toFixed(4)}.`)] : null)),
      sideBlock('База знаний для бота',
        h('p', { class: 'cqa-muted' }, 'Пары «вопрос клиента → ответ» в JSONL: черновики LLM и ответы операторов с итогом от 80. Персональные данные скрыты.'),
        api.knowledgeUrl() && h('a', { class: 'cqa-btn cqa-btn--outline cqa-btn--sm', href: api.knowledgeUrl(), download: 'bot-knowledge.jsonl' }, icon('layers', 14), 'Скачать JSONL')),
    ));
  }

  await load();
  render();
  poll();
  return { setRole() {}, destroy() { S.destroyed = true; clearTimeout(S.timer); } };
}
