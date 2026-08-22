import { HttpService } from '@nestjs/axios';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { firstValueFrom } from 'rxjs';
import { appConfig } from '../../../../config/configuration';
import {
  FinalizeProviderPort,
  FinalizeSessionInput,
} from '../../domain/ports/finalize-provider.port';

interface FinalizeRequestBody {
  session_id: string;
  candidate_id: string;
  items: Record<string, unknown>[];
  expected_items: { item_id: string; mode: 'writing' | 'speaking' }[];
}

/** assessment 서비스(전재완 담당)의 POST /finalize를 호출하는 실제 어댑터. */
@Injectable()
export class AssessmentFinalizeAdapter implements FinalizeProviderPort {
  constructor(
    private readonly httpService: HttpService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async finalize(input: FinalizeSessionInput): Promise<Record<string, unknown>> {
    const body: FinalizeRequestBody = {
      session_id: input.sessionId,
      candidate_id: input.candidateId,
      items: input.items,
      expected_items: input.expectedItems.map((item) => ({
        item_id: item.itemId,
        mode: item.mode,
      })),
    };

    const headers = this.config.assessment.apiKey
      ? { 'X-API-Key': this.config.assessment.apiKey }
      : undefined;

    const response = await firstValueFrom(
      this.httpService.post<Record<string, unknown>>(
        `${this.config.assessment.url}/finalize`,
        body,
        { headers },
      ),
    );

    return response.data;
  }
}
