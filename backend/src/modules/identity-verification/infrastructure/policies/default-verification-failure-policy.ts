import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import { VerificationFailureAction } from '../../domain/enums/verification-failure-action.enum';
import { VerificationFailurePolicy } from '../../domain/policies/verification-failure-policy.interface';

/**
 * consecutiveFailures = 0            -> NONE
 * 1 <= consecutiveFailures < max     -> WARNING
 * consecutiveFailures >= max         -> DISQUALIFICATION
 * `max` is `IDENTITY_VERIFICATION_MAX_FAILURES_BEFORE_DISQUALIFICATION`.
 */
@Injectable()
export class DefaultVerificationFailurePolicy implements VerificationFailurePolicy {
  constructor(@Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>) {}

  decide(consecutiveFailures: number): VerificationFailureAction {
    const { maxFailuresBeforeDisqualification } = this.config.identityVerification;

    if (consecutiveFailures <= 0) {
      return VerificationFailureAction.NONE;
    }
    if (consecutiveFailures >= maxFailuresBeforeDisqualification) {
      return VerificationFailureAction.DISQUALIFICATION;
    }
    return VerificationFailureAction.WARNING;
  }
}
