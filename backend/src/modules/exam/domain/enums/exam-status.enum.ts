/** DB에 저장되지 않는다 — open_at/close_at과 현재 시각으로 매번 계산된다. */
export enum ExamStatus {
  SCHEDULED = 'SCHEDULED',
  OPEN = 'OPEN',
  CLOSED = 'CLOSED',
}
