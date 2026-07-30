import { VerificationFailureAction } from '../enums/verification-failure-action.enum';

export const VERIFICATION_FAILED_EVENT = 'verification.failed';

/**
 * Verifications 모듈은 Submission 모듈을 직접 호출하지 않고 이 이벤트만
 * 발행한다 — Submission이 구독해서 WARNING/DISQUALIFICATION을 반영한다
 * (submission/application/listeners/verification-failed.listener.ts).
 * 어떤 인증 타입이 실패를 발행했는지는 이벤트 자체가 신경 쓰지 않는다.
 *
 * 현재는 아무 서비스도 이 이벤트를 발행하지 않는다 — id-card 검증이 실제
 * 대조(FastAPI 연동) 없이 matched를 항상 null로 반환하기 때문이다. FastAPI
 * 연동 후 실패 정책을 다시 붙일 때 이 이벤트를 발행하면 된다.
 */
export class VerificationFailedEvent {
  constructor(
    readonly submissionId: string,
    readonly userId: string,
    readonly sessionId: string,
    readonly consecutiveFailures: number,
    readonly action: VerificationFailureAction,
  ) {}
}
