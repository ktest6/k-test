import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { StoragePublicUrlService } from '../../../infrastructure/supabase/storage-public-url.service';
import { Answer } from '../../answer/domain/entities/answer.entity';
import { AnswerStatus } from '../../answer/domain/enums/answer-status.enum';
import { AnswerType } from '../../answer/domain/enums/answer-type.enum';
import { Question } from '../../question/domain/entities/question.entity';
import { ExamSession } from '../domain/entities/exam-session.entity';
import { SessionStatus } from '../domain/enums/session-status.enum';
import { ExamSessionAnswerService } from '../application/services/exam-session-answer.service';
import { ExamSessionQuestionService } from '../application/services/exam-session-question.service';
import { ExamSessionService } from '../application/services/exam-session.service';
import { ExamSessionController } from './exam-session.controller';

function buildUser(): AuthenticatedUser {
  return { id: '1', email: 'user@test.com', role: Role.USER };
}

function buildSession(overrides: Partial<{ currentQuestionId: string | null }> = {}): ExamSession {
  return new ExamSession(
    '1',
    '1',
    '1',
    SessionStatus.INPROGRESS,
    new Date('2026-06-01T00:00:00.000Z'),
    overrides.currentQuestionId ?? null,
    null,
    null,
    new Date(),
  );
}

function buildQuestion(id: string): Question {
  return new Question(
    id,
    'work_log',
    {
      item_id: `WRT-00${id}`,
      prompt: `프롬프트 ${id}`,
      expected_register: 'formal',
      reference_keywords: ['a'],
    },
    null,
    [{ id: '1', code: 'c1', description: '채점 기준', weight: 1.5, displayOrder: 0 }],
    new Date(),
  );
}

function buildAnswer(overrides: Partial<{ id: string; questionId: string }> = {}): Answer {
  return new Answer(
    overrides.id ?? '1',
    '1',
    overrides.questionId ?? '1',
    AnswerType.TEXT,
    '내용',
    null,
    AnswerStatus.DRAFT,
    new Date('2026-06-01T00:00:00.000Z'),
  );
}

function buildStoragePublicUrlService(): StoragePublicUrlService {
  return {
    toPublicUrl: jest.fn(
      (bucket: string, path: string) =>
        `https://project.supabase.co/storage/v1/object/public/${bucket}/${path}`,
    ),
  } as unknown as StoragePublicUrlService;
}

function buildController(
  sessionOverrides: Partial<{
    start: jest.Mock;
    getStatus: jest.Mock;
  }> = {},
  questionOverrides: Partial<{
    listQuestions: jest.Mock;
    getQuestion: jest.Mock;
  }> = {},
  answerOverrides: Partial<{
    save: jest.Mock;
    get: jest.Mock;
  }> = {},
) {
  const sessionService = {
    start: jest.fn(),
    getStatus: jest.fn(),
    ...sessionOverrides,
  } as unknown as ExamSessionService;
  const questionService = {
    listQuestions: jest.fn(),
    getQuestion: jest.fn(),
    ...questionOverrides,
  } as unknown as ExamSessionQuestionService;
  const answerService = {
    save: jest.fn(),
    get: jest.fn(),
    ...answerOverrides,
  } as unknown as ExamSessionAnswerService;
  return new ExamSessionController(
    sessionService,
    questionService,
    answerService,
    buildStoragePublicUrlService(),
  );
}

describe('ExamSessionController.start', () => {
  it('delegates to ExamSessionService.start and maps the response', async () => {
    const session = buildSession();
    const start = jest.fn().mockResolvedValue(session);
    const controller = buildController({ start });

    const result = await controller.start('1', buildUser());

    expect(start).toHaveBeenCalledWith('1', '1');
    expect(result).toEqual({
      id: '1',
      examId: '1',
      status: SessionStatus.INPROGRESS,
      startedAt: session.startedAt,
    });
  });
});

describe('ExamSessionController.getStatus', () => {
  it('delegates to ExamSessionService.getStatus and maps the response', async () => {
    const session = buildSession({ currentQuestionId: '5' });
    const getStatus = jest.fn().mockResolvedValue({
      session,
      status: SessionStatus.INPROGRESS,
      remainingSeconds: 120,
    });
    const controller = buildController({ getStatus });

    const result = await controller.getStatus('1', buildUser());

    expect(getStatus).toHaveBeenCalledWith('1', '1');
    expect(result).toEqual({
      id: '1',
      examId: '1',
      status: SessionStatus.INPROGRESS,
      currentQuestionId: '5',
      remainingSeconds: 120,
    });
  });
});

