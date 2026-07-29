import { Inject, Injectable } from '@nestjs/common';
import { AI_PROVIDER, AiProvider, AiProviderStatus } from '../../domain/ports/ai-provider.port';

@Injectable()
export class AiService {
  constructor(@Inject(AI_PROVIDER) private readonly aiProvider: AiProvider) {}

  getStatus(): Promise<AiProviderStatus> {
    return this.aiProvider.getStatus();
  }
}
