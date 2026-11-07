// Карточка диалога в три колонки: транскрипт | критерии | итог.
import { api } from '../api.js';
import { computeScore, fmt, scaleMax } from '../scoring.js';
import { h, fill, offsetsOf, mmss, clockOf, SPEAKER, reducedMotion, toast } from '../util.js';
import { icon } from '../icons.js';
import { REASON } from './bot.js';
import { nextInQueue, reviewerName, setReviewerName } from '../worklist.js';

const TYPE_LABEL = { binary: 'Да / Нет', scale: 'Шкала', flag: 'Флаг · без баллов' };
const LANG = { RU: 'Русский', KZ: 'Қазақша', EN: 'English' };
// цвета секций — точки бренд-градиента
const SEC_COLOR = ['#7d8dee', '#1ccc9e', '#ffa700', '#ee5555', '#13ad64', '#5f6d80'];

export async function mountCard(root, { id, role, onNavigate, crit }) {
  const S = {
    id, role,
    dialog: null, checklist: null, evaluation: null, appeals: [], ids: [],
    pinned: null, hover: null, filter: null, evaluating: false, error: null,
    drafts: {}, decisions: {}, justLoaded: false, audio: null, offsets: [],
  };

  fill(root, h('div', { class: 'cqa-loading' }, icon('refresh', 16, 'cqa-spin'), 'Загружаем диалог…'));

  try {
    const [dialog, checklist, list] = await Promise.all([api.getDialog(id), api.getActiveChecklist(), api.listDialogs()]);
    Object.assign(S, { dialog, checklist, rows: list, ids: list.map(d => d.conversation_id), offsets: offsetsOf(dialog.transcript) });
    S.active = checklist;
    [S.evaluation, S.handoff] = await Promise.all([api.getEvaluation(id), api.getDialogHandoff(id)]);
    if (S.evaluation) {
      S.checklist = S.evaluation.checklist || checklist;
      S.appeals = await api.listAppeals({ evaluation_id: S.evaluation.evaluation_id });
      if (crit && S.checklist.criteria.some(c => c.id === crit)) S.pinned = crit;
    }
  } catch (e) {
    fill(root, h('div', { class: 'cqa-loading' }, h('div', { class: 'cqa-error' }, `Не удалось загрузить диалог: ${e.message}`)));
    return { setRole() {}, destroy() {} };
  }

  const isCall = S.dialog.channel === 'voice call';
  const secColor = sid => SEC_COLOR[Math.max(0, S.checklist.sections.findIndex(s => s.id === sid)) % SEC_COLOR.length];

  // ---------- каркас ----------
  const docEl = h('section', { class: 'cqa-doc', 'aria-label': 'Транскрипт' });
  const critEl = h('section', { class: 'cqa-crits', 'aria-label': 'Критерии' });
  const sumEl = h('aside', { class: 'cqa-sum', 'aria-label': 'Итог' });
  let scroller, msgEls = [], tickEls = [];
  const beams = svgBeams();
  fill(root, h('div', { class: 'cqa-card' }, docEl, critEl, sumEl), beams.el);

  // ---------- данные ----------
  const critById = cid => S.checklist.criteria.find(c => c.id === cid);
  const resultOf = cid => S.evaluation?.results.find(r => r.criterion_id === cid);
  const appealOf = cid => [...S.appeals].reverse().find(a => a.criterion_id === cid);
  const originalAnswers = () => Object.fromEntries((S.evaluation?.results || []).map(r => [r.criterion_id, r.answer]));
  const finalAnswers = () => {
    const a = originalAnswers();
    for (const ap of S.appeals) if (ap.status === 'changed') a[ap.criterion_id] = ap.decision.answer;
    return a;
  };
  const activeId = () => S.pinned || S.hover;
  const rerender = () => { renderCrits(); renderSum(); applyHighlights(); };

  // ---------- центр: транскрипт ----------
  function buildDoc() {
    const T = S.dialog.transcript;
    const total = S.offsets[S.offsets.length - 1] || 1;
    const i = S.ids.indexOf(S.id);
    const prev = S.ids[i - 1], next = S.ids[i + 1];

    msgEls = T.map((t, k) => {
      const time = isCall ? mmss(S.offsets[k]) : t.timestamp;
      const el = h('div', { class: `cqa-msg cqa-msg--${t.speaker}`, id: `cqa-m-${k}` },
        h('div', { class: 'cqa-msg-meta' },
          h('span', { class: 'cqa-msg-idx' }, `#${k + 1}`), h('b', null, SPEAKER[t.speaker] || t.speaker),
          h('span', { class: 'cqa-num', title: isCall ? clockOf(t.timestamp) : null }, time)),
        h('div', { class: 'cqa-bubble', 'data-idx': `#${k + 1} · ${time}` }, t.text));
      if (isCall) el.addEventListener('dblclick', () => seek(k));
      return el;
    });

    let audioBar = null;
    if (isCall) {
      tickEls = T.map((t, k) => h('button', {
        class: `cqa-tick cqa-tick--${t.speaker}`, style: { left: `${(S.offsets[k] / total) * 100}%` },
        title: `#${k + 1} · ${SPEAKER[t.speaker]} · ${mmss(S.offsets[k])}`, onclick: () => jumpTo(k),
      }));
      const playhead = h('div', { class: 'cqa-playhead', style: { display: 'none' } });
      const timeEl = h('span', { class: 'cqa-audio-time' }, `00:00 / ${mmss(total)}`);
      const playBtn = h('button', { class: 'cqa-play', disabled: true, title: 'Запись загружается…', 'aria-label': 'Воспроизвести' }, icon('play', 16));
      audioBar = h('div', { class: 'cqa-audio' }, playBtn, h('div', { class: 'cqa-timeline' }, tickEls, playhead), timeEl,
        h('a', { href: S.dialog.audio_url, target: '_blank', rel: 'noopener' }, 'Плеер', icon('external', 13)));
      api.getAudio(S.id).then(a => {
        if (!a?.url) { playBtn.title = 'Прямой mp3 отдаёт бэкенд (GET /dialogs/:id/audio). Пока — внешний плеер.'; return; }
        const audio = new Audio(a.url);
        S.audio = audio;
        // прямая SAS-ссылка не открылась — пробуем запись через бэк, затем сдаёмся на внешний плеер
        audio.onerror = () => {
          if (a.stream_url && audio.src !== a.stream_url) { audio.src = a.stream_url; return; }
          playBtn.disabled = true; playBtn.title = 'Запись недоступна — откройте внешний плеер';
        };
        playBtn.disabled = false; playBtn.title = 'Воспроизвести';
        playBtn.onclick = () => (audio.paused ? audio.play() : audio.pause());
        audio.onplay = () => fill(playBtn, icon('pause', 16));
        audio.onpause = () => fill(playBtn, icon('play', 16));
        audio.ontimeupdate = () => {
          playhead.style.display = 'block';
          playhead.style.left = `${(audio.currentTime / total) * 100}%`;
          timeEl.textContent = `${mmss(audio.currentTime)} / ${mmss(total)}`;
          let cur = 0; S.offsets.forEach((o, k) => { if (o <= audio.currentTime) cur = k; });
          msgEls.forEach((m, k) => m.classList.toggle('is-playing', k === cur));
        };
      }).catch(() => {});
    }

    scroller = h('div', { class: 'cqa-doc-scroll' },
      h('div', { class: 'cqa-doc-inner' },
        h('nav', { class: 'cqa-crumbs', 'aria-label': 'Навигация' },
          h('a', { href: '#/dialogs' }, 'Диалоги'), icon('arrowRight', 14), h('span', { class: 'cqa-here' }, S.id),
          h('div', { class: 'cqa-crumbs-nav' },
            h('button', { class: 'cqa-iconbtn', title: 'Предыдущий диалог', disabled: !prev, onclick: () => onNavigate(prev) }, icon('chevronLeft', 16)),
            h('button', { class: 'cqa-iconbtn', title: 'Следующий диалог', disabled: !next, onclick: () => onNavigate(next) }, icon('chevronRight', 16)))),
        h('h1', { class: 'cqa-title cqa-num' }, S.id),
        h('div', { class: 'cqa-chips' },
          h('span', { class: 'cqa-chip' }, icon(isCall ? 'headphones' : 'chat', 14), isCall ? 'Звонок' : 'Чат'),
          h('span', { class: 'cqa-chip' }, LANG[S.dialog.language] || S.dialog.language),
          h('span', { class: 'cqa-chip cqa-num' }, `${T.length} реплик`),
          h('span', { class: 'cqa-legend' },
            h('span', null, h('i', { class: 'is-client' }), 'клиент'),
            h('span', null, h('i', { class: 'is-operator' }), 'оператор'),
            h('span', null, h('i', { class: 'is-bot' }), 'бот · контекст'))),
        audioBar,
        h('div', { class: 'cqa-msgs' }, msgEls),
      ),
    );
    fill(docEl, scroller, h('div', { class: 'cqa-scan', 'aria-hidden': 'true' }));
  }

  function seek(k) { if (S.audio && S.offsets[k] != null) { S.audio.currentTime = S.offsets[k]; S.audio.play(); } }

  function jumpTo(k, { play = true } = {}) {
    const el = msgEls[k];
    if (!el) return;
    const sr = scroller.getBoundingClientRect(), er = el.getBoundingClientRect();
    if (scroller.scrollHeight > scroller.clientHeight + 2) {
      const top = scroller.scrollTop + (er.top - sr.top) - scroller.clientHeight / 2 + er.height / 2;
      scroller.scrollTo({ top, behavior: reducedMotion() ? 'auto' : 'smooth' });
    } else el.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'center' });
    el.classList.remove('is-flash'); void el.offsetWidth; el.classList.add('is-flash');
    if (play) seek(k);
  }

  // ---------- подсветка ----------
  function applyHighlights() {
    const r = resultOf(activeId());
    const evSet = new Set((r?.evidence || []).map(e => e.msg));
    const [a, b] = r?.checked_range || [-1, -2];
    msgEls.forEach((el, k) => {
      el.classList.toggle('is-evidence', evSet.has(k));
      el.classList.toggle('is-range', k >= a && k <= b && !evSet.has(k));
    });
    tickEls.forEach((t, k) => t.classList.toggle('is-evidence', evSet.has(k)));
    scroller?.classList.toggle('is-dimmed', !!S.pinned && !!r);
    critEl.querySelectorAll('.cqa-crit').forEach(el => el.classList.toggle('is-active', el.dataset.crit === activeId()));
    sumEl.querySelectorAll('.cqa-seg').forEach(el => el.classList.toggle('is-active', el.dataset.crit === activeId()));
    beams.schedule();
  }

  function setPinned(cid, { scroll = true } = {}) {
    S.pinned = S.pinned === cid ? null : cid;
    renderCrits(); applyHighlights();
    const r = resultOf(S.pinned);
    if (scroll && r) {
      const first = r.evidence?.[0]?.msg ?? r.checked_range?.[0];
      if (first != null) jumpTo(first, { play: false });
    }
    if (S.pinned) requestAnimationFrame(() => critEl.querySelector(`.cqa-crit[data-crit="${S.pinned}"]`)
      ?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'nearest' }));
  }

  async function runEvaluation() {
    if (S.evaluating) return;
    S.evaluating = true; S.error = null; S.pinned = null; S.hover = null;
    docEl.classList.add('is-scanning');
    rerender();
    try {
      const prevTotal = S.evaluation ? computeScore(S.checklist, finalAnswers()).total : null;
      S.evaluation = await api.evaluate(S.id);
      S.active = S.evaluation.checklist || await api.getActiveChecklist();
      S.checklist = S.active;
      S.appeals = await api.listAppeals({ evaluation_id: S.evaluation.evaluation_id });
      S.justLoaded = true;
      const t = computeScore(S.checklist, finalAnswers()).total;
      toast(prevTotal == null ? `Оценено: ${fmt(t)}` : `Переоценено: ${fmt(prevTotal)} → ${fmt(t)}`, { icon: icon('check', 16) });
    } catch (e) {
      S.error = e.message;
    } finally {
      S.evaluating = false;
      docEl.classList.remove('is-scanning');
      rerender();
      S.justLoaded = false;
    }
  }

  // ---------- bot handoff ----------
  function handoffBlock() {
    const x = S.handoff;
    if (!x?.escalated) return null;
    return h('section', { class: 'cqa-handoff', 'aria-label': 'Передача от бота' },
      h('h3', null, icon('spark', 14), 'Передача от бота', h('a', { class: 'cqa-link', href: '#/bot', style: { marginLeft: 'auto', fontWeight: 400 } }, 'все')),
      h('dl', { class: 'cqa-qa' },
        h('dt', null, 'Тема · причина'), h('dd', null, `${x.topic || 'Другое'} · ${REASON[x.reason] || '—'}`),
        x.wait_s != null && [h('dt', null, 'Оператор подключился через'), h('dd', { class: 'cqa-num' }, mmss(x.wait_s))],
        x.bot_answer && [h('dt', null, 'Бот ответил'), h('dd', null,
          x.bot_answer_index != null ? h('button', { class: 'cqa-link', onclick: () => jumpTo(x.bot_answer_index, { play: false }) }, x.bot_answer) : x.bot_answer)],
        x.bot_gap && [h('dt', null, 'Чего не хватило боту'), h('dd', null, x.bot_gap)],
        x.suggested_bot_answer && [h('dt', { class: 'is-new' }, 'Бот мог бы ответить'), h('dd', { class: 'is-new' }, x.suggested_bot_answer)]));
  }

  // ---------- review status ----------
  async function markReviewed(goNext, by, note) {
    if (by) setReviewerName(by);
    try {
      const ev = await api.markReviewed(S.evaluation.evaluation_id, { by: by || null, note: note || null });
      S.evaluation.review = ev.review;
      S.rows = await api.listDialogs();
      toast('Отмечено как проверенное', { icon: icon('check', 16) });
      const next = nextInQueue(S.rows, S.id);
      if (goNext && next) { onNavigate(next); return; }
      if (goNext) toast('Очередь пуста — всё проверено', { icon: icon('check', 16) });
      rerender();
    } catch (e) { toast(e.message, { icon: icon('alert', 16) }); }
  }

  async function unmarkReviewed() {
    try {
      const ev = await api.unmarkReviewed(S.evaluation.evaluation_id);
      S.evaluation.review = ev.review;
      S.rows = await api.listDialogs();
      rerender();
    } catch (e) { toast(e.message, { icon: icon('alert', 16) }); }
  }

  function reviewBlock() {
    const ev = S.evaluation;
    if (!ev || S.evaluating) return null;
    const isReviewer = S.role === 'reviewer';
    const open = S.appeals.filter(a => a.status === 'open').length;
    const next = nextInQueue(S.rows || [], S.id);
    const goNext = next && h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm', onclick: () => onNavigate(next) }, 'Следующий в очереди', icon('arrowRight', 14));
    const when = t => new Date(t).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });

    if (open) {
      return h('div', { class: 'cqa-review is-appeal' },
        h('div', { class: 'cqa-review-head' }, icon('gavel', 14), `Ждёт решения по апелляции · ${open}`),
        h('span', null, isReviewer ? 'Решите апелляцию в критерии — после этого диалог закроется сам.' : 'Проверяющий рассмотрит апелляцию и пересчитает итог.'));
    }
    if (ev.review) {
      return h('div', { class: 'cqa-review is-done' },
        h('div', { class: 'cqa-review-head' }, icon('check', 14), 'Проверено'),
        h('span', { class: 'cqa-review-meta' }, [ev.review.by || 'без имени', when(ev.review.reviewed_at)].join(' · ')),
        ev.review.note && h('span', null, `«${ev.review.note}»`),
        isReviewer && h('div', { class: 'cqa-review-actions' },
          h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm', onclick: unmarkReviewed }, icon('refresh', 14), 'Вернуть в работу'),
          goNext));
    }
    if (!isReviewer) {
      return h('div', { class: 'cqa-review' },
        h('div', { class: 'cqa-review-head' }, icon('flag', 14), 'Ждёт проверки'),
        h('span', { class: 'cqa-review-meta' }, 'Проверяющий ещё не смотрел эту оценку. Не согласны с критерием — оспорьте его.'));
    }
    const name = h('input', { class: 'cqa-input', placeholder: 'Ваше имя', value: reviewerName(), 'aria-label': 'Имя проверяющего' });
    const note = h('input', { class: 'cqa-input', placeholder: 'Комментарий (необязательно)', 'aria-label': 'Комментарий' });
    const go = n => markReviewed(n, name.value.trim(), note.value.trim());
    return h('div', { class: 'cqa-review' },
      h('div', { class: 'cqa-review-head' }, icon('flag', 14), 'Ждёт проверки'),
      h('span', { class: 'cqa-review-meta' }, 'Согласны с оценкой — закройте диалог. Не согласны — оспорьте критерий.'),
      !reviewerName() && name, note,
      h('div', { class: 'cqa-review-actions' },
        h('button', { class: 'cqa-btn cqa-btn--primary cqa-btn--sm', onclick: () => go(true) }, icon('check', 14), next ? 'Проверено → следующий' : 'Проверено'),
        next && h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm', onclick: () => go(false) }, 'Только отметить')));
  }

  // ---------- правая колонка: итог ----------
  function renderSum() {
    const cl = S.checklist;
    const ev = S.evaluation;
    const btn = h('button', { class: 'cqa-btn cqa-btn--primary cqa-btn--block', disabled: S.evaluating, onclick: runEvaluation },
      icon(S.evaluating ? 'refresh' : 'spark', 16, S.evaluating ? 'cqa-spin' : ''),
      S.evaluating ? 'Оцениваем…' : ev ? 'Переоценить' : 'Оценить');

    if (!ev || S.evaluating) {
      fill(sumEl, h('div', { class: 'cqa-sum-inner' },
        h('div', { class: 'cqa-overall' }, h('span', { class: 'cqa-overall-label' }, 'Итоговая оценка'), h('span', { class: 'cqa-total' }, '—')),
        btn,
        h('p', { class: 'cqa-muted' }, `Модель читает ${S.dialog.transcript.length} реплик и проверяет ${cl.criteria.length} критериев.`),
        handoffBlock()));
      return;
    }

    const orig = computeScore(cl, originalAnswers());
    const fin = computeScore(cl, finalAnswers());
    const crits = cl.criteria.filter(c => c.type !== 'flag');
    const app = crits.filter(c => !fin.rows[c.id].na);
    const openAppeals = S.appeals.filter(a => a.status === 'open');
    const counts = sid => cl.criteria.filter(c => !sid || c.section === sid).length;

    fill(sumEl, h('div', { class: 'cqa-sum-inner' },
      h('div', { class: 'cqa-overall' },
        h('span', { class: 'cqa-overall-label' }, 'Итоговая оценка',
          orig.total !== fin.total && h('span', { class: 'cqa-was' }, 'исходно ', h('s', { class: 'cqa-num' }, fmt(orig.total)))),
        h('span', { class: 'cqa-total' }, fin.total == null ? '—' : fmt(fin.total, cl.rules?.rounding ?? 2))),

      fin.total != null && h('div', { class: 'cqa-bar', role: 'img', 'aria-label': 'Вклад критериев в итог' },
        app.map(c => {
          const r = fin.rows[c.id];
          return h('button', {
            class: 'cqa-seg', 'data-crit': c.id, style: { flex: `${r.effWeight} 1 0` },
            title: `${c.code} ${c.name}: ${fmt(r.points)} из ${fmt(r.effWeight)}`,
            onmouseenter: () => { S.hover = c.id; applyHighlights(); },
            onmouseleave: () => { S.hover = null; applyHighlights(); },
            onclick: () => { S.filter = null; setPinned(c.id); },
          }, h('i', { style: { width: `${r.frac * 100}%` } }));
        })),
      fin.total == null && h('p', { class: 'cqa-muted' }, 'Нет применимых критериев с весом — итог не рассчитывается.'),

      fin.grossErrors.length
        ? h('button', { class: 'cqa-gross', onclick: () => setPinned(fin.grossErrors[0]) }, icon('alert', 18),
            h('span', null, h('b', null, 'Грубая ошибка'), resultOf(fin.grossErrors[0])?.explanation))
        : h('div', { class: 'cqa-flag-ok' }, icon('check', 14), 'Грубых ошибок нет'),

      reviewBlock(),

      ev.checklist_version !== S.active.version && h('div', { class: 'cqa-stale-box' },
        icon('layers', 16), h('span', null, `Оценено по чек-листу v${ev.checklist_version}. Активна v${S.active.version}: нажмите «Переоценить», чтобы применить новые критерии.`)),

      btn,

      h('nav', { class: 'cqa-secs', 'aria-label': 'Секции' },
        h('button', { class: 'cqa-secs-item', 'aria-pressed': String(!S.filter), onclick: () => { S.filter = null; rerender(); } },
          h('span', { class: 'cqa-secs-name' }, 'Все критерии'), h('span', { class: 'cqa-secs-val cqa-num' }, counts())),
        cl.sections.map(sec => {
          const sc = fin.sections.find(s => s.id === sec.id);
          const pct = sc && sc.max > 0 ? (sc.points / sc.max) * 100 : null;
          const grossHere = fin.grossErrors.some(g => critById(g).section === sec.id);
          return h('button', {
            class: 'cqa-secs-item', 'aria-pressed': String(S.filter === sec.id), style: { '--c': secColor(sec.id) },
            onclick: () => { S.filter = S.filter === sec.id ? null : sec.id; rerender(); },
          },
            h('span', { class: 'cqa-secs-name' }, sec.name),
            h('span', { class: 'cqa-secs-val cqa-num' }, sc ? (sc.max > 0 ? `${fmt(sc.points, 1)} / ${fmt(sc.max, 1)}` : 'N/A') : grossHere ? 'выявлены' : 'нет'),
            h('span', { class: 'cqa-secs-bar' }, h('i', { style: { width: `${pct ?? (grossHere ? 100 : 0)}%` } })));
        })),

      fin.naIds.length > 0 && h('p', { class: 'cqa-muted' },
        `N/A: ${fin.naIds.map(x => critById(x).code).join(', ')}. Их вес (${fin.naIds.reduce((a, x) => a + critById(x).weight, 0)}) перераспределён между остальными.`),

      S.role === 'reviewer' && openAppeals.length > 0 && h('div', { class: 'cqa-queue' },
        h('b', null, icon('gavel', 14), `На рассмотрении: ${openAppeals.length}`),
        openAppeals.map(a => h('button', { onclick: () => { S.filter = null; S.pinned = null; setPinned(a.criterion_id); } },
          `${critById(a.criterion_id).code} · ${critById(a.criterion_id).name}`))),

      h('dl', { class: 'cqa-facts' },
        h('dt', null, 'Модель'), h('dd', null, ev.model, ev.is_mock && h('span', { class: 'cqa-chip cqa-chip--mock' }, 'MOCK')),
        h('dt', null, 'Время'), h('dd', { class: 'cqa-num' }, ev.latency_ms == null ? '—' : `${(ev.latency_ms / 1000).toFixed(1)} с`),
        h('dt', null, 'Стоимость'), h('dd', { class: 'cqa-num' }, ev.cost_usd == null ? '—' : `$${ev.cost_usd.toFixed(4)}`),
        h('dt', null, 'Чек-лист'), h('dd', null, `v${ev.checklist_version}`,
          ev.checklist_version !== S.active.version && h('span', { class: 'cqa-stale' }, ` · активна v${S.active.version}`)),
        h('dt', null, 'Оценено'), h('dd', { class: 'cqa-num' }, new Date(ev.created_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }))),
      handoffBlock(),
    ));
  }

  // ---------- колонка критериев ----------
  function renderCrits() {
    const cl = S.checklist;
    if (S.error) {
      fill(critEl, h('div', { class: 'cqa-crits-inner' }, h('div', { class: 'cqa-error' }, `Оценка не выполнена: ${S.error}. `,
        h('button', { class: 'cqa-btn cqa-btn--sm cqa-btn--outline', onclick: runEvaluation }, 'Повторить'))));
      return;
    }
    const head = (count, label) => h('div', { class: 'cqa-crits-head' },
      h('span', { class: 'cqa-count cqa-num' }, count), h('h2', null, label),
      S.filter && h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm', onclick: () => { S.filter = null; rerender(); } }, icon('x', 14), 'Все'));

    if (S.evaluating || !S.evaluation) {
      fill(critEl, h('div', { class: 'cqa-crits-inner' },
        head(cl.criteria.length, 'Критерии'),
        h('div', { class: 'cqa-status-line' }, icon('scan', 16), 'Проверяем по чек-листу…'),
        cl.criteria.map(() => h('div', { class: 'cqa-skel' }))));
      return;
    }
    const fin = computeScore(cl, finalAnswers());
    const list = cl.criteria.filter(c => !S.filter || c.section === S.filter);
    let n = 0;
    fill(critEl, h('div', { class: 'cqa-crits-inner' },
      head(list.length, S.filter ? cl.sections.find(s => s.id === S.filter)?.name : 'Все критерии'),
      list.map(c => critCard(c, fin, S.justLoaded ? n++ : null))));
  }

  function answerText(c, a) {
    if (a === 'na') return 'N/A';
    if (c.type === 'scale') return `${a} / ${scaleMax(c)}`;
    if (c.type === 'flag') return a === 'yes' ? 'Выявлены' : 'Нет';
    return a === 'yes' ? 'Да' : 'Нет';
  }
  function answerTone(c, a) {
    if (a === 'na') return 'na';
    if (c.type === 'flag') return a === 'yes' ? 'no' : 'yes';
    if (c.type === 'scale') { const f = a / scaleMax(c); return f >= 0.99 ? 'yes' : f >= 0.5 ? 'mid' : 'no'; }
    return a;
  }
  function answerBadge(c, answer, was) {
    return h('span', { class: `cqa-ans cqa-ans--${answerTone(c, answer)}` },
      was !== undefined && was !== answer && h('s', null, answerText(c, was)), answerText(c, answer));
  }
  function optionsFor(c) {
    if (c.type === 'scale') return [...c.scale.map(s => ({ v: s.value, label: String(s.value), hint: s.label })), ...(c.na_allowed ? [{ v: 'na', label: 'N/A' }] : [])];
    return [{ v: 'yes', label: 'Да' }, { v: 'no', label: 'Нет' }, ...(c.na_allowed ? [{ v: 'na', label: 'N/A' }] : [])];
  }

  function evidenceChips(r) {
    if (!r) return [];
    const T = S.dialog.transcript;
    const go = (k, ev) => { ev.stopPropagation(); jumpTo(k); };
    const chips = (r.evidence || []).filter(e => e.msg < T.length).map(e => h('button', { class: 'cqa-ev', 'data-ev-msg': e.msg, title: 'Перейти к реплике', onclick: ev => go(e.msg, ev) },
      h('span', { class: 'cqa-ev-ref' }, `#${e.msg + 1} · ${isCall ? mmss(S.offsets[e.msg]) : T[e.msg]?.timestamp}`),
      h('span', { class: 'cqa-ev-q' }, `«${e.quote || T[e.msg]?.text || ''}»`)));
    if (r.checked_range) {
      const [a, b] = r.checked_range;
      chips.push(h('button', { class: 'cqa-ev cqa-ev--range', 'data-ev-msg': a, title: 'Проверенный участок', onclick: ev => go(a, ev) },
        h('span', { class: 'cqa-ev-ref' }, a === b ? `Проверено #${a + 1}` : `Проверено #${a + 1}–#${b + 1}`)));
    }
    return chips;
  }

  function critCard(c, sc, enterIdx) {
    const r = resultOf(c.id);
    const appeal = appealOf(c.id);
    const orig = r?.answer;
    const final = appeal?.status === 'changed' ? appeal.decision.answer : orig;
    const row = sc.rows[c.id];
    const open = S.pinned === c.id;
    const sec = S.checklist.sections.find(s => s.id === c.section);
    const was = appeal?.status === 'changed' ? orig : undefined;

    const el = h('article', {
      class: `cqa-crit ${open ? 'is-open' : ''} ${enterIdx != null ? 'cqa-enter' : ''}`, 'data-crit': c.id, tabindex: 0,
      style: { '--c': secColor(c.section), animationDelay: enterIdx != null ? `${enterIdx * 60}ms` : null },
      onmouseenter: () => { S.hover = c.id; applyHighlights(); },
      onmouseleave: () => { S.hover = null; applyHighlights(); },
      onclick: e => { if (e.target.closest('.cqa-appeal, button, textarea')) return; setPinned(c.id); },
      onkeydown: e => { if ((e.key === 'Enter' || e.key === ' ') && e.target === el) { e.preventDefault(); setPinned(c.id); } },
      'aria-expanded': String(open),
    });

    if (!open) {
      return fill(el, h('div', { class: 'cqa-crit-row' },
        h('i', { class: 'cqa-dot' }),
        h('span', { class: 'cqa-crit-name' }, c.name),
        appeal && h('span', { class: `cqa-appeal-mark cqa-appeal-mark--${appeal.status}`, title: 'Есть апелляция' }, icon('gavel', 12)),
        answerBadge(c, final, was),
        c.type !== 'flag' && h('span', { class: 'cqa-crit-pts cqa-num' }, row?.na ? '—' : fmt(row?.points, 1))));
    }

    let formula = null;
    if (c.type !== 'flag' && row && !row.na) {
      const part = c.type === 'scale' ? `${final}/${scaleMax(c)}` : final === 'yes' ? '1' : '0';
      formula = `${part} × ${fmt(row.effWeight)}${Math.abs(row.effWeight - c.weight) > 0.001 ? ` · вес ${c.weight} → ${fmt(row.effWeight)} после N/A` : ''}`;
    }
    const typeText = c.type === 'flag' ? TYPE_LABEL.flag : `${TYPE_LABEL[c.type]}${c.na_allowed ? ' / N/A' : ''} · вес ${c.weight}`;

    return fill(el,
      h('div', { class: 'cqa-crit-kicker' }, h('i', { class: 'cqa-dot' }), h('span', null, `${c.code} · ${sec?.name || ''}`),
        h('button', { class: 'cqa-iconbtn cqa-iconbtn--plain', title: 'Свернуть', onclick: () => setPinned(c.id) }, icon('x', 14))),
      h('div', { class: 'cqa-crit-top' },
        h('div', { class: 'cqa-crit-title' }, h('h3', null, c.name), h('div', { class: 'cqa-crit-type' }, typeText)),
        h('div', { class: 'cqa-crit-score' },
          answerBadge(c, final, was),
          c.type !== 'flag' && h('div', { class: 'cqa-pts' },
            h('b', { class: 'cqa-num' }, row?.na ? '—' : fmt(row?.points)),
            h('span', { class: 'cqa-num' }, row?.na ? 'исключён' : `из ${fmt(row?.effWeight)}`)))),
      r && [
        h('p', { class: 'cqa-expl' }, final === 'na' || r.answer === 'na' ? [h('em', null, 'Причина N/A: '), r.na_reason || r.explanation] : r.explanation),
        h('div', { class: 'cqa-evs' }, evidenceChips(r)),
        h('div', { class: 'cqa-foot' },
          r.confidence != null && h('span', { class: `cqa-conf ${r.confidence < 0.7 ? 'is-low' : ''}`, title: 'Уверенность модели' },
            h('i', { style: { '--v': `${Math.round(r.confidence * 100)}%` } }), `уверенность ${Math.round(r.confidence * 100)}%`),
          formula && h('span', { class: 'cqa-formula cqa-num' }, formula)),
        S.role === 'operator' && !appeal && !S.drafts[c.id] && h('div', { class: 'cqa-row' },
          h('button', { class: 'cqa-btn cqa-btn--outline cqa-btn--sm', onclick: () => { S.drafts[c.id] = { comment: '' }; renderCrits(); applyHighlights(); focusDraft(c.id); } },
            icon('flag', 14), 'Оспорить оценку')),
        appealZone(c, r, appeal),
      ],
    );
  }

  function focusDraft(cid) { requestAnimationFrame(() => critEl.querySelector(`[data-draft="${cid}"]`)?.focus()); }

  function appealZone(c, r, appeal) {
    if (!appeal && S.drafts[c.id] && S.role === 'operator') {
      const d = S.drafts[c.id];
      const ta = h('textarea', {
        id: `cqa-ap-${c.id}`, class: `cqa-textarea ${d.error ? 'is-invalid' : ''}`, 'data-draft': c.id,
        placeholder: 'Почему вы не согласны? Сошлитесь на реплику, например «#12 — оператор представился».',
        oninput: e => { d.comment = e.target.value; },
      });
      ta.value = d.comment;
      return h('div', { class: 'cqa-appeal' },
        h('label', { for: `cqa-ap-${c.id}` }, 'Апелляция'), ta,
        d.error && h('span', { class: 'cqa-err' }, d.error),
        h('div', { class: 'cqa-row cqa-row--end' },
          h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm', onclick: () => { delete S.drafts[c.id]; renderCrits(); applyHighlights(); } }, 'Отмена'),
          h('button', {
            class: 'cqa-btn cqa-btn--primary cqa-btn--sm', disabled: d.saving,
            onclick: async () => {
              if (d.comment.trim().length < 5) { d.error = 'Опишите причину: проверяющий увидит этот комментарий.'; renderCrits(); applyHighlights(); focusDraft(c.id); return; }
              d.saving = true;
              const a = await api.createAppeal({ evaluation_id: S.evaluation.evaluation_id, conversation_id: S.id, criterion_id: c.id, comment: d.comment.trim() });
              S.appeals.push(a); delete S.drafts[c.id]; rerender();
              toast('Апелляция отправлена проверяющему', { icon: icon('flag', 16) });
            },
          }, 'Отправить')));
    }
    if (!appeal) return null;

    const statusText = { open: 'На рассмотрении', confirmed: 'Оценка подтверждена', changed: 'Оценка изменена' }[appeal.status];
    const head = h('div', { class: 'cqa-appeal-head' },
      icon('gavel', 14), h('b', null, 'Апелляция'), h('span', { class: `cqa-status cqa-status--${appeal.status}` }, statusText),
      h('span', { class: 'cqa-num' }, new Date(appeal.created_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })));
    const comment = h('blockquote', null, appeal.comment);

    if (appeal.status !== 'open') {
      return h('div', { class: 'cqa-appeal' }, head, comment,
        h('dl', { class: 'cqa-decision' },
          h('dt', null, 'Исходно'), h('dd', null, answerText(c, r.answer)),
          h('dt', null, 'Решение'), h('dd', null, appeal.status === 'changed' ? `Изменить на «${answerText(c, appeal.decision.answer)}»` : 'Оставить без изменений'),
          h('dt', null, 'Причина'), h('dd', null, appeal.decision.reason),
          appeal.decision.by && [h('dt', null, 'Решил'), h('dd', null, appeal.decision.by)],
          h('dt', null, 'Итог'), h('dd', null, h('b', null, answerText(c, appeal.status === 'changed' ? appeal.decision.answer : r.answer)))));
    }
    if (S.role !== 'reviewer') return h('div', { class: 'cqa-appeal' }, head, comment,
      h('p', { class: 'cqa-muted' }, 'Решение примет проверяющий: переключите роль внизу меню слева.'));

    const d = S.decisions[appeal.appeal_id] ||= { answer: r.answer, reason: '' };
    const reason = h('textarea', {
      class: `cqa-textarea ${d.error ? 'is-invalid' : ''}`, placeholder: 'Причина решения: сохранится в карточке', id: `cqa-dec-${appeal.appeal_id}`,
      oninput: e => { d.reason = e.target.value; },
    });
    reason.value = d.reason;
    const submit = async action => {
      if (d.reason.trim().length < 3) { d.error = 'Укажите причину решения.'; renderCrits(); applyHighlights(); return; }
      const before = computeScore(S.checklist, finalAnswers()).total;
      const upd = await api.decideAppeal(appeal.appeal_id, { action, answer: d.answer, reason: d.reason.trim(), by: reviewerName() || null });
      Object.assign(appeal, upd); delete S.decisions[appeal.appeal_id];
      // The backend closes the dialog once its last appeal is decided.
      const [fresh, rows] = await Promise.all([api.getEvaluation(S.id).catch(() => null), api.listDialogs().catch(() => S.rows)]);
      if (fresh?.evaluation_id === S.evaluation.evaluation_id) S.evaluation.review = fresh.review;
      S.rows = rows;
      rerender();
      const after = computeScore(S.checklist, finalAnswers()).total;
      toast(action === 'change' ? `Итог пересчитан: ${fmt(before)} → ${fmt(after)}` : 'Оценка подтверждена', { icon: icon('check', 16) });
    };
    return h('div', { class: 'cqa-appeal' }, head, comment,
      h('label', null, 'Оценка по критерию'),
      h('div', { class: 'cqa-opts', role: 'radiogroup' }, optionsFor(c).map(o => h('button', {
        class: 'cqa-opt', role: 'radio', 'aria-checked': String(d.answer === o.v), title: o.hint || null,
        onclick: () => { d.answer = o.v; renderCrits(); applyHighlights(); },
      }, o.label))),
      h('label', { for: `cqa-dec-${appeal.appeal_id}` }, 'Причина'), reason,
      d.error && h('span', { class: 'cqa-err' }, d.error),
      h('div', { class: 'cqa-row cqa-row--end' },
        h('button', { class: 'cqa-btn cqa-btn--ghost cqa-btn--sm', onclick: () => submit('confirm') }, 'Оставить'),
        h('button', { class: 'cqa-btn cqa-btn--primary cqa-btn--sm', disabled: d.answer === r.answer, onclick: () => submit('change') }, icon('check', 14), 'Изменить')));
  }

  // ---------- лучи: доказательство → реплика ----------
  function svgBeams() {
    const ns = 'http://www.w3.org/2000/svg';
    const el = document.createElementNS(ns, 'svg');
    el.setAttribute('class', 'cqa-beams');
    el.innerHTML = '<defs><linearGradient id="cqa-beam-grad" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="#1ae276"/><stop offset=".6" stop-color="#1ccc9e"/><stop offset="1" stop-color="#7d8dee"/></linearGradient></defs><g></g>';
    const g = el.querySelector('g');
    let raf = 0, lastKey = '';
    function draw() {
      raf = 0;
      const cid = activeId();
      const card = cid && critEl.querySelector(`.cqa-crit[data-crit="${cid}"]`);
      if (!card || !scroller || window.matchMedia('(max-width: 860px)').matches) { fill(g); lastKey = ''; return; }
      const box = scroller.getBoundingClientRect();
      const cbox = critEl.getBoundingClientRect();
      const chips = [...card.querySelectorAll('[data-ev-msg]')];
      // раскрытая карточка — луч от каждого чипа; свёрнутая — от строки к каждому доказательству
      const pairs = chips.length
        ? chips.map(t => [t, Number(t.dataset.evMsg)])
        : (resultOf(cid)?.evidence || []).map(e => [card, e.msg]);
      const seen = new Set(), paths = [];
      for (const [from, k] of pairs) {
        if (seen.has(k)) continue; seen.add(k);
        const bubble = msgEls[k]?.querySelector('.cqa-bubble');
        if (!bubble) continue;
        const m = bubble.getBoundingClientRect(), c = from.getBoundingClientRect();
        // A message or chip scrolled out of view keeps its beam: the end sticks to the panel edge.
        const clamp = (y, top, bottom, pad) => (y < top + pad ? [top + pad, -1] : y > bottom - pad ? [bottom - pad, 1] : [y, 0]);
        const [my, off] = clamp(m.top + Math.min(m.height / 2, 18), box.top, box.bottom, 14);
        const [cy, offC] = clamp(c.top + Math.min(c.height / 2, 22), cbox.top, cbox.bottom, 10);
        const x1 = c.left - 4, x2 = Math.min(m.right, box.right - 8) + 6;
        const dx = Math.max(30, (x1 - x2) * 0.5);
        paths.push({ d: `M${x1},${cy} C${x1 - dx},${cy} ${x2 + dx},${my} ${x2},${my}`, x1, y1: cy, x2, y2: my, off, offC, len: Math.hypot(x1 - x2, cy - my) * 1.3 });
      }
      const key = cid + paths.length;
      const fresh = key !== lastKey; lastKey = key;
      const dot = (x, y) => { const c = document.createElementNS(ns, 'circle'); c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', 2.5); return c; };
      const arrow = (x, y, dir) => {
        const a = document.createElementNS(ns, 'path');
        a.setAttribute('class', 'cqa-beam-arrow');
        a.setAttribute('d', `M${x - 5},${y - dir * 2} L${x},${y + dir * 4} L${x + 5},${y - dir * 2}`);
        return a;
      };
      fill(g, paths.map(p => {
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', p.d);
        if (p.off || p.offC) path.classList.add('is-off');
        else if (fresh && !reducedMotion()) { path.classList.add('is-new'); path.style.setProperty('--len', p.len); }
        return [path, p.offC ? arrow(p.x1, p.y1, p.offC) : dot(p.x1, p.y1), p.off ? arrow(p.x2, p.y2, p.off) : dot(p.x2, p.y2)];
      }));
    }
    const schedule = () => { if (!raf) raf = requestAnimationFrame(draw); };
    addEventListener('scroll', schedule, { passive: true, capture: true });
    addEventListener('resize', schedule);
    return { el, schedule, destroy() { removeEventListener('scroll', schedule, { capture: true }); removeEventListener('resize', schedule); } };
  }

  buildDoc();
  rerender();
  if (!S.evaluation) runEvaluation();
  else if (S.pinned) {
    const r = resultOf(S.pinned);
    const first = r?.evidence?.[0]?.msg ?? r?.checked_range?.[0];
    requestAnimationFrame(() => {
      if (first != null) jumpTo(first, { play: false });
      critEl.querySelector(`.cqa-crit[data-crit="${S.pinned}"]`)?.scrollIntoView({ block: 'nearest' });
    });
  }

  return {
    setRole(r) { S.role = r; S.drafts = {}; rerender(); },
    destroy() { beams.destroy(); S.audio?.pause(); },
  };
}
