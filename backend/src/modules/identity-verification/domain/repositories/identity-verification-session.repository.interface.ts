import { IdentityVerificationSession } from '../entities/identity-verification-session.entity';
import { VerificationStatus } from '../enums/verification-status.enum';
import { VerificationType } from '../enums/verification-type.enum';

export interface CreateSessionInput {
  submissionId: string;
  userId: string;
  type: VerificationType;
  providerRef: string | null;
  expiresAt: Date;
}

export const IDENTITY_VERIFICATION_SESSION_REPOSITORY = Symbol(
  'IDENTITY_VERIFICATION_SESSION_REPOSITORY',
);

export interface IdentityVerificationSessionRepository {
  create(input: CreateSessionInput): Promise<IdentityVerificationSession>;
  findById(id: string): Promise<IdentityVerificationSession | null>;
  updateStatus(
    id: string,
    status: VerificationStatus,
    nextCheckAt?: Date | null,
  ): Promise<IdentityVerificationSession>;
  findLatestBySubmissionId(submissionId: string): Promise<IdentityVerificationSession | null>;
}
