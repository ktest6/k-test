import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../../exam/domain/entities/exam.entity';
import { ExamService } from '../../../exam/application/services/exam.service';
import { ExamResult } from '../../../scoring/domain/entities/exam-result.entity';
import { ExamResultService } from '../../../scoring/application/services/exam-result.service';
import { EarphoneDetectionService } from '../../../verifications/application/services/earphone-detection.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { ExamSessionRepository } from '../../domain/exam-session.repository.interface';
import { ExamSessionService } from './exam-session.service';

function buildExam(overrides: Partial<{ id: string; roundName: string }> = {}): Exam {
  return new Exam(overrides.id ?? '1', overrides.roundName ?? '2026년 1회차', new Date());
}

function buildSession(
  overrides: Partial<{
    id: string;
    examId: string;
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
    overrides.examId ?? '1',
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
    findByUserAndExam: jest.fn().mockResolvedValue(null),
    updateResumeCount: jest.fn(),
    updateStatus: jest.fn(),
    markSubmitted: jest.fn(),
    findAllSubmitted: jest.fn().mockResolvedValue([]),
    findAllInProgress: jest.fn().mockResolvedValue([]),
    findInProgressByUser: jest.fn().mockResolvedValue(null),
    findAllByUser: jest.fn().mockResolvedValue([]),
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
    examService: Partial<ExamService>;
    idCardVerificationService: ReturnType<typeof buildIdCardVerificationService>;
    earphoneDetectionService: ReturnType<typeof buildEarphoneDetectionService>;
    examResultService: ExamResultService;
    config: ConfigType<typeof appConfig>;
  }> = {},
) {
  const repository = buildRepository(overrides.repository);
  const examService = {
    findById: jest.fn().mockResolvedValue(buildExam()),
    list: jest.fn().mockResolvedValue([buildExam()]),
    ...overrides.examService,
  } as unknown as ExamService;
  const idCardVerificationService =
    overrides.idCardVerificationService ?? buildIdCardVerificationService();
  const earphoneDetectionService =
    overrides.earphoneDetectionService ?? buildEarphoneDetectionService();
  const examResultService = overrides.examResultService ?? buildExamResultService();
  const config = overrides.config ?? buildConfig();

  const service = new ExamSessionService(
    repository,
    examService,
    idCardVerificationService,
    earphoneDetectionService,
    examResultService,
    config,
  );

  return {
    service,
    repository,
    examService,
    idCardVerificationService,
    earphoneDetectionService,
    examResultService,
  };
}

