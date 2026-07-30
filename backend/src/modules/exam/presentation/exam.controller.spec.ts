import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { Exam } from '../domain/entities/exam.entity';
import { ExamApplicationService } from '../application/services/exam-application.service';
import { ExamService } from '../application/services/exam.service';
import { ExamController } from './exam.controller';

function buildExam(): Exam {
  return new Exam(
    '1',
    '2026년 1회차',
    new Date('2026-07-01T00:00:00.000Z'),
    new Date('2026-07-14T23:59:59.000Z'),
    new Date('2026-08-01T00:00:00.000Z'),
    new Date('2026-08-14T23:59:59.000Z'),
    100,
    new Date(),
  );
}

function buildUser(role: Role): AuthenticatedUser {
  return { id: '1', email: 'user@test.com', role };
}

function buildApplicationService(countActive = 0) {
  const apply = jest.fn();
  const cancel = jest.fn();
  const countActiveFn = jest.fn().mockResolvedValue(countActive);
  const service = {
    countActive: countActiveFn,
    apply,
    cancel,
  } as unknown as ExamApplicationService;
  return { service, apply, cancel, countActive: countActiveFn };
}

describe('ExamController.list', () => {
  it('includes capacity and applicantCount for admins', async () => {
    const list = jest.fn().mockResolvedValue([buildExam()]);
    const { service } = buildApplicationService(7);
    const controller = new ExamController({ list } as unknown as ExamService, service);

    const [result] = await controller.list(buildUser(Role.ADMIN));

    expect(result).toMatchObject({ id: '1', capacity: 100, applicantCount: 7 });
  });

  it('omits capacity and applicantCount for regular users', async () => {
    const list = jest.fn().mockResolvedValue([buildExam()]);
    const { service } = buildApplicationService();
    const controller = new ExamController({ list } as unknown as ExamService, service);

    const [result] = await controller.list(buildUser(Role.USER));

    expect(result).not.toHaveProperty('capacity');
    expect(result).not.toHaveProperty('applicantCount');
    expect(result).toMatchObject({ id: '1', roundName: '2026년 1회차' });
  });
});

describe('ExamController.findById', () => {
  it('includes capacity and applicantCount for admins', async () => {
    const findById = jest.fn().mockResolvedValue(buildExam());
    const { service } = buildApplicationService(3);
    const controller = new ExamController({ findById } as unknown as ExamService, service);

    const result = await controller.findById('1', buildUser(Role.ADMIN));

    expect(findById).toHaveBeenCalledWith('1');
    expect(result).toMatchObject({ id: '1', capacity: 100, applicantCount: 3 });
  });

  it('omits capacity and applicantCount for regular users', async () => {
    const findById = jest.fn().mockResolvedValue(buildExam());
    const { service } = buildApplicationService();
    const controller = new ExamController({ findById } as unknown as ExamService, service);

    const result = await controller.findById('1', buildUser(Role.USER));

    expect(result).not.toHaveProperty('capacity');
    expect(result).not.toHaveProperty('applicantCount');
  });
});

describe('ExamController.apply', () => {
  it('delegates to ExamApplicationService.apply and maps the response', async () => {
    const appliedAt = new Date('2026-07-01T00:00:00.000Z');
    const { service, apply } = buildApplicationService();
    apply.mockResolvedValue({ id: '10', examId: '1', userId: '1', appliedAt });
    const controller = new ExamController({} as unknown as ExamService, service);

    const result = await controller.apply('1', buildUser(Role.USER));

    expect(apply).toHaveBeenCalledWith('1', '1');
    expect(result).toEqual({ id: '10', examId: '1', appliedAt });
  });
});

describe('ExamController.cancelApplication', () => {
  it('delegates to ExamApplicationService.cancel', async () => {
    const { service, cancel } = buildApplicationService();
    const controller = new ExamController({} as unknown as ExamService, service);

    await controller.cancelApplication('1', buildUser(Role.USER));

    expect(cancel).toHaveBeenCalledWith('1', '1');
  });
});
