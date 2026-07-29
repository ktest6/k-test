import { AttemptResult } from '../enums/attempt-result.enum';

export class IdentityVerificationAttempt {
  constructor(
    readonly id: string,
    readonly sessionId: string,
    readonly result: AttemptResult,
    readonly method: string,
    readonly providerRef: string | null,
    readonly createdAt: Date,
  ) {}
}
