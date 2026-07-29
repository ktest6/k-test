import { AppConfig } from '../../../../config/configuration';
import { VerificationFailureAction } from '../../domain/enums/verification-failure-action.enum';
import { DefaultVerificationFailurePolicy } from './default-verification-failure-policy';

function buildConfig(maxFailuresBeforeDisqualification: number): AppConfig {
  return {
    env: 'test',
    port: 3000,
    corsOrigin: '*',
    swaggerEnabled: false,
    supabase: { url: '', anonKey: '', serviceRoleKey: '' },
    identityVerification: {
      minIntervalMinutes: 5,
      maxIntervalMinutes: 15,
      maxFailuresBeforeDisqualification,
      mockForceFail: false,
    },
    jwt: {
      accessSecret: 'test-access-secret',
      accessExpiresIn: '1h',
      refreshSecret: 'test-refresh-secret',
      refreshExpiresIn: '14d',
    },
  };
}

describe('DefaultVerificationFailurePolicy', () => {
  it('returns NONE when there are no consecutive failures', () => {
    const policy = new DefaultVerificationFailurePolicy(buildConfig(2));
    expect(policy.decide(0)).toBe(VerificationFailureAction.NONE);
  });

  it('returns WARNING while under the disqualification threshold', () => {
    const policy = new DefaultVerificationFailurePolicy(buildConfig(2));
    expect(policy.decide(1)).toBe(VerificationFailureAction.WARNING);
  });

  it('returns DISQUALIFICATION once the threshold is reached', () => {
    const policy = new DefaultVerificationFailurePolicy(buildConfig(2));
    expect(policy.decide(2)).toBe(VerificationFailureAction.DISQUALIFICATION);
    expect(policy.decide(5)).toBe(VerificationFailureAction.DISQUALIFICATION);
  });

  it('respects a configurable threshold', () => {
    const policy = new DefaultVerificationFailurePolicy(buildConfig(1));
    expect(policy.decide(1)).toBe(VerificationFailureAction.DISQUALIFICATION);
  });
});
