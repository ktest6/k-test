import { VerificationStatus } from '../enums/verification-status.enum';
import { VerificationType } from '../enums/verification-type.enum';

export class IdentityVerificationSession {
  constructor(
    readonly id: string,
    readonly submissionId: string,
    readonly userId: string,
    readonly type: VerificationType,
    readonly status: VerificationStatus,
    readonly providerRef: string | null,
    readonly createdAt: Date,
    readonly expiresAt: Date,
    readonly nextCheckAt: Date | null,
  ) {}
}