describe('ExamSessionController.listQuestions', () => {
  it('delegates to ExamSessionQuestionService.listQuestions and strips grading info from the response', async () => {
    const listQuestions = jest.fn().mockResolvedValue([buildQuestion('1'), buildQuestion('2')]);
    const controller = buildController({}, { listQuestions });

    const result = await controller.listQuestions('1', buildUser());

    expect(listQuestions).toHaveBeenCalledWith('1', '1');
    expect(result).toEqual([
      { id: '1', part: 'work_log', prompt: '프롬프트 1', imageUrl: null, mode: null },
      { id: '2', part: 'work_log', prompt: '프롬프트 2', imageUrl: null, mode: null },
    ]);
    result.forEach((dto) => {
      expect(dto).not.toHaveProperty('checklistItems');
      expect(dto).not.toHaveProperty('expectedRegister');
      expect(dto).not.toHaveProperty('referenceKeywords');
    });
  });
});

describe('ExamSessionController.getQuestion', () => {
  it('delegates to ExamSessionQuestionService.getQuestion and strips grading info from the response', async () => {
    const getQuestion = jest.fn().mockResolvedValue(buildQuestion('3'));
    const controller = buildController({}, { getQuestion });

    const result = await controller.getQuestion('1', '3', buildUser());

    expect(getQuestion).toHaveBeenCalledWith('1', '3', '1', false);
    expect(result).toEqual({
      id: '3',
      part: 'work_log',
      prompt: '프롬프트 3',
      imageUrl: null,
      mode: null,
    });
  });

  it('exposes imageUrl and mode for picture-description questions', async () => {
    const question = new Question(
      '4',
      'picture_description',
      {
        item_id: 'PIC-001',
        prompt: '그림을 보고 상황을 설명하세요.',
        expected_register: 'formal',
        reference_keywords: [],
        image_url: 'pic-001.png',
        mode: 'speaking',
      },
      null,
      [],
      new Date(),
    );
    const getQuestion = jest.fn().mockResolvedValue(question);
    const controller = buildController({}, { getQuestion });

    const result = await controller.getQuestion('1', '4', buildUser());

    expect(result.imageUrl).toBe(
      'https://project.supabase.co/storage/v1/object/public/question-assets/pic-001.png',
    );
    expect(result.mode).toBe('speaking');
  });

  it('tells the service the caller is an admin so ownership can be bypassed', async () => {
    const getQuestion = jest.fn().mockResolvedValue(buildQuestion('3'));
    const controller = buildController({}, { getQuestion });
    const admin: AuthenticatedUser = { id: '9', email: 'admin@test.com', role: Role.ADMIN };

    await controller.getQuestion('1', '3', admin);

    expect(getQuestion).toHaveBeenCalledWith('1', '3', '9', true);
  });
});

describe('ExamSessionController.saveAnswer', () => {
  it('delegates to ExamSessionAnswerService.save and maps the response', async () => {
    const answer = buildAnswer();
    const save = jest.fn().mockResolvedValue({ answer, graded: false, score: null });
    const controller = buildController({}, {}, { save });
    const dto = { type: AnswerType.TEXT, contentText: '내용' };

    const result = await controller.saveAnswer('1', '1', dto, buildUser());

    expect(save).toHaveBeenCalledWith('1', '1', '1', dto);
    expect(result).toEqual({
      id: '1',
      questionId: '1',
      type: AnswerType.TEXT,
      contentText: '내용',
      audioFileUrl: null,
      status: AnswerStatus.DRAFT,
      modifiedAt: answer.modifiedAt,
      graded: false,
      score: null,
    });
  });

  it('converts a stored AUDIO path to a full public URL in the response', async () => {
    const answer = new Answer(
      '1',
      '1',
      '1',
      AnswerType.AUDIO,
      null,
      '9/1/1.webm',
      AnswerStatus.DRAFT,
      new Date('2026-06-01T00:00:00.000Z'),
    );
    const save = jest.fn().mockResolvedValue({ answer, graded: false, score: null });
    const controller = buildController({}, {}, { save });
    const dto = { type: AnswerType.AUDIO, audioFileUrl: '9/1/1.webm' };

    const result = await controller.saveAnswer('1', '1', dto, buildUser());

    expect(result.audioFileUrl).toBe(
      'https://project.supabase.co/storage/v1/object/public/answer-audio/9/1/1.webm',
    );
  });
});

describe('ExamSessionController.getAnswer', () => {
  it('delegates to ExamSessionAnswerService.get and includes the grading status', async () => {
    const answer = buildAnswer();
    const get = jest.fn().mockResolvedValue({ answer, graded: true, score: { total: 90 } });
    const controller = buildController({}, {}, { get });

    const result = await controller.getAnswer('1', '1', buildUser());

    expect(get).toHaveBeenCalledWith('1', '1', '1');
    expect(result.graded).toBe(true);
    expect(result.score).toEqual({ total: 90 });
  });
});
