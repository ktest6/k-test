import { Module } from '@nestjs/common';
import { AI_PROVIDER } from './domain/ports/ai-provider.port';
import { AiService } from './application/services/ai.service';
import { StubAiProviderAdapter } from './infrastructure/providers/stub-ai-provider.adapter';
import { AiController } from './presentation/ai.controller';

@Module({
  controllers: [AiController],
  providers: [AiService, { provide: AI_PROVIDER, useClass: StubAiProviderAdapter }],
})
export class AiModule {}
