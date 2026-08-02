import { AnswerStatus } from '../enums/answer-status.enum';
import { AnswerType } from '../enums/answer-type.enum';

export class Answer {
  constructor(
    readonly id: string,
    readonly examSessionId: string,
    readonly questionId: string,
    readonly type: AnswerType,
    readonly contentText: string | null,
    readonly audioFileUrl: string | null,
    readonly status: AnswerStatus,
    readonly modifiedAt: Date,
  ) {}
}
