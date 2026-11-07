// Reviewer worklist: review status, priority, next dialog.
import { store } from './util.js';

export const REVIEW = {
  appeal: { label: 'Апелляция', pill: 'cqa-pill--amber', icon: 'gavel' },
  to_review: { label: 'Ждёт проверки', pill: 'cqa-pill--outline', icon: 'flag' },
  reviewed: { label: 'Проверен', pill: 'cqa-pill--green', icon: 'check' },
  none: { label: 'Не оценён', pill: '', icon: null },
};

export const needsAction = r => r.review_status === 'appeal' || r.review_status === 'to_review';

// Lower comes first: appeals, grave errors, then the lowest totals.
export function priority(r) {
  switch (r.review_status) {
    case 'appeal': return 0;
    case 'to_review': return (r.gross_error ? 1 : 2) + (r.total ?? 100) / 1000;
    case 'reviewed': return 5;
    default: return 6;
  }
}

export const byPriority = (a, b) => priority(a) - priority(b) || a.conversation_id.localeCompare(b.conversation_id);

export function nextInQueue(rows, currentId) {
  return rows.filter(r => needsAction(r) && r.conversation_id !== currentId).sort(byPriority)[0]?.conversation_id ?? null;
}

export const reviewerName = () => store('cqa.name') || '';
export const setReviewerName = v => store('cqa.name', v.trim() || null);
