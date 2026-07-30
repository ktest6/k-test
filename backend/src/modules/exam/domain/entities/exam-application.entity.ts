export class ExamApplication {
  constructor(
    readonly id: string,
    readonly examId: string,
    readonly userId: string,
    readonly appliedAt: Date,
  ) {}
}
