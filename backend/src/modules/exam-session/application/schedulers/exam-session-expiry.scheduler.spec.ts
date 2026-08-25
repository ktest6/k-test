import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import { ExamSessionReportService } from '../services/exam-session-report.service';
import { ExamSessionExpiryScheduler } from './exam-session-expiry.scheduler';

function buildConfig(
  overrides: Partial<{ reportRetrySchedulerEnabled: boolean }> = {},
): ConfigType<typeof appConfig> {
  return {
    reportRetrySchedulerEnabled: overrides.reportRetrySchedulerEnabled ?? true,
  } as ConfigType<typeof appConfig>;
}

describe('ExamSessionExpiryScheduler', () => {
  it('delegates to ExamSessionReportService.expireAbandonedSessions', async () => {
    const expireAbandonedSessions = jest
      .fn()
      .mockResolvedValue({ expiredCount: 1, forcedSubmitCount: 2 });
    const examSessionReportService = {
      expireAbandonedSessions,
    } as unknown as ExamSessionReportService;
    const scheduler = new ExamSessionExpiryScheduler(examSessionReportService, buildConfig());

    await scheduler.handleAbandonedSessions();

    expect(expireAbandonedSessions).toHaveBeenCalledTimes(1);
  });

  it('skips a tick that starts while the previous run is still in progress', async () => {
    let resolveFirstRun: () => void = () => {};
    const firstRunPromise = new Promise<{ expiredCount: number; forcedSubmitCount: number }>(
      (resolve) => {
        resolveFirstRun = () => resolve({ expiredCount: 0, forcedSubmitCount: 0 });
      },
    );
    const expireAbandonedSessions = jest
      .fn()
      .mockReturnValueOnce(firstRunPromise)
      .mockResolvedValueOnce({ expiredCount: 0, forcedSubmitCount: 0 });
    const examSessionReportService = {
      expireAbandonedSessions,
    } as unknown as ExamSessionReportService;
    const scheduler = new ExamSessionExpiryScheduler(examSessionReportService, buildConfig());

    const firstCall = scheduler.handleAbandonedSessions();
    const secondCall = scheduler.handleAbandonedSessions();
    resolveFirstRun();
    await Promise.all([firstCall, secondCall]);

    expect(expireAbandonedSessions).toHaveBeenCalledTimes(1);
  });

  it('runs again on the next tick once the previous run has finished', async () => {
    const expireAbandonedSessions = jest
      .fn()
      .mockResolvedValue({ expiredCount: 0, forcedSubmitCount: 0 });
    const examSessionReportService = {
      expireAbandonedSessions,
    } as unknown as ExamSessionReportService;
    const scheduler = new ExamSessionExpiryScheduler(examSessionReportService, buildConfig());

    await scheduler.handleAbandonedSessions();
    await scheduler.handleAbandonedSessions();

    expect(expireAbandonedSessions).toHaveBeenCalledTimes(2);
  });

  it('does nothing when the scheduler is disabled via config', async () => {
    const expireAbandonedSessions = jest
      .fn()
      .mockResolvedValue({ expiredCount: 0, forcedSubmitCount: 0 });
    const examSessionReportService = {
      expireAbandonedSessions,
    } as unknown as ExamSessionReportService;
    const scheduler = new ExamSessionExpiryScheduler(
      examSessionReportService,
      buildConfig({ reportRetrySchedulerEnabled: false }),
    );

    await scheduler.handleAbandonedSessions();

    expect(expireAbandonedSessions).not.toHaveBeenCalled();
  });
});
