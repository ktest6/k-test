import { Module } from '@nestjs/common';
import { AiModule } from '../ai/ai.module';
import { QuestionModule } from '../question/question.module';
import { SCORING_REPOSITORY } from './domain/scoring.repository.interface';
import { AnswerSavedListener } from './application/listeners/answer-saved.listener';
import { ScoringService } from './application/services/scoring.service';
import { SupabaseScoringRepository } from './infrastructure/repositories/supabase-scoring.repository';
import { AdminScoringController } from './presentation/admin-scoring.controller';
import { ScoringController } from './presentation/scoring.controller';

@Module({
  imports: [AiModule, QuestionModule],
  controllers: [ScoringController, AdminScoringController],
  providers: [
    ScoringService,
    AnswerSavedListener,
    { provide: SCORING_REPOSITORY, useClass: SupabaseScoringRepository },
  ],
  exports: [ScoringService],
})
export class ScoringModule {}
