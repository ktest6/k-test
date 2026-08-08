import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../../exam/domain/entities/exam.entity';
import { ExamApplicationService } from '../../../exam/application/services/exam-application.service';
import { ExamService } from '../../../exam/application/services/exam.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { ExamSessionRepository } from '../../domain/exam-session.repository.interface';
import { ExamSessionQuestionService } from './exam-session-question.service';
import { ExamSessionService } from './exam-session.service';

function buildQuestion(id: string): Question {
  return new Question(
    id,
    'PART1',
    { item_id: id, prompt: '', expected_register: '', reference_keywords: [] },
    null,
    [],
    new Date(),
  );
}

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

function buildIdCardVerificationService(
  overrides: Partial<{ hasVerifiedExam: jest.Mock; cleanupVerifiedFaceImage: jest.Mock }> = {},
) {
  return {
    hasVerifiedExam: jest.fn().mockResolvedValue(true),
    cleanupVerifiedFaceImage: jest.fn().mockResolvedValue(undefined),
    ...overrides,
  } as unknown as IdCardVerificationService;
}

function buildExamSessionQuestionService(overrides: Partial<{ listQuestions: jest.Mock }> = {}) {
  return {
    listQuestions: jest.fn().mockResolvedValue([]),
    ...overrides,
  } as unknown as ExamSessionQuestionService;
}

function buildAnswerService(overrides: Partial<{ listAnsweredQuestionIds: jest.Mock }> = {}) {
  return {
    listAnsweredQuestionIds: jest.fn().mockResolvedValue([]),
    ...overrides,
  } as unknown as AnswerService;
}

describe('ExamSessionService.start', () => {
  it('rejects when the exam is not currently OPEN', async () => {
    const exam = buildExam({ openAt: new Date('2099-01-01T00:00:00.000Z') });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn(),
    } as unknown as ExamApplicationService;
    const repository = buildRepository();
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await expect(service.start('1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects when the caller has no active application', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const hasActiveApplication = jest.fn().mockResolvedValue(false);
    const examApplicationService = { hasActiveApplication } as unknown as ExamApplicationService;
    const repository = buildRepository();
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await expect(service.start('1', '1')).rejects.toThrow(ForbiddenDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects when the caller has not completed identity verification', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const repository = buildRepository();
    const idCardVerificationService = buildIdCardVerificationService({
      hasVerifiedExam: jest.fn().mockResolvedValue(false),
    });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      idCardVerificationService,
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

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
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

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
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

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
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

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
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await expect(service.getStatus('1', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects when the caller is not the session owner', async () => {
    const session = buildSession({ userId: '2' });
    const examService = {} as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await expect(service.getStatus('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('reports EXPIRED with 0 remaining seconds when past the exam close time but still INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const exam = buildExam({ closeAt: new Date('2020-01-01T00:00:00.000Z') });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

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
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

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
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.SUBMITTED);
    expect(result.remainingSeconds).toBe(0);
  });

  it('cleans up the verified face image once the session is no longer INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const exam = buildExam({ closeAt: new Date('2020-01-01T00:00:00.000Z') });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const cleanupVerifiedFaceImage = jest.fn().mockResolvedValue(undefined);
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService({ cleanupVerifiedFaceImage }),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await service.getStatus('6', '1');

    expect(cleanupVerifiedFaceImage).toHaveBeenCalledWith('1', '1');
  });

  it('does not clean up the verified face image while the session is still INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const exam = buildExam({ closeAt: new Date(Date.now() + 3600_000) });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const cleanupVerifiedFaceImage = jest.fn().mockResolvedValue(undefined);
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService({ cleanupVerifiedFaceImage }),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await service.getStatus('1', '1');

    expect(cleanupVerifiedFaceImage).not.toHaveBeenCalled();
  });

  it('returns the first question without a saved answer, in assigned order', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const exam = buildExam({ closeAt: new Date(Date.now() + 3600_000) });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const examSessionQuestionService = buildExamSessionQuestionService({
      listQuestions: jest
        .fn()
        .mockResolvedValue([buildQuestion('1'), buildQuestion('2'), buildQuestion('3')]),
    });
    const answerService = buildAnswerService({
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1']),
    });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      examSessionQuestionService,
      answerService,
    );

    const result = await service.getStatus('1', '1');

    expect(result.nextQuestionId).toBe('2');
  });

  it('returns null when every assigned question already has an answer', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const exam = buildExam({ closeAt: new Date(Date.now() + 3600_000) });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const examSessionQuestionService = buildExamSessionQuestionService({
      listQuestions: jest.fn().mockResolvedValue([buildQuestion('1'), buildQuestion('2')]),
    });
    const answerService = buildAnswerService({
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1', '2']),
    });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      examSessionQuestionService,
      answerService,
    );

    const result = await service.getStatus('1', '1');

    expect(result.nextQuestionId).toBeNull();
  });

  it('returns null without computing anything when the session is no longer INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const exam = buildExam({ closeAt: new Date(Date.now() + 3600_000) });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const listQuestions = jest.fn();
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService({ listQuestions }),
      buildAnswerService(),
    );

    const result = await service.getStatus('1', '1');

    expect(result.nextQuestionId).toBeNull();
    expect(listQuestions).not.toHaveBeenCalled();
  });
});

describe('ExamSessionService.assertActiveSession', () => {
  it('rejects when the session does not exist', async () => {
    const examService = {} as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository();
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects when the caller is not the session owner', async () => {
    const session = buildSession({ userId: '2' });
    const examService = {} as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('rejects when the session is already SUBMITTED', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const examService = {} as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(ConflictDomainException);
  });

  it('rejects when INPROGRESS but past the exam close time', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const exam = buildExam({ closeAt: new Date('2020-01-01T00:00:00.000Z') });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(ConflictDomainException);
  });

  it('returns the session when INPROGRESS and still within the exam period', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const exam = buildExam({ closeAt: new Date(Date.now() + 3600_000) });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildExamSessionQuestionService(),
      buildAnswerService(),
    );

    const result = await service.assertActiveSession('1', '1');

    expect(result).toBe(session);
  });
});
