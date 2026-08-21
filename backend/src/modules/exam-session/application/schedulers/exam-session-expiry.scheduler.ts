import { Injectable, Logger } from '@nestjs/common';
import { Cron, CronExpression } from '@nestjs/schedule';
import { ExamSessionService } from '../services/exam-session.service';

/**
 * 마감시각이 지나도록 아무도 조회하지 않아 INPROGRESS로 방치된 세션을 주기적으로 훑어서
 * SUBMITTED로 동기화한다. 조회 시점 lazy 동기화(ExamSessionService.syncExpiredSession)만으로는
 * 화면을 꺼두고 다시 돌아오지 않는 응시자의 세션이 영영 정리되지 않기 때문에 필요한 안전망이다.
 */
@Injectable()
export class ExamSessionExpiryScheduler {
  private readonly logger = new Logger(ExamSessionExpiryScheduler.name);

  constructor(private readonly examSessionService: ExamSessionService) {}

  @Cron(CronExpression.EVERY_5_MINUTES)
  async handleExpiredSessions(): Promise<void> {
    const syncedCount = await this.examSessionService.syncAllExpiredSessions();
    if (syncedCount > 0) {
      this.logger.log(`마감 지난 세션 ${syncedCount}건을 SUBMITTED로 동기화했습니다.`);
    }
  }
}
