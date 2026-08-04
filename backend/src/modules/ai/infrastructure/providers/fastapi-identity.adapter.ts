import { HttpService } from '@nestjs/axios';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import FormData from 'form-data';
import { firstValueFrom } from 'rxjs';
import { appConfig } from '../../../../config/configuration';
import {
  IdentityProviderPort,
  VerifyIdentityInput,
  VerifyIdentityResult,
} from '../../domain/ports/identity-provider.port';

interface RawVerifyResponse {
  verified: boolean;
  face_verified: boolean;
  similarity: number;
  threshold: number;
  matched_face_count: number;
  unmatched_face_count: number;
  applicant_verified: boolean;
  document_type: string;
  field_matches: Record<string, unknown>;
  message: string;
  [key: string]: unknown;
}

const DOCUMENT_TYPE_BY_INPUT: Record<VerifyIdentityInput['documentType'], string> = {
  PASSPORT: 'passport',
  ARC: 'alien_registration_card',
};

/** 신분증-얼굴 대조를 맡는 FastAPI 서비스의 POST /identity/verify를 호출하는 실제 어댑터. */
@Injectable()
export class FastApiIdentityAdapter implements IdentityProviderPort {
  constructor(
    private readonly httpService: HttpService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async verify(input: VerifyIdentityInput): Promise<VerifyIdentityResult> {
    const form = new FormData();
    form.append('exam_id', input.examId);
    form.append('examinee_id', input.examineeId);
    form.append('captured_at', input.capturedAt);
    form.append('first_name', input.firstName);
    form.append('last_name', input.lastName);
    form.append('birth_date', input.birthDate);
    form.append('document_type', DOCUMENT_TYPE_BY_INPUT[input.documentType]);
    form.append('source_image', input.sourceImage.buffer, {
      filename: input.sourceImage.filename,
      contentType: input.sourceImage.contentType,
    });
    form.append('target_image', input.targetImage.buffer, {
      filename: input.targetImage.filename,
      contentType: input.targetImage.contentType,
    });

    const response = await firstValueFrom(
      this.httpService.post<RawVerifyResponse>(
        `${this.config.monitoring.url}/identity/verify`,
        form,
        {
          headers: form.getHeaders(),
        },
      ),
    );

    const raw = response.data;
    return {
      verified: raw.verified,
      faceVerified: raw.face_verified,
      similarity: raw.similarity,
      threshold: raw.threshold,
      matchedFaceCount: raw.matched_face_count,
      unmatchedFaceCount: raw.unmatched_face_count,
      applicantVerified: raw.applicant_verified,
      documentType: raw.document_type,
      fieldMatches: raw.field_matches,
      message: raw.message,
      raw: raw as unknown as Record<string, unknown>,
    };
  }
}
