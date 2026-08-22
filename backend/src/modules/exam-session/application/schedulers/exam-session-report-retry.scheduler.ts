import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { Cron, CronExpression } from '@nestjs/schedule';
import { appConfig } from '../../../../config/configuration';
import { ExamSessionReportService } from '../services/exam-session-report.service';

/**
 * 문항을 이미 다 처리(답변/스킵)했는데 최종 리포트 제출(/finalize)이 실패해서
 * SUBMITTED로 못 넘어간 세션을 주기적으로 재시도한다. 응시자는 더 이상 답안이나
 * 스킵을 보낼 일이 없으므로(이미 다 끝냈으니) checkAndFinalize가 다시 불릴 자연스러운
 * 계기가 없다 — 이 스케줄러가 그 계기를 만들어준다.
 */
@Injectable()
export class ExamSessionReportRetryScheduler {
  private readonly logger = new Logger(ExamSessionReportRetryScheduler.name);
  /** 처리할 세션이 많거나 assessment 응답이 느리면 한 번 실행이 5분을 넘길 수 있다 —
   * @Cron은 이전 실행이 끝났는지 신경 쓰지 않으므로, 같은 세션에 /score·/finalize를
   * 중복 호출하지 않도록 이 플래그로 겹치는 실행을 막는다. */
  private isRunning = false;

  constructor(
    private readonly examSessionReportService: ExamSessionReportService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  @Cron(CronExpression.EVERY_5_MINUTES)
  async handlePendingReports(): Promise<void> {
    if (!this.config.reportRetrySchedulerEnabled) {
      return;
    }

    if (this.isRunning) {
      this.logger.warn('이전 재시도 배치가 아직 실행 중이라 이번 tick은 건너뜁니다.');
      return;
    }

    this.isRunning = true;
    try {
      const submittedCount = await this.examSessionReportService.syncPendingReports();
      if (submittedCount > 0) {
        this.logger.log(`재시도로 최종 리포트 제출을 완료한 세션 ${submittedCount}건.`);
      }
    } finally {
      this.isRunning = false;
    }
  }
}
