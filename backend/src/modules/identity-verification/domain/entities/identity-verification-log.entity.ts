export class IdentityVerificationLog {
  constructor(
    readonly id: string,
    readonly sessionId: string,
    readonly attemptId: string | null,
    readonly eventType: string,
    readonly payload: Record<string, unknown>,
    readonly createdAt: Date,
  ) {}
}
