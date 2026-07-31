import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../../exam/domain/entities/exam.entity';
import { ExamApplicationService } from '../../../exam/application/services/exam-application.service';
import { ExamService } from '../../../exam/application/services/exam.service';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { ExamSessionRepository } from '../../domain/exam-session.repository.interface';
import { ExamSessionService } from './exam-session.service';

function buildExam(overrides: Partial<{ openAt: Date; closeAt: Date }> = {}): Exam {
  return new Exam(
    '1',
    '2026년 1회차',
    new Date('2026-01-01T00:00:00.000Z'),
    new Date('2026-12-31T23:59:59.000Z'),
    overrides.openAt ?? new Date('2026-01-01T00:00:00.000Z'),
    overrides.closeAt ?? new Date('2026-12-31T23:59:59.000Z'),
    100,
    new Date(),
  );
}

function buildSession(
  overrides: Partial<{
    status: SessionStatus;
    userId: string;
    currentQuestionId: string | null;
  }> = {},
): ExamSession {
  return new ExamSession(
    '1',
    '1',
    overrides.userId ?? '1',
    overrides.status ?? SessionStatus.INPROGRESS,
    new Date('2026-06-01T00:00:00.000Z'),
    overrides.currentQuestionId ?? null,
    null,
    null,
    new Date(),
  );
}

function buildRepository(overrides: Partial<ExamSessionRepository> = {}) {
  return {
    create: jest.fn(),
    findById: jest.fn().mockResolvedValue(null),
    findByUserAndExam: jest.fn().mockResolvedValue(null),
    ...overrides,
  };
}

describe('ExamSessionService.start', () => {
  it('rejects when the exam is not currently OPEN', async () => {
    const exam = buildExam({ openAt: new Date('2099-01-01T00:00:00.000Z') });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn(),
    } as unknown as ExamApplicationService;
    const repository = buildRepository();
    const service = new ExamSessionService(repository, examService, examApplicationService);

    await expect(service.start('1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects when the caller has no active application', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const hasActiveApplication = jest.fn().mockResolvedValue(false);
    const examApplicationService = { hasActiveApplication } as unknown as ExamApplicationService;
    const repository = buildRepository();
    const service = new ExamSessionService(repository, examService, examApplicationService);

    await expect(service.start('1', '1')).rejects.toThrow(ForbiddenDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects starting again once the existing session is already SUBMITTED', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const existing = buildSession({ status: SessionStatus.SUBMITTED });
    const repository = buildRepository({
      findByUserAndExam: jest.fn().mockResolvedValue(existing),
    });
    const service = new ExamSessionService(repository, examService, examApplicationService);

    await expect(service.start('1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('resumes the existing session instead of creating a new one when still INPROGRESS', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const existing = buildSession({ status: SessionStatus.INPROGRESS });
    const repository = buildRepository({
      findByUserAndExam: jest.fn().mockResolvedValue(existing),
    });
    const service = new ExamSessionService(repository, examService, examApplicationService);

    const result = await service.start('1', '1');

    expect(result).toBe(existing);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('creates a new session when none exists yet', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const created = buildSession();
    const repository = buildRepository({ create: jest.fn().mockResolvedValue(created) });
    const service = new ExamSessionService(repository, examService, examApplicationService);

    const result = await service.start('1', '1');

    expect(repository.create).toHaveBeenCalledWith({ examId: '1', userId: '1' });
    expect(result).toBe(created);
  });
});

describe('ExamSessionService.getStatus', () => {
  it('rejects when the session does not exist', async () => {
    const examService = {} as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository();
    const service = new ExamSessionService(repository, examService, examApplicationService);

    await expect(service.getStatus('1', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects when the caller is not the session owner', async () => {
    const session = buildSession({ userId: '2' });
    const examService = {} as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(repository, examService, examApplicationService);

    await expect(service.getStatus('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('reports EXPIRED with 0 remaining seconds when past the exam close time but still INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const exam = buildExam({ closeAt: new Date('2020-01-01T00:00:00.000Z') });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(repository, examService, examApplicationService);

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.EXPIRED);
    expect(result.remainingSeconds).toBe(0);
  });

  it('reports INPROGRESS with positive remaining seconds when still within the exam period', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS, currentQuestionId: '3' });
    const exam = buildExam({ closeAt: new Date(Date.now() + 3600_000) });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(repository, examService, examApplicationService);

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.INPROGRESS);
    expect(result.remainingSeconds).toBeGreaterThan(0);
    expect(result.session.currentQuestionId).toBe('3');
  });

  it('reports SUBMITTED as-is with 0 remaining seconds regardless of the exam close time', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const exam = buildExam({ closeAt: new Date(Date.now() + 3600_000) });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(repository, examService, examApplicationService);

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.SUBMITTED);
    expect(result.remainingSeconds).toBe(0);
  });
});
