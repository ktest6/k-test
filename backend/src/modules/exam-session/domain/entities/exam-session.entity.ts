import { SessionStatus } from '../enums/session-status.enum';

export class ExamSession {
  constructor(
    readonly id: string,
    readonly examId: string,
    readonly userId: string,
    readonly status: SessionStatus,
    readonly startedAt: Date,
    readonly currentQuestionId: string | null,
    readonly lastSavedAt: Date | null,
    readonly submittedAt: Date | null,
    readonly createdAt: Date,
  ) {}
}
