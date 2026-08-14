import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import * as nodemailer from 'nodemailer';
import { appConfig } from '../../config/configuration';

/**
 * SMTP 발송 자체가 실패해도 예외를 던지지 않는다 — 이메일 인증은 부가 기능이라
 * 회원가입/재발송 같은 핵심 흐름을 막을 이유가 아니다. 실패는 로그로만 남기고,
 * 호출부(AuthService)가 "발송 실패해도 계속 진행"할 수 있게 한다.
 */
@Injectable()
export class MailService {
  private readonly logger = new Logger(MailService.name);
  private readonly transporter: nodemailer.Transporter;

  constructor(@Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>) {
    this.transporter = nodemailer.createTransport({
      host: this.config.mail.smtpHost,
      port: this.config.mail.smtpPort,
      secure: this.config.mail.smtpPort === 465,
      auth: this.config.mail.smtpUser
        ? { user: this.config.mail.smtpUser, pass: this.config.mail.smtpPassword }
        : undefined,
    });
  }

  async sendVerificationCode(email: string, code: string): Promise<void> {
    try {
      await this.transporter.sendMail({
        from: this.config.mail.from,
        to: email,
        subject: '[K-TEST] 이메일 인증번호',
        text: `인증번호: ${code}\n10분 이내에 입력해주세요.`,
        html: `<p>인증번호: <strong>${code}</strong></p><p>10분 이내에 입력해주세요.</p>`,
      });
    } catch (err) {
      this.logger.warn(`인증 메일 발송 실패 (email=${email}): ${(err as Error).message}`);
    }
  }
}
