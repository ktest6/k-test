import { Module } from '@nestjs/common';
import { EXAM_REPOSITORY } from './domain/exam.repository.interface';
import { ExamService } from './application/services/exam.service';
import { SupabaseExamRepository } from './infrastructure/repositories/supabase-exam.repository';
import { AdminExamController } from './presentation/admin-exam.controller';
import { ExamController } from './presentation/exam.controller';

@Module({
  controllers: [ExamController, AdminExamController],
  providers: [ExamService, { provide: EXAM_REPOSITORY, useClass: SupabaseExamRepository }],
  exports: [ExamService],
})
export class ExamModule {}
