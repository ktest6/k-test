import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { describeError } from '../../../../common/utils/describe-error.util';
import { MailService } from '../../../../infrastructure/mail/mail.service';
import { UserService } from '../../../user/application/services/user.service';
import {
  EXAM_RESULT_RECORDED_EVENT,
  ExamResultRecordedEvent,
} from '../../domain/events/exam-result-recorded.event';

/**
 * exam-result.recorded 이벤트를 받아 응시자에게 "채점 결과가 준비됐다" 메일을
 * 보낸다. 메일 발송 실패는(SMTP 장애 등) 로그만 남기고 삼킨다 — 이미 결과는
 * 저장됐으므로 안내 메일 하나 실패했다고 되돌릴 이유가 없다. 재시도는 하지
 * 않는다(안내용이라 다음 로그인 때 마이페이지에서 확인 가능).
 */
@Injectable()
export class ExamResultRecordedListener {
  private readonly logger = new Logger(ExamResultRecordedListener.name);

  constructor(
    private readonly userService: UserService,
    private readonly mailService: MailService,
  ) {}

  @OnEvent(EXAM_RESULT_RECORDED_EVENT)
  async handle(event: ExamResultRecordedEvent): Promise<void> {
    try {
      const user = await this.userService.findById(event.userId);
      await this.mailService.sendExamResultReady(user.email);
    } catch (err) {
      this.logger.error(
        `결과 안내 메일 발송 실패 (examSessionId=${event.examSessionId}, userId=${event.userId}): ${describeError(err)}`,
      );
    }
  }
}
