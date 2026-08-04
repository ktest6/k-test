import { HttpModule } from '@nestjs/axios';
import { Module } from '@nestjs/common';
import { AI_PROVIDER } from './domain/ports/ai-provider.port';
import { IDENTITY_PROVIDER } from './domain/ports/identity-provider.port';
import { MONITORING_PROVIDER } from './domain/ports/monitoring-provider.port';
import { QUESTION_GENERATOR } from './domain/ports/question-generator.port';
import { SCORING_PROVIDER } from './domain/ports/scoring-provider.port';
import { AiService } from './application/services/ai.service';
import { AssessmentScoringAdapter } from './infrastructure/providers/assessment-scoring.adapter';
import { FastApiIdentityAdapter } from './infrastructure/providers/fastapi-identity.adapter';
import { MockQuestionGeneratorAdapter } from './infrastructure/providers/mock-question-generator.adapter';
import { MonitoringAdapter } from './infrastructure/providers/monitoring.adapter';
import { StubAiProviderAdapter } from './infrastructure/providers/stub-ai-provider.adapter';
import { AiController } from './presentation/ai.controller';

@Module({
  imports: [HttpModule],
  controllers: [AiController],
  providers: [
    AiService,
    { provide: AI_PROVIDER, useClass: StubAiProviderAdapter },
    { provide: QUESTION_GENERATOR, useClass: MockQuestionGeneratorAdapter },
    { provide: SCORING_PROVIDER, useClass: AssessmentScoringAdapter },
    { provide: MONITORING_PROVIDER, useClass: MonitoringAdapter },
    { provide: IDENTITY_PROVIDER, useClass: FastApiIdentityAdapter },
  ],
  exports: [QUESTION_GENERATOR, SCORING_PROVIDER, MONITORING_PROVIDER, IDENTITY_PROVIDER],
})
export class AiModule {}
