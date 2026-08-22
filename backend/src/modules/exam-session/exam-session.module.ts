import { Module } from '@nestjs/common';
import { AiModule } from '../ai/ai.module';
import { AnswerModule } from '../answer/answer.module';
import { ExamModule } from '../exam/exam.module';
import { ExamQuestionModule } from '../exam-question/exam-question.module';
import { QuestionModule } from '../question/question.module';
import { ScoringModule } from '../scoring/scoring.module';
import { VerificationsModule } from '../verifications/verifications.module';
import { EXAM_SESSION_REPOSITORY } from './domain/exam-session.repository.interface';
import { SKIPPED_QUESTION_REPOSITORY } from './domain/skipped-question.repository.interface';
import { ExamSessionReportRetryScheduler } from './application/schedulers/exam-session-report-retry.scheduler';
import { ExamSessionAnswerService } from './application/services/exam-session-answer.service';
import { ExamSessionQuestionService } from './application/services/exam-session-question.service';
import { ExamSessionReportService } from './application/services/exam-session-report.service';
import { ExamSessionService } from './application/services/exam-session.service';
import { SupabaseExamSessionRepository } from './infrastructure/repositories/supabase-exam-session.repository';
import { SupabaseSkippedQuestionRepository } from './infrastructure/repositories/supabase-skipped-question.repository';
import { AdminExamSessionController } from './presentation/admin-exam-session.controller';
import { ExamSessionController } from './presentation/exam-session.controller';
import { MypageController } from './presentation/mypage.controller';

@Module({
  imports: [
    ExamModule,
    ExamQuestionModule,
    QuestionModule,
    VerificationsModule,
    AnswerModule,
    ScoringModule,
    AiModule,
  ],
  controllers: [ExamSessionController, MypageController, AdminExamSessionController],
  providers: [
    ExamSessionService,
    ExamSessionQuestionService,
    ExamSessionAnswerService,
    ExamSessionReportService,
    ExamSessionReportRetryScheduler,
    { provide: EXAM_SESSION_REPOSITORY, useClass: SupabaseExamSessionRepository },
    { provide: SKIPPED_QUESTION_REPOSITORY, useClass: SupabaseSkippedQuestionRepository },
  ],
  exports: [ExamSessionService, ExamSessionQuestionService, ExamSessionAnswerService],
})
export class ExamSessionModule {}
