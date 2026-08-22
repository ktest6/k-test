import { Module } from '@nestjs/common';
import { MailModule } from '../../infrastructure/mail/mail.module';
import { AiModule } from '../ai/ai.module';
import { QuestionModule } from '../question/question.module';
import { UserModule } from '../user/user.module';
import { EXAM_RESULT_REPOSITORY } from './domain/exam-result.repository.interface';
import { SCORING_REPOSITORY } from './domain/scoring.repository.interface';
import { AnswerSavedListener } from './application/listeners/answer-saved.listener';
import { ExamResultRecordedListener } from './application/listeners/exam-result-recorded.listener';
import { ExamResultService } from './application/services/exam-result.service';
import { ScoringService } from './application/services/scoring.service';
import { SupabaseExamResultRepository } from './infrastructure/repositories/supabase-exam-result.repository';
import { SupabaseScoringRepository } from './infrastructure/repositories/supabase-scoring.repository';
import { AdminScoringController } from './presentation/admin-scoring.controller';
import { ScoringController } from './presentation/scoring.controller';

@Module({
  imports: [AiModule, QuestionModule, UserModule, MailModule],
  controllers: [ScoringController, AdminScoringController],
  providers: [
    ScoringService,
    ExamResultService,
    AnswerSavedListener,
    ExamResultRecordedListener,
    { provide: SCORING_REPOSITORY, useClass: SupabaseScoringRepository },
    { provide: EXAM_RESULT_REPOSITORY, useClass: SupabaseExamResultRepository },
  ],
  exports: [ScoringService, ExamResultService],
})
export class ScoringModule {}
