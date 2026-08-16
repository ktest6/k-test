import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { Exam } from '../../exam/domain/entities/exam.entity';
import { ExamStatus } from '../../exam/domain/enums/exam-status.enum';
import { SessionStatus } from '../domain/enums/session-status.enum';
import { ExamSessionService } from '../application/services/exam-session.service';
import { MypageController } from './mypage.controller';

function buildUser(): AuthenticatedUser {
  return { id: '1', email: 'user@test.com', role: Role.USER };
}

function buildController(overrides: Partial<{ listMine: jest.Mock }> = {}) {
  const examSessionService = {
    listMine: jest.fn(),
    ...overrides,
  } as unknown as ExamSessionService;
  return new MypageController(examSessionService);
}

describe('MypageController.listMine', () => {
  it('delegates to ExamSessionService.listMine and maps null session fields for exams never started', async () => {
    const exam = new Exam(
      '1',
      '2026년 1회차',
      new Date('2026-01-01T00:00:00.000Z'),
      new Date('2026-12-31T23:59:59.000Z'),
      new Date('2026-08-01T00:00:00.000Z'),
      new Date('2026-08-14T23:59:59.000Z'),
      100,
      new Date(),
    );
    const appliedAt = new Date('2026-07-01T00:00:00.000Z');
    const listMine = jest.fn().mockResolvedValue([
      { exam, examStatus: ExamStatus.OPEN, appliedAt, session: null },
      {
        exam,
        examStatus: ExamStatus.OPEN,
        appliedAt,
        session: { id: '11', status: SessionStatus.INPROGRESS },
      },
    ]);
    const controller = buildController({ listMine });

    const result = await controller.listMine(buildUser());

    expect(listMine).toHaveBeenCalledWith('1');
    expect(result).toEqual([
      {
        examId: '1',
        roundName: '2026년 1회차',
        openAt: exam.openAt,
        closeAt: exam.closeAt,
        examStatus: ExamStatus.OPEN,
        appliedAt,
        examSessionId: null,
        sessionStatus: null,
      },
      {
        examId: '1',
        roundName: '2026년 1회차',
        openAt: exam.openAt,
        closeAt: exam.closeAt,
        examStatus: ExamStatus.OPEN,
        appliedAt,
        examSessionId: '11',
        sessionStatus: SessionStatus.INPROGRESS,
      },
    ]);
  });
});
