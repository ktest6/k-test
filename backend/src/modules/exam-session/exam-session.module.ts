import { Module } from '@nestjs/common';
import { ExamModule } from '../exam/exam.module';
import { ExamQuestionModule } from '../exam-question/exam-question.module';
import { EXAM_SESSION_REPOSITORY } from './domain/exam-session.repository.interface';
import { ExamSessionQuestionService } from './application/services/exam-session-question.service';
import { ExamSessionService } from './application/services/exam-session.service';
import { SupabaseExamSessionRepository } from './infrastructure/repositories/supabase-exam-session.repository';
import { ExamSessionController } from './presentation/exam-session.controller';

@Module({
  imports: [ExamModule, ExamQuestionModule],
  controllers: [ExamSessionController],
  providers: [
    ExamSessionService,
    ExamSessionQuestionService,
    { provide: EXAM_SESSION_REPOSITORY, useClass: SupabaseExamSessionRepository },
  ],
  exports: [ExamSessionService, ExamSessionQuestionService],
})
export class ExamSessionModule {}
