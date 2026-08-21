import { Module } from '@nestjs/common';
import { AnswerModule } from '../answer/answer.module';
import { ExamModule } from '../exam/exam.module';
import { ExamQuestionModule } from '../exam-question/exam-question.module';
import { ScoringModule } from '../scoring/scoring.module';
import { VerificationsModule } from '../verifications/verifications.module';
import { EXAM_SESSION_REPOSITORY } from './domain/exam-session.repository.interface';
import { ExamSessionExpiryScheduler } from './application/schedulers/exam-session-expiry.scheduler';
import { ExamSessionAnswerService } from './application/services/exam-session-answer.service';
import { ExamSessionQuestionService } from './application/services/exam-session-question.service';
import { ExamSessionService } from './application/services/exam-session.service';
import { SupabaseExamSessionRepository } from './infrastructure/repositories/supabase-exam-session.repository';
import { AdminExamSessionController } from './presentation/admin-exam-session.controller';
import { ExamSessionController } from './presentation/exam-session.controller';
import { MypageController } from './presentation/mypage.controller';

@Module({
  imports: [ExamModule, ExamQuestionModule, VerificationsModule, AnswerModule, ScoringModule],
  controllers: [ExamSessionController, MypageController, AdminExamSessionController],
  providers: [
    ExamSessionService,
    ExamSessionQuestionService,
    ExamSessionAnswerService,
    ExamSessionExpiryScheduler,
    { provide: EXAM_SESSION_REPOSITORY, useClass: SupabaseExamSessionRepository },
  ],
  exports: [ExamSessionService, ExamSessionQuestionService, ExamSessionAnswerService],
})
export class ExamSessionModule {}
