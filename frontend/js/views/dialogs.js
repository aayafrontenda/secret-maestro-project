// Список диалогов: импорт набора, фильтры, массовая оценка.
import { api } from '../api.js';
import { CONFIG } from '../config.js';
import { fmt } from '../scoring.js';
import { h, fill, store, toast } from '../util.js';
import { icon } from '../icons.js';
import { pageLayout, pageHead, tabs, input, sideBlock, stat, emptyState, pickFile, segmented } from '../ui.js';
import { REVIEW, needsAction, byPriority, nextInQueue, reviewerName, setReviewerName } from '../worklist.js';

const LANG = { RU: 'RU', KZ: 'KZ', EN: 'EN' };
const ML_KIND = { cloud: 'Облако', local: 'Локальная', demo: 'Демо без модели' };
const STATUSES = ['todo', 'appeal', 'to_review', 'reviewed', 'none', 'gross', 'stale', 'all'];
const DEFAULT_F = { lang: 'all', channel: 'all', status: 'todo', q: '', sort: 'priority' };
const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function mountDialogs(root) {
  const S = {
    rows: [], active: null, error: null,
    f: { ...DEFAULT_F, ...(store('cqa.filters') || {}) },
    group: CONFIG.DEFAULT_GROUP_ID, importing: false,
    batch: null, // { total, done, failed, stop, label }
  };
  if (!STATUSES.includes(S.f.status)) S.f.status = 'todo';
  S.ml = null;
  const L = pageLayout();
  fill(root, L.el);

  async function load() {
    try {
      [S.rows, S.active, S.ml] = await Promise.all([api.listDialogs(), api.getActiveChecklist(), api.getML().catch(() => null)]);
      S.error = null;
    } catch (e) { S.error = e.message; }
  }

  const stale = r => r.evaluation === 'done' && r.checklist_version !== S.active?.version;
  const matchStatus = (r, st) =>
    st === 'all' ? true
      : st === 'todo' ? needsAction(r)
        : st === 'gross' ? r.gross_error
          : st === 'stale' ? stale(r)
            : r.review_status === st;
  function filtered() {
    const q = S.f.q.trim().toLowerCase();
    const rows = S.rows.filter(r =>
      (S.f.lang === 'all' || r.language === S.f.lang) &&
      (S.f.channel === 'all' || r.channel === S.f.channel) &&
      matchStatus(r, S.f.status) &&
      (!q || r.conversation_id.toLowerCase().includes(q)));
    return S.f.sort === 'priority' ? rows.sort(byPriority) : rows.sort((a, b) => a.conversation_id.localeCompare(b.conversation_id));
  }
  const setF = (k, v) => { S.f[k] = v; store('cqa.filters', S.f); renderMain(); renderSide(); };

  // ---------- основная колонка ----------
  const listEl = h('div', { class: 'cqa-table', role: 'table', 'aria-label': 'Диалоги' });
  function renderMain() {
    const rows = filtered();
    const cnt = fn => S.rows.filter(fn).length;
    fill(L.main,
      pageHead({ title: 'Диалоги', count: S.rows.length, sub: `Чек-лист «${S.active?.name ?? ''}» · v${S.active?.version ?? '—'}. Откройте диалог, чтобы увидеть оценку, доказательства и апелляции.` }),
      h('div', { class: 'cqa-filters' },
        tabs([{ value: 'all', label: 'Все' }, ...['RU', 'KZ', 'EN'].map(l => ({ value: l, label: LANG[l], count: cnt(r => r.language === l) }))], S.f.lang, v => setF('lang', v), 'Язык'),
        tabs([{ value: 'all', label: 'Все каналы' }, { value: 'agent chat', label: 'Чаты', count: cnt(r => r.channel === 'agent chat') }, { value: 'voice call', label: 'Звонки', count: cnt(r => r.channel === 'voice call') }], S.f.channel, v => setF('channel', v), 'Канал'),
        tabs([
          { value: 'todo', label: 'Мне проверить', count: cnt(needsAction) },
          { value: 'appeal', label: 'Апелляции', count: cnt(r => r.review_status === 'appeal') },
          { value: 'to_review', label: 'Ждут проверки', count: cnt(r => r.review_status === 'to_review') },
          { value: 'reviewed', label: 'Проверены', count: cnt(r => r.review_status === 'reviewed') },
          { value: 'none', label: 'Не оценены', count: cnt(r => r.review_status === 'none') },
          { value: 'gross', label: 'Грубые ошибки', count: cnt(r => r.gross_error) },
          { value: 'stale', label: 'Старая версия', count: cnt(stale) },
          { value: 'all', label: 'Все', count: S.rows.length },
        ].filter(o => ['todo', 'all'].includes(o.value) || o.count > 0 || S.f.status === o.value), S.f.status, v => setF('status', v), 'Статус проверки'),
        segmented([{ value: 'priority', label: 'По приоритету', hint: 'Апелляции, грубые ошибки, затем низкий итог' }, { value: 'id', label: 'По ID' }], S.f.sort, v => setF('sort', v), 'Сортировка'),
        h('div', { class: 'cqa-search' }, icon('scan', 16),
          input({ placeholder: 'Поиск по ID', value: S.f.q, 'aria-label': 'Поиск по ID', oninput: e => { S.f.q = e.target.value; store('cqa.filters', S.f); renderTable(); renderSide(); } })),
      ),
      S.error ? h('div', { class: 'cqa-error' }, `Не удалось загрузить диалоги: ${S.error}`) : listEl,
    );
    renderTable();
  }

  function renderTable() {
    const rows = filtered();
    if (!S.rows.length) {
      fill(listEl, emptyState('Диалогов пока нет', 'Импортируйте набор по group_id или загрузите JSON-файл справа.'));
      return;
    }
    fill(listEl,
      h('div', { class: 'cqa-tr cqa-tr--head', role: 'row' },
        ['ID', 'Канал', 'Язык', 'Реплик', 'Итог', 'Статус'].map((t, i) => h('span', { role: 'columnheader', class: `cqa-td cqa-td--${i}` }, t)),
        h('span', { class: 'cqa-td cqa-td--go' })),
      rows.length === 0 && h('div', { class: 'cqa-table-empty' }, 'Под фильтры ничего не подходит. ',
        S.f.status === 'todo' && !S.f.q && S.f.lang === 'all' && S.f.channel === 'all'
          ? 'Всё проверено: открытых апелляций и непроверенных оценок нет. '
          : null,
        h('button', { class: 'cqa-link', onclick: () => { S.f = { ...DEFAULT_F, status: 'all' }; store('cqa.filters', S.f); renderMain(); renderSide(); } }, 'Показать все диалоги')),
      rows.map(r => {
        const st = r.review_status;
        const rv = REVIEW[st];
        const running = S.batch?.current?.has(r.conversation_id);
        return h('a', { class: `cqa-tr ${running ? 'is-running' : ''} ${st === 'reviewed' ? 'is-done' : ''}`, role: 'row', href: `#/dialogs/${encodeURIComponent(r.conversation_id)}` },
          h('span', { class: 'cqa-td cqa-td--0 cqa-num' }, h('b', null, r.conversation_id)),
          h('span', { class: 'cqa-td cqa-td--1' }, icon(r.channel === 'voice call' ? 'headphones' : 'chat', 15), r.channel === 'voice call' ? 'Звонок' : 'Чат'),
          h('span', { class: 'cqa-td cqa-td--2' }, h('span', { class: 'cqa-lang' }, r.language)),
          h('span', { class: 'cqa-td cqa-td--3 cqa-num' }, r.turns),
          h('span', { class: 'cqa-td cqa-td--4' },
            r.total == null
              ? h('span', { class: 'cqa-muted' }, running ? 'оцениваем…' : '—')
              : [h('b', { class: 'cqa-num' }, fmt(r.total)), h('span', { class: 'cqa-minibar' }, h('i', { style: { width: `${r.total}%` } }))]),
          h('span', { class: 'cqa-td cqa-td--5' },
            r.gross_error && h('span', { class: 'cqa-pill cqa-pill--red' }, icon('alert', 12), 'грубая'),
            st === 'none'
              ? !running && h('span', { class: 'cqa-muted' }, 'не оценён')
              : h('span', {
                  class: `cqa-pill ${rv.pill}`,
                  title: st === 'reviewed' ? [r.reviewed_by, r.reviewed_at && new Date(r.reviewed_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })].filter(Boolean).join(' · ') : null,
                }, rv.icon && icon(rv.icon, 12), st === 'appeal' ? `${rv.label} · ${r.appeals_open}` : rv.label),
            stale(r) && h('span', { class: 'cqa-pill', title: `Оценено по v${r.checklist_version}, активна v${S.active?.version}` }, `v${r.checklist_version}`)),
          h('span', { class: 'cqa-td cqa-td--go' }, icon('chevronRight', 16)));
      }));
  }

  // ---------- правая панель ----------
  function renderSide() {
    const done = S.rows.filter(r => r.evaluation === 'done');
    const totals = done.map(r => r.total).filter(x => x != null);
    const avg = totals.length ? totals.reduce((a, b) => a + b, 0) / totals.length : null;
    const notDone = S.rows.filter(r => r.evaluation === 'none');
    const staleRows = S.rows.filter(stale);
    const visible = filtered();
    const b = S.batch;

    const groupInput = input({ value: S.group, 'aria-label': 'group_id', placeholder: 'group_id', oninput: e => { S.group = e.target.value; }, onkeydown: e => e.key === 'Enter' && doImport() });

    const todo = S.rows.filter(needsAction);
    const evaluated = S.rows.filter(r => r.review_status !== 'none');
    const reviewed = S.rows.filter(r => r.review_status === 'reviewed');
    const first = nextInQueue(S.rows, null);
    const nameInput = input({ value: reviewerName(), placeholder: 'Ваше имя', 'aria-label': 'Имя проверяющего', onchange: e => setReviewerName(e.target.value) });

    fill(L.side, h('div', { class: 'cqa-side-inner' },
      sideBlock('Моя очередь',
        h('div', { class: 'cqa-stats' },
          stat('Мне проверить', todo.length, `апелляций: ${todo.filter(r => r.review_status === 'appeal').length}`),
          stat('Проверено', `${reviewed.length} / ${evaluated.length}`)),
        evaluated.length > 0 && h('div', { class: 'cqa-progress-bar' }, h('i', { style: { width: `${(reviewed.length / evaluated.length) * 100}%` } })),
        h('button', { class: 'cqa-btn cqa-btn--primary cqa-btn--block', disabled: !first, onclick: () => { location.hash = `#/dialogs/${encodeURIComponent(first)}`; } },
          icon(first ? 'arrowRight' : 'check', 16), first ? 'Начать проверку' : 'Очередь пуста'),
        h('p', { class: 'cqa-muted' }, 'Сначала апелляции, потом грубые ошибки, потом самые низкие баллы. В карточке нажмите «Проверено → следующий».'),
        h('label', { class: 'cqa-label' }, 'Проверяющий'), nameInput),

      S.ml && S.ml.providers.length > 1 && sideBlock('Модель оценки',
        h('div', { class: 'cqa-ml-list', role: 'radiogroup', 'aria-label': 'Модель оценки' }, S.ml.providers.map(p => h('button', {
          class: `cqa-ml ${p.active ? 'is-active' : ''}`, role: 'radio', 'aria-checked': String(p.active), disabled: !!S.batch,
          onclick: async () => {
            if (p.active) return;
            if (!p.reachable) { toast('Модель не отвечает: проверьте, что сервис запущен', { icon: icon('alert', 16) }); return; }
            try { S.ml = await api.setML(p.id); renderSide(); toast(`Новые оценки: ${ML_KIND[p.kind]}${p.model ? ` · ${p.model}` : ''}`, { icon: icon('check', 16) }); }
            catch (e) { toast(e.message, { icon: icon('alert', 16) }); }
          },
        },
          h('i', { class: `cqa-ml-dot ${p.reachable ? 'is-ok' : 'is-bad'}`, title: p.reachable ? 'доступна' : 'не отвечает' }),
          // the ML service (questions + rules) is marked, so two cloud entries are not confused
          h('span', { class: 'cqa-ml-name' }, ML_KIND[p.kind] || p.kind, p.id === 'http' && h('small', { class: 'cqa-ml-via' }, 'сервис ML')),
          h('span', { class: 'cqa-ml-model', title: p.model || null }, p.model || ''),
        ))),
        h('p', { class: 'cqa-muted' }, 'Переключает модель для новых оценок без перезапуска. Готовые оценки хранят свою модель — их можно сравнить.')),

      sideBlock('Данные',
        h('div', { class: 'cqa-inline' }, groupInput,
          h('button', { class: 'cqa-btn cqa-btn--outline cqa-btn--sm', disabled: S.importing, onclick: doImport }, icon(S.importing ? 'refresh' : 'arrowRight', 14, S.importing ? 'cqa-spin' : ''), 'Импорт')),
        h('p', { class: 'cqa-muted' }, 'Набор у организаторов по group_id. Для контроля введите выданный id.'),
        h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', onclick: doUpload }, icon('layers', 14), 'Загрузить JSON-файл')),

      sideBlock('Оценка',
        b
          ? h('div', { class: 'cqa-progress' },
              h('div', { class: 'cqa-progress-top' }, h('span', null, b.label), h('b', { class: 'cqa-num' }, `${b.done} / ${b.total}`)),
              h('div', { class: 'cqa-progress-bar' }, h('i', { style: { width: `${(b.done / b.total) * 100}%` } })),
              b.failed > 0 && h('span', { class: 'cqa-err' }, `Ошибок: ${b.failed}`),
              h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm', disabled: b.stop, onclick: () => { b.stop = true; renderSide(); } }, icon('x', 14), b.stop ? 'Останавливаем…' : 'Остановить'))
          : [
              h('button', { class: 'cqa-btn cqa-btn--primary cqa-btn--block', disabled: !notDone.length, onclick: () => runBatch(notDone, 'Оцениваем новые') },
                icon('spark', 16), notDone.length ? `Оценить новые · ${notDone.length}` : 'Все диалоги оценены'),
              staleRows.length > 0 && h('button', { class: 'cqa-btn cqa-btn--outline cqa-btn--block', onclick: () => runBatch(staleRows, `Переоцениваем по v${S.active.version}`) },
                icon('refresh', 16), `Переоценить по v${S.active.version} · ${staleRows.length}`),
              h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', disabled: !visible.length, onclick: () => runBatch(visible, 'Переоцениваем выбранные') },
                icon('refresh', 14), `Переоценить по фильтру · ${visible.length}`),
            ]),

      sideBlock('Сводка',
        h('div', { class: 'cqa-stats' },
          stat('Оценено', `${done.length} / ${S.rows.length}`),
          stat('Средний итог', avg == null ? '—' : fmt(avg)),
          stat('Грубые ошибки', S.rows.filter(r => r.gross_error).length),
          stat('Апелляции', S.rows.reduce((a, r) => a + r.appeals_open, 0), 'открыто'))),

      CONFIG.USE_MOCKS && h('button', {
        class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left cqa-reset',
        onclick: async () => { if (!confirm('Удалить все оценки, апелляции и версии чек-листа из мок-хранилища?')) return; await api.resetAll(); await refresh(); toast('Мок-данные сброшены', { icon: icon('check', 16) }); },
      }, icon('x', 14), 'Сбросить мок-данные'),
    ));
  }

  async function doImport() {
    if (!S.group.trim()) return;
    S.importing = true; renderSide();
    try {
      const r = await api.importDataset(S.group);
      toast(`Импортировано: ${r.imported} диалогов из ${r.group_id}`, { icon: icon('check', 16) });
      await refresh();
    } catch (e) { toast(e.message, { icon: icon('alert', 16) }); }
    S.importing = false; renderSide();
  }

  async function doUpload() {
    const file = await pickFile();
    if (!file) return;
    try {
      const r = await api.uploadDataset(JSON.parse(await file.text()), file.name.replace(/\.json$/i, '').toUpperCase());
      toast(`Загружено: ${r.imported} диалогов`, { icon: icon('check', 16) });
      await refresh();
    } catch (e) { toast(e instanceof SyntaxError ? 'Файл не похож на JSON' : e.message, { icon: icon('alert', 16) }); }
  }

  async function runBatch(rows, label) {
    if (!rows.length || S.batch) return;
    if (api.startBatch) return runServerBatch(rows, label);
    const queue = rows.map(r => r.conversation_id);
    const b = S.batch = { total: queue.length, done: 0, failed: 0, stop: false, label, current: new Set() };
    renderSide(); renderTable();
    const worker = async () => {
      while (queue.length && !b.stop) {
        const id = queue.shift();
        b.current.add(id); renderTable();
        try { await api.evaluate(id); } catch { b.failed++; }
        b.current.delete(id); b.done++;
        S.rows = await api.listDialogs();
        renderSide(); renderTable();
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    const stopped = b.stop;
    S.batch = null;
    await refresh();
    toast(stopped ? `Остановлено: оценено ${b.done} из ${b.total}` : `Готово: оценено ${b.done}${b.failed ? `, ошибок ${b.failed}` : ''}`, { icon: icon('check', 16) });
  }

  // Массовая оценка на бэке: очередь живёт на сервере, страница только следит за прогрессом.
  // id батча храним в localStorage — после перехода в карточку или перезагрузки слежение продолжается.
  async function runServerBatch(rows, label) {
    S.batch = { total: rows.length, done: 0, failed: 0, stop: false, label, current: new Set() };
    renderSide();
    try {
      const r = await api.startBatch(rows.map(r => r.conversation_id));
      if (!r.queued) { S.batch = null; renderSide(); toast('Нечего оценивать', { icon: icon('check', 16) }); return; }
      store('cqa.batch', { id: r.batch_id, label, total: r.queued });
      await watchBatch({ id: r.batch_id, label, total: r.queued });
    } catch (e) {
      S.batch = null; renderSide(); renderTable();
      toast(e.message, { icon: icon('alert', 16) });
    }
  }

  async function watchBatch({ id, label, total }) {
    const b = S.batch = { id, total, done: 0, failed: 0, stop: false, label, current: new Set() };
    renderSide(); renderTable();
    let cancelSent = false, st = null, lastRows = 0;
    while (!b.detached) {
      if (b.stop && !cancelSent) {
        cancelSent = true;
        try { await api.cancelBatch(id); } catch (e) { toast(e.message, { icon: icon('alert', 16) }); }
      }
      try {
        const [s, items] = await Promise.all([api.batchStatus(id), api.batchItems(id)]);
        st = s;
        b.total = s.total; b.done = s.done; b.failed = s.failed;
        b.current = new Set(items.filter(i => i.status === 'running').map(i => i.conversation_id));
        if (s.completed !== lastRows || s.finished) { lastRows = s.completed; S.rows = await api.listDialogs(); }
        if (!b.detached) { renderSide(); renderTable(); }
        if (s.finished) break;
      } catch (e) {
        if (e.status === 404) break; // батч исчез (БД пересоздали)
        // сеть моргнула — пробуем дальше
      }
      await sleep(2000);
    }
    if (b.detached) return; // ушли со страницы: бэк продолжает, вернёмся — подхватим
    store('cqa.batch', null);
    S.batch = null;
    await refresh();
    if (st) {
      const msg = st.cancelled
        ? `Остановлено: оценено ${st.completed} из ${st.total}`
        : `Готово: оценено ${st.completed}${st.failed ? `, ошибок ${st.failed}` : ''}`;
      toast(msg, { icon: icon(st.failed ? 'alert' : 'check', 16) });
    }
  }

  async function refresh() { await load(); renderMain(); renderSide(); }

  fill(L.main, h('div', { class: 'cqa-loading' }, icon('refresh', 16, 'cqa-spin'), 'Загружаем диалоги…'));
  await refresh();
  const pending = api.startBatch && store('cqa.batch');
  if (pending?.id) watchBatch(pending);

  return {
    setRole() {},
    destroy() {
      if (!S.batch) return;
      if (S.batch.id) S.batch.detached = true; // серверный батч продолжает работать
      else S.batch.stop = true;                // локальный (моки) — останавливаем
    },
  };
}
