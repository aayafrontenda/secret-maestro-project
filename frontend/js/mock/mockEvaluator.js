// МОК-оценщик на регулярках. Нужен только чтобы фронт жил без бэкенда.
// Настоящая оценка — LLM на бэкенде, формат ответа тот же (см. docs/API_CONTRACT.md).
import { offsetsOf } from '../util.js';

const RX = {
  greet: /(здравствуйте|добрый (день|вечер)|доброе утро|приветствую|сәлеметсіз|қайырлы|hello|\bhi\b|good (morning|afternoon|evening))/i,
  intro: /(меня зовут|на связи|менің атым|атым|my name is|this is [a-z]+ (from|at)|i am [a-z]+ (from|at)|i'm [a-z]+ (from|at)|you're chatting with)/i,
  sensitive: /(сч[её]т|баланс|вывод|вывест|пароль|паспорт|договор|пополн|шот|ақша|қаражат|account|balance|withdraw|password|transfer|deposit)/i,
  verify: /(иин|жсн|дата рождения|кодов|верифик|подтвердите личность|последние .* цифр|туған күн|verify|verification|date of birth|identity)/i,
  thanks: /(спасибо|благодарю|рахмет|thank)/i,
  polite: /(пожалуйста|спасибо|извините|прошу прощения|понимаю|рахмет|кешіріңіз|өтінемін|please|thank|sorry|apolog|understand)/i,
  wait: /(минут|подождите|ожидайте|секунду|күте|минут|wait|moment|minute)/i,
  bye: /(хорошего|до свидания|всего доброго|обращайтесь|ещ[её] вопрос|сау болыңыз|күн|сұрағыңыз|have a (nice|great|good)|goodbye|bye|anything else|other questions)/i,
  gross: /(личн(ый|ого) (номер|сч[её]т|карт)|переведите мне|на мою карту|мой личный|жеке нөмір|personal (number|account)|my card)/i,
};

function hash(s) { let x = 0; for (const ch of s) x = (x * 31 + ch.charCodeAt(0)) | 0; return Math.abs(x); }
const conf = (seed, lo = 0.62) => Math.round((lo + (hash(seed) % 33) / 100) * 100) / 100;
const quote = t => (t.length > 120 ? `${t.slice(0, 117)}…` : t);

