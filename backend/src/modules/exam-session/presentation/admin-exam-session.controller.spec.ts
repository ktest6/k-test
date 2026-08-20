import { SessionStatus } from '../domain/enums/session-status.enum';
import { ExamSession } from '../domain/entities/exam-session.entity';
import { ExamSessionService } from '../application/services/exam-session.service';
import { AdminExamSessionController } from './admin-exam-session.controller';

function buildSession(status: SessionStatus): ExamSession {
  return new ExamSession(
    '100',
    '7',
    '9',
    status,
    0,
    new Date('2026-08-04T00:00:00.000Z'),
    null,
    null,
    null,
    new Date(),
  );
}

function buildController(overrides: Partial<{ disqualify: jest.Mock }> = {}) {
  const examSessionService = {
    disqualify: jest.fn(),
    ...overrides,
  } as unknown as ExamSessionService;
  return new AdminExamSessionController(examSessionService);
}

describe('AdminExamSessionController.disqualify', () => {
  it('delegates to ExamSessionService.disqualify and maps the response', async () => {
    const disqualify = jest.fn().mockResolvedValue(buildSession(SessionStatus.DISQUALIFIED));
    const controller = buildController({ disqualify });

    const result = await controller.disqualify('100');

    expect(disqualify).toHaveBeenCalledWith('100');
    expect(result).toEqual({ id: '100', examId: '7', status: SessionStatus.DISQUALIFIED });
  });
});
