import { SessionStatus } from '../enums/session-status.enum';

export class ExamSession {
  constructor(
    readonly id: string,
    readonly examId: string,
    readonly userId: string,
    readonly status: SessionStatus,
    /** 재개(재시작) 시도 횟수 — SESSION-01 참고, RESUME_ATTEMPT_LIMIT에 도달하면 BLOCKED로 전환된다. */
    readonly resumeCount: number,
    readonly startedAt: Date,
    readonly currentQuestionId: string | null,
    readonly lastSavedAt: Date | null,
    readonly submittedAt: Date | null,
    readonly createdAt: Date,
  ) {}
}
