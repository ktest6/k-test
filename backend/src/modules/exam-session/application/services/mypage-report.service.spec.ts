import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { Answer } from '../../../answer/domain/entities/answer.entity';
import { AnswerStatus } from '../../../answer/domain/enums/answer-status.enum';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import { ProctoringEvent } from '../../../monitoring/domain/entities/proctoring-event.entity';
import { ProctoringEventRepository } from '../../../monitoring/domain/proctoring-event.repository.interface';
import { Question } from '../../../question/domain/entities/question.entity';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import { ExamResult } from '../../../scoring/domain/entities/exam-result.entity';
import { ExamResultService } from '../../../scoring/application/services/exam-result.service';
import { Score } from '../../../scoring/domain/entities/score.entity';
import { ScoringService } from '../../../scoring/application/services/scoring.service';
import { User } from '../../../user/domain/entities/user.entity';
import { IdentityDocumentType } from '../../../user/domain/enums/identity-document-type.enum';
import { UserService } from '../../../user/application/services/user.service';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import { ExamSessionRepository } from '../../domain/exam-session.repository.interface';
import { SkippedQuestionRepository } from '../../domain/skipped-question.repository.interface';
import { ExamSessionQuestionService } from './exam-session-question.service';
import { MypageReportService } from './mypage-report.service';

function buildSession(overrides: Partial<{ userId: string }> = {}): ExamSession {
  return new ExamSession(
    '100',
    overrides.userId ?? '9',
    SessionStatus.SUBMITTED,
    0,
    new Date('2026-08-01T00:00:00.000Z'),
    null,
    null,
    new Date('2026-08-01T00:30:00.000Z'),
    new Date('2026-08-01T00:00:00.000Z'),
  );
}

function buildUser(): User {
  return new User(
    '9',
    'yena@test.com',
    'Yena',
    'Back',
    'Korea',
    '1990-01-01',
    IdentityDocumentType.PASSPORT,
    'X1234567',
    null,
    new Date(),
    new Date(),
    new Date(),
    0,
    null,
    new Date(),
    new Date(),
    null,
  );
}

function buildQuestion(
  id: string,
  part: QuestionSectionType = QuestionSectionType.SITUATION_DESCRIPTION,
): Question {
  return new Question(
    id,
    part,
    { preparationSeconds: 40, responseSeconds: 60, guideTexts: ['안내'] },
    null,
    [],
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
    AnswerStatus.FINAL,
    new Date(),
  );
}

function buildExamResult(
  overrides: Partial<{ examSessionId: string; domainScores: Record<string, unknown> | null }> = {},
): ExamResult {
  return new ExamResult(
    'r1',
    overrides.examSessionId ?? '100',
    'B',
    70.5,
    overrides.domainScores ?? { subscores: [{ area: 'content_task', score: 80 }] },
    null,
    {},
    new Date(),
  );
}

function buildProctoringEvent(
  eventType: string,
  severity: 'LOW' | 'MEDIUM' | 'HIGH',
): ProctoringEvent {
  return new ProctoringEvent('e1', '100', eventType, severity, {}, new Date(), null, null);
}

interface Mocks {
  findSessionById: jest.Mock;
  listSkippedQuestionIds: jest.Mock;
  findEventsBySession: jest.Mock;
  getAssignedQuestions: jest.Mock;
  listBySession: jest.Mock;
  findByAnswerId: jest.Mock;
  findExamResultById: jest.Mock;
  findUserById: jest.Mock;
}

function buildService(overrides: Partial<Mocks> = {}) {
  const mocks: Mocks = {
    findSessionById: jest.fn().mockResolvedValue(buildSession()),
    listSkippedQuestionIds: jest.fn().mockResolvedValue([]),
    findEventsBySession: jest.fn().mockResolvedValue([]),
    getAssignedQuestions: jest.fn().mockResolvedValue([]),
    listBySession: jest.fn().mockResolvedValue([]),
    findByAnswerId: jest.fn().mockResolvedValue(null),
    findExamResultById: jest.fn().mockResolvedValue(buildExamResult()),
    findUserById: jest.fn().mockResolvedValue(buildUser()),
    ...overrides,
  };

  const examSessionRepository = {
    findById: mocks.findSessionById,
  } as unknown as ExamSessionRepository;
  const skippedQuestionRepository = {
    listSkippedQuestionIds: mocks.listSkippedQuestionIds,
  } as unknown as SkippedQuestionRepository;
  const proctoringEventRepository = {
    findByExamSessionId: mocks.findEventsBySession,
  } as unknown as ProctoringEventRepository;
  const examSessionQuestionService = {
    getAssignedQuestions: mocks.getAssignedQuestions,
  } as unknown as ExamSessionQuestionService;
  const answerService = { listBySession: mocks.listBySession } as unknown as AnswerService;
  const scoringService = { findByAnswerId: mocks.findByAnswerId } as unknown as ScoringService;
  const examResultService = { findById: mocks.findExamResultById } as unknown as ExamResultService;
  const userService = { findById: mocks.findUserById } as unknown as UserService;

  const service = new MypageReportService(
    examSessionRepository,
    skippedQuestionRepository,
    proctoringEventRepository,
    examSessionQuestionService,
    answerService,
    scoringService,
    examResultService,
    userService,
  );

  return { service, mocks };
}

