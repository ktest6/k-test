export const IDENTITY_PROVIDER = Symbol('IDENTITY_PROVIDER');

export interface InitiateChallengeInput {
  userId: string;
  submissionId: string;
}

export interface InitiateChallengeResult {
  providerRef: string;
}

export interface VerifyChallengeInput {
  sessionId: string;
  userId: string;
  providerRef: string | null;
  payload?: Record<string, unknown>;
  /** Dev/test-only override — real providers ignore this. */
  forceResult?: 'SUCCESS' | 'FAILED';
}

export interface VerifyChallengeResult {
  success: boolean;
  providerRef: string | null;
}

/**
 * Abstraction over the actual identity-verification mechanism (PASS/NICE,
 * face match, OTP, ...). The mock adapter is the only implementation today;
 * swapping providers means adding a new adapter, not touching the service.
 */
export interface IdentityProvider {
  initiate(input: InitiateChallengeInput): Promise<InitiateChallengeResult>;
  verify(input: VerifyChallengeInput): Promise<VerifyChallengeResult>;
}
