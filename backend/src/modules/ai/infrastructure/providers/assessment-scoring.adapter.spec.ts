import { HttpService } from '@nestjs/axios';
import { of } from 'rxjs';
import { AppConfig } from '../../../../config/configuration';
import { StoragePublicUrlService } from '../../../../infrastructure/supabase/storage-public-url.service';
import { ScoreItemInput } from '../../domain/ports/scoring-provider.port';
import { AssessmentScoringAdapter } from './assessment-scoring.adapter';

function buildConfig(overrides: Partial<{ url: string; apiKey: string }> = {}): AppConfig {
  return {
    env: 'test',
    port: 3000,
    corsOrigin: '*',
    swaggerEnabled: false,
    requireIdentityVerification: true,
    supabase: { url: 'https://project.supabase.co', anonKey: '', serviceRoleKey: '' },
    identityVerification: {
      minIntervalMinutes: 5,
      maxIntervalMinutes: 15,
      maxFailuresBeforeDisqualification: 2,
      mockForceFail: false,
    },
    jwt: { accessSecret: '', accessExpiresIn: '1h', refreshSecret: '', refreshExpiresIn: '14d' },
    admin: { signupSecret: '' },
    assessment: { url: 'https://assessment.internal', apiKey: '', ...overrides },
    monitoring: { url: '' },
    mail: { smtpHost: '', smtpPort: 587, smtpUser: '', smtpPassword: '', from: '' },
  };
}

function buildStoragePublicUrlService(): StoragePublicUrlService {
  return new StoragePublicUrlService(buildConfig());
}

function buildAudioInput(overrides: Partial<ScoreItemInput> = {}): ScoreItemInput {
  return {
    answerId: '500',
    answerType: 'AUDIO',
    contentText: null,
    audioFileUrl: '12/100/50.webm',
    durationMs: null,
    ...overrides,
    item: {
      itemId: 'PIC-001',
      prompt: '그림을 보고 상황을 설명하세요.',
      expectedRegister: 'formal',
      checklist: [{ id: 'c1', description: '상황을 정확히 묘사했는가', weight: 1.5 }],
    },
  };
}

describe('AssessmentScoringAdapter.score', () => {
  it('sends a speaking request with the public audio URL and no answer_text', async () => {
    const post = jest.fn().mockReturnValue(of({ data: { total_score: 80 } }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new AssessmentScoringAdapter(
      httpService,
      buildConfig(),
      buildStoragePublicUrlService(),
    );

    const result = await adapter.score(buildAudioInput());

    expect(post).toHaveBeenCalledWith(
      'https://assessment.internal/score',
      {
        submission_id: '500',
        mode: 'speaking',
        answer_text: '',
        item: {
          item_id: 'PIC-001',
          prompt: '그림을 보고 상황을 설명하세요.',
          expected_register: 'formal',
          checklist: [{ id: 'c1', description: '상황을 정확히 묘사했는가', weight: 1.5 }],
        },
        audio: {
          url: 'https://project.supabase.co/storage/v1/object/public/answer-audio/12/100/50.webm',
        },
      },
      { headers: undefined },
    );
    expect(result).toEqual({ total_score: 80 });
  });

  it('sends a writing request with answer_text and no audio field', async () => {
    const post = jest.fn().mockReturnValue(of({ data: { total_score: 90 } }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new AssessmentScoringAdapter(
      httpService,
      buildConfig(),
      buildStoragePublicUrlService(),
    );
    const input: ScoreItemInput = {
      answerId: '501',
      answerType: 'TEXT',
      contentText: '오늘 작업일지입니다.',
      audioFileUrl: null,
      durationMs: null,
      item: {
        itemId: 'WRT-001',
        prompt: '작업일지를 쓰세요.',
        expectedRegister: 'formal',
        checklist: [],
      },
    };

    await adapter.score(input);

    const [, body] = post.mock.calls[0] as [string, Record<string, unknown>];
    expect(body).toMatchObject({ mode: 'writing', answer_text: '오늘 작업일지입니다.' });
    expect(body).not.toHaveProperty('audio');
  });

  it('includes audio.duration_ms when the input has one (non-wav formats need it)', async () => {
    const post = jest.fn().mockReturnValue(of({ data: {} }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new AssessmentScoringAdapter(
      httpService,
      buildConfig(),
      buildStoragePublicUrlService(),
    );

    await adapter.score(buildAudioInput({ durationMs: 11760 }));

    const [, body] = post.mock.calls[0] as [string, Record<string, unknown>];
    expect(body).toMatchObject({ audio: { duration_ms: 11760 } });
  });

  it('omits audio.duration_ms when the input has none', async () => {
    const post = jest.fn().mockReturnValue(of({ data: {} }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new AssessmentScoringAdapter(
      httpService,
      buildConfig(),
      buildStoragePublicUrlService(),
    );

    await adapter.score(buildAudioInput());

    const [, body] = post.mock.calls[0] as [string, { audio: Record<string, unknown> }];
    expect(body.audio).not.toHaveProperty('duration_ms');
  });

  it('adds the X-API-Key header when configured', async () => {
    const post = jest.fn().mockReturnValue(of({ data: {} }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new AssessmentScoringAdapter(
      httpService,
      buildConfig({ apiKey: 'secret-key' }),
      buildStoragePublicUrlService(),
    );

    await adapter.score(buildAudioInput());

    const [, , options] = post.mock.calls[0] as [
      string,
      unknown,
      { headers?: Record<string, string> },
    ];
    expect(options.headers).toEqual({ 'X-API-Key': 'secret-key' });
  });
});
