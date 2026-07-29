import { randomUUID } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import {
  IdentityProvider,
  InitiateChallengeInput,
  InitiateChallengeResult,
  VerifyChallengeInput,
  VerifyChallengeResult,
} from '../../application/ports/identity-provider.port';

/**
 * Placeholder for a real provider (PASS/NICE, face match, OTP, ...).
 * Supports forcing a result so the failure policy (WARNING →
 * DISQUALIFICATION) can be exercised deterministically in tests/dev:
 * - `IDENTITY_VERIFICATION_MOCK_FORCE_FAIL=true` forces every attempt to fail
 * - per-request `forceResult` overrides it further (non-production only)
 */
@Injectable()
export class MockIdentityProviderAdapter implements IdentityProvider {
  constructor(@Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>) {}

  initiate(_input: InitiateChallengeInput): Promise<InitiateChallengeResult> {
    return Promise.resolve({ providerRef: `mock_${randomUUID()}` });
  }

  verify(input: VerifyChallengeInput): Promise<VerifyChallengeResult> {
    const isProduction = this.config.env === 'production';

    let success = true;
    if (this.config.identityVerification.mockForceFail) {
      success = false;
    }
    if (!isProduction && input.forceResult) {
      success = input.forceResult === 'SUCCESS';
    }

    return Promise.resolve({ success, providerRef: input.providerRef });
  }
}
