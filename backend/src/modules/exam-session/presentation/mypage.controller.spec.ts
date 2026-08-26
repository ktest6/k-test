import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { SessionStatus } from '../domain/enums/session-status.enum';
import { ExamSessionService } from '../application/services/exam-session.service';
import { MypageReportService } from '../application/services/mypage-report.service';
import { MypageController } from './mypage.controller';

function buildUser(): AuthenticatedUser {
  return { id: '1', email: 'user@test.com', role: Role.USER };
}

function buildController(
  overrides: Partial<{
    listMine: jest.Mock;
    getReport: jest.Mock;
    getViolationSummary: jest.Mock;
  }> = {},
) {
  const examSessionService = {
    listMine: jest.fn(),
    ...overrides,
  } as unknown as ExamSessionService;
  const mypageReportService = {
    getReport: jest.fn(),
    getViolationSummary: jest.fn(),
    ...overrides,
  } as unknown as MypageReportService;
  return new MypageController(examSessionService, mypageReportService);
}

describe('MypageController.listMine', () => {
  it('delegates to ExamSessionService.listMine and maps each session', async () => {
    const startedAt = new Date('2026-08-01T00:00:00.000Z');
    const listMine = jest.fn().mockResolvedValue([
      {
        session: { id: '11', status: SessionStatus.INPROGRESS, startedAt, submittedAt: null },
        examResultId: null,
        finalGrade: null,
      },
    ]);
    const controller = buildController({ listMine });

    const result = await controller.listMine(buildUser());

    expect(listMine).toHaveBeenCalledWith('1');
    expect(result).toEqual([
      {
        examSessionId: '11',
        sessionStatus: SessionStatus.INPROGRESS,
        startedAt,
        submittedAt: null,
        examResultId: null,
        finalGrade: null,
      },
    ]);
  });

  it('includes submittedAt/examResultId/finalGrade once a report has been recorded', async () => {
    const startedAt = new Date('2026-08-01T00:00:00.000Z');
    const submittedAt = new Date('2026-08-05T00:00:00.000Z');
    const listMine = jest.fn().mockResolvedValue([
      {
        session: { id: '11', status: SessionStatus.SUBMITTED, startedAt, submittedAt },
        examResultId: 'r1',
        finalGrade: 'B',
      },
    ]);
    const controller = buildController({ listMine });

    const [result] = await controller.listMine(buildUser());

    expect(result).toMatchObject({ submittedAt, examResultId: 'r1', finalGrade: 'B' });
  });

  it('can list multiple sessions for the same user (retakes)', async () => {
    const startedAt = new Date('2026-08-01T00:00:00.000Z');
    const listMine = jest.fn().mockResolvedValue([
      {
        session: { id: '11', status: SessionStatus.SUBMITTED, startedAt, submittedAt: startedAt },
        examResultId: 'r1',
        finalGrade: 'B',
      },
      {
        session: { id: '12', status: SessionStatus.INPROGRESS, startedAt, submittedAt: null },
        examResultId: null,
        finalGrade: null,
      },
    ]);
    const controller = buildController({ listMine });

    const result = await controller.listMine(buildUser());

    expect(result).toHaveLength(2);
    expect(result.map((r) => r.examSessionId)).toEqual(['11', '12']);
  });
});

describe('MypageController.getReport', () => {
  it('delegates to MypageReportService.getReport', async () => {
    const report = { examResultId: 'r1', examSessionId: '100', candidateName: 'Yena Back' };
    const getReport = jest.fn().mockResolvedValue(report);
    const controller = buildController({ getReport });

    const result = await controller.getReport('r1', buildUser());

    expect(getReport).toHaveBeenCalledWith('r1', '1');
    expect(result).toBe(report);
  });
});

describe('MypageController.getViolationSummary', () => {
  it('delegates to MypageReportService.getViolationSummary', async () => {
    const summary = { examSessionId: '100', candidateName: 'Yena Back', violations: [] };
    const getViolationSummary = jest.fn().mockResolvedValue(summary);
    const controller = buildController({ getViolationSummary });

    const result = await controller.getViolationSummary('100', buildUser());

    expect(getViolationSummary).toHaveBeenCalledWith('100', '1');
    expect(result).toBe(summary);
  });
});
