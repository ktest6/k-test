import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import * as nodemailer from 'nodemailer';
import { appConfig } from '../../config/configuration';
import { buildVerificationCodeEmail } from './templates/verification-code.template';

/**
 * 이 서비스의 유일한 용도(인증코드 발송)는 실제로 메일이 가는 것 자체가 목적이라,
 * 실패를 조용히 삼키면 호출자가 "성공"으로 착각한 채 응답을 받게 된다 — 사용자는
 * 오지도 않을 메일을 하염없이 기다리게 된다. 그래서 실패는 로그로 남기는 동시에
 * 예외를 그대로 던져서 호출부(AuthService)가 실패를 클라이언트에 알릴 수 있게 한다.
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
    const { subject, text, html } = buildVerificationCodeEmail(code);
    try {
      await this.transporter.sendMail({
        from: this.config.mail.from,
        to: email,
        subject,
        text,
        html,
      });
    } catch (err) {
      this.logger.warn(`인증 메일 발송 실패 (email=${email}): ${(err as Error).message}`);
      throw err;
    }
  }
}
