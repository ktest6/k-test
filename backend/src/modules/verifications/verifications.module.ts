import { HttpModule } from '@nestjs/axios';
import { Module } from '@nestjs/common';
import { UserModule } from '../user/user.module';
import { ExamSessionAccessService } from './application/services/exam-session-access.service';
import { IdCardUploadUrlService } from './application/services/id-card-upload-url.service';
import { IdCardVerificationService } from './application/services/id-card-verification.service';
import { IdCardController } from './presentation/id-card.controller';

@Module({
  imports: [HttpModule, UserModule],
  controllers: [IdCardController],
  providers: [ExamSessionAccessService, IdCardUploadUrlService, IdCardVerificationService],
})
export class VerificationsModule {}
