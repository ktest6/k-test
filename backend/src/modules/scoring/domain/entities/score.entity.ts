export class Score {
  constructor(
    readonly id: string,
    readonly answerId: string,
    readonly rawResponse: Record<string, unknown>,
    readonly createdAt: Date,
  ) {}
}