describe('ExamSessionService.start', () => {
  it('rejects when the exam does not exist', async () => {
    const { service, repository } = buildService({
      examService: { findById: jest.fn().mockRejectedValue(new NotFoundDomainException('없음')) },
    });

    await expect(service.start('1', '1')).rejects.toThrow(NotFoundDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('rejects when the caller has not completed identity verification', async () => {
    const { service } = buildService({
      idCardVerificationService: buildIdCardVerificationService({
        hasVerifiedExam: jest.fn().mockResolvedValue(false),
      }),
    });

    await expect(service.start('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('skips the identity verification check when requireIdentityVerification is false', async () => {
    const hasVerifiedExam = jest.fn().mockResolvedValue(false);
    const { service, repository } = buildService({
      idCardVerificationService: buildIdCardVerificationService({ hasVerifiedExam }),
      config: buildConfig({ requireIdentityVerification: false }),
    });

    await service.start('1', '1');

    expect(hasVerifiedExam).not.toHaveBeenCalled();
    expect(repository.create).toHaveBeenCalled();
  });

  it('rejects when the caller has not passed the earphone check', async () => {
    const { service } = buildService({
      earphoneDetectionService: buildEarphoneDetectionService({
        hasPassedCheck: jest.fn().mockResolvedValue(false),
      }),
    });

    await expect(service.start('1', '1')).rejects.toThrow(ForbiddenDomainException);
  });

  it('skips the earphone check when requireEarphoneCheck is false', async () => {
    const hasPassedCheck = jest.fn().mockResolvedValue(false);
    const { service, repository } = buildService({
      earphoneDetectionService: buildEarphoneDetectionService({ hasPassedCheck }),
      config: buildConfig({ requireEarphoneCheck: false }),
    });

    await service.start('1', '1');

    expect(hasPassedCheck).not.toHaveBeenCalled();
    expect(repository.create).toHaveBeenCalled();
  });

  it('rejects starting again once the existing session is already SUBMITTED', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const { service } = buildService({
      repository: { findByUserAndExam: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.start('1', '1')).rejects.toThrow(ConflictDomainException);
  });

  it('resumes the existing session and increments the resume count when still INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS, resumeCount: 0 });
    const updateResumeCount = jest.fn().mockResolvedValue(session);
    const { service, repository } = buildService({
      repository: { findByUserAndExam: jest.fn().mockResolvedValue(session), updateResumeCount },
    });

    await service.start('1', '1');

    expect(updateResumeCount).toHaveBeenCalledWith('1', 1);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('blocks the session instead of resuming once the 3rd resume attempt is reached', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS, resumeCount: 2 });
    const updateStatus = jest.fn().mockResolvedValue(session);
    const { service } = buildService({
      repository: { findByUserAndExam: jest.fn().mockResolvedValue(session), updateStatus },
    });

    await expect(service.start('1', '1')).rejects.toThrow(ForbiddenDomainException);
    expect(updateStatus).toHaveBeenCalledWith('1', SessionStatus.BLOCKED);
  });

  it('rejects starting again once the existing session is already BLOCKED', async () => {
    const session = buildSession({ status: SessionStatus.BLOCKED, resumeCount: 3 });
    const { service } = buildService({
      repository: { findByUserAndExam: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.start('1', '1')).rejects.toThrow(ConflictDomainException);
  });

  it('rejects starting a different exam while another one is already INPROGRESS', async () => {
    const otherSession = buildSession({ id: '9', examId: '2', status: SessionStatus.INPROGRESS });
    const { service, repository } = buildService({
      repository: {
        findByUserAndExam: jest.fn().mockResolvedValue(null),
        findInProgressByUser: jest.fn().mockResolvedValue(otherSession),
      },
    });

    await expect(service.start('1', '1')).rejects.toThrow(ConflictDomainException);
    expect(repository.create).not.toHaveBeenCalled();
  });

  it('creates a new session when none exists yet and nothing else is in progress', async () => {
    const { service, repository } = buildService();

    await service.start('1', '1');

    expect(repository.create).toHaveBeenCalledWith({ examId: '1', userId: '1' });
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

    expect(cleanupVerifiedFaceImage).toHaveBeenCalledWith('1', '1');
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

  it('rejects when the session is BLOCKED (반복 재접속으로 차단된 세션)', async () => {
    const session = buildSession({ status: SessionStatus.BLOCKED, resumeCount: 3 });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.assertActiveSession('1', '1')).rejects.toThrow(ConflictDomainException);
  });

  it('returns the session when INPROGRESS', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    const result = await service.assertActiveSession('1', '1');

    expect(result).toBe(session);
  });
});

describe('ExamSessionService.listMine', () => {
  it('returns an empty array when the user has never started a session', async () => {
    const { service } = buildService({
      repository: { findAllByUser: jest.fn().mockResolvedValue([]) },
    });

    const result = await service.listMine('1');

    expect(result).toEqual([]);
  });

  it('includes the session id/status/startedAt/submittedAt for each started exam', async () => {
    const exam = buildExam({ id: '9', roundName: '202609' });
    const session = buildSession({
      id: '11',
      examId: '9',
      status: SessionStatus.INPROGRESS,
      startedAt: new Date('2026-08-01T00:00:00.000Z'),
    });
    const { service } = buildService({
      repository: { findAllByUser: jest.fn().mockResolvedValue([session]) },
      examService: { findById: jest.fn().mockResolvedValue(exam) },
    });

    const [result] = await service.listMine('1');

    expect(result.exam).toBe(exam);
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
    const examResult = { id: '501', finalGrade: 'B' } as unknown as ExamResult;
    const { service } = buildService({
      repository: { findAllByUser: jest.fn().mockResolvedValue([session]) },
      examResultService: buildExamResultService({
        findByExamSessionId: jest.fn().mockResolvedValue(examResult),
      }),
    });

    const [result] = await service.listMine('1');

    expect(result.examResultId).toBe('501');
    expect(result.finalGrade).toBe('B');
  });
});

describe('ExamSessionService.listAvailable', () => {
  it('marks canStart true when the user has no session anywhere', async () => {
    const exam = buildExam({ id: '1' });
    const { service } = buildService({
      examService: { list: jest.fn().mockResolvedValue([exam]) },
      repository: {
        findByUserAndExam: jest.fn().mockResolvedValue(null),
        findInProgressByUser: jest.fn().mockResolvedValue(null),
      },
    });

    const [result] = await service.listAvailable('1');

    expect(result.session).toBeNull();
    expect(result.canStart).toBe(true);
  });

  it('marks canStart false and includes the session when this exam already has one', async () => {
    const exam = buildExam({ id: '1' });
    const session = buildSession({ id: '11', examId: '1', status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      examService: { list: jest.fn().mockResolvedValue([exam]) },
      repository: {
        findByUserAndExam: jest.fn().mockResolvedValue(session),
        findInProgressByUser: jest.fn().mockResolvedValue(session),
      },
    });

    const [result] = await service.listAvailable('1');

    expect(result.session).toEqual({ id: '11', status: SessionStatus.INPROGRESS });
    expect(result.canStart).toBe(false);
  });

  it('marks canStart false for other exams while a different exam is INPROGRESS', async () => {
    const exam = buildExam({ id: '2' });
    const otherSession = buildSession({ id: '11', examId: '1', status: SessionStatus.INPROGRESS });
    const { service } = buildService({
      examService: { list: jest.fn().mockResolvedValue([exam]) },
      repository: {
        findByUserAndExam: jest.fn().mockResolvedValue(null),
        findInProgressByUser: jest.fn().mockResolvedValue(otherSession),
      },
    });

    const [result] = await service.listAvailable('1');

    expect(result.session).toBeNull();
    expect(result.canStart).toBe(false);
  });

  it('returns session/canStart as null for every exam when the caller is anonymous', async () => {
    const exam = buildExam({ id: '1' });
    const findByUserAndExam = jest.fn();
    const { service } = buildService({
      examService: { list: jest.fn().mockResolvedValue([exam]) },
      repository: { findByUserAndExam },
    });

    const [result] = await service.listAvailable(null);

    expect(result.session).toBeNull();
    expect(result.canStart).toBeNull();
    expect(findByUserAndExam).not.toHaveBeenCalled();
  });
});

describe('ExamSessionService.disqualify', () => {
  it('rejects when the session does not exist', async () => {
    const { service } = buildService();

    await expect(service.disqualify('1')).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects disqualifying an already-SUBMITTED session', async () => {
    const session = buildSession({ status: SessionStatus.SUBMITTED });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    await expect(service.disqualify('1')).rejects.toThrow(ConflictDomainException);
  });

  it('returns the session as-is when already DISQUALIFIED (idempotent)', async () => {
    const session = buildSession({ status: SessionStatus.DISQUALIFIED });
    const { service } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session) },
    });

    const result = await service.disqualify('1');

    expect(result).toBe(session);
  });

  it('disqualifies an INPROGRESS session', async () => {
    const session = buildSession({ status: SessionStatus.INPROGRESS });
    const updateStatus = jest
      .fn()
      .mockResolvedValue({ ...session, status: SessionStatus.DISQUALIFIED });
    const { service, repository } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session), updateStatus },
    });

    await service.disqualify('1');

    expect(repository.updateStatus).toHaveBeenCalledWith('1', SessionStatus.DISQUALIFIED);
  });

  it('disqualifies a BLOCKED session', async () => {
    const session = buildSession({ status: SessionStatus.BLOCKED });
    const updateStatus = jest
      .fn()
      .mockResolvedValue({ ...session, status: SessionStatus.DISQUALIFIED });
    const { service, repository } = buildService({
      repository: { findById: jest.fn().mockResolvedValue(session), updateStatus },
    });

    await service.disqualify('1');

    expect(repository.updateStatus).toHaveBeenCalledWith('1', SessionStatus.DISQUALIFIED);
  });
});
