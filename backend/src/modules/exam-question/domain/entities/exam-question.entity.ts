/** 회차-문항 배정 한 건. 문항 하나가 여러 회차에 배정될 수 있어 다대다 관계의 조인 행이다. */
export class ExamQuestion {
  constructor(
    readonly id: string,
    readonly examId: string,
    readonly questionId: string,
    readonly assignedBy: string | null,
    readonly createdAt: Date,
  ) {}
}
