export class Exam {
  constructor(
    readonly id: string,
    readonly roundName: string,
    readonly applicationOpenAt: Date,
    readonly applicationCloseAt: Date,
    readonly openAt: Date,
    readonly closeAt: Date,
    readonly capacity: number,
    readonly createdAt: Date,
  ) {}
}
