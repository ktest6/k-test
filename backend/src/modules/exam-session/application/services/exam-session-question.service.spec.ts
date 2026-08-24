import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { QuestionService } from '../../../question/application/services/question.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { SkippedQuestionRepository } from '../../domain/skipped-question.repository.interface';
import { ExamSessionQuestionService } from './exam-session-question.service';
import { ExamSessionService } from './exam-session.service';

function buildSession(overrides: Partial<{ userId: string }> = {}): ExamSession {
  return new ExamSession(
    '1',
    overrides.userId ?? '1',
    SessionStatus.INPROGRESS,
    0,
    new Date('2026-06-01T00:00:00.000Z'),
    null,
    null,
    null,
    new Date(),
  );
}

function buildQuestion(id: string, part = QuestionSectionType.SITUATION_DESCRIPTION): Question {
  return new Question(
    id,
    part,
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

/** 파트별로 넉넉한 풀(각 5개)을 만든다 — 세션마다 3개씩 결정적으로 뽑힌다. */
function buildQuestionPools(): Record<QuestionSectionType, Question[]> {
  return {
    [QuestionSectionType.SITUATION_DESCRIPTION]: Array.from({ length: 5 }, (_, i) =>
      buildQuestion(`sit-${i + 1}`, QuestionSectionType.SITUATION_DESCRIPTION),
    ),
    [QuestionSectionType.READ_AND_EXPLAIN]: Array.from({ length: 5 }, (_, i) =>
      buildQuestion(`read-${i + 1}`, QuestionSectionType.READ_AND_EXPLAIN),
    ),
    [QuestionSectionType.ANSWER_QUESTION]: Array.from({ length: 5 }, (_, i) =>
      buildQuestion(`ans-${i + 1}`, QuestionSectionType.ANSWER_QUESTION),
    ),
  };
}

function buildQuestionService(
  pools: Record<QuestionSectionType, Question[]> = buildQuestionPools(),
) {
  const findByPart = jest.fn((part: QuestionSectionType) => Promise.resolve(pools[part]));
  return { findByPart } as unknown as QuestionService;
}

function buildAnswerService(overrides: Partial<{ listAnsweredQuestionIds: jest.Mock }> = {}) {
  return {
    listAnsweredQuestionIds: jest.fn().mockResolvedValue([]),
    ...overrides,
  } as unknown as AnswerService;
}

function buildSkippedQuestionRepository(
  overrides: Partial<{ listSkippedQuestionIds: jest.Mock }> = {},
) {
  return {
    create: jest.fn(),
    listSkippedQuestionIds: jest.fn().mockResolvedValue([]),
    deleteBySessionAndQuestion: jest.fn(),
    ...overrides,
  } as unknown as SkippedQuestionRepository;
}

function buildExamSessionService(
  overrides: Partial<{
    assertVerifiedSession: jest.Mock;
    getSessionOrThrow: jest.Mock;
  }> = {},
) {
  return {
    assertVerifiedSession: jest.fn().mockResolvedValue(buildSession()),
    getSessionOrThrow: jest.fn().mockResolvedValue(buildSession()),
    ...overrides,
  } as unknown as ExamSessionService;
}

describe('ExamSessionQuestionService.listQuestions', () => {
  it('rejects when the caller has not completed verification (delegated to assertVerifiedSession)', async () => {
    const assertVerifiedSession = jest
      .fn()
      .mockRejectedValue(new ForbiddenDomainException('본인인증을 먼저 완료해야 합니다.'));
    const examSessionService = buildExamSessionService({ assertVerifiedSession });
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      buildAnswerService(),
    );

    await expect(service.listQuestions('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('returns 3 questions per part, stable across repeated calls for the same session', async () => {
    const examSessionService = buildExamSessionService();
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      buildAnswerService(),
    );

    const resultA1 = await service.listQuestions('session-a', '1');
    const resultA2 = await service.listQuestions('session-a', '1');

    expect(resultA1).toHaveLength(9);
    expect(resultA1.map((r) => r.question.id)).toEqual(resultA2.map((r) => r.question.id));
    expect(new Set(resultA1.map((r) => r.question.id)).size).toBe(9);
  });

  it('produces a different selection for a different session id', async () => {
    const examSessionService = buildExamSessionService();
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      buildAnswerService(),
    );

    const orderA = (await service.listQuestions('session-a', '1')).map((r) => r.question.id);
    const orderB = (await service.listQuestions('session-b', '1')).map((r) => r.question.id);

    expect(orderA).not.toEqual(orderB);
  });

  it('groups questions by section in a fixed order (상황묘사 → 읽고설명 → 질문답변), 3 per section', async () => {
    const examSessionService = buildExamSessionService();
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      buildAnswerService(),
    );

    const result = await service.listQuestions('session-a', '1');

    expect(result.map((r) => r.question.part)).toEqual([
      QuestionSectionType.SITUATION_DESCRIPTION,
      QuestionSectionType.SITUATION_DESCRIPTION,
      QuestionSectionType.SITUATION_DESCRIPTION,
      QuestionSectionType.READ_AND_EXPLAIN,
      QuestionSectionType.READ_AND_EXPLAIN,
      QuestionSectionType.READ_AND_EXPLAIN,
      QuestionSectionType.ANSWER_QUESTION,
      QuestionSectionType.ANSWER_QUESTION,
      QuestionSectionType.ANSWER_QUESTION,
    ]);
  });

  it('marks each question as answered based on the session’s saved answers', async () => {
    const examSessionService = buildExamSessionService();
    const answerService = buildAnswerService({
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['sit-1']),
    });
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      answerService,
    );

    const result = await service.listQuestions('session-a', '1');

    const situationResults = result.filter(
      (r) => r.question.part === QuestionSectionType.SITUATION_DESCRIPTION,
    );
    expect(situationResults.some((r) => r.answered)).toBe(
      situationResults.some((r) => r.question.id === 'sit-1'),
    );
  });
});

