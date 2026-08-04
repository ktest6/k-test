import { AnswerType } from '../enums/answer-type.enum';

export const ANSWER_SAVED_EVENT = 'answer.saved';

/**
 * answer 모듈은 scoring 모듈을 직접 호출하지 않고 이 이벤트만 발행한다
 * (document → question 생성과 같은 패턴) — 채점 요청은
 * AnswerSavedListener(scoring 모듈)가 구독해서 처리한다.
 */
export class AnswerSavedEvent {
  constructor(
    readonly answerId: string,
    readonly questionId: string,
    readonly type: AnswerType,
    readonly contentText: string | null,
    readonly audioFileUrl: string | null,
    readonly durationMs: number | null,
  ) {}
}
