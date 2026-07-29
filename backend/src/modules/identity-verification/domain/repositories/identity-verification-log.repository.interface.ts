import { IdentityVerificationLog } from '../entities/identity-verification-log.entity';

export interface CreateLogInput {
  sessionId: string;
  attemptId: string | null;
  eventType: string;
  payload: Record<string, unknown>;
}

export const IDENTITY_VERIFICATION_LOG_REPOSITORY = Symbol('IDENTITY_VERIFICATION_LOG_REPOSITORY');

export interface IdentityVerificationLogRepository {
  create(input: CreateLogInput): Promise<IdentityVerificationLog>;
  findBySubmissionId(submissionId: string): Promise<IdentityVerificationLog[]>;
}
