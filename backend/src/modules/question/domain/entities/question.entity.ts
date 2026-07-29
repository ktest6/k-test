import { QuestionType } from '../enums/question-type.enum';

export class Question {
  constructor(
    readonly id: string,
    readonly testId: string,
    readonly type: QuestionType,
    readonly content: string,
    readonly choices: string[] | null,
    readonly correctAnswer: string | null,
    readonly points: number,
    readonly createdAt: Date,
  ) {}
}
