import { Module } from '@nestjs/common';
import { MailModule } from '../../infrastructure/mail/mail.module';
import { AdminModule } from '../admin/admin.module';
import { UserModule } from '../user/user.module';
import { AuthService } from './application/services/auth.service';
import { EmailVerificationService } from './application/services/email-verification.service';
import { AuthController } from './presentation/auth.controller';

@Module({
  imports: [UserModule, AdminModule, MailModule],
  controllers: [AuthController],
  providers: [AuthService, EmailVerificationService],
})
export class AuthModule {}
