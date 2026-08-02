import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { ExamQuestionService } from '../../../exam-question/application/services/exam-question.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { ExamSessionRepository } from '../../domain/exam-session.repository.interface';
import { ExamSessionQuestionService } from './exam-session-question.service';

function buildSession(overrides: Partial<{ userId: string; examId: string }> = {}): ExamSession {
  return new ExamSession(
    '1',
    overrides.examId ?? '1',
    overrides.userId ?? '1',
    SessionStatus.INPROGRESS,
    new Date('2026-06-01T00:00:00.000Z'),
    null,
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
      reference_keywords: [],
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
    ...overrides,
  };
}

describe('ExamSessionQuestionService.listQuestions', () => {
  it('rejects when the session does not exist', async () => {
    const repository = buildRepository();
    const examQuestionService = {
      listAssignedQuestions: jest.fn(),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(repository, examQuestionService);

    await expect(service.listQuestions('1', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects when the caller is not the session owner', async () => {
    const repository = buildRepository({
      findById: jest.fn().mockResolvedValue(buildSession({ userId: '2' })),
    });
    const examQuestionService = {
      listAssignedQuestions: jest.fn(),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(repository, examQuestionService);

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
    const serviceA = new ExamSessionQuestionService(repositoryA, examQuestionService);
    const resultA1 = await serviceA.listQuestions('session-a', '1');
    const resultA2 = await serviceA.listQuestions('session-a', '1');

    expect(listAssignedQuestions).toHaveBeenCalledWith('9');
    expect(resultA1.map((q) => q.id)).toEqual(resultA2.map((q) => q.id));
    expect(resultA1).toHaveLength(5);
    expect(new Set(resultA1.map((q) => q.id)).size).toBe(5);
  });

  it('produces a different order for a different session id', async () => {
    const questions = Array.from({ length: 10 }, (_, i) => buildQuestion(String(i + 1)));
    const listAssignedQuestions = jest.fn().mockResolvedValue(questions);
    const examQuestionService = { listAssignedQuestions } as unknown as ExamQuestionService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(buildSession()) });
    const service = new ExamSessionQuestionService(repository, examQuestionService);

    const orderA = (await service.listQuestions('session-a', '1')).map((q) => q.id);
    const orderB = (await service.listQuestions('session-b', '1')).map((q) => q.id);

    expect(orderA).not.toEqual(orderB);
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
    const service = new ExamSessionQuestionService(repository, examQuestionService);

    await expect(service.getQuestion('1', '5', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('rejects when the question is not assigned to this session’s exam', async () => {
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(buildSession()) });
    const examQuestionService = {
      listAssignedQuestions: jest.fn().mockResolvedValue([buildQuestion('1')]),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(repository, examQuestionService);

    await expect(service.getQuestion('1', '999', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('returns the matching question', async () => {
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(buildSession()) });
    const target = buildQuestion('2');
    const examQuestionService = {
      listAssignedQuestions: jest.fn().mockResolvedValue([buildQuestion('1'), target]),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(repository, examQuestionService);

    const result = await service.getQuestion('1', '2', '1');

    expect(result).toBe(target);
  });

  it('allows an admin to bypass the ownership check', async () => {
    const repository = buildRepository({
      findById: jest.fn().mockResolvedValue(buildSession({ userId: '2' })),
    });
    const target = buildQuestion('2');
    const examQuestionService = {
      listAssignedQuestions: jest.fn().mockResolvedValue([target]),
    } as unknown as ExamQuestionService;
    const service = new ExamSessionQuestionService(repository, examQuestionService);

    const result = await service.getQuestion('1', '2', '1', true);

    expect(result).toBe(target);
  });
});
