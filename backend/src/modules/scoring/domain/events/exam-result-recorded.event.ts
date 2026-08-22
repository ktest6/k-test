export const EXAM_RESULT_RECORDED_EVENT = 'exam-result.recorded';

/**
 * scoring 모듈은 user/mail 모듈을 직접 호출하지 않고 이 이벤트만 발행한다
 * (document.uploaded와 동일한 패턴) — 결과 안내 메일 발송은
 * ExamResultRecordedListener가 구독해서 처리한다.
 */
export class ExamResultRecordedEvent {
  constructor(
    readonly examSessionId: string,
    readonly userId: string,
  ) {}
}
