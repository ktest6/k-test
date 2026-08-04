import { Module } from '@nestjs/common';
import { AiModule } from '../ai/ai.module';
import { ExamModule } from '../exam/exam.module';
import { UserModule } from '../user/user.module';
import { EarphoneDetectionService } from './application/services/earphone-detection.service';
import { ExamAccessService } from './application/services/exam-access.service';
import { IdCardUploadUrlService } from './application/services/id-card-upload-url.service';
import { IdCardVerificationService } from './application/services/id-card-verification.service';
import { EarphoneController } from './presentation/earphone.controller';
import { IdCardController } from './presentation/id-card.controller';

@Module({
  imports: [AiModule, UserModule, ExamModule],
  controllers: [IdCardController, EarphoneController],
  providers: [
    ExamAccessService,
    IdCardUploadUrlService,
    IdCardVerificationService,
    EarphoneDetectionService,
  ],
  exports: [IdCardVerificationService],
})
export class VerificationsModule {}
