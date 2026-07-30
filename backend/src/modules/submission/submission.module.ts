import { Module } from '@nestjs/common';
import { SUBMISSION_REPOSITORY } from './domain/submission.repository.interface';
import { VerificationFailedListener } from './application/listeners/verification-failed.listener';
import { SubmissionService } from './application/services/submission.service';
import { SupabaseSubmissionRepository } from './infrastructure/repositories/supabase-submission.repository';
import { SubmissionController } from './presentation/submission.controller';

@Module({
  controllers: [SubmissionController],
  providers: [
    SubmissionService,
    VerificationFailedListener,
    { provide: SUBMISSION_REPOSITORY, useClass: SupabaseSubmissionRepository },
  ],
  exports: [SubmissionService],
})
export class SubmissionModule {}
