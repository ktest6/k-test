import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../../exam/domain/entities/exam.entity';
import { ExamApplicationService } from '../../../exam/application/services/exam-application.service';
import { ExamService } from '../../../exam/application/services/exam.service';
import { EarphoneDetectionService } from '../../../verifications/application/services/earphone-detection.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
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
    resumeCount: number;
  }> = {},
): ExamSession {
  return new ExamSession(
    '1',
    '1',
    overrides.userId ?? '1',
    overrides.status ?? SessionStatus.INPROGRESS,
    overrides.resumeCount ?? 0,
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
    updateResumeCount: jest.fn(),
    updateStatus: jest.fn(),
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

function buildEarphoneDetectionService(overrides: Partial<{ hasPassedCheck: jest.Mock }> = {}) {
  return {
    hasPassedCheck: jest.fn().mockResolvedValue(true),
    ...overrides,
  } as unknown as EarphoneDetectionService;
}

function buildConfig(
  overrides: Partial<{ requireIdentityVerification: boolean; requireEarphoneCheck: boolean }> = {},
): ConfigType<typeof appConfig> {
  return {
    requireIdentityVerification: overrides.requireIdentityVerification ?? true,
    requireEarphoneCheck: overrides.requireEarphoneCheck ?? true,
  } as ConfigType<typeof appConfig>;
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
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    await expect(service.start('1', '1')).rejects.toThrow(ForbiddenDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('skips the identity verification check when requireIdentityVerification is false', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const created = buildSession();
    const repository = buildRepository({ create: jest.fn().mockResolvedValue(created) });
    const hasVerifiedExam = jest.fn().mockResolvedValue(false);
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService({ hasVerifiedExam }),
      buildEarphoneDetectionService(),
      buildConfig({ requireIdentityVerification: false }),
    );

    const result = await service.start('1', '1');

    expect(hasVerifiedExam).not.toHaveBeenCalled();
    expect(result).toBe(created);
  });

  it('rejects when the caller has not passed the earphone check', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const repository = buildRepository();
    const earphoneDetectionService = buildEarphoneDetectionService({
      hasPassedCheck: jest.fn().mockResolvedValue(false),
    });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      earphoneDetectionService,
      buildConfig(),
    );

    await expect(service.start('1', '1')).rejects.toThrow(ForbiddenDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('skips the earphone check when requireEarphoneCheck is false', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const created = buildSession();
    const repository = buildRepository({ create: jest.fn().mockResolvedValue(created) });
    const hasPassedCheck = jest.fn().mockResolvedValue(false);
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildEarphoneDetectionService({ hasPassedCheck }),
      buildConfig({ requireEarphoneCheck: false }),
    );

    const result = await service.start('1', '1');

    expect(hasPassedCheck).not.toHaveBeenCalled();
    expect(result).toBe(created);
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    await expect(service.start('1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('resumes the existing session and increments the resume count when still INPROGRESS', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const existing = buildSession({ status: SessionStatus.INPROGRESS, resumeCount: 1 });
    const resumed = buildSession({ status: SessionStatus.INPROGRESS, resumeCount: 2 });
    const updateResumeCount = jest.fn().mockResolvedValue(resumed);
    const repository = buildRepository({
      findByUserAndExam: jest.fn().mockResolvedValue(existing),
      updateResumeCount,
    });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    const result = await service.start('1', '1');

    expect(updateResumeCount).toHaveBeenCalledWith('1', 2);
    expect(result).toBe(resumed);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('blocks the session instead of resuming once the 3rd resume attempt is reached', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const existing = buildSession({ status: SessionStatus.INPROGRESS, resumeCount: 2 });
    const updateStatus = jest
      .fn()
      .mockResolvedValue(buildSession({ status: SessionStatus.BLOCKED, resumeCount: 2 }));
    const repository = buildRepository({
      findByUserAndExam: jest.fn().mockResolvedValue(existing),
      updateStatus,
    });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    await expect(service.start('1', '1')).rejects.toThrow(ForbiddenDomainException);

    expect(updateStatus).toHaveBeenCalledWith('1', SessionStatus.BLOCKED);
    expect(repository.updateResumeCount).not.toHaveBeenCalled();
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects starting again once the existing session is already BLOCKED', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      hasActiveApplication: jest.fn().mockResolvedValue(true),
    } as unknown as ExamApplicationService;
    const existing = buildSession({ status: SessionStatus.BLOCKED, resumeCount: 3 });
    const repository = buildRepository({
      findByUserAndExam: jest.fn().mockResolvedValue(existing),
    });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    await expect(service.start('1', '1')).rejects.toThrow(ConflictDomainException);
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
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    await expect(service.getStatus('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('computes EXPIRED when past the exam close time but still stored as INPROGRESS', async () => {
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.EXPIRED);
  });

  it('reports INPROGRESS as-is while still within the exam period', async () => {
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.INPROGRESS);
    expect(result.session.currentQuestionId).toBe('3');
  });

  it('reports SUBMITTED as-is regardless of the exam close time', async () => {
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.SUBMITTED);
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
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    await service.getStatus('1', '1');

    expect(cleanupVerifiedFaceImage).not.toHaveBeenCalled();
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
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(ConflictDomainException);
  });

  it('rejects when the session is BLOCKED (반복 재접속으로 차단된 세션)', async () => {
    const session = buildSession({ status: SessionStatus.BLOCKED, resumeCount: 3 });
    const examService = {} as unknown as ExamService;
    const examApplicationService = {} as unknown as ExamApplicationService;
    const repository = buildRepository({ findById: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
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
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    const result = await service.assertActiveSession('1', '1');

    expect(result).toBe(session);
  });
});

describe('ExamSessionService.listMine', () => {
  it('returns null session fields for an exam never started', async () => {
    const exam = buildExam();
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      listMine: jest
        .fn()
        .mockResolvedValue([{ id: '1', examId: '1', userId: '1', appliedAt: new Date() }]),
    } as unknown as ExamApplicationService;
    const repository = buildRepository({ findByUserAndExam: jest.fn().mockResolvedValue(null) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    const [result] = await service.listMine('1');

    expect(result.exam).toBe(exam);
    expect(result.session).toBeNull();
  });

  it('includes the session id and computed status when a session exists', async () => {
    const exam = buildExam({ closeAt: new Date(Date.now() + 3600_000) });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      listMine: jest
        .fn()
        .mockResolvedValue([{ id: '1', examId: '1', userId: '1', appliedAt: new Date() }]),
    } as unknown as ExamApplicationService;
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const repository = buildRepository({ findByUserAndExam: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    const [result] = await service.listMine('1');

    expect(result.session).toEqual({ id: session.id, status: SessionStatus.INPROGRESS });
  });

  it('reports EXPIRED for a session stored as INPROGRESS past the exam close time', async () => {
    const exam = buildExam({ closeAt: new Date('2020-01-01T00:00:00.000Z') });
    const examService = { findById: jest.fn().mockResolvedValue(exam) } as unknown as ExamService;
    const examApplicationService = {
      listMine: jest
        .fn()
        .mockResolvedValue([{ id: '1', examId: '1', userId: '1', appliedAt: new Date() }]),
    } as unknown as ExamApplicationService;
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const repository = buildRepository({ findByUserAndExam: jest.fn().mockResolvedValue(session) });
    const service = new ExamSessionService(
      repository,
      examService,
      examApplicationService,
      buildIdCardVerificationService(),
      buildEarphoneDetectionService(),
      buildConfig(),
    );

    const [result] = await service.listMine('1');

    expect(result.session?.status).toBe(SessionStatus.EXPIRED);
  });
});
