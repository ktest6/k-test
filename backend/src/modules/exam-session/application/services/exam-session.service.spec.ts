import { ConfigType } from '@nestjs/config';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { appConfig } from '../../../../config/configuration';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { ExamResult } from '../../../scoring/domain/entities/exam-result.entity';
import { ExamResultService } from '../../../scoring/application/services/exam-result.service';
import { EarphoneDetectionService } from '../../../verifications/application/services/earphone-detection.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { ExamSessionRepository } from '../../domain/exam-session.repository.interface';
import { SessionDisqualifiedEvent } from '../../domain/events/session-disqualified.event';
import { ExamSessionAccessService } from './exam-session-access.service';
import { ExamSessionService } from './exam-session.service';

function buildSession(
  overrides: Partial<{
    id: string;
    status: SessionStatus;
    userId: string;
    currentQuestionId: string | null;
    resumeCount: number;
    startedAt: Date;
    submittedAt: Date | null;
  }> = {},
): ExamSession {
  return new ExamSession(
    overrides.id ?? '1',
    overrides.userId ?? '1',
    overrides.status ?? SessionStatus.INPROGRESS,
    overrides.resumeCount ?? 0,
    overrides.startedAt ?? new Date('2026-06-01T00:00:00.000Z'),
    overrides.currentQuestionId ?? null,
    null,
    overrides.submittedAt ?? null,
    new Date(),
  );
}

function buildRepository(overrides: Partial<ExamSessionRepository> = {}) {
  return {
    create: jest.fn(),
    findById: jest.fn().mockResolvedValue(null),
    findInProgressByUser: jest.fn().mockResolvedValue(null),
    findAllByUser: jest.fn().mockResolvedValue([]),
    updateResumeCount: jest.fn(),
    updateStatus: jest.fn(),
    markSubmitted: jest.fn(),
    findAllSubmitted: jest.fn().mockResolvedValue([]),
    findAllInProgress: jest.fn().mockResolvedValue([]),
    ...overrides,
  };
}