export function mockEvaluate(dialog, checklist) {
  const T = dialog.transcript.map((t, i) => ({ ...t, i }));
  const ops = T.filter(t => t.speaker === 'operator');
  const clients = T.filter(t => t.speaker === 'client');
  const firstOp = ops[0];
  const lastOp = ops[ops.length - 1];
  const opRange = firstOp ? [firstOp.i, lastOp.i] : [0, T.length - 1];
  const ev = t => ({ msg: t.i, quote: quote(t.text) });
  const off = offsetsOf(dialog.transcript);

  const H = {
    c01() {
      if (!firstOp) return { answer: 'no', explanation: 'Оператор не подключился — приветствия нет.', checked_range: [0, T.length - 1] };
      const g = RX.greet.test(firstOp.text), n = RX.intro.test(firstOp.text);
      return g && n
        ? { answer: 'yes', explanation: 'Оператор поздоровался и представился в первом ответе.', evidence: [ev(firstOp)] }
        : { answer: 'no', explanation: `В первом ответе ${g ? 'нет представления' : 'нет приветствия'}.`, evidence: [ev(firstOp)], checked_range: [firstOp.i, firstOp.i] };
    },
    c02() {
      const q = ops.slice(0, 3).find(t => t.text.includes('?'));
      return q
        ? { answer: 'yes', explanation: 'Оператор уточнил недостающие детали до ответа.', evidence: [ev(q)] }
        : { answer: 'na', na_reason: 'Клиент сразу описал запрос, данных для ответа хватало.', evidence: clients[0] ? [ev(clients[0])] : [] };
    },
    c03() {
      const s = clients.find(t => RX.sensitive.test(t.text));
      const v = ops.find(t => RX.verify.test(t.text));
      if (!s) return { answer: 'na', na_reason: 'Запрос общий и не требовал идентификации.', evidence: clients[0] ? [ev(clients[0])] : [] };
      return v
        ? { answer: 'yes', explanation: 'Личность проверена до раскрытия данных.', evidence: [ev(s), ev(v)] }
        : { answer: 'no', explanation: 'Запрос касался счёта, но проверка личности в чате не подтверждена.', evidence: [ev(s)], checked_range: opRange };
    },
    c04() {
      if (!firstOp) return { answer: 'na', na_reason: 'Чат закончился до ответа оператора.' };
      const after = clients.filter(t => t.i > firstOp.i);
      const thanked = after.find(t => RX.thanks.test(t.text));
      if (thanked) return { answer: 20, explanation: 'Клиент получил ответ и подтвердил, что вопрос решён.', evidence: [ev(firstOp), ev(thanked)] };
      return ops.length >= 2
        ? { answer: 15, explanation: 'Основной вопрос закрыт, подтверждения от клиента нет.', evidence: [ev(ops[1])] }
        : { answer: 10, explanation: 'Ответ дан частично, клиент остался без следующего шага.', evidence: [ev(firstOp)] };
    },
    c05() {
      const p = ops.find(t => RX.polite.test(t.text));
      return p
        ? { answer: 'yes', explanation: 'Оператор вежлив и реагирует на ситуацию клиента.', evidence: [ev(p)] }
        : { answer: 'no', explanation: 'Нет вежливых формулировок и реакции на неудобство клиента.', checked_range: opRange };
    },
    c06() {
      let gap = null;
      for (const o of ops) {
        const prev = T[o.i - 1];
        if (prev && off[o.i] != null && off[prev.i] != null && off[o.i] - off[prev.i] > 120) {
          const warned = ops.some(w => w.i < o.i && w.i >= prev.i - 2 && RX.wait.test(w.text));
          if (!warned) { gap = o; break; }
        }
      }
      return gap
        ? { answer: 7, explanation: 'Пауза больше 2 минут без предупреждения об ожидании.', evidence: [ev(gap)] }
        : { answer: 10, explanation: 'Ответы ясные и последовательные, долгих пауз без предупреждения нет.', evidence: firstOp ? [ev(firstOp)] : [] };
    },
    c07() {
      if (!lastOp) return { answer: 'na', na_reason: 'Оператора не было — завершать нечего.' };
      const tail = T.slice(lastOp.i + 1);
      const aborted = tail.some(t => t.speaker === 'client' && t.text.length > 20);
      if (aborted) return { answer: 'na', na_reason: 'Чат оборвался со стороны клиента до завершения.', evidence: [ev(tail[tail.length - 1])] };
      return RX.bye.test(lastOp.text)
        ? { answer: 'yes', explanation: 'Оператор попрощался и предложил помощь.', evidence: [ev(lastOp)] }
        : { answer: 'no', explanation: 'После ответа оператор закрыл чат без прощания.', evidence: [ev(lastOp)], checked_range: [lastOp.i, T.length - 1] };
    },
    c08() {
      const g = ops.find(t => RX.gross.test(t.text));
      return g
        ? { answer: 'yes', explanation: 'Оператор предложил услугу в обход компании.', evidence: [ev(g)] }
        : { answer: 'no', explanation: 'Оскорблений, предложений в обход компании и раскрытия данных нет.', checked_range: opRange };
    },
  };

  const results = checklist.criteria.map(c => {
    const fn = H[c.id];
    let r = fn ? fn() : {
      answer: c.type === 'scale' ? Math.max(...c.scale.map(s => s.value)) : c.type === 'flag' ? 'no' : 'yes',
      explanation: 'Мок: для нового критерия эвристики нет, ответ условный.',
      evidence: firstOp ? [ev(firstOp)] : [],
    };
    if (r.answer === 'na' && !c.na_allowed) r = { ...r, answer: 'no', explanation: r.na_reason };
    const confidence = conf(dialog.conversation_id + c.id);
    // Mock of the cascade check: a second model "disagrees" where the mock is unsure.
    const disputed = confidence < 0.68 && c.type !== 'flag';
    const other = c.type === 'scale'
      ? ([...c.scale].map(s => s.value).sort((a, b) => b - a).find(v => v !== r.answer) ?? r.answer)
      : r.answer === 'yes' ? 'no' : 'yes';
    return {
      needs_review: disputed,
      second_opinion: disputed ? { answer: other, model: 'mock-check' } : null,
      criterion_id: c.id,
      answer: r.answer,
      explanation: r.explanation || null,
      na_reason: r.na_reason || null,
      evidence: r.evidence || [],
      checked_range: r.checked_range || null,
      confidence,
    };
  });

  return results;
}
