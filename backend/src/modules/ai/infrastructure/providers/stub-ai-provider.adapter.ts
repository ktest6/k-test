import { Injectable } from '@nestjs/common';
import { AiProvider, AiProviderStatus } from '../../domain/ports/ai-provider.port';

/** No real provider wired yet — always reports itself as the stub. */
@Injectable()
export class StubAiProviderAdapter implements AiProvider {
  getStatus(): Promise<AiProviderStatus> {
    return Promise.resolve({ provider: 'stub', available: true });
  }
}
