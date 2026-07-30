import { ExamStatus } from './enums/exam-status.enum';

/**
 * 상태를 저장하지 않고 매번 계산한다 — 정원 마감 로직 없음(요구사항 없음).
 * 경계값은 포함: now === openAt → OPEN, now === closeAt → OPEN.
 */
export function computeExamStatus(openAt: Date, closeAt: Date, now: Date = new Date()): ExamStatus {
  if (now.getTime() < openAt.getTime()) {
    return ExamStatus.SCHEDULED;
  }
  if (now.getTime() > closeAt.getTime()) {
    return ExamStatus.CLOSED;
  }
  return ExamStatus.OPEN;
}

/** 신청 가능 기간(application_open_at ~ application_close_at)인지 — 경계값 포함. */
export function isApplicationOpen(
  applicationOpenAt: Date,
  applicationCloseAt: Date,
  now: Date = new Date(),
): boolean {
  return (
    now.getTime() >= applicationOpenAt.getTime() && now.getTime() <= applicationCloseAt.getTime()
  );
}
