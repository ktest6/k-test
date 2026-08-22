import { AnswerService } from '../../../answer/application/services/answer.service';
import { Answer } from '../../../answer/domain/entities/answer.entity';
import { AnswerStatus } from '../../../answer/domain/enums/answer-status.enum';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import { FinalizeProviderPort } from '../../../ai/domain/ports/finalize-provider.port';
import { ScoringProviderPort } from '../../../ai/domain/ports/scoring-provider.port';
import { Exam } from '../../../exam/domain/entities/exam.entity';
import { ExamService } from '../../../exam/application/services/exam.service';
import { ExamQuestionService } from '../../../exam-question/application/services/exam-question.service';
import { QuestionService } from '../../../question/application/services/question.service';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import { ExamResult } from '../../../scoring/domain/entities/exam-result.entity';
import { ExamResultService } from '../../../scoring/application/services/exam-result.service';
import { ScoringService } from '../../../scoring/application/services/scoring.service';
import { Score } from '../../../scoring/domain/entities/score.entity';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { ExamSessionRepository } from '../../domain/exam-session.repository.interface';
import { SkippedQuestionRepository } from '../../domain/skipped-question.repository.interface';
import { ExamSessionReportService } from './exam-session-report.service';

function buildSession(
  overrides: Partial<{ id: string; userId: string; status: SessionStatus }> = {},
): ExamSession {
  return new ExamSession(
    overrides.id ?? '100',
    '7',
    overrides.userId ?? '9',
    overrides.status ?? SessionStatus.INPROGRESS,
    0,
    new Date('2026-08-04T00:00:00.000Z'),
    null,
    null,
    null,
    new Date(),
  );
}

function buildExam(overrides: Partial<{ id: string; closeAt: Date }> = {}): Exam {
  return new Exam(
    overrides.id ?? '7',
    '202601',
    new Date('2026-08-01T00:00:00.000Z'),
    new Date('2026-08-03T00:00:00.000Z'),
    new Date('2026-08-04T00:00:00.000Z'),
    overrides.closeAt ?? new Date('2026-08-05T00:00:00.000Z'),
    10,
    new Date('2026-08-01T00:00:00.000Z'),
  );
}

function buildQuestion(id: string): Question {
  return new Question(
    id,
    QuestionSectionType.SITUATION_DESCRIPTION,
    {
      preparationSeconds: 40,
      responseSeconds: 60,
      guideTexts: ['안내'],
      instruction: `프롬프트 ${id}`,
    },
    null,
    [{ id: '1', code: 'c1', description: '기준', weight: 1, displayOrder: 0 }],
    new Date(),
  );
}

function buildAnswer(id: string, questionId: string): Answer {
  return new Answer(
    id,
    '100',
    questionId,
    AnswerType.AUDIO,
    null,
    `9/100/${questionId}.webm`,
    AnswerStatus.DRAFT,
    new Date(),
  );
}

interface BuildServiceMocks {
  findById: jest.Mock;
  markSubmitted: jest.Mock;
  findAllSubmitted: jest.Mock;
  findAllInProgress: jest.Mock;
  updateStatus: jest.Mock;
  findExamById: jest.Mock;
  listSkippedQuestionIds: jest.Mock;
  listAssignedQuestions: jest.Mock;
  findQuestionById: jest.Mock;
  listAnsweredQuestionIds: jest.Mock;
  listBySession: jest.Mock;
  findByAnswerId: jest.Mock;
  recordScore: jest.Mock;
  recordExamResult: jest.Mock;
  findExamResultBySessionId: jest.Mock;
  listExamSessionIdsWithResult: jest.Mock;
  score: jest.Mock;
  finalize: jest.Mock;
}

