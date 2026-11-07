// Редактор чек-листа: критерии, веса, типы, шкалы, N/A, версии.
import { api } from '../api.js';
import { validateChecklist, fmt } from '../scoring.js';
import { h, fill, toast } from '../util.js';
import { icon } from '../icons.js';
import { pageLayout, pageHead, segmented, field, input, textarea, toggle, sideBlock, download, pickFile } from '../ui.js';

const SEC_COLOR = ['#7d8dee', '#1ccc9e', '#ffa700', '#ee5555', '#13ad64', '#5f6d80'];
const TYPES = [
  { value: 'binary', label: 'Да / Нет' },
  { value: 'scale', label: 'Шкала' },
  { value: 'flag', label: 'Флаг', hint: 'Грубое нарушение: без баллов, отмечается отдельно' },
];
const clone = x => JSON.parse(JSON.stringify(x));
const nid = p => `${p}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;

export async function mountChecklist(root) {
  const S = { saved: null, draft: null, versions: [], open: null, saving: false, showErrors: false };
  const L = pageLayout();
  fill(root, L.el);
  fill(L.main, h('div', { class: 'cqa-loading' }, icon('refresh', 16, 'cqa-spin'), 'Загружаем чек-лист…'));

  async function load() {
    [S.saved, S.versions] = await Promise.all([api.getActiveChecklist(), api.listChecklistVersions()]);
    S.draft = clone(S.saved);
  }
  const dirty = () => JSON.stringify(S.draft) !== JSON.stringify(S.saved);
  const secColor = sid => SEC_COLOR[Math.max(0, S.draft.sections.findIndex(s => s.id === sid)) % SEC_COLOR.length];
  const errs = () => validateChecklist(S.draft);
  const errFor = (id, f) => S.showErrors ? errs().find(e => e.id === id && e.field === f)?.msg : null;

  function renumber() {
    let n = 1;
    for (const sec of S.draft.sections) for (const c of S.draft.criteria.filter(c => c.section === sec.id)) c.code = String(n++).padStart(2, '0');
    // критерии держим в порядке секций
    S.draft.criteria.sort((a, b) => Number(a.code) - Number(b.code));
  }
  const change = (structural = false) => { if (structural) { renumber(); renderMain(); } renderSide(); };

  // ---------- основная колонка ----------
  function renderMain() {
    const cl = S.draft;
    fill(L.main,
      pageHead({
        title: 'Чек-лист', count: `v${S.saved.version}`,
        sub: 'Критерии собираются в промпт модели. Новый или изменённый критерий применяется после сохранения и переоценки.',
      }),
      h('div', { class: 'cqa-cl-meta' },
        field('Название', input({ id: 'cqa-cl-name', value: cl.name, oninput: e => { cl.name = e.target.value; change(); } }), { id: 'cqa-cl-name', error: S.showErrors && !cl.name.trim() ? 'Укажите название.' : null }),
        field('Общие правила для модели', textarea({
          id: 'cqa-cl-notes', rows: 4, value: (cl.rules?.notes || []).join('\n'),
          oninput: e => { cl.rules = { ...cl.rules, notes: e.target.value.split('\n').map(s => s.trim()).filter(Boolean) }; change(); },
        }), { id: 'cqa-cl-notes', hint: 'По одному правилу в строке. Например: «Общий вопрос о тарифах не требует идентификации».' })),

      cl.sections.map(sec => {
        const list = cl.criteria.filter(c => c.section === sec.id);
        const w = list.filter(c => c.type !== 'flag').reduce((a, c) => a + (Number(c.weight) || 0), 0);
        return h('section', { class: 'cqa-cl-sec', style: { '--c': secColor(sec.id) } },
          h('div', { class: 'cqa-cl-sec-head' },
            h('i', { class: 'cqa-dot' }),
            input({ class: 'cqa-input cqa-input--title', value: sec.name, 'aria-label': 'Название секции', oninput: e => { sec.name = e.target.value; change(); } }),
            h('span', { class: 'cqa-muted cqa-num' }, w ? `вес ${w}` : ''),
            h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm', onclick: () => addCriterion(sec.id) }, icon('spark', 14), 'Критерий'),
            !list.length && cl.sections.length > 1 && h('button', { class: 'cqa-iconbtn cqa-iconbtn--plain', title: 'Удалить пустую секцию', onclick: () => { cl.sections = cl.sections.filter(s => s.id !== sec.id); change(true); } }, icon('x', 14))),
          h('div', { class: 'cqa-cl-list' },
            list.length ? list.map(c => critEditor(c)) : h('p', { class: 'cqa-muted cqa-cl-empty' }, 'В секции нет критериев.')));
      }),
      h('button', { class: 'cqa-btn cqa-btn--outline cqa-btn--sm', onclick: () => { cl.sections.push({ id: nid('s'), name: 'Новая секция' }); change(true); } }, icon('layers', 14), 'Добавить секцию'),
    );
  }

  function addCriterion(section) {
    const c = { id: nid('c'), code: '', section, name: 'Новый критерий', type: 'binary', weight: 0, na_allowed: false, description: '' };
    S.draft.criteria.push(c);
    S.open = c.id;
    change(true);
    requestAnimationFrame(() => L.main.querySelector(`[data-edit="${c.id}"] input`)?.select());
  }

  function critEditor(c) {
    const open = S.open === c.id;
    const hasErr = S.showErrors && errs().some(e => e.id === c.id);
    const meta = [
      c.type === 'flag' ? 'Флаг · без баллов' : `${c.type === 'scale' ? `Шкала 0–${Math.max(0, ...(c.scale || []).map(s => Number(s.value) || 0))}` : 'Да / Нет'}${c.na_allowed ? ' / N/A' : ''}`,
    ];
    const row = h('button', { class: 'cqa-crit-row', type: 'button', 'aria-expanded': String(open), onclick: () => { S.open = open ? null : c.id; renderMain(); } },
      h('span', { class: 'cqa-code cqa-num' }, c.code),
      h('span', { class: 'cqa-crit-name' }, c.name || 'Без названия'),
      hasErr && h('span', { class: 'cqa-pill cqa-pill--red' }, icon('alert', 12), 'ошибка'),
      h('span', { class: 'cqa-muted' }, meta),
      h('span', { class: 'cqa-crit-pts cqa-num' }, c.type === 'flag' ? '—' : c.weight || 0));
    if (!open) return h('article', { class: 'cqa-crit', 'data-edit': c.id, style: { '--c': secColor(c.section) } }, row);

    const id = k => `cqa-${c.id}-${k}`;
    const cl = S.draft;
    const idx = cl.criteria.indexOf(c);
    const sameSec = cl.criteria.filter(x => x.section === c.section);
    const pos = sameSec.indexOf(c);
    const move = d => {
      const other = sameSec[pos + d];
      if (!other) return;
      const j = cl.criteria.indexOf(other);
      [cl.criteria[idx], cl.criteria[j]] = [cl.criteria[j], cl.criteria[idx]];
      [c.code, other.code] = [other.code, c.code];
      change(true);
    };

    return h('article', { class: 'cqa-crit is-open cqa-cl-edit', 'data-edit': c.id, style: { '--c': secColor(c.section) } },
      h('div', { class: 'cqa-crit-kicker' }, h('i', { class: 'cqa-dot' }), h('span', null, `Критерий ${c.code}`),
        h('button', { class: 'cqa-iconbtn cqa-iconbtn--plain', title: 'Выше', disabled: pos === 0, onclick: () => move(-1) }, icon('chevronLeft', 14, 'cqa-rot90')),
        h('button', { class: 'cqa-iconbtn cqa-iconbtn--plain', title: 'Ниже', disabled: pos === sameSec.length - 1, onclick: () => move(1) }, icon('chevronRight', 14, 'cqa-rot90')),
        h('button', { class: 'cqa-iconbtn cqa-iconbtn--plain', title: 'Свернуть', onclick: () => { S.open = null; renderMain(); } }, icon('x', 14))),
      h('div', { class: 'cqa-form-grid' },
        field('Название', input({ id: id('name'), value: c.name, oninput: e => { c.name = e.target.value; change(); } }), { id: id('name'), error: errFor(c.id, 'name') }),
        field('Секция', h('select', { class: 'cqa-input', id: id('sec'), onchange: e => { c.section = e.target.value; change(true); } },
          cl.sections.map(s => h('option', { value: s.id, selected: s.id === c.section }, s.name))), { id: id('sec') })),
      field('Тип ответа', segmented(TYPES, c.type, v => {
        c.type = v;
        if (v === 'scale' && !c.scale?.length) c.scale = [{ value: 10, label: 'Полностью выполнено' }, { value: 5, label: 'Частично' }, { value: 0, label: 'Не выполнено' }];
        if (v === 'flag') { c.weight = 0; c.na_allowed = false; }
        change(true);
      }, 'Тип ответа')),
      c.type !== 'flag' && h('div', { class: 'cqa-form-grid' },
        field('Вес', input({ id: id('w'), type: 'number', min: 0, step: 1, value: c.weight, oninput: e => { c.weight = Number(e.target.value); change(); renderRowPts(c); } }),
          { id: id('w'), error: errFor(c.id, 'weight'), hint: 'Сумма весов всех критериев = 100' }),
        h('div', { class: 'cqa-field cqa-field--toggle' }, toggle({ id: id('na'), checked: c.na_allowed, label: 'Можно поставить N/A', onChange: v => { c.na_allowed = v; change(true); } }))),
      c.na_allowed && field('Когда ставить N/A', textarea({ id: id('nac'), rows: 2, value: c.na_condition || '', placeholder: 'Например: запрос не требовал идентификации.', oninput: e => { c.na_condition = e.target.value; change(); } }),
        { id: id('nac'), error: errFor(c.id, 'na_condition'), hint: 'Вес N/A перераспределяется между остальными критериями.' }),
      field('Правило оценки', textarea({ id: id('d'), rows: 3, value: c.description || '', placeholder: 'Да — оператор поздоровался на языке клиента и представился в первом ответе.', oninput: e => { c.description = e.target.value; change(); } }),
        { id: id('d'), error: errFor(c.id, 'description'), hint: 'Этот текст модель получает дословно.' }),
      c.type === 'scale' && field('Ступени шкалы', h('div', { class: 'cqa-scale-ed' },
        (c.scale || []).map((s, k) => h('div', { class: 'cqa-scale-row' },
          input({ type: 'number', min: 0, step: 1, class: 'cqa-input cqa-input--num', value: s.value, 'aria-label': 'Баллы ступени', oninput: e => { s.value = Number(e.target.value); change(); } }),
          input({ value: s.label, placeholder: 'Что означает эта ступень', 'aria-label': 'Описание ступени', oninput: e => { s.label = e.target.value; change(); } }),
          h('button', { class: 'cqa-iconbtn cqa-iconbtn--plain', title: 'Удалить ступень', disabled: c.scale.length <= 2, onclick: () => { c.scale.splice(k, 1); change(true); } }, icon('x', 14)))),
        h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', onclick: () => { c.scale.push({ value: 0, label: '' }); change(true); } }, icon('spark', 14), 'Добавить ступень')),
      { error: errFor(c.id, 'scale'), hint: 'Верхняя ступень даёт полный вес критерия.' }),
      h('div', { class: 'cqa-row cqa-row--end' },
        h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--danger', onclick: () => { cl.criteria = cl.criteria.filter(x => x !== c); S.open = null; change(true); } }, icon('x', 14), 'Удалить критерий')),
    );
  }
  function renderRowPts() { /* вес виден в правой панели; строку перерисуем при сворачивании */ }

  // ---------- правая панель ----------
  function renderSide() {
    const cl = S.draft;
    const scored = cl.criteria.filter(c => c.type !== 'flag');
    const sum = scored.reduce((a, c) => a + (Number(c.weight) || 0), 0);
    const ok = Math.abs(sum - 100) < 0.001;
    const E = errs();
    const isDirty = dirty();

    fill(L.side, h('div', { class: 'cqa-side-inner' },
      h('div', { class: 'cqa-overall' },
        h('span', { class: 'cqa-overall-label' }, 'Сумма весов', h('span', { class: ok ? 'cqa-ok' : 'cqa-bad' }, ok ? 'ровно 100' : sum > 100 ? `лишние ${fmt(sum - 100, 0)}` : `не хватает ${fmt(100 - sum, 0)}`)),
        h('span', { class: `cqa-total ${ok ? '' : 'is-bad'}` }, fmt(sum, 0), h('small', null, ' / 100'))),
      h('div', { class: 'cqa-bar cqa-bar--weights', role: 'img', 'aria-label': 'Веса критериев' },
        scored.map(c => h('button', {
          class: 'cqa-seg', style: { flex: `${Math.max(0.5, Number(c.weight) || 0)} 1 0`, '--c': secColor(c.section) }, title: `${c.code} ${c.name}: ${c.weight}`,
          onclick: () => { S.open = c.id; renderMain(); L.main.querySelector(`[data-edit="${c.id}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }); },
        }, h('i', { style: { width: '100%', background: 'var(--c)' } }))),
        sum < 100 && h('span', { class: 'cqa-seg cqa-seg--gap', style: { flex: `${100 - sum} 1 0` }, title: `Не распределено: ${100 - sum}` })),

      !ok && scored.length > 1 && h('button', { class: 'cqa-btn cqa-btn--outline cqa-btn--block', onclick: rebalance, title: 'Вес открытого критерия не меняется, остальные пересчитываются пропорционально' },
        icon('refresh', 16), S.open && scored.some(c => c.id === S.open) ? 'Распределить остальные до 100' : 'Распределить до 100'),
      h('button', { class: 'cqa-btn cqa-btn--primary cqa-btn--block', disabled: S.saving || !isDirty, onclick: save },
        icon(S.saving ? 'refresh' : 'check', 16, S.saving ? 'cqa-spin' : ''), isDirty ? `Сохранить как v${S.versions[S.versions.length - 1]?.version + 1}` : 'Изменений нет'),
      isDirty && h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', onclick: () => { S.draft = clone(S.saved); S.showErrors = false; S.open = null; renderMain(); renderSide(); } }, icon('x', 14), 'Отменить изменения'),

      S.showErrors && E.length > 0 && h('div', { class: 'cqa-errbox', role: 'alert' },
        h('b', null, icon('alert', 14), `Исправьте ${E.length} ${E.length === 1 ? 'ошибку' : 'ошибки'}`),
        E.slice(0, 6).map(e => h('button', { onclick: () => { if (e.id) { S.open = e.id; renderMain(); L.main.querySelector(`[data-edit="${e.id}"]`)?.scrollIntoView({ block: 'center' }); } } }, e.msg))),

      sideBlock('Состав',
        h('div', { class: 'cqa-stats' },
          h('div', { class: 'cqa-stat' }, h('span', { class: 'cqa-stat-label' }, 'Критериев'), h('b', { class: 'cqa-num' }, cl.criteria.length)),
          h('div', { class: 'cqa-stat' }, h('span', { class: 'cqa-stat-label' }, 'С N/A'), h('b', { class: 'cqa-num' }, cl.criteria.filter(c => c.na_allowed).length)),
          h('div', { class: 'cqa-stat' }, h('span', { class: 'cqa-stat-label' }, 'Шкальных'), h('b', { class: 'cqa-num' }, cl.criteria.filter(c => c.type === 'scale').length)),
          h('div', { class: 'cqa-stat' }, h('span', { class: 'cqa-stat-label' }, 'Флагов'), h('b', { class: 'cqa-num' }, cl.criteria.filter(c => c.type === 'flag').length)))),

      sideBlock('Файл',
        h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', onclick: () => download(`checklist-v${S.saved.version}.json`, JSON.stringify(S.draft, null, 2)) }, icon('external', 14), 'Экспорт JSON'),
        h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', onclick: importJson }, icon('layers', 14), 'Импорт JSON в черновик'),
        h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm cqa-btn--left', onclick: resetDefault }, icon('refresh', 14), 'Вернуть исходный из PDF')),

      sideBlock('Версии',
        h('ol', { class: 'cqa-versions' }, [...S.versions].reverse().map(v => h('li', { class: v.version === S.saved.version ? 'is-current' : '' },
          h('b', { class: 'cqa-num' }, `v${v.version}`),
          h('span', null, v.updated_at ? new Date(v.updated_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : 'исходный'),
          h('span', { class: 'cqa-muted cqa-num' }, `${v.criteria} крит.`))))),
    ));
  }

  // Scale the other weights so the scored criteria add up to exactly 100 (whole numbers,
  // largest remainder), keeping the weight of the criterion being edited.
  function rebalance() {
    const scored = S.draft.criteria.filter(c => c.type !== 'flag');
    const fixed = scored.find(c => c.id === S.open);
    const others = scored.filter(c => c !== fixed);
    const target = 100 - (fixed ? Math.round(Number(fixed.weight) || 0) : 0);
    const base = others.reduce((a, c) => a + (Number(c.weight) || 0), 0);
    if (fixed) fixed.weight = Math.round(Number(fixed.weight) || 0);
    if (!others.length || target < others.length || base <= 0) {
      toast(target < others.length ? 'Вес открытого критерия слишком большой: остальным не хватит баллов' : 'Сначала задайте веса', { icon: icon('alert', 16) });
      return;
    }
    const raw = others.map(c => ((Number(c.weight) || 0) * target) / base);
    const out = raw.map(r => Math.max(1, Math.floor(r)));
    let rest = target - out.reduce((a, b) => a + b, 0);
    const order = raw.map((r, i) => [r - Math.floor(r), i]).sort((a, b) => b[0] - a[0]).map(x => x[1]);
    for (let k = 0; rest > 0; k = (k + 1) % order.length, rest--) out[order[k]]++;
    for (let k = 0; rest < 0; k = (k + 1) % order.length) if (out[order[order.length - 1 - k]] > 1) { out[order[order.length - 1 - k]]--; rest++; }
    others.forEach((c, i) => { c.weight = out[i]; });
    renderMain(); renderSide();
    toast('Веса распределены: сумма 100', { icon: icon('check', 16) });
  }

  async function save() {
    S.showErrors = true;
    if (errs().length) { renderMain(); renderSide(); toast('Чек-лист не сохранён: есть ошибки', { icon: icon('alert', 16) }); return; }
    S.saving = true; renderSide();
    try {
      const saved = await api.saveChecklist(S.draft);
      S.versions = await api.listChecklistVersions();
      S.saved = saved; S.draft = clone(saved); S.showErrors = false;
      toast(`Сохранено как v${saved.version}. Переоцените диалоги на странице «Диалоги».`, { icon: icon('check', 16) });
    } catch (e) { toast(`Не сохранилось: ${e.message}`, { icon: icon('alert', 16) }); }
    S.saving = false; renderMain(); renderSide();
  }

  async function importJson() {
    const file = await pickFile();
    if (!file) return;
    try {
      const j = JSON.parse(await file.text());
      if (!Array.isArray(j.criteria) || !Array.isArray(j.sections)) throw new Error('В файле нет sections[] и criteria[]');
      S.draft = { ...S.draft, ...j, version: S.saved.version };
      S.showErrors = true; S.open = null; renderMain(); renderSide();
      toast('Чек-лист загружен в черновик. Проверьте и сохраните.', { icon: icon('check', 16) });
    } catch (e) { toast(`Не удалось прочитать: ${e.message}`, { icon: icon('alert', 16) }); }
  }

  async function resetDefault() {
    if (!confirm('Создать новую версию из исходного чек-листа (PDF)? Текущие версии останутся в истории.')) return;
    S.saved = await api.resetChecklist();
    S.versions = await api.listChecklistVersions();
    S.draft = clone(S.saved); S.open = null; S.showErrors = false;
    renderMain(); renderSide();
    toast(`Исходный чек-лист восстановлен как v${S.saved.version}`, { icon: icon('check', 16) });
  }

  const onLeave = e => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } };
  addEventListener('beforeunload', onLeave);

  await load();
  renderMain(); renderSide();
  return {
    setRole() {},
    destroy() { removeEventListener('beforeunload', onLeave); },
    canLeave: () => !dirty() || confirm('Есть несохранённые изменения чек-листа. Уйти без сохранения?'),
  };
}
