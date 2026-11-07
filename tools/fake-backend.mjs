// Фейковый бэк по docs/API_CONTRACT.md: проверяем, что фронт работает с USE_MOCKS=false.
// Ответы нарочно «неполные»: без cost/latency/snapshot, шкала строкой.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const FRONT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../frontend');
const dev = JSON.parse(fs.readFileSync(FRONT + '/mocks/dev.json', 'utf8')).data.records;
let checklist = JSON.parse(fs.readFileSync(FRONT + '/mocks/checklist.default.json', 'utf8'));
const versions = [checklist];
const evals = {}; const appeals = [];
let n = 0;
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };

function evaluate(id) {
  const d = dev.find(x => x.conversation_id === id);
  const op = d.transcript.findIndex(t => t.speaker === 'operator');
  return {
    evaluation_id: 'ev' + (++n), conversation_id: id, checklist_id: checklist.id, checklist_version: checklist.version,
    model: 'fake-llm', created_at: new Date().toISOString(),
    results: checklist.criteria.map(c => ({
      criterion_id: c.id,
      answer: c.type === 'scale' ? String(c.scale[1]?.value ?? c.scale[0].value) : c.type === 'flag' ? 'no' : c.na_allowed && c.id === 'c03' ? 'N/A' : 'yes',
      explanation: 'Фейковое объяснение', evidence: op >= 0 ? [{ msg: op, quote: d.transcript[op].text.slice(0, 40) }, { msg: 999 }] : [],
    })),
  };
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const send = (code, body) => { res.writeHead(code, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Allow-Methods': 'GET,POST,PUT' }); res.end(body === undefined ? '' : JSON.stringify(body)); };
  if (req.method === 'OPTIONS') return send(204);
  let body = '';
  for await (const ch of req) body += ch;
  const json = body ? JSON.parse(body) : null;
  const p = url.pathname;

  if (!p.startsWith('/api')) {
    if (p === '/js/config.js') { res.writeHead(200, { 'Content-Type': 'text/javascript' }); return res.end("export const CONFIG = { USE_MOCKS: false, API_BASE: 'http://127.0.0.1:8787/api', DEFAULT_GROUP_ID: 'DEV' };"); }
    const f = path.join(FRONT, p === '/' ? 'index.html' : p);
    if (!f.startsWith(FRONT) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' }); return res.end(fs.readFileSync(f));
  }
  const m = s => p.match(s);
  let r;
  if (p === '/api/dialogs') return send(200, dev.map(d => ({ conversation_id: d.conversation_id, channel: d.channel, language: d.language, evaluation: evals[d.conversation_id] ? 'done' : 'none', total: evals[d.conversation_id] ? 77.5 : null })));
  if ((r = m(/^\/api\/dialogs\/([^/]+)\/evaluation$/))) return evals[r[1]] ? send(200, evals[r[1]]) : send(404, { error: 'нет оценки' });
  if ((r = m(/^\/api\/dialogs\/([^/]+)\/audio$/))) return send(200, { url: null });
  if ((r = m(/^\/api\/dialogs\/([^/]+)$/))) return send(200, dev.find(x => x.conversation_id === decodeURIComponent(r[1])));
  if (p === '/api/evaluations') { const e = evaluate(json.conversation_id); evals[json.conversation_id] = e; return send(200, e); }
  if (p === '/api/checklists/active' && req.method === 'GET') return send(200, checklist);
  if (p === '/api/checklists/active' && req.method === 'PUT') { checklist = { ...json, version: checklist.version + 1 }; versions.push(checklist); return send(200, checklist); }
  if (p === '/api/checklists/active/versions') return send(200, versions.map(v => ({ version: v.version, name: v.name, criteria: v.criteria.length })));
  if (p === '/api/appeals' && req.method === 'GET') return send(200, appeals.filter(a => !url.searchParams.get('evaluation_id') || a.evaluation_id === url.searchParams.get('evaluation_id')));
  if (p === '/api/appeals') { const a = { appeal_id: 'ap' + (++n), ...json, status: 'open', created_at: new Date().toISOString(), decision: null }; appeals.push(a); return send(200, a); }
  if ((r = m(/^\/api\/appeals\/([^/]+)\/decision$/))) { const a = appeals.find(x => x.appeal_id === r[1]); a.status = json.action === 'change' ? 'changed' : 'confirmed'; a.decision = { ...json, decided_at: new Date().toISOString() }; return send(200, a); }
  if (p === '/api/datasets/import') return send(200, { group_id: json.group_id, imported: dev.length });
  send(404, { error: 'not found ' + p });
}).listen(8787, '127.0.0.1', () => console.log('fake backend on 8787'));