function buildService(overrides: Partial<BuildServiceMocks> = {}) {
  const mocks: BuildServiceMocks = {
    findById: jest.fn().mockResolvedValue(buildSession()),
    markSubmitted: jest.fn(),
    findAllSubmitted: jest.fn().mockResolvedValue([]),
    findAllInProgress: jest.fn().mockResolvedValue([]),
    updateStatus: jest.fn(),
    findExamById: jest.fn().mockResolvedValue(buildExam()),
    listSkippedQuestionIds: jest.fn().mockResolvedValue([]),
    listAssignedQuestions: jest.fn().mockResolvedValue([]),
    findQuestionById: jest.fn(),
    listAnsweredQuestionIds: jest.fn().mockResolvedValue([]),
    listBySession: jest.fn().mockResolvedValue([]),
    findByAnswerId: jest.fn().mockResolvedValue(null),
    recordScore: jest.fn(),
    recordExamResult: jest.fn(),
    findExamResultBySessionId: jest.fn().mockResolvedValue(null),
    listExamSessionIdsWithResult: jest.fn().mockResolvedValue([]),
    score: jest.fn(),
    finalize: jest.fn().mockResolvedValue({ overall_grade: 'B', percentile: 70.5 }),
    ...overrides,
  };

  const examSessionRepository = {
    findById: mocks.findById,
    markSubmitted: mocks.markSubmitted,
    findAllSubmitted: mocks.findAllSubmitted,
    findAllInProgress: mocks.findAllInProgress,
    updateStatus: mocks.updateStatus,
  } as unknown as ExamSessionRepository;
  const skippedQuestionRepository = {
    listSkippedQuestionIds: mocks.listSkippedQuestionIds,
  } as unknown as SkippedQuestionRepository;
  const examService = { findById: mocks.findExamById } as unknown as ExamService;
  const examQuestionService = {
    listAssignedQuestions: mocks.listAssignedQuestions,
  } as unknown as ExamQuestionService;
  const questionService = { findById: mocks.findQuestionById } as unknown as QuestionService;
  const answerService = {
    listAnsweredQuestionIds: mocks.listAnsweredQuestionIds,
    listBySession: mocks.listBySession,
  } as unknown as AnswerService;
  const scoringService = {
    findByAnswerId: mocks.findByAnswerId,
    record: mocks.recordScore,
  } as unknown as ScoringService;
  const examResultService = {
    record: mocks.recordExamResult,
    findByExamSessionId: mocks.findExamResultBySessionId,
    listExamSessionIdsWithResult: mocks.listExamSessionIdsWithResult,
  } as unknown as ExamResultService;
  const scoringProvider = { score: mocks.score } as unknown as ScoringProviderPort;
  const finalizeProvider = { finalize: mocks.finalize } as unknown as FinalizeProviderPort;

  const service = new ExamSessionReportService(
    examSessionRepository,
    skippedQuestionRepository,
    examService,
    examQuestionService,
    questionService,
    answerService,
    scoringService,
    examResultService,
    scoringProvider,
    finalizeProvider,
  );

  return { service, mocks };
}

