import { VerificationFailureAction } from '../enums/verification-failure-action.enum';

export const IDENTITY_VERIFICATION_FAILED_EVENT = 'identity-verification.failed';
export const IDENTITY_VERIFICATION_SUCCEEDED_EVENT = 'identity-verification.succeeded';

/**
 * Published instead of calling the Submission module directly, so
 * Identity Verification never imports it — Submission listens and decides
 * how to react (e.g. today: warn/disqualify; tomorrow: something else).
 */
export class IdentityVerificationFailedEvent {
  constructor(
    readonly submissionId: string,
    readonly userId: string,
    readonly sessionId: string,
    readonly consecutiveFailures: number,
    readonly action: VerificationFailureAction,
  ) {}
}

export class IdentityVerificationSucceededEvent {
  constructor(
    readonly submissionId: string,
    readonly userId: string,
    readonly sessionId: string,
  ) {}
}
