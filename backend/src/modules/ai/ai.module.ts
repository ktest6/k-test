import { Module } from '@nestjs/common';
import { AI_PROVIDER } from './domain/ports/ai-provider.port';
import { QUESTION_GENERATOR } from './domain/ports/question-generator.port';
import { AiService } from './application/services/ai.service';
import { MockQuestionGeneratorAdapter } from './infrastructure/providers/mock-question-generator.adapter';
import { StubAiProviderAdapter } from './infrastructure/providers/stub-ai-provider.adapter';
import { AiController } from './presentation/ai.controller';

@Module({
  controllers: [AiController],
  providers: [
    AiService,
    { provide: AI_PROVIDER, useClass: StubAiProviderAdapter },
    { provide: QUESTION_GENERATOR, useClass: MockQuestionGeneratorAdapter },
  ],
  exports: [QUESTION_GENERATOR],
})
export class AiModule {}
