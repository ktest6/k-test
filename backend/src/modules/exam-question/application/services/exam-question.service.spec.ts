import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../../exam/domain/entities/exam.entity';
import { ExamService } from '../../../exam/application/services/exam.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionService } from '../../../question/application/services/question.service';
import { ExamQuestion } from '../../domain/entities/exam-question.entity';
import { ExamQuestionRepository } from '../../domain/exam-question.repository.interface';
import { ExamQuestionService } from './exam-question.service';

function buildExam(): Exam {
  return new Exam(
    '1',
    '2026년 1회차',
    new Date('2026-01-01T00:00:00.000Z'),
    new Date('2026-12-31T23:59:59.000Z'),
    new Date('2027-01-01T00:00:00.000Z'),
    new Date('2027-01-14T23:59:59.000Z'),
    100,
    new Date(),
  );
}

function buildQuestion(id = '1'): Question {
  return new Question(
    id,
    'work_log',
    { item_id: 'WRT-001', prompt: 'p', expected_register: 'formal', reference_keywords: ['a'] },
    null,
    [],
    new Date(),
  );
}

function buildAssignment(
  overrides: Partial<{ id: string; questionId: string }> = {},
): ExamQuestion {
  return new ExamQuestion(overrides.id ?? '1', '1', overrides.questionId ?? '1', '1', new Date());
}

function buildRepository(overrides: Partial<ExamQuestionRepository> = {}) {
  return {
    create: jest.fn(),
    findActiveByExamAndQuestion: jest.fn().mockResolvedValue(null),
    findActiveByExam: jest.fn().mockResolvedValue([]),
    unassign: jest.fn(),
    ...overrides,
  };
}

describe('ExamQuestionService.assign', () => {
  it('rejects when the exam does not exist', async () => {
    const examService = {
      findById: jest.fn().mockRejectedValue(new NotFoundDomainException('없음')),
    } as unknown as ExamService;
    const questionService = { findById: jest.fn() } as unknown as QuestionService;
    const repository = buildRepository();
    const service = new ExamQuestionService(repository, examService, questionService);

    await expect(service.assign('1', '1', '1')).rejects.toThrow(NotFoundDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects when the question does not exist', async () => {
    const examService = {
      findById: jest.fn().mockResolvedValue(buildExam()),
    } as unknown as ExamService;
    const questionService = {
      findById: jest.fn().mockRejectedValue(new NotFoundDomainException('없음')),
    } as unknown as QuestionService;
    const repository = buildRepository();
    const service = new ExamQuestionService(repository, examService, questionService);

    await expect(service.assign('1', '1', '1')).rejects.toThrow(NotFoundDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects when the question is already assigned to this exam', async () => {
    const examService = {
      findById: jest.fn().mockResolvedValue(buildExam()),
    } as unknown as ExamService;
    const questionService = {
      findById: jest.fn().mockResolvedValue(buildQuestion()),
    } as unknown as QuestionService;
    const repository = buildRepository({
      findActiveByExamAndQuestion: jest.fn().mockResolvedValue(buildAssignment()),
    });
    const service = new ExamQuestionService(repository, examService, questionService);

    await expect(service.assign('1', '1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('creates the assignment when the exam/question exist and are not already linked', async () => {
    const examService = {
      findById: jest.fn().mockResolvedValue(buildExam()),
    } as unknown as ExamService;
    const questionService = {
      findById: jest.fn().mockResolvedValue(buildQuestion()),
    } as unknown as QuestionService;
    const created = buildAssignment();
    const repository = buildRepository({ create: jest.fn().mockResolvedValue(created) });
    const service = new ExamQuestionService(repository, examService, questionService);

    const result = await service.assign('1', '1', '5');

    expect(repository.create).toHaveBeenCalledWith({
      examId: '1',
      questionId: '1',
      assignedBy: '5',
    });
    expect(result).toBe(created);
  });
});

describe('ExamQuestionService.unassign', () => {
  it('rejects when there is no active assignment', async () => {
    const examService = {} as unknown as ExamService;
    const questionService = {} as unknown as QuestionService;
    const repository = buildRepository();
    const service = new ExamQuestionService(repository, examService, questionService);

    await expect(service.unassign('1', '1')).rejects.toThrow(NotFoundDomainException);
    expect(repository.unassign).not.toHaveBeenCalled();
  });

  it('soft-deletes the found assignment', async () => {
    const examService = {} as unknown as ExamService;
    const questionService = {} as unknown as QuestionService;
    const existing = buildAssignment({ id: '9' });
    const repository = buildRepository({
      findActiveByExamAndQuestion: jest.fn().mockResolvedValue(existing),
    });
    const service = new ExamQuestionService(repository, examService, questionService);

    await service.unassign('1', '1');

    expect(repository.unassign).toHaveBeenCalledWith('9');
  });
});

describe('ExamQuestionService.listAssignedQuestions', () => {
  it('checks the exam exists, then resolves the assigned questions by id', async () => {
    const findExamById = jest.fn().mockResolvedValue(buildExam());
    const examService = { findById: findExamById } as unknown as ExamService;
    const questions = [buildQuestion('1'), buildQuestion('2')];
    const findByIds = jest.fn().mockResolvedValue(questions);
    const questionService = { findByIds } as unknown as QuestionService;
    const repository = buildRepository({
      findActiveByExam: jest
        .fn()
        .mockResolvedValue([
          buildAssignment({ questionId: '1' }),
          buildAssignment({ questionId: '2' }),
        ]),
    });
    const service = new ExamQuestionService(repository, examService, questionService);

    const result = await service.listAssignedQuestions('1');

    expect(findExamById).toHaveBeenCalledWith('1');
    expect(findByIds).toHaveBeenCalledWith(['1', '2']);
    expect(result).toBe(questions);
  });
});
