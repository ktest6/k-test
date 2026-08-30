import { HttpModule } from '@nestjs/axios';
import { Module } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../config/configuration';
import { AI_PROVIDER } from './domain/ports/ai-provider.port';
import { EARPHONE_PROVIDER } from './domain/ports/earphone-provider.port';
import { FINALIZE_PROVIDER } from './domain/ports/finalize-provider.port';
import { IDENTITY_PROVIDER, IdentityProviderPort } from './domain/ports/identity-provider.port';
import { MONITORING_PROVIDER } from './domain/ports/monitoring-provider.port';
import { QUESTION_GENERATOR } from './domain/ports/question-generator.port';
import { SCORING_PROVIDER } from './domain/ports/scoring-provider.port';
import { AiService } from './application/services/ai.service';
import { AssessmentFinalizeAdapter } from './infrastructure/providers/assessment-finalize.adapter';
import { AssessmentScoringAdapter } from './infrastructure/providers/assessment-scoring.adapter';
import { FastApiEarphoneAdapter } from './infrastructure/providers/fastapi-earphone.adapter';
import { FastApiIdentityAdapter } from './infrastructure/providers/fastapi-identity.adapter';
import { MockIdentityAdapter } from './infrastructure/providers/mock-identity.adapter';
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
    { provide: FINALIZE_PROVIDER, useClass: AssessmentFinalizeAdapter },
    { provide: MONITORING_PROVIDER, useClass: MonitoringAdapter },
    FastApiIdentityAdapter,
    MockIdentityAdapter,
    {
      provide: IDENTITY_PROVIDER,
      useFactory: (
        config: ConfigType<typeof appConfig>,
        real: FastApiIdentityAdapter,
        mock: MockIdentityAdapter,
      ): IdentityProviderPort => (config.mockIdentityVerification ? mock : real),
      inject: [appConfig.KEY, FastApiIdentityAdapter, MockIdentityAdapter],
    },
    { provide: EARPHONE_PROVIDER, useClass: FastApiEarphoneAdapter },
  ],
  exports: [
    QUESTION_GENERATOR,
    SCORING_PROVIDER,
    FINALIZE_PROVIDER,
    MONITORING_PROVIDER,
    IDENTITY_PROVIDER,
    EARPHONE_PROVIDER,
  ],
})
export class AiModule {}
