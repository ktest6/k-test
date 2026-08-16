import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../domain/entities/exam.entity';
import { ExamApplication } from '../../domain/entities/exam-application.entity';
import { ExamApplicationRepository } from '../../domain/exam-application.repository.interface';
import { ExamApplicationService } from './exam-application.service';
import { ExamService } from './exam.service';

function buildExam(
  overrides: Partial<{
    applicationOpenAt: Date;
    applicationCloseAt: Date;
    openAt: Date;
    closeAt: Date;
    capacity: number;
  }> = {},
): Exam {
  return new Exam(
    '1',
    '2026년 1회차',
    overrides.applicationOpenAt ?? new Date('2026-01-01T00:00:00.000Z'),
    overrides.applicationCloseAt ?? new Date('2026-12-31T23:59:59.000Z'),
    overrides.openAt ?? new Date('2027-01-01T00:00:00.000Z'),
    overrides.closeAt ?? new Date('2027-01-14T23:59:59.000Z'),
    overrides.capacity ?? 100,
    new Date(),
  );
}

function buildRepository(overrides: Partial<ExamApplicationRepository> = {}) {
  return {
    create: jest.fn(),
    findActiveByExamAndUser: jest.fn().mockResolvedValue(null),
    cancel: jest.fn(),
    countActiveByExam: jest.fn().mockResolvedValue(0),
    listActiveByUser: jest.fn().mockResolvedValue([]),
    ...overrides,
  };
}

describe('ExamApplicationService.apply', () => {
  it('rejects when the current time is outside the application period', async () => {
    const exam = buildExam({ applicationOpenAt: new Date('2099-01-01T00:00:00.000Z') }); // 아직 신청 시작 전
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const repository = buildRepository();
    const service = new ExamApplicationService(examService, repository);

    await expect(service.apply('1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects a duplicate active application', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const existing = new ExamApplication('5', '1', '1', new Date());
    const repository = buildRepository({
      findActiveByExamAndUser: jest.fn().mockResolvedValue(existing),
    });
    const service = new ExamApplicationService(examService, repository);

    await expect(service.apply('1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects when capacity is already full', async () => {
    const exam = buildExam({ capacity: 2 });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const repository = buildRepository({ countActiveByExam: jest.fn().mockResolvedValue(2) });
    const service = new ExamApplicationService(examService, repository);

    await expect(service.apply('1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('creates the application when open, not duplicated, and under capacity', async () => {
    const exam = buildExam({ capacity: 2 });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const created = new ExamApplication('9', '1', '1', new Date());
    const repository = buildRepository({
      countActiveByExam: jest.fn().mockResolvedValue(1),
      create: jest.fn().mockResolvedValue(created),
    });
    const service = new ExamApplicationService(examService, repository);

    const result = await service.apply('1', '1');

    expect(repository.create).toHaveBeenCalledWith({ examId: '1', userId: '1' });
    expect(result).toBe(created);
  });
});

describe('ExamApplicationService.cancel', () => {
  it('rejects when there is no active application', async () => {
    const examService = {} as unknown as ExamService;
    const repository = buildRepository();
    const service = new ExamApplicationService(examService, repository);

    await expect(service.cancel('1', '1')).rejects.toThrow(NotFoundDomainException);
    expect(repository.cancel).not.toHaveBeenCalled();
  });

  it('cancels the caller’s own active application', async () => {
    const examService = {} as unknown as ExamService;
    const existing = new ExamApplication('5', '1', '1', new Date());
    const repository = buildRepository({
      findActiveByExamAndUser: jest.fn().mockResolvedValue(existing),
    });
    const service = new ExamApplicationService(examService, repository);

    await service.cancel('1', '1');

    expect(repository.cancel).toHaveBeenCalledWith('5');
  });
});

describe('ExamApplicationService.listMine', () => {
  it('delegates to the repository', async () => {
    const examService = {} as unknown as ExamService;
    const applications = [new ExamApplication('5', '1', '9', new Date())];
    const listActiveByUser = jest.fn().mockResolvedValue(applications);
    const repository = buildRepository({ listActiveByUser });
    const service = new ExamApplicationService(examService, repository);

    const result = await service.listMine('9');

    expect(listActiveByUser).toHaveBeenCalledWith('9');
    expect(result).toBe(applications);
  });
});
