import { Module } from '@nestjs/common';
import { AiModule } from '../ai/ai.module';
import { AnswerModule } from '../answer/answer.module';
import { ExamModule } from '../exam/exam.module';
import { ExamQuestionModule } from '../exam-question/exam-question.module';
import { PROCTORING_EVENT_REPOSITORY } from '../monitoring/domain/proctoring-event.repository.interface';
import { SupabaseProctoringEventRepository } from '../monitoring/infrastructure/repositories/supabase-proctoring-event.repository';
import { QuestionModule } from '../question/question.module';
import { ScoringModule } from '../scoring/scoring.module';
import { UserModule } from '../user/user.module';
import { VerificationsModule } from '../verifications/verifications.module';
import { EXAM_SESSION_REPOSITORY } from './domain/exam-session.repository.interface';
import { SKIPPED_QUESTION_REPOSITORY } from './domain/skipped-question.repository.interface';
import { ExamSessionExpiryScheduler } from './application/schedulers/exam-session-expiry.scheduler';
import { ExamSessionReportRetryScheduler } from './application/schedulers/exam-session-report-retry.scheduler';
import { ExamSessionAnswerService } from './application/services/exam-session-answer.service';
import { ExamSessionQuestionService } from './application/services/exam-session-question.service';
import { ExamSessionReportService } from './application/services/exam-session-report.service';
import { ExamSessionService } from './application/services/exam-session.service';
import { MypageReportService } from './application/services/mypage-report.service';
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
    UserModule,
  ],
  controllers: [ExamSessionController, MypageController, AdminExamSessionController],
  providers: [
    ExamSessionService,
    ExamSessionQuestionService,
    ExamSessionAnswerService,
    ExamSessionReportService,
    ExamSessionReportRetryScheduler,
    ExamSessionExpiryScheduler,
    MypageReportService,
    { provide: EXAM_SESSION_REPOSITORY, useClass: SupabaseExamSessionRepository },
    { provide: SKIPPED_QUESTION_REPOSITORY, useClass: SupabaseSkippedQuestionRepository },
    // MonitoringModule이 이미 ExamSessionModule을 가져다 쓰기 때문에(순환 참조 방지),
    // 리포트에서 부정행위 로그를 읽기 위해 여기서 리포지토리를 별도로 바인딩한다.
    { provide: PROCTORING_EVENT_REPOSITORY, useClass: SupabaseProctoringEventRepository },
  ],
  exports: [ExamSessionService, ExamSessionQuestionService, ExamSessionAnswerService],
})
export class ExamSessionModule {}
