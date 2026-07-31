import { Module } from '@nestjs/common';
import { ExamModule } from '../exam/exam.module';
import { EXAM_SESSION_REPOSITORY } from './domain/exam-session.repository.interface';
import { ExamSessionService } from './application/services/exam-session.service';
import { SupabaseExamSessionRepository } from './infrastructure/repositories/supabase-exam-session.repository';
import { ExamSessionController } from './presentation/exam-session.controller';

@Module({
  imports: [ExamModule],
  controllers: [ExamSessionController],
  providers: [
    ExamSessionService,
    { provide: EXAM_SESSION_REPOSITORY, useClass: SupabaseExamSessionRepository },
  ],
  exports: [ExamSessionService],
})
export class ExamSessionModule {}
