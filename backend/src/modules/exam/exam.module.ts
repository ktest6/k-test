import { Module } from '@nestjs/common';
import { EXAM_APPLICATION_REPOSITORY } from './domain/exam-application.repository.interface';
import { EXAM_REPOSITORY } from './domain/exam.repository.interface';
import { ExamApplicationService } from './application/services/exam-application.service';
import { ExamService } from './application/services/exam.service';
import { SupabaseExamApplicationRepository } from './infrastructure/repositories/supabase-exam-application.repository';
import { SupabaseExamRepository } from './infrastructure/repositories/supabase-exam.repository';
import { AdminExamController } from './presentation/admin-exam.controller';
import { ExamController } from './presentation/exam.controller';

@Module({
  controllers: [ExamController, AdminExamController],
  providers: [
    ExamService,
    ExamApplicationService,
    { provide: EXAM_REPOSITORY, useClass: SupabaseExamRepository },
    { provide: EXAM_APPLICATION_REPOSITORY, useClass: SupabaseExamApplicationRepository },
  ],
  exports: [ExamService, ExamApplicationService],
})
export class ExamModule {}
