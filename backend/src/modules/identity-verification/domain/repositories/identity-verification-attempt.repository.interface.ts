import { IdentityVerificationAttempt } from '../entities/identity-verification-attempt.entity';
import { AttemptResult } from '../enums/attempt-result.enum';

export interface CreateAttemptInput {
  sessionId: string;
  result: AttemptResult;
  method: string;
  providerRef: string | null;
}

export const IDENTITY_VERIFICATION_ATTEMPT_REPOSITORY = Symbol(
  'IDENTITY_VERIFICATION_ATTEMPT_REPOSITORY',
);

export interface IdentityVerificationAttemptRepository {
  create(input: CreateAttemptInput): Promise<IdentityVerificationAttempt>;
  /** Consecutive FAILED attempts for a submission, counted back from the most recent attempt. */
  countConsecutiveFailures(submissionId: string): Promise<number>;
  findLatestSuccessAt(submissionId: string): Promise<Date | null>;
}
