// Мок-реализация API. Сигнатуры совпадают с httpApi в ../api.js.
// Хранение: localStorage (оценки, апелляции, версии чек-листа, загруженные наборы).
import { mockEvaluate } from './mockEvaluator.js';
import { store } from '../util.js';
import { computeScore, finalAnswersOf } from '../scoring.js';

const base = new URL('../../mocks/', import.meta.url);
let devRecords, defaultChecklist;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const uid = p => `${p}_${Math.random().toString(36).slice(2, 10)}`;
const clone = x => JSON.parse(JSON.stringify(x));

async function loadDev() {
  if (!devRecords) {
    const json = await (await fetch(new URL('dev.json', base))).json();
    devRecords = json.data.records.map(r => ({ ...r, group_id: json.data.dataset_group_id || 'DEV' }));
  }
  return devRecords;
}
async function loadDefaultChecklist() {
  if (!defaultChecklist) defaultChecklist = await (await fetch(new URL('checklist.default.json', base))).json();
  return clone(defaultChecklist);
}
async function allRecords() {
  const dev = await loadDev();
  const uploaded = store('cqa.uploaded') || [];
  const ids = new Set(uploaded.map(r => r.conversation_id));
  return [...uploaded, ...dev.filter(r => !ids.has(r.conversation_id))];
}

// Разбор ответа организаторов или голого массива записей.
function parseRecords(json, fallbackGroup) {
  const recs = Array.isArray(json) ? json : json?.data?.records || json?.records;
  if (!Array.isArray(recs) || !recs.length) throw new Error('В файле нет записей: ожидается data.records[] как в ответе API организаторов.');
  const group = json?.data?.dataset_group_id || fallbackGroup;
  return recs.map((r, i) => {
    if (!r.conversation_id || !Array.isArray(r.transcript)) throw new Error(`Запись ${i + 1}: нужны conversation_id и transcript[].`);
    return { conversation_id: String(r.conversation_id), channel: r.channel || 'agent chat', language: r.language || 'RU', transcript: r.transcript, audio_url: r.audio_url ?? null, group_id: group };
  });
}

