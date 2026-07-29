import { SubmissionStatus } from '../enums/submission-status.enum';

export class Submission {
  constructor(
    readonly id: string,
    readonly testId: string,
    readonly userId: string,
    readonly status: SubmissionStatus,
    readonly warningCount: number,
    readonly startedAt: Date,
    readonly submittedAt: Date | null,
    readonly createdAt: Date,
  ) {}
}
