import { AppConfig } from '../../../../config/configuration';
import { VerificationSchedulerService } from './verification-scheduler.service';

function buildConfig(minIntervalMinutes: number, maxIntervalMinutes: number): AppConfig {
  return {
    env: 'test',
    port: 3000,
    corsOrigin: '*',
    swaggerEnabled: false,
    supabase: { url: '', anonKey: '', serviceRoleKey: '' },
    identityVerification: {
      minIntervalMinutes,
      maxIntervalMinutes,
      maxFailuresBeforeDisqualification: 2,
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

describe('VerificationSchedulerService', () => {
  it('always computes a next check time within [min, max] minutes of `from`', () => {
    const min = 5;
    const max = 15;
    const service = new VerificationSchedulerService(buildConfig(min, max));
    const from = new Date('2026-01-01T00:00:00.000Z');

    for (let i = 0; i < 200; i++) {
      const nextCheckAt = service.computeNextCheckAt(from);
      const diffMinutes = (nextCheckAt.getTime() - from.getTime()) / 60_000;

      expect(diffMinutes).toBeGreaterThanOrEqual(min);
      expect(diffMinutes).toBeLessThanOrEqual(max);
    }
  });

  it('returns the fixed offset when min equals max', () => {
    const service = new VerificationSchedulerService(buildConfig(10, 10));
    const from = new Date('2026-01-01T00:00:00.000Z');

    const nextCheckAt = service.computeNextCheckAt(from);

    expect(nextCheckAt.getTime() - from.getTime()).toBe(10 * 60_000);
  });

  describe('isDue', () => {
    const service = new VerificationSchedulerService(buildConfig(5, 15));

    it('is false before the scheduled time', () => {
      const nextCheckAt = new Date('2026-01-01T00:10:00.000Z');
      const now = new Date('2026-01-01T00:09:00.000Z');
      expect(service.isDue(nextCheckAt, now)).toBe(false);
    });

    it('is true at or after the scheduled time', () => {
      const nextCheckAt = new Date('2026-01-01T00:10:00.000Z');
      const now = new Date('2026-01-01T00:10:00.000Z');
      expect(service.isDue(nextCheckAt, now)).toBe(true);
    });
  });
});
