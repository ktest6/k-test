export class Test {
  constructor(
    readonly id: string,
    readonly title: string,
    readonly description: string | null,
    readonly durationMinutes: number,
    readonly createdBy: string,
    readonly createdAt: Date,
  ) {}
}