describe('MypageReportService.getReport', () => {
  it('throws NotFoundDomainException when the report does not exist', async () => {
    const { service } = buildService({ findExamResultById: jest.fn().mockResolvedValue(null) });

    await expect(service.getReport('r1', '9')).rejects.toThrow(NotFoundDomainException);
  });

  it('throws ForbiddenDomainException when the caller does not own the session', async () => {
    const { service } = buildService({
      findSessionById: jest.fn().mockResolvedValue(buildSession({ userId: '9' })),
    });

    await expect(service.getReport('r1', '99')).rejects.toThrow(ForbiddenDomainException);
  });

  it('marks a question with no answer as skipped and omits response/requiredPoints', async () => {
    const question = buildQuestion('1');
    const { service } = buildService({
      getAssignedQuestions: jest.fn().mockResolvedValue([question]),
      listBySession: jest.fn().mockResolvedValue([]),
    });

    const result = await service.getReport('r1', '9');

    expect(result.tasks).toEqual([
      { questionId: '1', part: question.part, skipped: true, response: null, requiredPoints: null },
    ]);
  });

  it('includes the STT transcript and checklist results for an answered, scored question', async () => {
    const question = buildQuestion('1');
    const answer = buildAnswer('a1', '1');
    const score = new Score(
      's1',
      'a1',
      {
        meta: { stt_transcript: '위험하니까 안전모를 쓰세요.' },
        checklist_results: [{ id: 'c1', description: 'Tell him to wear a safety helmet.', met: 1 }],
      },
      new Date(),
    );
    const { service } = buildService({
      getAssignedQuestions: jest.fn().mockResolvedValue([question]),
      listBySession: jest.fn().mockResolvedValue([answer]),
      findByAnswerId: jest.fn().mockResolvedValue(score),
    });

    const result = await service.getReport('r1', '9');

    expect(result.tasks).toEqual([
      {
        questionId: '1',
        part: question.part,
        skipped: false,
        response: '위험하니까 안전모를 쓰세요.',
        requiredPoints: [{ description: 'Tell him to wear a safety helmet.', met: true }],
      },
    ]);
  });

  it('maps domainScores from the stored result and aggregates violation counts by type and severity', async () => {
    const examResult = buildExamResult({
      domainScores: {
        subscores: [
          { area: 'content_task', score: 80 },
          { area: 'language_use', score: 70 },
        ],
      },
    });
    const events = [
      buildProctoringEvent('TAB_SWITCH', 'MEDIUM'),
      buildProctoringEvent('TAB_SWITCH', 'MEDIUM'),
      buildProctoringEvent('EYE_GAZE_AWAY', 'LOW'),
    ];
    const { service } = buildService({
      findExamResultById: jest.fn().mockResolvedValue(examResult),
      findEventsBySession: jest.fn().mockResolvedValue(events),
    });

    const result = await service.getReport('r1', '9');

    expect(result.domainScores).toEqual([
      { area: 'content_task', score: 80 },
      { area: 'language_use', score: 70 },
    ]);
    expect(result.violations).toEqual(
      expect.arrayContaining([
        { eventType: 'TAB_SWITCH', severity: 'MEDIUM', count: 2 },
        { eventType: 'EYE_GAZE_AWAY', severity: 'LOW', count: 1 },
      ]),
    );
  });

  it('builds candidateName from the user first/last name and passes through grade/percentile/startedAt', async () => {
    const { service } = buildService();

    const result = await service.getReport('r1', '9');

    expect(result.candidateName).toBe('Yena Back');
    expect(result.finalGrade).toBe('B');
    expect(result.percentile).toBe(70.5);
    expect(result.startedAt).toEqual(new Date('2026-08-01T00:00:00.000Z'));
  });
});
