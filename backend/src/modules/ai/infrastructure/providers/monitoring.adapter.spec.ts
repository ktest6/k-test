import { HttpService } from '@nestjs/axios';
import FormData from 'form-data';
import { of } from 'rxjs';
import { AppConfig } from '../../../../config/configuration';
import { AnalyzeFrameInput } from '../../domain/ports/monitoring-provider.port';
import { MonitoringAdapter } from './monitoring.adapter';

function buildConfig(url = 'https://monitoring.internal'): AppConfig {
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
    fastApi: { url: '' },
    monitoring: { url },
  };
}

function buildInput(overrides: Partial<AnalyzeFrameInput> = {}): AnalyzeFrameInput {
  return {
    examId: '7',
    examineeId: '9',
    requestId: 'req-1',
    capturedAt: '2026-08-04T13:05:00+09:00',
    elapsedMs: 300000,
    captureSequence: 60,
    runIdentityCheck: false,
    currentImage: {
      buffer: Buffer.from('frame'),
      filename: 'frame.jpg',
      contentType: 'image/jpeg',
    },
    ...overrides,
  };
}

const RAW_RESPONSE = {
  event_summary: {
    event_detected: true,
    event_count: 1,
    severity: 'MEDIUM',
    decision: 'RECORD_EVENT',
    create_clip: false,
  },
  events: [{ event_type: 'FACE_OUT_OF_FRAME', details: { face_count: 0 } }],
};

describe('MonitoringAdapter.analyze', () => {
  it('posts to {url}/monitoring/analyze with the expected fields and parses the response', async () => {
    const post = jest.fn().mockReturnValue(of({ data: RAW_RESPONSE }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new MonitoringAdapter(httpService, buildConfig());

    const result = await adapter.analyze(buildInput());

    expect(post).toHaveBeenCalledTimes(1);
    const [url, body, options] = post.mock.calls[0] as [string, FormData, { headers: unknown }];
    expect(url).toBe('https://monitoring.internal/monitoring/analyze');
    expect(body).toBeInstanceOf(FormData);
    expect(options.headers).toEqual(body.getHeaders());

    const raw = body.getBuffer().toString('utf-8');
    expect(raw).toContain('name="exam_id"');
    expect(raw).toContain('7');
    expect(raw).toContain('name="examinee_id"');
    expect(raw).toContain('name="run_identity_check"');
    expect(raw).toContain('false');
    expect(raw).toContain('name="current_image"');
    expect(raw).not.toContain('name="reference_image"');

    expect(result).toEqual({
      eventSummary: {
        eventDetected: true,
        eventCount: 1,
        severity: 'MEDIUM',
        decision: 'RECORD_EVENT',
        createClip: false,
      },
      events: [{ eventType: 'FACE_OUT_OF_FRAME', details: { face_count: 0 } }],
      raw: RAW_RESPONSE,
    });
  });

  it('includes reference_image field when provided', async () => {
    const post = jest.fn().mockReturnValue(of({ data: RAW_RESPONSE }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new MonitoringAdapter(httpService, buildConfig());
    const input = buildInput({
      runIdentityCheck: true,
      referenceImage: {
        buffer: Buffer.from('ref'),
        filename: 'ref.jpg',
        contentType: 'image/jpeg',
      },
    });

    await adapter.analyze(input);

    const [, body] = post.mock.calls[0] as [string, FormData];
    const raw = body.getBuffer().toString('utf-8');
    expect(raw).toContain('name="reference_image"');
    expect(raw).toContain('name="run_identity_check"');
    expect(raw).toContain('true');
  });
});
