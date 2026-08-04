import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { StorageUploadUrlService } from '../../../../infrastructure/supabase/storage-upload-url.service';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { Answer } from '../../../answer/domain/entities/answer.entity';
import { AnswerStatus } from '../../../answer/domain/enums/answer-status.enum';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import { Question } from '../../../question/domain/entities/question.entity';
import { ScoringService } from '../../../scoring/application/services/scoring.service';
import { Score } from '../../../scoring/domain/entities/score.entity';
import { ExamSessionQuestionService } from './exam-session-question.service';
import { ExamSessionService } from './exam-session.service';
import { ExamSessionAnswerService } from './exam-session-answer.service';

function buildAnswer(): Answer {
  return new Answer('1', '1', '1', AnswerType.TEXT, '내용', null, AnswerStatus.DRAFT, new Date());
}

function buildQuestion(): Question {
  return new Question(
    '1',
    'work_log',
    { item_id: 'WRT-001', prompt: '프롬프트', expected_register: 'formal', reference_keywords: [] },
    null,
    [],
    new Date(),
  );
}

function buildStorageUploadUrlService(
  overrides: Partial<{ createSignedUploadUrl: jest.Mock }> = {},
) {
  return {
    createSignedUploadUrl: jest
      .fn()
      .mockResolvedValue({ path: '1/1/1.webm', signedUrl: 'https://signed', token: 'token' }),
    ...overrides,
  } as unknown as StorageUploadUrlService;
}

describe('ExamSessionAnswerService.save', () => {
  it('gates on assertActiveSession and question membership before saving', async () => {
    const assertActiveSession = jest.fn().mockResolvedValue(undefined);
    const examSessionService = { assertActiveSession } as unknown as ExamSessionService;
    const getQuestion = jest.fn().mockResolvedValue(buildQuestion());
    const examSessionQuestionService = { getQuestion } as unknown as ExamSessionQuestionService;
    const saved = buildAnswer();
    const save = jest.fn().mockResolvedValue(saved);
    const answerService = { save } as unknown as AnswerService;
    const findByAnswerId = jest.fn().mockResolvedValue(null);
    const scoringService = { findByAnswerId } as unknown as ScoringService;
    const service = new ExamSessionAnswerService(
      examSessionService,
      examSessionQuestionService,
      answerService,
      scoringService,
      buildStorageUploadUrlService(),
    );

    const result = await service.save('1', '1', '1', {
      type: AnswerType.TEXT,
      contentText: '내용',
    });

    expect(assertActiveSession).toHaveBeenCalledWith('1', '1');
    expect(getQuestion).toHaveBeenCalledWith('1', '1', '1');
    expect(save).toHaveBeenCalledWith(
      {
        examSessionId: '1',
        questionId: '1',
        type: AnswerType.TEXT,
        contentText: '내용',
        audioFileUrl: null,
      },
      null,
    );
    expect(result).toEqual({ answer: saved, graded: false, score: null });
  });

  it('passes durationMs through to AnswerService.save when provided', async () => {
    const assertActiveSession = jest.fn().mockResolvedValue(undefined);
    const examSessionService = { assertActiveSession } as unknown as ExamSessionService;
    const getQuestion = jest.fn().mockResolvedValue(buildQuestion());
    const examSessionQuestionService = { getQuestion } as unknown as ExamSessionQuestionService;
    const save = jest.fn().mockResolvedValue(buildAnswer());
    const answerService = { save } as unknown as AnswerService;
    const findByAnswerId = jest.fn().mockResolvedValue(null);
    const scoringService = { findByAnswerId } as unknown as ScoringService;
    const service = new ExamSessionAnswerService(
      examSessionService,
      examSessionQuestionService,
      answerService,
      scoringService,
      buildStorageUploadUrlService(),
    );

    await service.save('1', '1', '1', {
      type: AnswerType.AUDIO,
      audioFileUrl: '1/1/1.webm',
      durationMs: 11760,
    });

    expect(save).toHaveBeenCalledWith(
      {
        examSessionId: '1',
        questionId: '1',
        type: AnswerType.AUDIO,
        contentText: null,
        audioFileUrl: '1/1/1.webm',
      },
      11760,
    );
  });

  it('propagates a rejection from assertActiveSession without saving', async () => {
    const assertActiveSession = jest.fn().mockRejectedValue(new Error('session not active'));
    const examSessionService = { assertActiveSession } as unknown as ExamSessionService;
    const getQuestion = jest.fn();
    const examSessionQuestionService = { getQuestion } as unknown as ExamSessionQuestionService;
    const save = jest.fn();
    const answerService = { save } as unknown as AnswerService;
    const scoringService = {} as unknown as ScoringService;
    const service = new ExamSessionAnswerService(
      examSessionService,
      examSessionQuestionService,
      answerService,
      scoringService,
      buildStorageUploadUrlService(),
    );

    await expect(
      service.save('1', '1', '1', { type: AnswerType.TEXT, contentText: '내용' }),
    ).rejects.toThrow('session not active');
    expect(getQuestion).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
  });
});

