import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { Cron, CronExpression } from '@nestjs/schedule';
import { appConfig } from '../../../../config/configuration';
import { ExamSessionReportService } from '../services/exam-session-report.service';

/**
 * 마감 후 오래(3시간 이상) INPROGRESS로 방치된 세션을 정리한다. 응시자가 응시
 * 도중 이탈해서 문항을 다 처리하지 못하면 `checkAndFinalize`가 자연히 불릴
 * 계기(답변/스킵)가 더 이상 없어 세션이 영원히 INPROGRESS로 남는다 — 이 스케줄러가
 * 그 계기를 만든다. 답변한 게 하나도 없으면 EXPIRED로, 하나라도 있으면 그때까지
 * 푼 것만이라도 강제로 채점·제출한다(`ExamSessionReportService.expireAbandonedSessions`).
 */
@Injectable()
export class ExamSessionExpiryScheduler {
  private readonly logger = new Logger(ExamSessionExpiryScheduler.name);
  /** 강제 제출 경로도 /score·/finalize를 호출하므로 재시도 스케줄러와 같은 이유로
   * 겹치는 실행을 막는다. */
  private isRunning = false;

  constructor(
    private readonly examSessionReportService: ExamSessionReportService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  @Cron(CronExpression.EVERY_30_MINUTES)
  async handleAbandonedSessions(): Promise<void> {
    // 강제 제출 경로가 assessment를 호출하므로 재시도 스케줄러와 같은 플래그로 묶는다 —
    // assessment가 항상 떠있지 않은 개발 환경에서 둘 다 같이 꺼둘 수 있어야 한다.
    if (!this.config.reportRetrySchedulerEnabled) {
      return;
    }

    if (this.isRunning) {
      this.logger.warn('이전 방치 세션 정리 배치가 아직 실행 중이라 이번 tick은 건너뜁니다.');
      return;
    }

    this.isRunning = true;
    try {
      const { expiredCount, forcedSubmitCount } =
        await this.examSessionReportService.expireAbandonedSessions();
      if (expiredCount > 0 || forcedSubmitCount > 0) {
        this.logger.log(
          `방치 세션 정리: EXPIRED 처리 ${expiredCount}건, 강제 제출 ${forcedSubmitCount}건.`,
        );
      }
    } finally {
      this.isRunning = false;
    }
  }
}
