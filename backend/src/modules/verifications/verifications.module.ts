import { HttpModule } from '@nestjs/axios';
import { Module } from '@nestjs/common';
import { ExamModule } from '../exam/exam.module';
import { UserModule } from '../user/user.module';
import { ExamAccessService } from './application/services/exam-access.service';
import { IdCardUploadUrlService } from './application/services/id-card-upload-url.service';
import { IdCardVerificationService } from './application/services/id-card-verification.service';
import { IdCardController } from './presentation/id-card.controller';

@Module({
  imports: [HttpModule, UserModule, ExamModule],
  controllers: [IdCardController],
  providers: [ExamAccessService, IdCardUploadUrlService, IdCardVerificationService],
  exports: [IdCardVerificationService],
})
export class VerificationsModule {}
