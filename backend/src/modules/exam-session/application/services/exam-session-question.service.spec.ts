import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { ExamQuestionService } from '../../../exam-question/application/services/exam-question.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { ExamSessionRepository } from '../../domain/exam-session.repository.interface';
import { SkippedQuestionRepository } from '../../domain/skipped-question.repository.interface';
import { ExamSessionQuestionService } from './exam-session-question.service';

function buildSession(overrides: Partial<{ userId: string; examId: string }> = {}): ExamSession {
  return new ExamSession(
    '1',
    overrides.examId ?? '1',
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

function buildRepository(overrides: Partial<ExamSessionRepository> = {}) {
  return {
    create: jest.fn(),
    findById: jest.fn().mockResolvedValue(null),
    findByUserAndExam: jest.fn(),
    updateResumeCount: jest.fn(),
    updateStatus: jest.fn(),
    ...overrides,
  };
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

describe('ExamSessionQuestionService.listQuestions', () => {
  it('rejects when the session does not exist', async () => {
    const repository = buildRepository();
    const examQuestionService = {
      listAssignedQuestions: jest.fn(),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      buildAnswerService(),
    );

    await expect(service.listQuestions('1', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects when the caller is not the session owner', async () => {
    const repository = buildRepository({
      findById: jest.fn().mockResolvedValue(buildSession({ userId: '2' })),
    });
    const examQuestionService = {
      listAssignedQuestions: jest.fn(),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      buildAnswerService(),
    );

    await expect(service.listQuestions('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('returns the exam-assigned questions in a stable session-specific shuffled order, never twice the same for two different sessions', async () => {
    const questions = [
      buildQuestion('1'),
      buildQuestion('2'),
      buildQuestion('3'),
      buildQuestion('4'),
      buildQuestion('5'),
    ];
    const listAssignedQuestions = jest.fn().mockResolvedValue(questions);
    const examQuestionService = { listAssignedQuestions } as unknown as ExamQuestionService;

    const repositoryA = buildRepository({
      findById: jest.fn().mockResolvedValue(buildSession({ examId: '9' })),
    });
    const serviceA = new ExamSessionQuestionService(
      repositoryA,
      buildSkippedQuestionRepository(),
      examQuestionService,
      buildAnswerService(),
    );
    const resultA1 = await serviceA.listQuestions('session-a', '1');
    const resultA2 = await serviceA.listQuestions('session-a', '1');

    expect(listAssignedQuestions).toHaveBeenCalledWith('9');
    expect(resultA1.map((r) => r.question.id)).toEqual(resultA2.map((r) => r.question.id));
    expect(resultA1).toHaveLength(5);
    expect(new Set(resultA1.map((r) => r.question.id)).size).toBe(5);
  });

  it('produces a different order for a different session id', async () => {
    const questions = Array.from({ length: 10 }, (_, i) => buildQuestion(String(i + 1)));
    const listAssignedQuestions = jest.fn().mockResolvedValue(questions);
    const examQuestionService = { listAssignedQuestions } as unknown as ExamQuestionService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(buildSession()) });
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      buildAnswerService(),
    );

    const orderA = (await service.listQuestions('session-a', '1')).map((r) => r.question.id);
    const orderB = (await service.listQuestions('session-b', '1')).map((r) => r.question.id);

    expect(orderA).not.toEqual(orderB);
  });

  it('groups questions by section in a fixed order, shuffling only within each section', async () => {
    // 일부러 뒤죽박죽 순서로 배정 목록을 준다 — 결과는 그래도 1섹션(2개) → 2섹션(2개) → 3섹션(2개)여야 한다.
    const questions = [
      buildQuestion('answer-1', QuestionSectionType.ANSWER_QUESTION),
      buildQuestion('situation-1', QuestionSectionType.SITUATION_DESCRIPTION),
      buildQuestion('read-1', QuestionSectionType.READ_AND_EXPLAIN),
      buildQuestion('answer-2', QuestionSectionType.ANSWER_QUESTION),
      buildQuestion('situation-2', QuestionSectionType.SITUATION_DESCRIPTION),
      buildQuestion('read-2', QuestionSectionType.READ_AND_EXPLAIN),
    ];
    const listAssignedQuestions = jest.fn().mockResolvedValue(questions);
    const examQuestionService = { listAssignedQuestions } as unknown as ExamQuestionService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(buildSession()) });
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      buildAnswerService(),
    );

    const result = await service.listQuestions('session-a', '1');

    expect(result.map((r) => r.question.part)).toEqual([
      QuestionSectionType.SITUATION_DESCRIPTION,
      QuestionSectionType.SITUATION_DESCRIPTION,
      QuestionSectionType.READ_AND_EXPLAIN,
      QuestionSectionType.READ_AND_EXPLAIN,
      QuestionSectionType.ANSWER_QUESTION,
      QuestionSectionType.ANSWER_QUESTION,
    ]);
  });

  it('marks each question as answered based on the session’s saved answers', async () => {
    const questions = [buildQuestion('1'), buildQuestion('2'), buildQuestion('3')];
    const listAssignedQuestions = jest.fn().mockResolvedValue(questions);
    const examQuestionService = { listAssignedQuestions } as unknown as ExamQuestionService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(buildSession()) });
    const answerService = buildAnswerService({
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1', '3']),
    });
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      answerService,
    );

    const result = await service.listQuestions('session-a', '1');

    expect(
      result
        .map((r) => ({ id: r.question.id, answered: r.answered }))
        .sort((a, b) => (a.id > b.id ? 1 : -1)),
    ).toEqual([
      { id: '1', answered: true },
      { id: '2', answered: false },
      { id: '3', answered: true },
    ]);
  });
});

describe('ExamSessionQuestionService.getQuestion', () => {
  it('rejects when the caller is not the session owner', async () => {
    const repository = buildRepository({
      findById: jest.fn().mockResolvedValue(buildSession({ userId: '2' })),
    });
    const examQuestionService = {
      listAssignedQuestions: jest.fn(),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      buildAnswerService(),
    );

    await expect(service.getQuestion('1', '5', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('rejects when the question is not assigned to this session’s exam', async () => {
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(buildSession()) });
    const examQuestionService = {
      listAssignedQuestions: jest.fn().mockResolvedValue([buildQuestion('1')]),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      buildAnswerService(),
    );

    await expect(service.getQuestion('1', '999', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('returns the matching question with its answered flag', async () => {
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(buildSession()) });
    const target = buildQuestion('2');
    const examQuestionService = {
      listAssignedQuestions: jest.fn().mockResolvedValue([buildQuestion('1'), target]),
    } as unknown as ExamQuestionService;
    const answerService = buildAnswerService({
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['2']),
    });
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      answerService,
    );

    const result = await service.getQuestion('1', '2', '1');

    expect(result.question).toBe(target);
    expect(result.answered).toBe(true);
  });

  it('allows an admin to bypass the ownership check', async () => {
    const repository = buildRepository({
      findById: jest.fn().mockResolvedValue(buildSession({ userId: '2' })),
    });
    const target = buildQuestion('2');
    const examQuestionService = {
      listAssignedQuestions: jest.fn().mockResolvedValue([target]),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(
      repository,
      buildSkippedQuestionRepository(),
      examQuestionService,
      buildAnswerService(),
    );

    const result = await service.getQuestion('1', '2', '1', true);

    expect(result.question).toBe(target);
  });
});
