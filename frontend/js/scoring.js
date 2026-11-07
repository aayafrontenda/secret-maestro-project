// Расчёт итога по правилам чек-листа (стр. 2 PDF). Чистая функция — бэкенд должен считать так же.
//   1. N/A только где разрешён.
//   2. «Да» = полный вес, «Нет» = 0, шкала = ступень / верхняя ступень × вес.
//   3. Веса N/A пропорционально перераспределяются между применимыми критериями (максимум 100).
//   4. Итог округляется до rules.rounding знаков. Нет применимых — итог не считается.
//   5. Критерии type=flag (грубые ошибки) баллов не дают, отмечаются отдельно.

export function scaleMax(criterion) {
  return Math.max(...criterion.scale.map(s => s.value));
}

export function fraction(criterion, answer) {
  if (answer === 'na' || answer == null) return null;
  if (criterion.type === 'binary') return answer === 'yes' ? 1 : 0;
  if (criterion.type === 'scale') return Number(answer) / scaleMax(criterion);
  return null;
}

const round = (x, d) => Math.round((x + Number.EPSILON) * 10 ** d) / 10 ** d;

/**
 * @param checklist  объект чек-листа
 * @param answers    { [criterion_id]: 'yes' | 'no' | 'na' | number }
 */
export function computeScore(checklist, answers) {
  const digits = checklist.rules?.rounding ?? 2;
  const scored = checklist.criteria.filter(c => c.type !== 'flag');
  const applicable = scored.filter(c => answers[c.id] !== 'na' && answers[c.id] != null);
  const applicableWeight = applicable.reduce((s, c) => s + c.weight, 0);

  const rows = {};
  for (const c of scored) {
    const frac = fraction(c, answers[c.id]);
    if (frac == null || applicableWeight === 0) {
      rows[c.id] = { na: true, weight: c.weight, effWeight: 0, points: 0, frac: null };
      continue;
    }
    const effWeight = (c.weight * 100) / applicableWeight;
    rows[c.id] = { na: false, weight: c.weight, effWeight, points: frac * effWeight, frac };
  }

  const sections = checklist.sections.map(s => {
    const inSection = scored.filter(c => c.section === s.id);
    return {
      id: s.id,
      name: s.name,
      hasScored: inSection.length > 0,
      points: round(inSection.reduce((a, c) => a + rows[c.id].points, 0), digits),
      max: round(inSection.reduce((a, c) => a + rows[c.id].effWeight, 0), digits),
    };
  }).filter(s => s.hasScored);

  const total = applicableWeight === 0
    ? null
    : round(Object.values(rows).reduce((a, r) => a + r.points, 0), digits);

  const grossErrors = checklist.criteria
    .filter(c => c.type === 'flag' && answers[c.id] === 'yes')
    .map(c => c.id);

  return { total, rows, sections, grossErrors, naIds: scored.filter(c => rows[c.id].na).map(c => c.id) };
}

export const fmt = (n, d = 2) => (n == null ? '—' : n.toFixed(d));

// Ответы оценки с учётом решений по апелляциям (исходная оценка не меняется).
export function originalAnswersOf(evaluation) {
  return Object.fromEntries((evaluation?.results || []).map(r => [r.criterion_id, r.answer]));
}
export function finalAnswersOf(evaluation, appeals = []) {
  const a = originalAnswersOf(evaluation);
  for (const ap of appeals) {
    if (ap.evaluation_id === evaluation?.evaluation_id && ap.status === 'changed') a[ap.criterion_id] = ap.decision.answer;
  }
  return a;
}

// Проверка чек-листа перед сохранением. Возвращает список ошибок (пусто — ок).
export function validateChecklist(cl) {
  const errs = [];
  if (!cl.name?.trim()) errs.push({ field: 'name', msg: 'Укажите название чек-листа.' });
  if (!cl.criteria.length) errs.push({ field: 'criteria', msg: 'Добавьте хотя бы один критерий.' });
  const sum = cl.criteria.filter(c => c.type !== 'flag').reduce((s, c) => s + (Number(c.weight) || 0), 0);
  if (Math.abs(sum - 100) > 0.001) errs.push({ field: 'weights', msg: `Сумма весов ${sum}, должна быть 100.` });
  for (const c of cl.criteria) {
    const tag = `«${c.name || 'без названия'}»`;
    if (!c.name?.trim()) errs.push({ id: c.id, field: 'name', msg: 'Название критерия не заполнено.' });
    if (!c.description?.trim()) errs.push({ id: c.id, field: 'description', msg: `${tag}: опишите правило оценки.` });
    if (c.type !== 'flag' && !(Number(c.weight) > 0)) errs.push({ id: c.id, field: 'weight', msg: `${tag}: вес должен быть больше 0.` });
    if (c.na_allowed && !c.na_condition?.trim()) errs.push({ id: c.id, field: 'na_condition', msg: `${tag}: опишите, когда ставить N/A.` });
    if (c.type === 'scale') {
      const vals = (c.scale || []).map(s => Number(s.value));
      if (vals.length < 2) errs.push({ id: c.id, field: 'scale', msg: `${tag}: в шкале нужно минимум 2 ступени.` });
      if (new Set(vals).size !== vals.length) errs.push({ id: c.id, field: 'scale', msg: `${tag}: ступени шкалы повторяются.` });
      if (!(Math.max(...vals) > 0)) errs.push({ id: c.id, field: 'scale', msg: `${tag}: верхняя ступень должна быть больше 0.` });
    }
  }
  return errs;
}
