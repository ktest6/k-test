import { VerificationFailureAction } from '../enums/verification-failure-action.enum';

export const VERIFICATION_FAILURE_POLICY = Symbol('VERIFICATION_FAILURE_POLICY');

/**
 * Maps consecutive-failure count to an action. Swappable so failure
 * handling can change (e.g. per-test thresholds) without touching the
 * service that calls it.
 */
export interface VerificationFailurePolicy {
  decide(consecutiveFailures: number): VerificationFailureAction;
}
