import { Module } from '@nestjs/common';
import { SubmissionModule } from '../submission/submission.module';
import { SCORING_REPOSITORY } from './domain/scoring.repository.interface';
import { ScoringService } from './application/services/scoring.service';
import { SupabaseScoringRepository } from './infrastructure/repositories/supabase-scoring.repository';
import { ScoringController } from './presentation/scoring.controller';

@Module({
  imports: [SubmissionModule],
  controllers: [ScoringController],
  providers: [ScoringService, { provide: SCORING_REPOSITORY, useClass: SupabaseScoringRepository }],
})
export class ScoringModule {}
