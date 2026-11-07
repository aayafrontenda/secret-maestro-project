// Единая точка доступа к данным. UI вызывает только api.*, а не fetch напрямую.
// Контракт эндпоинтов: docs/API_CONTRACT.md
import { CONFIG } from './config.js';
import { mockApi } from './mock/mockApi.js';

async function req(path, opts = {}) {
  const res = await fetch(`${CONFIG.API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).error || msg; } catch {}
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}
const enc = encodeURIComponent;
const qs = o => { const p = new URLSearchParams(Object.entries(o || {}).filter(([, v]) => v != null)); return p.toString() ? `?${p}` : ''; };

// Страховка от неполных ответов бэка: дефолты вместо падений UI.
const num = v => (v == null || v === '' ? null : Number(v));
function normResult(r) {
  let answer = r.answer;
  if (typeof answer === 'string') {
    const a = answer.trim().toLowerCase();
    answer = a === 'yes' || a === 'да' ? 'yes' : a === 'no' || a === 'нет' ? 'no' : a === 'na' || a === 'n/a' ? 'na' : Number.isFinite(Number(a)) ? Number(a) : a;
  } else if (answer === true) answer = 'yes';
  else if (answer === false) answer = 'no';
  return {
    criterion_id: r.criterion_id,
    answer,
    explanation: r.explanation ?? null,
    na_reason: r.na_reason ?? null,
    evidence: (r.evidence || []).map(e => ({ msg: Number(e.msg), quote: e.quote ?? '' })).filter(e => Number.isInteger(e.msg) && e.msg >= 0),
    checked_range: Array.isArray(r.checked_range) && r.checked_range.length === 2 ? r.checked_range.map(Number) : null,
    confidence: num(r.confidence),
  };
}
function normEvaluation(ev) {
  if (!ev) return null;
  return {
    ...ev,
    model: ev.model ?? 'unknown',
    is_mock: !!ev.is_mock,
    latency_ms: num(ev.latency_ms),
    cost_usd: num(ev.cost_usd),
    created_at: ev.created_at ?? new Date().toISOString(),
    results: (ev.results || []).map(normResult),
  };
}
function normRow(r) {
  return {
    ...r,
    turns: r.turns ?? 0,
    evaluation: r.evaluation ?? (r.total != null ? 'done' : 'none'),
    total: num(r.total),
    gross_error: !!r.gross_error,
    checklist_version: r.checklist_version ?? null,
    appeals_open: Number(r.appeals_open) || 0,
    appeals_total: Number(r.appeals_total) || 0,
  };
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
const POLL_MS = 2000;
const POLL_LIMIT_MS = 20 * 60 * 1000;

// Бэк ждёт модель до ~85 с (лимит Cloudflare ~100 с). Не успела — отдаёт оценку
// со status queued/running, дальше опрашиваем GET /evaluations/:id.
async function waitEvaluation(ev) {
  const t0 = Date.now();
  while (ev.status === 'queued' || ev.status === 'running') {
    if (Date.now() - t0 > POLL_LIMIT_MS) throw new Error('Оценка не завершилась за 20 минут. Проверьте модель и откройте диалог позже.');
    await sleep(POLL_MS);
    ev = await req(`/evaluations/${ev.evaluation_id}`);
  }
  if (ev.status === 'failed') throw new Error(ev.error || 'Оценка не выполнена');
  if (ev.status === 'cancelled') throw new Error('Оценка отменена');
  return ev;
}

const httpApi = {
  importDataset: group_id => req('/datasets/import', { method: 'POST', body: { group_id } }),
  uploadDataset: (json, name) => req('/datasets/upload', { method: 'POST', body: { name, payload: json } }),
  listDialogs: () => req('/dialogs').then(rows => (rows || []).map(normRow)),
  getDialog: id => req(`/dialogs/${enc(id)}`),
  getAudio: id => req(`/dialogs/${enc(id)}/audio`)
    .then(a => ({ ...a, stream_url: a?.url ? `${CONFIG.API_BASE}/dialogs/${enc(id)}/audio/stream` : null })),

  getActiveChecklist: () => req('/checklists/active'),
  listChecklistVersions: () => req('/checklists/active/versions'),
  saveChecklist: cl => req('/checklists/active', { method: 'PUT', body: cl }),
  resetChecklist: () => req('/checklists/active/reset', { method: 'POST' }),

  // 404 = оценки ещё нет; остальные ошибки (бэк недоступен) пробрасываем, чтобы не запускать оценку зря.
  getEvaluation: id => req(`/dialogs/${enc(id)}/evaluation`).then(normEvaluation)
    .catch(e => { if (e.status === 404) return null; throw e; }),
  evaluate: id => req('/evaluations', { method: 'POST', body: { conversation_id: id } }).then(waitEvaluation).then(normEvaluation),

  // Массовая оценка на бэке: переживает закрытие вкладки и обрыв соединения.
  startBatch: conversation_ids => req('/evaluations/batch', { method: 'POST', body: { conversation_ids } }),
  batchStatus: batch_id => req(`/evaluations/batch/${enc(batch_id)}`),
  batchItems: batch_id => req(`/evaluations${qs({ batch_id, limit: 2000 })}`),
  cancelBatch: batch_id => req(`/evaluations/batch/${enc(batch_id)}/cancel`, { method: 'POST' }),

  listAppeals: filter => req(`/appeals${qs(filter)}`),
  createAppeal: body => req('/appeals', { method: 'POST', body }),
  decideAppeal: (id, body) => req(`/appeals/${id}/decision`, { method: 'POST', body }),

  // Очередь «Требуют внимания» и аналитика передач от бота оператору.
  getAttention: threshold => req(`/attention${qs({ threshold })}`),
  getHandoffs: () => req('/insights/handoffs'),
  analyzeHandoffs: (force = false) => req('/insights/handoffs/analyze', { method: 'POST', body: { force } }),
  getDialogHandoff: id => req(`/dialogs/${enc(id)}/handoff`).catch(() => null),
  knowledgeUrl: () => `${CONFIG.API_BASE}/insights/handoffs/knowledge?format=jsonl`,

  resetAll: async () => {},
};

export const api = CONFIG.USE_MOCKS ? mockApi : httpApi;