function buildIdCardVerificationService(
  overrides: Partial<{ hasVerifiedSession: jest.Mock; cleanupVerifiedFaceImage: jest.Mock }> = {},
) {
  return {
    hasVerifiedSession: jest.fn().mockResolvedValue(true),
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

function buildExamResultService(
  overrides: Partial<{ findByExamSessionId: jest.Mock }> = {},
): ExamResultService {
  return {
    findByExamSessionId: jest.fn().mockResolvedValue(null),
    ...overrides,
  } as unknown as ExamResultService;
}

function buildConfig(
  overrides: Partial<{ requireIdentityVerification: boolean; requireEarphoneCheck: boolean }> = {},
): ConfigType<typeof appConfig> {
  return {
    requireIdentityVerification: overrides.requireIdentityVerification ?? true,
    requireEarphoneCheck: overrides.requireEarphoneCheck ?? true,
  } as ConfigType<typeof appConfig>;
}

function buildService(
  overrides: Partial<{
    repository: Partial<ExamSessionRepository>;
    idCardVerificationService: ReturnType<typeof buildIdCardVerificationService>;
    earphoneDetectionService: ReturnType<typeof buildEarphoneDetectionService>;
    examResultService: ExamResultService;
    config: ConfigType<typeof appConfig>;
  }> = {},
) {
  const repository = buildRepository(overrides.repository);
  const examSessionAccessService = new ExamSessionAccessService(repository);
  const idCardVerificationService =
    overrides.idCardVerificationService ?? buildIdCardVerificationService();
  const earphoneDetectionService =
    overrides.earphoneDetectionService ?? buildEarphoneDetectionService();
  const examResultService = overrides.examResultService ?? buildExamResultService();
  const config = overrides.config ?? buildConfig();
  const emit = jest.fn();
  const eventEmitter = { emit } as unknown as EventEmitter2;

  const service = new ExamSessionService(
    repository,
    examSessionAccessService,
    idCardVerificationService,
    earphoneDetectionService,
    examResultService,
    config,
    eventEmitter,
  );

  return {
    service,
    repository,
    idCardVerificationService,
    earphoneDetectionService,
    examResultService,
    emit,
  };
}

describe('ExamSessionService.start', () => {
  it('creates a new session without checking identity/earphone verification', async () => {
    const hasVerifiedSession = jest.fn().mockResolvedValue(false);
    const hasPassedCheck = jest.fn().mockResolvedValue(false);
    const { service, repository } = buildService({
      idCardVerificationService: buildIdCardVerificationService({ hasVerifiedSession }),
      earphoneDetectionService: buildEarphoneDetectionService({ hasPassedCheck }),
    });

    await service.start('1');

    expect(repository.create).toHaveBeenCalledWith({ userId: '1' });
    expect(hasVerifiedSession).not.toHaveBeenCalled();
    expect(hasPassedCheck).not.toHaveBeenCalled();
  });

  it('resumes the existing INPROGRESS session and increments the resume count', async () => {
    const existing = buildSession({ status: SessionStatus.INPROGRESS, resumeCount: 1 });
    const resumed = buildSession({ status: SessionStatus.INPROGRESS, resumeCount: 2 });
    const updateResumeCount = jest.fn().mockResolvedValue(resumed);
    const { service, repository } = buildService({
      repository: {
        findInProgressByUser: jest.fn().mockResolvedValue(existing),
        updateResumeCount,
      },
    });

    const result = await service.start('1');

    expect(updateResumeCount).toHaveBeenCalledWith('1', 2);
    expect(result).toBe(resumed);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('blocks the session instead of resuming once the 3rd resume attempt is reached', async () => {
    const existing = buildSession({ status: SessionStatus.INPROGRESS, resumeCount: 2 });
    const updateStatus = jest
      .fn()
      .mockResolvedValue(buildSession({ status: SessionStatus.BLOCKED, resumeCount: 2 }));
    const { service, repository } = buildService({
      repository: { findInProgressByUser: jest.fn().mockResolvedValue(existing), updateStatus },
    });

    await expect(service.start('1')).rejects.toThrow(ForbiddenDomainException);

    expect(updateStatus).toHaveBeenCalledWith('1', SessionStatus.BLOCKED);
    expect(repository.updateResumeCount).not.toHaveBeenCalled();
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('creates a new session when nothing is in progress', async () => {
    const created = buildSession();
    const { service, repository } = buildService({
      repository: { create: jest.fn().mockResolvedValue(created) },
    });

    const result = await service.start('1');

    expect(repository.create).toHaveBeenCalledWith({ userId: '1' });
    expect(result).toBe(created);
  });
});

describe('ExamSessionService.getCurrentInProgress', () => {
  it('returns null when nothing is in progress', async () => {
    const { service } = buildService();

    await expect(service.getCurrentInProgress('1')).resolves.toBeNull();
  });

  it('returns the in-progress session', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      repository: { findInProgressByUser: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.getCurrentInProgress('1')).resolves.toBe(session);
  });
});

describe('ExamSessionService.getStatus', () => {
  it('rejects when the session does not exist', async () => {
    const { service } = buildService();

    await expect(service.getStatus('1', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects when the caller is not the session owner', async () => {
    const session = buildSession({ userId: '2' });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.getStatus('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('reports INPROGRESS as-is', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS, currentQuestionId: '3' });
    const { service, repository } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.INPROGRESS);
    expect(result.session.currentQuestionId).toBe('3');
    expect(repository.updateStatus).not.toHaveBeenCalled();
  });

  it('reports SUBMITTED as-is', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    const result = await service.getStatus('1', '1');

    expect(result.status).toBe(SessionStatus.SUBMITTED);
  });

  it('cleans up the verified face image once the session is no longer INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const cleanupVerifiedFaceImage = jest.fn().mockResolvedValue(undefined);
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
      idCardVerificationService: buildIdCardVerificationService({ cleanupVerifiedFaceImage }),
    });

    await service.getStatus('1', '1');

    expect(cleanupVerifiedFaceImage).toHaveBeenCalledWith('1');
  });

  it('does not clean up the verified face image while the session is still INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const cleanupVerifiedFaceImage = jest.fn().mockResolvedValue(undefined);
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
      idCardVerificationService: buildIdCardVerificationService({ cleanupVerifiedFaceImage }),
    });

    await service.getStatus('1', '1');

    expect(cleanupVerifiedFaceImage).not.toHaveBeenCalled();
  });
});

describe('ExamSessionService.assertActiveSession', () => {
  it('rejects when the session does not exist', async () => {
    const { service } = buildService();

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects when the caller is not the session owner', async () => {
    const session = buildSession({ userId: '2' });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('rejects when the session is already SUBMITTED', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(ConflictDomainException);
  });

  it('returns the session when INPROGRESS regardless of verification status', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
      idCardVerificationService: buildIdCardVerificationService({
        hasVerifiedSession: jest.fn().mockResolvedValue(false),
      }),
    });

    const result = await service.assertActiveSession('1', '1');

    expect(result).toBe(session);
  });
});

describe('ExamSessionService.assertVerifiedSession', () => {
  it('rejects when identity verification is still pending', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
      idCardVerificationService: buildIdCardVerificationService({
        hasVerifiedSession: jest.fn().mockResolvedValue(false),
      }),
    });

    await expect(service.assertVerifiedSession('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('rejects when the earphone check is still pending', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
      earphoneDetectionService: buildEarphoneDetectionService({
        hasPassedCheck: jest.fn().mockResolvedValue(false),
      }),
    });

    await expect(service.assertVerifiedSession('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('returns the session when verification is complete', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    const result = await service.assertVerifiedSession('1', '1');

    expect(result).toBe(session);
  });
});

