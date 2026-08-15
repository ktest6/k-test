import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { StoragePublicUrlService } from '../../../infrastructure/supabase/storage-public-url.service';
import { Answer } from '../../answer/domain/entities/answer.entity';
import { AnswerStatus } from '../../answer/domain/enums/answer-status.enum';
import { AnswerType } from '../../answer/domain/enums/answer-type.enum';
import { Question } from '../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../question/domain/enums/question-section-type.enum';
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
    QuestionSectionType.SITUATION_DESCRIPTION,
    {
      preparationSeconds: 40,
      responseSeconds: 60,
      guideTexts: ['안내문구'],
      instruction: `프롬프트 ${id}`,
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
    const session = buildSession();
    const getStatus = jest.fn().mockResolvedValue({
      session,
      status: SessionStatus.INPROGRESS,
      remainingSeconds: 120,
      nextQuestionId: '5',
    });
    const controller = buildController({ getStatus });

    const result = await controller.getStatus('1', buildUser());

    expect(getStatus).toHaveBeenCalledWith('1', '1');
    expect(result).toEqual({
      id: '1',
      examId: '1',
      status: SessionStatus.INPROGRESS,
      nextQuestionId: '5',
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
      {
        id: '1',
        part: QuestionSectionType.SITUATION_DESCRIPTION,
        preparationSeconds: 40,
        responseSeconds: 60,
        guideTexts: ['안내문구'],
        instruction: '프롬프트 1',
        imageUrl: null,
        safetyRulesTitle: null,
        safetyRules: null,
        audioUrl: null,
      },
      {
        id: '2',
        part: QuestionSectionType.SITUATION_DESCRIPTION,
        preparationSeconds: 40,
        responseSeconds: 60,
        guideTexts: ['안내문구'],
        instruction: '프롬프트 2',
        imageUrl: null,
        safetyRulesTitle: null,
        safetyRules: null,
        audioUrl: null,
      },
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
      part: QuestionSectionType.SITUATION_DESCRIPTION,
      preparationSeconds: 40,
      responseSeconds: 60,
      guideTexts: ['안내문구'],
      instruction: '프롬프트 3',
      imageUrl: null,
      safetyRulesTitle: null,
      safetyRules: null,
      audioUrl: null,
    });
  });

  it('exposes imageUrl and safetyRules for their respective question types', async () => {
    const question = new Question(
      '4',
      QuestionSectionType.READ_AND_EXPLAIN,
      {
        preparationSeconds: 70,
        responseSeconds: 80,
        guideTexts: ['90초 동안 말할 수 있습니다'],
        instruction: '다음 안전수칙을 읽고 새로 온 동료에게 알려주세요.',
        imageUrl: 'pic-001.png',
        safetyRulesTitle: '작업장 안전수칙',
        safetyRules: ['A. 안전모를 착용하세요', 'B. 지정된 통로로만 이동하세요'],
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
    expect(result.safetyRulesTitle).toBe('작업장 안전수칙');
    expect(result.safetyRules).toEqual(['A. 안전모를 착용하세요', 'B. 지정된 통로로만 이동하세요']);
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
    const dto = { audioFileUrl: '9/1/1.webm' };

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
    const dto = { audioFileUrl: '9/1/1.webm' };

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
