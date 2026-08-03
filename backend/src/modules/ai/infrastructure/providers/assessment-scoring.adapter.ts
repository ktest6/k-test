import { HttpService } from '@nestjs/axios';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { firstValueFrom } from 'rxjs';
import { appConfig } from '../../../../config/configuration';
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
  audio?: { url: string };
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
      body.audio = { url: this.toPublicAudioUrl(input.audioFileUrl) };
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

  /** Storage 경로(예: "12/100/50.webm")를 assessment가 바로 내려받을 수 있는 공개 URL로 바꾼다. */
  private toPublicAudioUrl(path: string): string {
    return `${this.config.supabase.url}/storage/v1/object/public/${ANSWER_AUDIO_BUCKET}/${path}`;
  }
}
