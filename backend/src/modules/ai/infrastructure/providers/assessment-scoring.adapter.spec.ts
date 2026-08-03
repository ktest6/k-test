import { HttpService } from '@nestjs/axios';
import { of } from 'rxjs';
import { AppConfig } from '../../../../config/configuration';
import { ScoreItemInput } from '../../domain/ports/scoring-provider.port';
import { AssessmentScoringAdapter } from './assessment-scoring.adapter';

function buildConfig(overrides: Partial<{ url: string; apiKey: string }> = {}): AppConfig {
  return {
    env: 'test',
    port: 3000,
    corsOrigin: '*',
    swaggerEnabled: false,
    supabase: { url: 'https://project.supabase.co', anonKey: '', serviceRoleKey: '' },
    identityVerification: {
      minIntervalMinutes: 5,
      maxIntervalMinutes: 15,
      maxFailuresBeforeDisqualification: 2,
      mockForceFail: false,
    },
    jwt: { accessSecret: '', accessExpiresIn: '1h', refreshSecret: '', refreshExpiresIn: '14d' },
    admin: { signupSecret: '' },
    fastApi: { url: '' },
    assessment: { url: 'https://assessment.internal', apiKey: '', ...overrides },
    monitoring: { url: '' },
  };
}

function buildAudioInput(): ScoreItemInput {
  return {
    answerId: '500',
    answerType: 'AUDIO',
    contentText: null,
    audioFileUrl: '12/100/50.webm',
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
    const adapter = new AssessmentScoringAdapter(httpService, buildConfig());

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
    const adapter = new AssessmentScoringAdapter(httpService, buildConfig());
    const input: ScoreItemInput = {
      answerId: '501',
      answerType: 'TEXT',
      contentText: '오늘 작업일지입니다.',
      audioFileUrl: null,
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

  it('adds the X-API-Key header when configured', async () => {
    const post = jest.fn().mockReturnValue(of({ data: {} }));
    const httpService = { post } as unknown as HttpService;
    const adapter = new AssessmentScoringAdapter(
      httpService,
      buildConfig({ apiKey: 'secret-key' }),
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
