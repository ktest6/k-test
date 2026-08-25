import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { describeError } from '../../../../common/utils/describe-error.util';
import { MailService } from '../../../../infrastructure/mail/mail.service';
import { UserService } from '../../../user/application/services/user.service';
import {
  SESSION_DISQUALIFIED_EVENT,
  SessionDisqualifiedEvent,
} from '../../domain/events/session-disqualified.event';

/**
 * exam-session.disqualified 이벤트를 받아 응시자에게 "실격 처리됐다" 메일을
 * 사유와 함께 보낸다. 메일 발송 실패는(SMTP 장애 등) 로그만 남기고 삼킨다 —
 * 이미 실격 처리는 끝났으므로 안내 메일 하나 실패했다고 되돌릴 이유가 없다.
 */
@Injectable()
export class SessionDisqualifiedListener {
  private readonly logger = new Logger(SessionDisqualifiedListener.name);

  constructor(
    private readonly userService: UserService,
    private readonly mailService: MailService,
  ) {}

  @OnEvent(SESSION_DISQUALIFIED_EVENT)
  async handle(event: SessionDisqualifiedEvent): Promise<void> {
    try {
      const user = await this.userService.findById(event.userId);
      await this.mailService.sendDisqualificationNotice(
        user.email,
        event.reason,
        event.examStartedAt,
      );
    } catch (err) {
      this.logger.error(
        `실격 안내 메일 발송 실패 (examSessionId=${event.examSessionId}, userId=${event.userId}): ${describeError(err)}`,
      );
    }
  }
}
