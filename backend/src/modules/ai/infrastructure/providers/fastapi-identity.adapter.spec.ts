import { HttpService } from '@nestjs/axios';
import { of } from 'rxjs';
import { AppConfig } from '../../../../config/configuration';
import { VerifyIdentityInput } from '../../domain/ports/identity-provider.port';
import { FastApiIdentityAdapter } from './fastapi-identity.adapter';

function buildConfig(): AppConfig {
  return {
    env: 'test',
    port: 3000,
    corsOrigin: '*',
    swaggerEnabled: false,
    requireIdentityVerification: true,
    requireEarphoneCheck: true,
    requireGazeCalibration: true,
    requireMonitoringService: true,
    reportRetrySchedulerEnabled: true,
    supabase: { url: '', anonKey: '', serviceRoleKey: '' },
    identityVerification: {
      minIntervalMinutes: 5,
      maxIntervalMinutes: 15,
      maxFailuresBeforeDisqualification: 2,
      mockForceFail: false,
    },
    jwt: { accessSecret: '', accessExpiresIn: '1h', refreshSecret: '', refreshExpiresIn: '14d' },
    admin: { signupSecret: '' },
    assessment: { url: '', apiKey: '' },
    monitoring: { url: 'https://fastapi.internal' },
    mail: { smtpHost: '', smtpPort: 587, smtpUser: '', smtpPassword: '', from: '' },
  };
}

function buildInput(overrides: Partial<VerifyIdentityInput> = {}): VerifyIdentityInput {
  return {
    examId: '7',
    examineeId: '9',
    capturedAt: '2026-08-04T13:05:00+09:00',
    sourceImage: {
      buffer: Buffer.from('passport'),
      filename: 'passport.jpg',
      contentType: 'image/jpeg',
    },
    targetImage: {
      buffer: Buffer.from('webcam'),
      filename: 'webcam.jpg',
      contentType: 'image/jpeg',
    },
    firstName: 'GILDONG',
    lastName: 'HONG',
    birthDate: '1995-03-21',
    documentNumber: 'M12345678',
    ...overrides,
  };
}

function buildRawResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    verified: true,
    face_verified: true,
    similarity: 92.4,
    threshold: 80,
    matched_face_count: 1,
    unmatched_face_count: 0,
    applicant_verified: true,
    document_type: 'passport',
    field_matches: { last_name: true, first_name: true, birth_date: true },
    message: '본인인증 성공',
    ...overrides,
  };
}

describe('FastApiIdentityAdapter.verify', () => {
  it('posts multipart form data with a fixed document_type of passport and the caller document_number, and camelCases the response', async () => {
    const post = jest.fn().mockReturnValue(of({ data: buildRawResponse() }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new FastApiIdentityAdapter(httpService, buildConfig());

    const result = await adapter.verify(buildInput());

    const [url, form, options] = post.mock.calls[0] as [
      string,
      { getBuffer: () => Buffer; getHeaders: () => Record<string, string> },
      { headers: unknown },
    ];
    expect(url).toBe('https://fastapi.internal/identity/verify');
    expect(options.headers).toEqual(form.getHeaders());
    const body = form.getBuffer().toString();
    expect(body).toContain('name="exam_id"');
    expect(body).toContain('7');
    expect(body).toContain('name="document_type"');
    expect(body).toContain('passport');
    expect(body).toContain('name="document_number"');
    expect(body).toContain('M12345678');
    expect(body).toContain('GILDONG');
    expect(body).toContain('HONG');

    expect(result).toEqual({
      verified: true,
      faceVerified: true,
      similarity: 92.4,
      threshold: 80,
      matchedFaceCount: 1,
      unmatchedFaceCount: 0,
      applicantVerified: true,
      documentType: 'passport',
      fieldMatches: { last_name: true, first_name: true, birth_date: true },
      message: '본인인증 성공',
      raw: buildRawResponse(),
    });
  });
});