describe('ExamSessionQuestionService.getQuestion', () => {
  it('rejects when the caller has not completed verification', async () => {
    const assertVerifiedSession = jest
      .fn()
      .mockRejectedValue(new ForbiddenDomainException('본인인증을 먼저 완료해야 합니다.'));
    const examSessionService = buildExamSessionService({ assertVerifiedSession });
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      buildAnswerService(),
    );

    await expect(service.getQuestion('1', 'sit-1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('rejects when the question is not part of this session’s selection', async () => {
    const examSessionService = buildExamSessionService();
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      buildAnswerService(),
    );

    await expect(service.getQuestion('1', 'not-in-pool', '1')).rejects.toThrow(
      NotFoundDomainException,
    );
  });

  it('returns the matching question with its answered flag', async () => {
    const examSessionService = buildExamSessionService();
    const answerService = buildAnswerService({
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['sit-1']),
    });
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      answerService,
    );

    const questions = await service.listQuestions('1', '1');
    const target = questions[0];

    const result = await service.getQuestion('1', target.question.id, '1');

    expect(result.question.id).toBe(target.question.id);
  });

  it('allows an admin to bypass ownership/verification checks', async () => {
    const getSessionOrThrow = jest.fn().mockResolvedValue(buildSession({ userId: '2' }));
    const examSessionService = buildExamSessionService({ getSessionOrThrow });
    const service = new ExamSessionQuestionService(
      examSessionService,
      buildSkippedQuestionRepository(),
      buildQuestionService(),
      buildAnswerService(),
    );

    const questions = await service.listQuestions('1', '2');
    const target = questions[0];

    const result = await service.getQuestion('1', target.question.id, '1', true);

    expect(result.question.id).toBe(target.question.id);
    expect(getSessionOrThrow).toHaveBeenCalledWith('1');
  });
});