describe('ExamSessionReportService.checkAndFinalize', () => {
  it('does nothing when the session does not exist', async () => {
    const { service, mocks } = buildService({ findById: jest.fn().mockResolvedValue(null) });

    await service.checkAndFinalize('100', '9');

    expect(mocks.finalize).not.toHaveBeenCalled();
    expect(mocks.markSubmitted).not.toHaveBeenCalled();
  });

  it('does nothing when some assigned questions are still unhandled', async () => {
    const { service, mocks } = buildService({
      listAssignedQuestions: jest.fn().mockResolvedValue([buildQuestion('1'), buildQuestion('2')]),
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1']),
      listSkippedQuestionIds: jest.fn().mockResolvedValue([]),
    });

    await service.checkAndFinalize('100', '9');

    expect(mocks.finalize).not.toHaveBeenCalled();
    expect(mocks.markSubmitted).not.toHaveBeenCalled();
  });

  it('finalizes an incomplete session anyway when force is true', async () => {
    const { service, mocks } = buildService({
      listAssignedQuestions: jest.fn().mockResolvedValue([buildQuestion('1'), buildQuestion('2')]),
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1']),
      listSkippedQuestionIds: jest.fn().mockResolvedValue([]),
      listBySession: jest.fn().mockResolvedValue([buildAnswer('a1', '1')]),
      findByAnswerId: jest
        .fn()
        .mockResolvedValue(new Score('s1', 'a1', { submission_id: 'a1' }, new Date())),
    });

    await service.checkAndFinalize('100', '9', { force: true });

    expect(mocks.finalize).toHaveBeenCalledWith(
      expect.objectContaining({
        expectedItems: [
          { itemId: '1', mode: 'speaking' },
          { itemId: '2', mode: 'speaking' },
        ],
      }),
    );
    expect(mocks.markSubmitted).toHaveBeenCalledWith('100');
  });

  it('finalizes once every assigned question is either answered or skipped', async () => {
    const answer1 = buildAnswer('a1', '1');
    const score1 = new Score('s1', 'a1', { submission_id: 'a1', overall_score: 80 }, new Date());
    const { service, mocks } = buildService({
      listAssignedQuestions: jest.fn().mockResolvedValue([buildQuestion('1'), buildQuestion('2')]),
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1']),
      listBySession: jest.fn().mockResolvedValue([answer1]),
      listSkippedQuestionIds: jest.fn().mockResolvedValue(['2']),
      findByAnswerId: jest.fn().mockResolvedValue(score1),
      finalize: jest.fn().mockResolvedValue({
        overall_grade: 'B',
        percentile: 70.5,
        subscores: [{ area: 'content_task' }],
        cross_mode_check: { flagged: false },
      }),
    });

    await service.checkAndFinalize('100', '9');

    expect(mocks.finalize).toHaveBeenCalledWith({
      sessionId: '100',
      candidateId: '9',
      items: [score1.rawResponse],
      expectedItems: [
        { itemId: '1', mode: 'speaking' },
        { itemId: '2', mode: 'speaking' },
      ],
    });
    expect(mocks.recordExamResult).toHaveBeenCalledWith(
      {
        examSessionId: '100',
        finalGrade: 'B',
        percentile: 70.5,
        domainScores: { subscores: [{ area: 'content_task' }] },
        crossValidationSignals: { flagged: false },
        rawResponse: {
          overall_grade: 'B',
          percentile: 70.5,
          subscores: [{ area: 'content_task' }],
          cross_mode_check: { flagged: false },
        },
      },
      '9',
    );
    expect(mocks.markSubmitted).toHaveBeenCalledWith('100');
  });

  it('scores any answered question that is missing a score before finalizing', async () => {
    const answer1 = buildAnswer('a1', '1');
    const question1 = buildQuestion('1');
    const freshRawResponse = { submission_id: 'a1', overall_score: 55 };
    const { service, mocks } = buildService({
      listAssignedQuestions: jest.fn().mockResolvedValue([question1]),
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1']),
      listBySession: jest.fn().mockResolvedValue([answer1]),
      findQuestionById: jest.fn().mockResolvedValue(question1),
      findByAnswerId: jest.fn().mockResolvedValue(null),
      score: jest.fn().mockResolvedValue(freshRawResponse),
    });

    await service.checkAndFinalize('100', '9');

    expect(mocks.score).toHaveBeenCalledWith(
      expect.objectContaining({ answerId: 'a1', answerType: 'AUDIO' }),
    );
    expect(mocks.recordScore).toHaveBeenCalledWith({
      answerId: 'a1',
      rawResponse: freshRawResponse,
    });
    expect(mocks.finalize).toHaveBeenCalledWith(
      expect.objectContaining({ items: [freshRawResponse] }),
    );
  });

  it('still marks the session submitted when the finalize call fails, without throwing', async () => {
    const { service, mocks } = buildService({
      listAssignedQuestions: jest.fn().mockResolvedValue([buildQuestion('1')]),
      listAnsweredQuestionIds: jest.fn().mockResolvedValue([]),
      listBySession: jest.fn().mockResolvedValue([]),
      listSkippedQuestionIds: jest.fn().mockResolvedValue(['1']),
      finalize: jest.fn().mockRejectedValue(new Error('assessment down')),
    });

    await expect(service.checkAndFinalize('100', '9')).resolves.toBeUndefined();

    expect(mocks.recordExamResult).not.toHaveBeenCalled();
    expect(mocks.markSubmitted).toHaveBeenCalledWith('100');
  });
});

describe('ExamSessionReportService.syncPendingReports', () => {
  it('does nothing when there are no submitted sessions', async () => {
    const { service } = buildService({ findAllSubmitted: jest.fn().mockResolvedValue([]) });

    const count = await service.syncPendingReports();

    expect(count).toBe(0);
  });

  it('skips sessions that already have a stored result', async () => {
    const sessionA = buildSession({ id: '100', userId: '9', status: SessionStatus.SUBMITTED });
    const { service, mocks } = buildService({
      findAllSubmitted: jest.fn().mockResolvedValue([sessionA]),
      listExamSessionIdsWithResult: jest.fn().mockResolvedValue(['100']),
    });
    const checkAndFinalizeSpy = jest.spyOn(service, 'checkAndFinalize');

    const count = await service.syncPendingReports();

    expect(checkAndFinalizeSpy).not.toHaveBeenCalled();
    expect(count).toBe(0);
    expect(mocks.markSubmitted).not.toHaveBeenCalled();
  });

  it('retries checkAndFinalize for submitted sessions missing a result and counts how many now have one', async () => {
    const sessionA = buildSession({ id: '100', userId: '9', status: SessionStatus.SUBMITTED });
    const sessionB = buildSession({ id: '200', userId: '15', status: SessionStatus.SUBMITTED });
    const resultA = new ExamResult('r1', '100', 'B', 70.5, null, null, {}, new Date());
    const findExamResultBySessionId = jest
      .fn()
      .mockImplementation((examSessionId: string) =>
        Promise.resolve(examSessionId === '100' ? resultA : null),
      );
    const { service } = buildService({
      findAllSubmitted: jest.fn().mockResolvedValue([sessionA, sessionB]),
      listExamSessionIdsWithResult: jest.fn().mockResolvedValue([]),
      findExamResultBySessionId,
    });
    const checkAndFinalizeSpy = jest
      .spyOn(service, 'checkAndFinalize')
      .mockResolvedValue(undefined);

    const count = await service.syncPendingReports();

    expect(checkAndFinalizeSpy).toHaveBeenCalledWith('100', '9');
    expect(checkAndFinalizeSpy).toHaveBeenCalledWith('200', '15');
    expect(count).toBe(1);
  });

  it('keeps processing the remaining sessions when one of them fails', async () => {
    const sessionA = buildSession({ id: '100', userId: '9', status: SessionStatus.SUBMITTED });
    const sessionB = buildSession({ id: '200', userId: '15', status: SessionStatus.SUBMITTED });
    const resultB = new ExamResult('r2', '200', 'B', 70.5, null, null, {}, new Date());
    const findExamResultBySessionId = jest
      .fn()
      .mockImplementation((examSessionId: string) =>
        Promise.resolve(examSessionId === '200' ? resultB : null),
      );
    const { service } = buildService({
      findAllSubmitted: jest.fn().mockResolvedValue([sessionA, sessionB]),
      listExamSessionIdsWithResult: jest.fn().mockResolvedValue([]),
      findExamResultBySessionId,
    });
    jest
      .spyOn(service, 'checkAndFinalize')
      .mockImplementation((examSessionId: string) =>
        examSessionId === '100'
          ? Promise.reject(new Error('assessment down'))
          : Promise.resolve(undefined),
      );

    const count = await service.syncPendingReports();

    expect(count).toBe(1);
  });
});

