import { HttpService } from '@nestjs/axios';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import FormData from 'form-data';
import { firstValueFrom } from 'rxjs';
import { appConfig } from '../../../../config/configuration';
import {
  DetectEarphoneInput,
  DetectEarphoneResult,
  EarphoneProviderPort,
} from '../../domain/ports/earphone-provider.port';

interface RawDetectResponse {
  earphone_detected: boolean;
  left_ear_detected: boolean;
  right_ear_detected: boolean;
  left_label: string | null;
  right_label: string | null;
  left_confidence: number;
  right_confidence: number;
  threshold: number;
  message: string;
  [key: string]: unknown;
}

/** 이어폰 착용 여부를 감지하는 FastAPI 서비스의 POST /earphone/detect를 호출하는 실제 어댑터. */
@Injectable()
export class FastApiEarphoneAdapter implements EarphoneProviderPort {
  constructor(
    private readonly httpService: HttpService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async detect(input: DetectEarphoneInput): Promise<DetectEarphoneResult> {
    const form = new FormData();
    form.append('exam_id', input.examId);
    form.append('examinee_id', input.examineeId);
    form.append('left_ear_image', input.leftEarImage.buffer, {
      filename: input.leftEarImage.filename,
      contentType: input.leftEarImage.contentType,
    });
    form.append('right_ear_image', input.rightEarImage.buffer, {
      filename: input.rightEarImage.filename,
      contentType: input.rightEarImage.contentType,
    });

    const response = await firstValueFrom(
      this.httpService.post<RawDetectResponse>(`${this.config.fastApi.url}/earphone/detect`, form, {
        headers: form.getHeaders(),
      }),
    );

    const raw = response.data;
    return {
      earphoneDetected: raw.earphone_detected,
      leftEarDetected: raw.left_ear_detected,
      rightEarDetected: raw.right_ear_detected,
      leftLabel: raw.left_label,
      rightLabel: raw.right_label,
      leftConfidence: raw.left_confidence,
      rightConfidence: raw.right_confidence,
      threshold: raw.threshold,
      message: raw.message,
    };
  }
}
