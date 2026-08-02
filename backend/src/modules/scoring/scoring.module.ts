import { Module } from '@nestjs/common';
import { SCORING_REPOSITORY } from './domain/scoring.repository.interface';
import { ScoringService } from './application/services/scoring.service';
import { SupabaseScoringRepository } from './infrastructure/repositories/supabase-scoring.repository';
import { ScoringController } from './presentation/scoring.controller';

@Module({
  controllers: [ScoringController],
  providers: [ScoringService, { provide: SCORING_REPOSITORY, useClass: SupabaseScoringRepository }],
  exports: [ScoringService],
})
export class ScoringModule {}
