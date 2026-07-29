/**
 * Action the rest of the system (Submission module) should take when a
 * verification attempt fails. Kept as an open-ended enum so the failure
 * policy can be swapped without touching callers.
 */
export enum VerificationFailureAction {
  NONE = 'NONE',
  WARNING = 'WARNING',
  DISQUALIFICATION = 'DISQUALIFICATION',
}
