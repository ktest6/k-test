export const SESSION_DISQUALIFIED_EVENT = 'exam-session.disqualified';

/**
 * exam-session 모듈은 mail 모듈을 직접 호출하지 않고 이 이벤트만 발행한다
 * (exam-result.recorded와 동일한 패턴) — 실격 안내 메일 발송은
 * SessionDisqualifiedListener가 구독해서 처리한다.
 */
export class SessionDisqualifiedEvent {
  constructor(
    readonly examSessionId: string,
    readonly userId: string,
    readonly reason: string,
    /** 실격된 세션이 시작된 시각 — 응시자가 여러 세션을 만들었을 수 있어 "어느 시험이 실격됐는지" 메일에 명시하는 데 쓴다. */
    readonly examStartedAt: Date,
  ) {}
}
