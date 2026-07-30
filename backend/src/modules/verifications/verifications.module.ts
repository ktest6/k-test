import { Module } from '@nestjs/common';
import { ExamSessionAccessService } from './application/services/exam-session-access.service';
import { IdCardUploadUrlService } from './application/services/id-card-upload-url.service';
import { IdCardVerificationService } from './application/services/id-card-verification.service';
import { IdCardController } from './presentation/id-card.controller';

@Module({
  controllers: [IdCardController],
  providers: [ExamSessionAccessService, IdCardUploadUrlService, IdCardVerificationService],
})
export class VerificationsModule {}