describe('ExamSessionReportService.expireAbandonedSessions', () => {
  it('leaves sessions alone while still within the grace period after close', async () => {
    const session = buildSession({ id: '100', userId: '9' });
    const { service, mocks } = buildService({
      findAllInProgress: jest.fn().mockResolvedValue([session]),
      findExamById: jest.fn().mockResolvedValue(buildExam({ closeAt: new Date() })),
    });

    const result = await service.expireAbandonedSessions();

    expect(mocks.updateStatus).not.toHaveBeenCalled();
    expect(result).toEqual({ expiredCount: 0, forcedSubmitCount: 0 });
  });

  it('marks a session EXPIRED when nothing was ever answered', async () => {
    const session = buildSession({ id: '100', userId: '9' });
    const longClosed = new Date(Date.now() - 4 * 60 * 60 * 1000);
    const { service, mocks } = buildService({
      findAllInProgress: jest.fn().mockResolvedValue([session]),
      findExamById: jest.fn().mockResolvedValue(buildExam({ closeAt: longClosed })),
      listAnsweredQuestionIds: jest.fn().mockResolvedValue([]),
    });

    const result = await service.expireAbandonedSessions();

    expect(mocks.updateStatus).toHaveBeenCalledWith('100', SessionStatus.EXPIRED);
    expect(result).toEqual({ expiredCount: 1, forcedSubmitCount: 0 });
  });

  it('force-finalizes a session that answered at least one question', async () => {
    const session = buildSession({ id: '100', userId: '9' });
    const longClosed = new Date(Date.now() - 4 * 60 * 60 * 1000);
    const { service, mocks } = buildService({
      findAllInProgress: jest.fn().mockResolvedValue([session]),
      findExamById: jest.fn().mockResolvedValue(buildExam({ closeAt: longClosed })),
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1']),
    });
    const checkAndFinalizeSpy = jest
      .spyOn(service, 'checkAndFinalize')
      .mockResolvedValue(undefined);

    const result = await service.expireAbandonedSessions();

    expect(checkAndFinalizeSpy).toHaveBeenCalledWith('100', '9', { force: true });
    expect(mocks.updateStatus).not.toHaveBeenCalled();
    expect(result).toEqual({ expiredCount: 0, forcedSubmitCount: 1 });
  });

  it('keeps processing remaining sessions when a force-finalize fails', async () => {
    const sessionA = buildSession({ id: '100', userId: '9' });
    const sessionB = buildSession({ id: '200', userId: '15' });
    const longClosed = new Date(Date.now() - 4 * 60 * 60 * 1000);
    const { service } = buildService({
      findAllInProgress: jest.fn().mockResolvedValue([sessionA, sessionB]),
      findExamById: jest.fn().mockResolvedValue(buildExam({ closeAt: longClosed })),
      listAnsweredQuestionIds: jest.fn().mockResolvedValue(['1']),
    });
    jest
      .spyOn(service, 'checkAndFinalize')
      .mockImplementation((examSessionId: string) =>
        examSessionId === '100'
          ? Promise.reject(new Error('assessment down'))
          : Promise.resolve(undefined),
      );

    const result = await service.expireAbandonedSessions();

    expect(result).toEqual({ expiredCount: 0, forcedSubmitCount: 1 });
  });
});
