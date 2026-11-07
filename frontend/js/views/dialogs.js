// Список диалогов: импорт набора, фильтры, массовая оценка.
import { api } from '../api.js';
import { CONFIG } from '../config.js';
import { fmt } from '../scoring.js';
import { h, fill, store, toast } from '../util.js';
import { icon } from '../icons.js';
import { pageLayout, pageHead, tabs, input, sideBlock, stat, emptyState, pickFile } from '../ui.js';

const LANG = { RU: 'RU', KZ: 'KZ', EN: 'EN' };
const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function mountDialogs(root) {
  const S = {
    rows: [], active: null, error: null,
    f: store('cqa.filters') || { lang: 'all', channel: 'all', status: 'all', q: '' },
    group: CONFIG.DEFAULT_GROUP_ID, importing: false,
    batch: null, // { total, done, failed, stop, label }
  };
  const L = pageLayout();
  fill(root, L.el);

  async function load() {
    try {
      [S.rows, S.active] = await Promise.all([api.listDialogs(), api.getActiveChecklist()]);
      S.error = null;
    } catch (e) { S.error = e.message; }
  }

  const stale = r => r.evaluation === 'done' && r.checklist_version !== S.active?.version;
  const statusOf = r => r.appeals_open ? 'appeal' : r.evaluation === 'none' ? 'none' : stale(r) ? 'stale' : 'done';
  function filtered() {
    const q = S.f.q.trim().toLowerCase();
    return S.rows.filter(r =>
      (S.f.lang === 'all' || r.language === S.f.lang) &&
      (S.f.channel === 'all' || r.channel === S.f.channel) &&
      (S.f.status === 'all' || (S.f.status === 'gross' ? r.gross_error : statusOf(r) === S.f.status)) &&
      (!q || r.conversation_id.toLowerCase().includes(q)));
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
          { value: 'all', label: 'Любой статус' },
          { value: 'none', label: 'Не оценены', count: cnt(r => statusOf(r) === 'none') },
          { value: 'done', label: 'Оценены', count: cnt(r => statusOf(r) === 'done') },
          { value: 'stale', label: 'Старая версия', count: cnt(r => statusOf(r) === 'stale') },
          { value: 'appeal', label: 'Апелляция', count: cnt(r => statusOf(r) === 'appeal') },
          { value: 'gross', label: 'Грубые ошибки', count: cnt(r => r.gross_error) },
        ].filter(o => o.value === 'all' || o.count > 0 || S.f.status === o.value), S.f.status, v => setF('status', v), 'Статус'),
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
        h('button', { class: 'cqa-link', onclick: () => { S.f = { lang: 'all', channel: 'all', status: 'all', q: '' }; store('cqa.filters', S.f); renderMain(); renderSide(); } }, 'Сбросить фильтры')),
      rows.map(r => {
        const st = statusOf(r);
        const running = S.batch?.current?.has(r.conversation_id);
        return h('a', { class: `cqa-tr ${running ? 'is-running' : ''}`, role: 'row', href: `#/dialogs/${encodeURIComponent(r.conversation_id)}` },
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
            r.appeals_open > 0 && h('span', { class: 'cqa-pill cqa-pill--amber' }, icon('gavel', 12), r.appeals_open),
            st === 'stale' && h('span', { class: 'cqa-pill' }, `v${r.checklist_version}`),
            st === 'none' && !running && h('span', { class: 'cqa-muted' }, 'не оценён')),
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

    fill(L.side, h('div', { class: 'cqa-side-inner' },
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