describe('ExamSessionAnswerService.get', () => {
  it('does not require an active session (read allowed after submit/expiry)', async () => {
    const examSessionService = {} as unknown as ExamSessionService;
    const getQuestion = jest.fn().mockResolvedValue(buildQuestion());
    const examSessionQuestionService = { getQuestion } as unknown as ExamSessionQuestionService;
    const answer = buildAnswer();
    const findBySessionAndQuestion = jest.fn().mockResolvedValue(answer);
    const answerService = { findBySessionAndQuestion } as unknown as AnswerService;
    const score = new Score('1', '1', { total: 90 }, new Date());
    const findByAnswerId = jest.fn().mockResolvedValue(score);
    const scoringService = { findByAnswerId } as unknown as ScoringService;
    const service = new ExamSessionAnswerService(
      examSessionService,
      examSessionQuestionService,
      answerService,
      scoringService,
      buildStorageUploadUrlService(),
    );

    const result = await service.get('1', '1', '1');

    expect(getQuestion).toHaveBeenCalledWith('1', '1', '1');
    expect(result).toEqual({ answer, graded: true, score: { total: 90 } });
  });

  it('throws when no answer has been saved yet', async () => {
    const examSessionService = {} as unknown as ExamSessionService;
    const getQuestion = jest.fn().mockResolvedValue(buildQuestion());
    const examSessionQuestionService = { getQuestion } as unknown as ExamSessionQuestionService;
    const findBySessionAndQuestion = jest.fn().mockResolvedValue(null);
    const answerService = { findBySessionAndQuestion } as unknown as AnswerService;
    const scoringService = {} as unknown as ScoringService;
    const service = new ExamSessionAnswerService(
      examSessionService,
      examSessionQuestionService,
      answerService,
      scoringService,
      buildStorageUploadUrlService(),
    );

    await expect(service.get('1', '1', '1')).rejects.toThrow(NotFoundDomainException);
  });
});

describe('ExamSessionAnswerService.createUploadUrl', () => {
  it('gates on assertActiveSession and question membership, then issues a signed URL scoped to session/question', async () => {
    const assertActiveSession = jest.fn().mockResolvedValue(undefined);
    const examSessionService = { assertActiveSession } as unknown as ExamSessionService;
    const getQuestion = jest.fn().mockResolvedValue(buildQuestion());
    const examSessionQuestionService = { getQuestion } as unknown as ExamSessionQuestionService;
    const answerService = {} as unknown as AnswerService;
    const scoringService = {} as unknown as ScoringService;
    const createSignedUploadUrl = jest
      .fn()
      .mockResolvedValue({ path: '9/100/50.webm', signedUrl: 'https://signed', token: 'token' });
    const storageUploadUrlService = buildStorageUploadUrlService({ createSignedUploadUrl });
    const service = new ExamSessionAnswerService(
      examSessionService,
      examSessionQuestionService,
      answerService,
      scoringService,
      storageUploadUrlService,
    );

    const result = await service.createUploadUrl('100', '50', '9', 'audio/webm');

    expect(assertActiveSession).toHaveBeenCalledWith('100', '9');
    expect(getQuestion).toHaveBeenCalledWith('100', '50', '9');
    expect(createSignedUploadUrl).toHaveBeenCalledWith('answer-audio', '9/100/50.webm', {
      upsert: true,
    });
    expect(result).toEqual({ path: '9/100/50.webm', signedUrl: 'https://signed', token: 'token' });
  });

  it('propagates a rejection from assertActiveSession without issuing a URL', async () => {
    const assertActiveSession = jest.fn().mockRejectedValue(new Error('session not active'));
    const examSessionService = { assertActiveSession } as unknown as ExamSessionService;
    const getQuestion = jest.fn();
    const examSessionQuestionService = { getQuestion } as unknown as ExamSessionQuestionService;
    const answerService = {} as unknown as AnswerService;
    const scoringService = {} as unknown as ScoringService;
    const createSignedUploadUrl = jest.fn();
    const storageUploadUrlService = buildStorageUploadUrlService({ createSignedUploadUrl });
    const service = new ExamSessionAnswerService(
      examSessionService,
      examSessionQuestionService,
      answerService,
      scoringService,
      storageUploadUrlService,
    );

    await expect(service.createUploadUrl('100', '50', '9', 'audio/webm')).rejects.toThrow(
      'session not active',
    );
    expect(getQuestion).not.toHaveBeenCalled();
    expect(createSignedUploadUrl).not.toHaveBeenCalled();
  });
});