export const mockApi = {
  // ---------- наборы и диалоги ----------
  async importDataset(group_id) {
    await sleep(500);
    const g = group_id.trim().toUpperCase();
    if (g === 'DEV') return { group_id: 'DEV', imported: (await loadDev()).length };
    throw new Error(`В мок-режиме доступен только DEV. Набор «${group_id}» подтянет бэкенд, а пока загрузите JSON-файл.`);
  },

  async uploadDataset(json, name = 'UPLOAD') {
    const recs = parseRecords(json, name);
    const prev = (store('cqa.uploaded') || []).filter(r => !recs.some(n => n.conversation_id === r.conversation_id));
    store('cqa.uploaded', [...recs, ...prev]);
    return { group_id: recs[0].group_id, imported: recs.length };
  },

  async listDialogs() {
    const rows = await allRecords();
    const appeals = store('cqa.appeals') || [];
    const active = await this.getActiveChecklist();
    return rows.map(d => {
      const ev = store(`cqa.eval.${d.conversation_id}`);
      const mine = ev ? appeals.filter(a => a.evaluation_id === ev.evaluation_id) : [];
      const sc = ev ? computeScore(ev.checklist || active, finalAnswersOf(ev, mine)) : null;
      return {
        conversation_id: d.conversation_id, channel: d.channel, language: d.language, group_id: d.group_id,
        turns: d.transcript.length,
        evaluation: ev ? 'done' : 'none',
        total: sc?.total ?? null,
        gross_error: sc ? sc.grossErrors.length > 0 : false,
        checklist_version: ev?.checklist_version ?? null,
        evaluated_at: ev?.created_at ?? null,
        appeals_open: mine.filter(a => a.status === 'open').length,
        appeals_total: mine.length,
        review_status: !ev ? 'none' : mine.some(a => a.status === 'open') ? 'appeal' : ev.review ? 'reviewed' : 'to_review',
        reviewed_at: ev?.review?.reviewed_at ?? null,
        reviewed_by: ev?.review?.by ?? null,
      };
    });
  },

  async getDialog(id) {
    const d = (await allRecords()).find(x => x.conversation_id === id);
    if (!d) throw new Error(`Диалог ${id} не найден`);
    return d;
  },

  async getAudio(id) {
    // Бэкенд: GET audio_url → HTML-плеер → вытащить <source src> (SAS-ссылка на mp3, живёт ~1 час).
    const d = await this.getDialog(id);
    return { url: null, player_url: d.audio_url, expires_at: null };
  },

  // ---------- чек-лист ----------
  async getActiveChecklist() {
    const versions = store('cqa.checklists');
    return versions?.length ? clone(versions[versions.length - 1]) : loadDefaultChecklist();
  },

  async listChecklistVersions() {
    const versions = store('cqa.checklists');
    if (versions?.length) return versions.map(v => ({ version: v.version, name: v.name, updated_at: v.updated_at, criteria: v.criteria.length }));
    const d = await loadDefaultChecklist();
    return [{ version: d.version, name: d.name, updated_at: null, criteria: d.criteria.length }];
  },

  async saveChecklist(cl) {
    const versions = store('cqa.checklists') || [await loadDefaultChecklist()];
    const next = { ...clone(cl), version: versions[versions.length - 1].version + 1, updated_at: new Date().toISOString() };
    versions.push(next);
    store('cqa.checklists', versions);
    await sleep(300);
    return clone(next);
  },

  async resetChecklist() {
    const versions = store('cqa.checklists') || [];
    const d = await loadDefaultChecklist();
    const last = versions[versions.length - 1];
    const next = { ...d, version: (last?.version || 1) + 1, updated_at: new Date().toISOString() };
    store('cqa.checklists', [...(versions.length ? versions : [d]), next]);
    return clone(next);
  },

  // Dry run of a draft: the same response shape as the backend's /checklists/active/simulate.
  async simulateChecklist(draft, limit = 10) {
    const t0 = performance.now();
    const active = await this.getActiveChecklist();
    const appeals = store('cqa.appeals') || [];
    const view = c => JSON.stringify([c.name.trim(), (c.description || '').trim(), c.type, c.na_allowed ? (c.na_condition || '').trim() : null,
      c.type === 'scale' ? [...(c.scale || [])].map(s => [Number(s.value), (s.label || '').trim()]).sort((a, b) => b[0] - a[0]) : null]);
    const notes = cl => JSON.stringify(cl.rules?.notes || []);
    const guidelinesChanged = notes(draft) !== notes(active);
    const old = Object.fromEntries(active.criteria.map(c => [c.id, c]));
    const changed = draft.criteria.flatMap(c => {
      const p = old[c.id];
      if (!p) return [{ criterion_id: c.id, criterion_name: c.name, reason: 'new', fields: [] }];
      if (view(p) !== view(c)) return [{ criterion_id: c.id, criterion_name: c.name, reason: 'edited', fields: [] }];
      return guidelinesChanged ? [{ criterion_id: c.id, criterion_name: c.name, reason: 'guidelines', fields: [] }] : [];
    });
    const codes = new Set(changed.map(c => c.criterion_id));
    const human = (ev, id) => {
      const a = appeals.find(x => x.evaluation_id === ev.evaluation_id && x.criterion_id === id && x.status !== 'open');
      if (!a) return null;
      return a.status === 'changed' ? a.decision.answer : ev.results.find(r => r.criterion_id === id)?.answer ?? null;
    };
    const evals = Object.keys(localStorage).filter(k => k.startsWith('cqa.eval.')).map(k => store(k)).filter(Boolean);
    const decided = ev => [...codes].filter(id => human(ev, id) != null).length;
    const sample = evals.sort((a, b) => decided(b) - decided(a) || String(b.created_at).localeCompare(String(a.created_at))).slice(0, limit);
    const hash = s => { let x = 0; for (const ch of s) x = (x * 31 + ch.charCodeAt(0)) | 0; return Math.abs(x); };
    await sleep(900 + 120 * sample.length);

    const dialogs = [];
    for (const ev of sample) {
      const d = await this.getDialog(ev.conversation_id);
      const was = finalAnswersOf(ev, appeals);
      const need = draft.criteria.filter(c => codes.has(c.id) || was[c.id] == null);
      const fresh = Object.fromEntries(mockEvaluate(d, { ...draft, criteria: need }).map(r => [r.criterion_id, r]));
      const changes = need.map(c => {
        let answer = fresh[c.id].answer;
        // The regex mock ignores wording; flip some answers so a reworded criterion visibly moves.
        if (old[c.id] && c.type !== 'flag' && hash(c.id + (c.description || '') + ev.conversation_id) % 4 === 0) {
          const steps = c.type === 'scale' ? c.scale.map(s => s.value).sort((a, b) => b - a) : null;
          answer = steps ? (steps.find(v => v !== answer) ?? answer) : answer === 'yes' ? 'no' : answer === 'no' ? 'yes' : answer;
        }
        const h = human(ev, c.id);
        return {
          criterion_id: c.id, criterion_name: c.name, old_answer: was[c.id] ?? null, new_answer: answer,
          model_answer: ev.results.find(r => r.criterion_id === c.id)?.answer ?? null, human_answer: h,
          changed: was[c.id] == null || String(was[c.id]) !== String(answer), explanation: fresh[c.id].explanation || '',
        };
      });
      const answers = { ...was };
      for (const ch of changes) answers[ch.criterion_id] = ch.new_answer;
      dialogs.push({
        conversation_id: ev.conversation_id, evaluation_id: ev.evaluation_id, language: d.language,
        old_total: computeScore(ev.checklist || active, was).total, new_total: computeScore(draft, answers).total,
        grave_error: computeScore(draft, answers).grossErrors.length > 0, changes,
      });
    }
    const criteria = changed.map(c => {
      const all = dialogs.flatMap(d => d.changes.filter(x => x.criterion_id === c.criterion_id));
      const dec = all.filter(x => x.human_answer != null);
      return {
        ...c, evaluated: all.length, changed: all.filter(x => x.changed).length, human_decided: dec.length,
        agree_before: dec.filter(x => String(x.model_answer) === String(x.human_answer)).length,
        agree_after: dec.filter(x => String(x.new_answer) === String(x.human_answer)).length,
      };
    });
    const deltas = dialogs.filter(d => d.old_total != null && d.new_total != null).map(d => d.new_total - d.old_total);
    return {
      checklist_version: active.version, changed_criteria: changed, guidelines_changed: guidelinesChanged, sample: dialogs.length,
      dialogs_changed: dialogs.filter(d => d.changes.some(x => x.changed)).length,
      score_changed: deltas.filter(x => Math.abs(x) >= 0.005).length,
      avg_delta: deltas.length ? Math.round((deltas.reduce((a, b) => a + b, 0) / deltas.length) * 100) / 100 : null,
      criteria, dialogs, failed: 0, model: { provider: 'mock', name: 'mock-heuristic' },
      usage: { prompt_tokens: 0, completion_tokens: 0, cost_usd: 0 }, duration_ms: Math.round(performance.now() - t0),
    };
  },

  // ---------- оценка ----------
  async getEvaluation(id) {
    return store(`cqa.eval.${id}`);
  },

  async evaluate(id) {
    const [d, cl] = await Promise.all([this.getDialog(id), this.getActiveChecklist()]);
    const t0 = performance.now();
    await sleep(1200 + Math.random() * 600);
    const evaluation = {
      evaluation_id: uid('ev'),
      conversation_id: id,
      checklist_id: cl.id,
      checklist_version: cl.version,
      checklist: cl,                       // снимок: оценка всегда показывается по тем критериям, по которым делалась
      model: 'mock-heuristic',
      is_mock: true,
      created_at: new Date().toISOString(),
      latency_ms: Math.round(performance.now() - t0),
      cost_usd: 0,
      tokens: { input: 0, output: 0 },
      results: mockEvaluate(d, cl),
    };
    store(`cqa.eval.${id}`, evaluation);
    return evaluation;
  },

  // ---------- апелляции ----------
  async listAppeals({ evaluation_id, status } = {}) {
    let all = store('cqa.appeals') || [];
    if (evaluation_id) all = all.filter(a => a.evaluation_id === evaluation_id);
    if (status) all = all.filter(a => a.status === status);
    return all;
  },

  async createAppeal({ evaluation_id, conversation_id, criterion_id, comment }) {
    const all = store('cqa.appeals') || [];
    const ev = store(`cqa.eval.${conversation_id}`);
    const res = ev?.results.find(r => r.criterion_id === criterion_id);
    const crit = ev?.checklist?.criteria.find(c => c.id === criterion_id);
    const a = {
      appeal_id: uid('ap'), evaluation_id, conversation_id, criterion_id, comment,
      criterion_name: crit?.name ?? criterion_id, original_answer: res?.answer ?? null,
      status: 'open', created_at: new Date().toISOString(), decision: null,
    };
    all.push(a);
    store('cqa.appeals', all);
    await sleep(250);
    return a;
  },

  async decideAppeal(appeal_id, { action, answer, reason, by = null }) {
    const all = store('cqa.appeals') || [];
    const a = all.find(x => x.appeal_id === appeal_id);
    if (!a) throw new Error('Апелляция не найдена');
    a.status = action === 'change' ? 'changed' : 'confirmed';
    a.decision = { action, answer: action === 'change' ? answer : null, reason, by, decided_at: new Date().toISOString() };
    store('cqa.appeals', all);
    // Deciding the last open appeal closes the dialog.
    const ev = store(`cqa.eval.${a.conversation_id}`);
    if (ev && !ev.review && !all.some(x => x.evaluation_id === a.evaluation_id && x.status === 'open')) {
      ev.review = { reviewed_at: new Date().toISOString(), by, note: null };
      store(`cqa.eval.${a.conversation_id}`, ev);
    }
    await sleep(250);
    return a;
  },

  async markReviewed(evaluation_id, { by = null, note = null } = {}) {
    const key = Object.keys(localStorage).find(k => k.startsWith('cqa.eval.') && store(k)?.evaluation_id === evaluation_id);
    const ev = key && store(key);
    if (!ev) throw new Error('Оценка не найдена');
    if ((store('cqa.appeals') || []).some(a => a.evaluation_id === evaluation_id && a.status === 'open')) throw new Error('Есть открытые апелляции: сначала примите по ним решение');
    ev.review = { reviewed_at: new Date().toISOString(), by, note };
    store(key, ev);
    return ev;
  },

  async unmarkReviewed(evaluation_id) {
    const key = Object.keys(localStorage).find(k => k.startsWith('cqa.eval.') && store(k)?.evaluation_id === evaluation_id);
    const ev = key && store(key);
    if (!ev) throw new Error('Оценка не найдена');
    ev.review = null;
    store(key, ev);
    return ev;
  },

  async getML() { return { active: 'mock', providers: [{ id: 'mock', kind: 'demo', model: 'heuristics', endpoint: null, active: true, reachable: true }] }; },
  async setML() { return this.getML(); },

  // ---------- backend-only analytics ----------
  async getAttention() { return { threshold: 60, counts: { total: 0 }, items: [], mock: true }; },
  async getHandoffs() { throw new Error('Раздел работает только с бэкендом (USE_MOCKS: false)'); },
  async analyzeHandoffs() { throw new Error('Раздел работает только с бэкендом'); },
  async getDialogHandoff() { return null; },
  knowledgeUrl: () => null,

  // ---------- служебное ----------
  async resetAll() {
    Object.keys(localStorage).filter(k => k.startsWith('cqa.') && k !== 'cqa.role').forEach(k => localStorage.removeItem(k));
  },
};
