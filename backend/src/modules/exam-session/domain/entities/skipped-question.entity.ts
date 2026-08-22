export class SkippedQuestion {
  constructor(
    readonly id: string,
    readonly examSessionId: string,
    readonly questionId: string,
    readonly skippedAt: Date,
  ) {}
}
