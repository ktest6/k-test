import { HttpService } from '@nestjs/axios';
import { of } from 'rxjs';
import { AppConfig } from '../../../../config/configuration';
import { DetectEarphoneInput } from '../../domain/ports/earphone-provider.port';
import { FastApiEarphoneAdapter } from './fastapi-earphone.adapter';

function buildConfig(): AppConfig {
  return {
    env: 'test',
    port: 3000,
    corsOrigin: '*',
    swaggerEnabled: false,
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
  };
}

function buildInput(overrides: Partial<DetectEarphoneInput> = {}): DetectEarphoneInput {
  return {
    examId: '7',
    examineeId: '9',
    leftEarImage: { buffer: Buffer.from('left'), filename: 'left.jpg', contentType: 'image/jpeg' },
    rightEarImage: {
      buffer: Buffer.from('right'),
      filename: 'right.jpg',
      contentType: 'image/jpeg',
    },
    ...overrides,
  };
}

function buildRawResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    earphone_detected: true,
    left_ear_detected: true,
    right_ear_detected: false,
    left_label: 'Earbuds',
    right_label: null,
    left_confidence: 68.14,
    right_confidence: 0.0,
    threshold: 45.0,
    message: '시험 시작 전에 이어폰을 제거해 주세요.',
    ...overrides,
  };
}

describe('FastApiEarphoneAdapter.detect', () => {
  it('posts both ear images as multipart form data and camelCases the response', async () => {
    const post = jest.fn().mockReturnValue(of({ data: buildRawResponse() }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new FastApiEarphoneAdapter(httpService, buildConfig());

    const result = await adapter.detect(buildInput());

    const [url, form, options] = post.mock.calls[0] as [
      string,
      { getBuffer: () => Buffer; getHeaders: () => Record<string, string> },
      { headers: unknown },
    ];
    expect(url).toBe('https://fastapi.internal/earphone/detect');
    expect(options.headers).toEqual(form.getHeaders());
    const body = form.getBuffer().toString();
    expect(body).toContain('name="exam_id"');
    expect(body).toContain('name="left_ear_image"');
    expect(body).toContain('name="right_ear_image"');

    expect(result).toEqual({
      earphoneDetected: true,
      leftEarDetected: true,
      rightEarDetected: false,
      leftLabel: 'Earbuds',
      rightLabel: null,
      leftConfidence: 68.14,
      rightConfidence: 0,
      threshold: 45,
      message: '시험 시작 전에 이어폰을 제거해 주세요.',
    });
  });

  it('passes through a not-detected result unchanged', async () => {
    const post = jest.fn().mockReturnValue(
      of({
        data: buildRawResponse({
          earphone_detected: false,
          left_ear_detected: false,
          right_ear_detected: false,
          left_label: null,
          right_label: null,
          left_confidence: 0,
          right_confidence: 0,
          message: '이어폰이 탐지되지 않았습니다.',
        }),
      }),
    );
    const httpService = { post } as unknown as HttpService;
    const adapter = new FastApiEarphoneAdapter(httpService, buildConfig());

    const result = await adapter.detect(buildInput());

    expect(result.earphoneDetected).toBe(false);
    expect(result.message).toBe('이어폰이 탐지되지 않았습니다.');
  });
});
