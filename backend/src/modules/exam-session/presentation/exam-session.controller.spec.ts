import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { ExamSession } from '../domain/entities/exam-session.entity';
import { SessionStatus } from '../domain/enums/session-status.enum';
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

describe('ExamSessionController.start', () => {
  it('delegates to ExamSessionService.start and maps the response', async () => {
    const session = buildSession();
    const start = jest.fn().mockResolvedValue(session);
    const controller = new ExamSessionController({ start } as unknown as ExamSessionService);

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
    const controller = new ExamSessionController({ getStatus } as unknown as ExamSessionService);

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
