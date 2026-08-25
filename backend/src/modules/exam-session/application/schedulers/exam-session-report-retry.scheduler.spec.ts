import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import { ExamSessionReportService } from '../services/exam-session-report.service';
import { ExamSessionReportRetryScheduler } from './exam-session-report-retry.scheduler';

function buildConfig(
  overrides: Partial<{ reportRetrySchedulerEnabled: boolean }> = {},
): ConfigType<typeof appConfig> {
  return {
    reportRetrySchedulerEnabled: overrides.reportRetrySchedulerEnabled ?? true,
  } as ConfigType<typeof appConfig>;
}

describe('ExamSessionReportRetryScheduler', () => {
  it('delegates to ExamSessionReportService.syncPendingReports', async () => {
    const syncPendingReports = jest.fn().mockResolvedValue(2);
    const examSessionReportService = {
      syncPendingReports,
    } as unknown as ExamSessionReportService;
    const scheduler = new ExamSessionReportRetryScheduler(examSessionReportService, buildConfig());

    await scheduler.handlePendingReports();

    expect(syncPendingReports).toHaveBeenCalledTimes(1);
  });

  it('skips a tick that starts while the previous run is still in progress', async () => {
    let resolveFirstRun: () => void = () => {};
    const firstRunPromise = new Promise<number>((resolve) => {
      resolveFirstRun = () => resolve(1);
    });
    const syncPendingReports = jest
      .fn()
      .mockReturnValueOnce(firstRunPromise)
      .mockResolvedValueOnce(2);
    const examSessionReportService = {
      syncPendingReports,
    } as unknown as ExamSessionReportService;
    const scheduler = new ExamSessionReportRetryScheduler(examSessionReportService, buildConfig());

    const firstCall = scheduler.handlePendingReports();
    const secondCall = scheduler.handlePendingReports();
    resolveFirstRun();
    await Promise.all([firstCall, secondCall]);

    expect(syncPendingReports).toHaveBeenCalledTimes(1);
  });

  it('runs again on the next tick once the previous run has finished', async () => {
    const syncPendingReports = jest.fn().mockResolvedValue(0);
    const examSessionReportService = {
      syncPendingReports,
    } as unknown as ExamSessionReportService;
    const scheduler = new ExamSessionReportRetryScheduler(examSessionReportService, buildConfig());

    await scheduler.handlePendingReports();
    await scheduler.handlePendingReports();

    expect(syncPendingReports).toHaveBeenCalledTimes(2);
  });

  it('does nothing when the scheduler is disabled via config', async () => {
    const syncPendingReports = jest.fn().mockResolvedValue(0);
    const examSessionReportService = {
      syncPendingReports,
    } as unknown as ExamSessionReportService;
    const scheduler = new ExamSessionReportRetryScheduler(
      examSessionReportService,
      buildConfig({ reportRetrySchedulerEnabled: false }),
    );

    await scheduler.handlePendingReports();

    expect(syncPendingReports).not.toHaveBeenCalled();
  });
});
