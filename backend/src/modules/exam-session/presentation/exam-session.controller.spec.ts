import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { Question } from '../../question/domain/entities/question.entity';
import { ExamSession } from '../domain/entities/exam-session.entity';
import { SessionStatus } from '../domain/enums/session-status.enum';
import { ExamSessionQuestionService } from '../application/services/exam-session-question.service';
import { ExamSessionService } from '../application/services/exam-session.service';
import { ExamSessionController } from './exam-session.controller';

function buildUser(): AuthenticatedUser {
  return { id: '1', email: 'user@test.com', role: Role.USER };
}

function buildSession(overrides: Partial<{ currentQuestionId: string | null }> = {}): ExamSession {
  return new ExamSession(
    '1',
    '1',
    '1',
    SessionStatus.INPROGRESS,
    new Date('2026-06-01T00:00:00.000Z'),
    overrides.currentQuestionId ?? null,
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
      reference_keywords: ['a'],
    },
    null,
    [{ id: '1', code: 'c1', description: '채점 기준', weight: 1.5, displayOrder: 0 }],
    new Date(),
  );
}

function buildController(
  sessionOverrides: Partial<{
    start: jest.Mock;
    getStatus: jest.Mock;
  }> = {},
  questionOverrides: Partial<{
    listQuestions: jest.Mock;
    getQuestion: jest.Mock;
  }> = {},
) {
  const sessionService = {
    start: jest.fn(),
    getStatus: jest.fn(),
    ...sessionOverrides,
  } as unknown as ExamSessionService;
  const questionService = {
    listQuestions: jest.fn(),
    getQuestion: jest.fn(),
    ...questionOverrides,
  } as unknown as ExamSessionQuestionService;
  return new ExamSessionController(sessionService, questionService);
}

describe('ExamSessionController.start', () => {
  it('delegates to ExamSessionService.start and maps the response', async () => {
    const session = buildSession();
    const start = jest.fn().mockResolvedValue(session);
    const controller = buildController({ start });

    const result = await controller.start('1', buildUser());

    expect(start).toHaveBeenCalledWith('1', '1');
    expect(result).toEqual({
      id: '1',
      examId: '1',
      status: SessionStatus.INPROGRESS,
      startedAt: session.startedAt,
    });
  });
});

describe('ExamSessionController.getStatus', () => {
  it('delegates to ExamSessionService.getStatus and maps the response', async () => {
    const session = buildSession({ currentQuestionId: '5' });
    const getStatus = jest.fn().mockResolvedValue({
      session,
      status: SessionStatus.INPROGRESS,
      remainingSeconds: 120,
    });
    const controller = buildController({ getStatus });

    const result = await controller.getStatus('1', buildUser());

    expect(getStatus).toHaveBeenCalledWith('1', '1');
    expect(result).toEqual({
      id: '1',
      examId: '1',
      status: SessionStatus.INPROGRESS,
      currentQuestionId: '5',
      remainingSeconds: 120,
    });
  });
});

describe('ExamSessionController.listQuestions', () => {
  it('delegates to ExamSessionQuestionService.listQuestions and strips grading info from the response', async () => {
    const listQuestions = jest.fn().mockResolvedValue([buildQuestion('1'), buildQuestion('2')]);
    const controller = buildController({}, { listQuestions });

    const result = await controller.listQuestions('1', buildUser());

    expect(listQuestions).toHaveBeenCalledWith('1', '1');
    expect(result).toEqual([
      { id: '1', part: 'work_log', prompt: '프롬프트 1' },
      { id: '2', part: 'work_log', prompt: '프롬프트 2' },
    ]);
    result.forEach((dto) => {
      expect(dto).not.toHaveProperty('checklistItems');
      expect(dto).not.toHaveProperty('expectedRegister');
      expect(dto).not.toHaveProperty('referenceKeywords');
    });
  });
});

describe('ExamSessionController.getQuestion', () => {
  it('delegates to ExamSessionQuestionService.getQuestion and strips grading info from the response', async () => {
    const getQuestion = jest.fn().mockResolvedValue(buildQuestion('3'));
    const controller = buildController({}, { getQuestion });

    const result = await controller.getQuestion('1', '3', buildUser());

    expect(getQuestion).toHaveBeenCalledWith('1', '3', '1');
    expect(result).toEqual({ id: '3', part: 'work_log', prompt: '프롬프트 3' });
  });
});