describe('ExamSessionService.isVerified', () => {
  it('returns false while identity verification is pending', async () => {
    const { service } = buildService({
      idCardVerificationService: buildIdCardVerificationService({
        hasVerifiedSession: jest.fn().mockResolvedValue(false),
      }),
    });

    await expect(service.isVerified('1')).resolves.toBe(false);
  });

  it('returns true once identity/earphone checks both pass', async () => {
    const { service } = buildService();

    await expect(service.isVerified('1')).resolves.toBe(true);
  });

  it('ignores the identity check when requireIdentityVerification is false', async () => {
    const hasVerifiedSession = jest.fn().mockResolvedValue(false);
    const { service } = buildService({
      idCardVerificationService: buildIdCardVerificationService({ hasVerifiedSession }),
      config: buildConfig({ requireIdentityVerification: false }),
    });

    await expect(service.isVerified('1')).resolves.toBe(true);
    expect(hasVerifiedSession).not.toHaveBeenCalled();
  });
});

describe('ExamSessionService.listMine', () => {
  it('returns an empty array when the user has never started a session', async () => {
    const { service } = buildService({
      repository: { findAllByUser: jest.fn().mockResolvedValue([]) },
    });

    await expect(service.listMine('1')).resolves.toEqual([]);
  });

  it('includes the session id/status/startedAt/submittedAt for each session', async () => {
    const session = buildSession({
      id: '11',
      status: SessionStatus.INPROGRESS,
      startedAt: new Date('2026-08-01T00:00:00.000Z'),
    });
    const { service } = buildService({
      repository: { findAllByUser: jest.fn().mockResolvedValue([session]) },
    });

    const [result] = await service.listMine('1');

    expect(result.session).toEqual({
      id: '11',
      status: SessionStatus.INPROGRESS,
      startedAt: new Date('2026-08-01T00:00:00.000Z'),
      submittedAt: null,
    });
    expect(result.examResultId).toBeNull();
    expect(result.finalGrade).toBeNull();
  });

  it('includes examResultId and finalGrade once a report has been recorded', async () => {
    const session = buildSession({ id: '11', status: SessionStatus.SUBMITTED });
    const examResult = { id: 'r1', finalGrade: 'B' } as unknown as ExamResult;
    const { service } = buildService({
      repository: { findAllByUser: jest.fn().mockResolvedValue([session]) },
      examResultService: buildExamResultService({
        findByExamSessionId: jest.fn().mockResolvedValue(examResult),
      }),
    });

    const [result] = await service.listMine('1');

    expect(result.examResultId).toBe('r1');
    expect(result.finalGrade).toBe('B');
  });

  it('can list multiple sessions for the same user (retakes)', async () => {
    const sessionA = buildSession({ id: '11', status: SessionStatus.SUBMITTED });
    const sessionB = buildSession({ id: '12', status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      repository: { findAllByUser: jest.fn().mockResolvedValue([sessionA, sessionB]) },
    });

    const result = await service.listMine('1');

    expect(result).toHaveLength(2);
    expect(result.map((r) => r.session.id)).toEqual(['11', '12']);
  });
});

describe('ExamSessionService.disqualify', () => {
  it('rejects when the session does not exist', async () => {
    const { service } = buildService();

    await expect(service.disqualify('1', 'reason')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects disqualifying an already-SUBMITTED session', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.disqualify('1', 'reason')).rejects.toThrow(ConflictDomainException);
  });

  it('returns the session as-is when already DISQUALIFIED (idempotent) and does not emit again', async () => {
    const session = buildSession({ status: SessionStatus.DISQUALIFIED });
    const { service, emit } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    const result = await service.disqualify('1', 'reason');

    expect(result).toBe(session);
    expect(emit).not.toHaveBeenCalled();
  });

  it('disqualifies an INPROGRESS session and emits a SessionDisqualifiedEvent with the reason and start time', async () => {
    const startedAt = new Date('2026-08-22T06:00:00.000Z');
    const session = buildSession({ status: SessionStatus.INPROGRESS, userId: '7', startedAt });
    const updateStatus = jest
      .fn()
      .mockResolvedValue({ ...session, status: SessionStatus.DISQUALIFIED });
    const { service, repository, emit } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session), updateStatus },
    });

    await service.disqualify('1', 'reason text');

    expect(repository.updateStatus).toHaveBeenCalledWith('1', SessionStatus.DISQUALIFIED);
    expect(emit).toHaveBeenCalledWith(
      'exam-session.disqualified',
      new SessionDisqualifiedEvent('1', '7', 'reason text', startedAt),
    );
  });

  it('disqualifies a BLOCKED session', async () => {
    const session = buildSession({ status: SessionStatus.BLOCKED });
    const updateStatus = jest
      .fn()
      .mockResolvedValue({ ...session, status: SessionStatus.DISQUALIFIED });
    const { service, repository } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session), updateStatus },
    });

    await service.disqualify('1', 'reason');

    expect(repository.updateStatus).toHaveBeenCalledWith('1', SessionStatus.DISQUALIFIED);
  });
});
