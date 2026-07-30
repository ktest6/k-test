import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { Exam } from '../domain/entities/exam.entity';
import { ExamService } from '../application/services/exam.service';
import { ExamController } from './exam.controller';

function buildExam(): Exam {
  return new Exam(
    '1',
    '2026년 1회차',
    new Date('2026-08-01T00:00:00.000Z'),
    new Date('2026-08-14T23:59:59.000Z'),
    100,
    new Date(),
  );
}

function buildUser(role: Role): AuthenticatedUser {
  return { id: '1', email: 'user@test.com', role };
}

describe('ExamController.list', () => {
  it('includes capacity for admins', async () => {
    const list = jest.fn().mockResolvedValue([buildExam()]);
    const controller = new ExamController({ list } as unknown as ExamService);

    const [result] = await controller.list(buildUser(Role.ADMIN));

    expect(result).toMatchObject({ id: '1', capacity: 100 });
  });

  it('omits capacity for regular users', async () => {
    const list = jest.fn().mockResolvedValue([buildExam()]);
    const controller = new ExamController({ list } as unknown as ExamService);

    const [result] = await controller.list(buildUser(Role.USER));

    expect(result).not.toHaveProperty('capacity');
    expect(result).toMatchObject({ id: '1', roundName: '2026년 1회차' });
  });
});
