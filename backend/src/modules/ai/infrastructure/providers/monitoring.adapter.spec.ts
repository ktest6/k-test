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
    monitoring: { url },
    mail: { smtpHost: '', smtpPort: 587, smtpUser: '', smtpPassword: '', from: '' },
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
    eyeYawCenter: -2.1937,
    eyePitchCenter: -20.7994,
    headYawCenter: 1.0,
    headPitchCenter: -2.0,
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
  events: [
    {
      rule_id: 'RULE_FACE_OUT_OF_FRAME',
      event_type: 'FACE_OUT_OF_FRAME',
      severity: 'MEDIUM',
      decision: 'RECORD_EVENT',
      message: '얼굴이 화면 밖으로 벗어났습니다.',
      details: { face_count: 0 },
    },
  ],
  identity_check_requested: false,
  identity_check_executed: false,
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
      events: [
        {
          ruleId: 'RULE_FACE_OUT_OF_FRAME',
          eventType: 'FACE_OUT_OF_FRAME',
          severity: 'MEDIUM',
          decision: 'RECORD_EVENT',
          message: '얼굴이 화면 밖으로 벗어났습니다.',
          details: { face_count: 0 },
        },
      ],
      gazeState: null,
      identityCheckRequested: false,
      identityCheckExecuted: false,
      raw: RAW_RESPONSE,
    });
  });

  it('includes previous_gaze_state when provided and omits it otherwise', async () => {
    const post = jest.fn().mockReturnValue(of({ data: RAW_RESPONSE }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new MonitoringAdapter(httpService, buildConfig());
    const previousGazeState = { consecutive_away_count: 2, last_direction: 'LEFT' };

    await adapter.analyze(buildInput({ previousGazeState }));

    const [, body] = post.mock.calls[0] as [string, FormData];
    const raw = body.getBuffer().toString('utf-8');
    expect(raw).toContain('name="previous_gaze_state"');
    expect(raw).toContain(JSON.stringify(previousGazeState));

    const post2 = jest.fn().mockReturnValue(of({ data: RAW_RESPONSE }));
    const adapter2 = new MonitoringAdapter(
      { post: post2 } as unknown as HttpService,
      buildConfig(),
    );
    await adapter2.analyze(buildInput());
    const [, body2] = post2.mock.calls[0] as [string, FormData];
    expect(body2.getBuffer().toString('utf-8')).not.toContain('name="previous_gaze_state"');
  });

  it('parses gaze_monitor.state from the response into gazeState', async () => {
    const nextState = { consecutive_away_count: 3, last_direction: 'RIGHT' };
    const post = jest
      .fn()
      .mockReturnValue(of({ data: { ...RAW_RESPONSE, gaze_monitor: { state: nextState } } }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new MonitoringAdapter(httpService, buildConfig());

    const result = await adapter.analyze(buildInput());

    expect(result.gazeState).toEqual(nextState);
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

  it('always includes eye/head yaw and pitch calibration values (anti-cheat requires all four)', async () => {
    const post = jest.fn().mockReturnValue(of({ data: RAW_RESPONSE }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new MonitoringAdapter(httpService, buildConfig());
    const input = buildInput({
      eyeYawCenter: -2.1937,
      eyePitchCenter: -20.7994,
      headYawCenter: 1.5,
      headPitchCenter: -3.5,
    });

    await adapter.analyze(input);

    const [, body] = post.mock.calls[0] as [string, FormData];
    const raw = body.getBuffer().toString('utf-8');
    expect(raw).toContain('name="eye_yaw_center"');
    expect(raw).toContain('-2.1937');
    expect(raw).toContain('name="eye_pitch_center"');
    expect(raw).toContain('-20.7994');
    expect(raw).toContain('name="head_yaw_center"');
    expect(raw).toContain('1.5');
    expect(raw).toContain('name="head_pitch_center"');
    expect(raw).toContain('-3.5');
  });
});

describe('MonitoringAdapter.calibrate', () => {
  const RAW_CALIBRATE_RESPONSE = {
    calibrated: true,
    sample_count: 6,
    eye_yaw_center: -2.1937,
    eye_pitch_center: -20.7994,
    head_yaw_center: 1.0,
    head_pitch_center: -2.0,
  };

  it('posts to {url}/monitoring/gaze-calibration with the expected fields and parses the response', async () => {
    const post = jest.fn().mockReturnValue(of({ data: RAW_CALIBRATE_RESPONSE }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new MonitoringAdapter(httpService, buildConfig());

    const result = await adapter.calibrate({
      examId: '7',
      examineeId: '9',
      calibrationImages: [
        { buffer: Buffer.from('a'), filename: 'center_1.jpg', contentType: 'image/jpeg' },
        { buffer: Buffer.from('b'), filename: 'center_2.jpg', contentType: 'image/jpeg' },
      ],
    });

    expect(post).toHaveBeenCalledTimes(1);
    const [url, body, options] = post.mock.calls[0] as [string, FormData, { headers: unknown }];
    expect(url).toBe('https://monitoring.internal/monitoring/gaze-calibration');
    expect(body).toBeInstanceOf(FormData);
    expect(options.headers).toEqual(body.getHeaders());

    const raw = body.getBuffer().toString('utf-8');
    expect(raw).toContain('name="exam_id"');
    expect(raw).toContain('name="examinee_id"');
    const calibrationImageOccurrences = raw.match(/name="calibration_images"/g) ?? [];
    expect(calibrationImageOccurrences).toHaveLength(2);

    expect(result).toEqual({
      calibrated: true,
      sampleCount: 6,
      eyeYawCenter: -2.1937,
      eyePitchCenter: -20.7994,
      headYawCenter: 1.0,
      headPitchCenter: -2.0,
    });
  });
});
