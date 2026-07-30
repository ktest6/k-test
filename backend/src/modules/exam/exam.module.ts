import { Module } from '@nestjs/common';
import { EXAM_REPOSITORY } from './domain/exam.repository.interface';
import { ExamService } from './application/services/exam.service';
import { SupabaseExamRepository } from './infrastructure/repositories/supabase-exam.repository';
import { ExamController } from './presentation/exam.controller';

@Module({
  controllers: [ExamController],
  providers: [ExamService, { provide: EXAM_REPOSITORY, useClass: SupabaseExamRepository }],
  exports: [ExamService],
})
export class ExamModule {}
