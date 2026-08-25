export class ExamResult {
  constructor(
    readonly id: string,
    readonly examSessionId: string,
    readonly finalGrade: string,
    readonly percentile: number | null,
    readonly domainScores: Record<string, unknown> | null,
    readonly crossValidationSignals: Record<string, unknown> | null,
    /** /finalize 응답 원본 전체(가공 없음). */
    readonly rawResponse: Record<string, unknown>,
    readonly createdAt: Date,
  ) {}
}
