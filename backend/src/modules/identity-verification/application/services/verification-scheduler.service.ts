import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';

/**
 * Pure calculation of when the next periodic re-verification is due.
 *
 * `computeNextCheckAt` is called once, at the moment a verification
 * succeeds, and the result is persisted on the session — it is NOT
 * recomputed on every status poll (that would hand the client a moving
 * target and make "when is my next check" undefined). No push mechanism
 * (WebSocket/SSE) yet — clients poll the persisted `nextCheckAt`, which
 * keeps this service swappable for a push-based scheduler later.
 */
@Injectable()
export class VerificationSchedulerService {
  constructor(@Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>) {}

  computeNextCheckAt(from: Date): Date {
    const { minIntervalMinutes, maxIntervalMinutes } = this.config.identityVerification;
    const randomMinutes =
      minIntervalMinutes + Math.random() * (maxIntervalMinutes - minIntervalMinutes);
    return new Date(from.getTime() + randomMinutes * 60_000);
  }

  isDue(nextCheckAt: Date, now: Date = new Date()): boolean {
    return now.getTime() >= nextCheckAt.getTime();
  }
}
