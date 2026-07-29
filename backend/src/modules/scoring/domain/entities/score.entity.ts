export class Score {
  constructor(
    readonly id: string,
    readonly submissionId: string,
    readonly totalScore: number,
    readonly maxScore: number,
    readonly gradedAt: Date,
  ) {}
}
