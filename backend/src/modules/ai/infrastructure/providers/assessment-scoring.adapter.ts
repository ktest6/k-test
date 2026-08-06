import { HttpService } from '@nestjs/axios';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { firstValueFrom } from 'rxjs';
import { appConfig } from '../../../../config/configuration';
import { StoragePublicUrlService } from '../../../../infrastructure/supabase/storage-public-url.service';
import { ScoreItemInput, ScoringProviderPort } from '../../domain/ports/scoring-provider.port';

const ANSWER_AUDIO_BUCKET = 'answer-audio';

interface ScoreRequestBody {
  submission_id: string;
  mode: 'writing' | 'speaking';
  answer_text: string;
  item: {
    item_id: string;
    prompt: string;
    expected_register: string;
    checklist: { id: string; description: string; weight: number }[];
  };
  audio?: { url: string; duration_ms?: number };
}

/**
 * assessment 서비스(전재완 담당, 별도 Python/FastAPI 서비스)의 POST /score를
 * 호출하는 실제 어댑터. writing은 answer_text를, speaking은 audio.url을
 * 채워서 보낸다 — 둘을 같이 보내거나 mode에 안 맞게 보내면 assessment가 400을
 * 준다(README 명시 규칙).
 */
@Injectable()
export class AssessmentScoringAdapter implements ScoringProviderPort {
  constructor(
    private readonly httpService: HttpService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
    private readonly storagePublicUrlService: StoragePublicUrlService,
  ) {}

  async score(input: ScoreItemInput): Promise<Record<string, unknown>> {
    const body: ScoreRequestBody = {
      submission_id: input.answerId,
      mode: input.answerType === 'AUDIO' ? 'speaking' : 'writing',
      answer_text: input.answerType === 'TEXT' ? (input.contentText ?? '') : '',
      item: {
        item_id: input.item.itemId,
        prompt: input.item.prompt,
        expected_register: input.item.expectedRegister,
        checklist: input.item.checklist,
      },
    };

    if (input.answerType === 'AUDIO' && input.audioFileUrl) {
      body.audio = {
        url: this.storagePublicUrlService.toPublicUrl(ANSWER_AUDIO_BUCKET, input.audioFileUrl),
        ...(input.durationMs != null ? { duration_ms: input.durationMs } : {}),
      };
    }

    const headers = this.config.assessment.apiKey
      ? { 'X-API-Key': this.config.assessment.apiKey }
      : undefined;

    const response = await firstValueFrom(
      this.httpService.post<Record<string, unknown>>(`${this.config.assessment.url}/score`, body, {
        headers,
      }),
    );

    return response.data;
  }
}
