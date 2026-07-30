import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../domain/entities/exam.entity';
import { ExamRepository } from '../../domain/exam.repository.interface';
import { ExamService } from './exam.service';

function buildInput(overrides: Partial<{ openAt: Date; closeAt: Date }> = {}) {
  return {
    roundName: '2026년 1회차',
    openAt: new Date('2026-08-01T00:00:00.000Z'),
    closeAt: new Date('2026-08-14T23:59:59.000Z'),
    capacity: 100,
    ...overrides,
  };
}

describe('ExamService.create', () => {
  it('rejects when closeAt is before openAt', async () => {
    const create = jest.fn();
    const service = new ExamService({ create } as unknown as ExamRepository);

    const input = buildInput({
      openAt: new Date('2026-08-14T00:00:00.000Z'),
      closeAt: new Date('2026-08-01T00:00:00.000Z'),
    });

    await expect(service.create(input)).rejects.toThrow(ConflictDomainException);
    expect(create).not.toHaveBeenCalled();
  });

  it('rejects when closeAt equals openAt', async () => {
    const create = jest.fn();
    const service = new ExamService({ create } as unknown as ExamRepository);

    const sameInstant = new Date('2026-08-01T00:00:00.000Z');
    const input = buildInput({ openAt: sameInstant, closeAt: sameInstant });

    await expect(service.create(input)).rejects.toThrow(ConflictDomainException);
  });

  it('creates the exam when closeAt is after openAt', async () => {
    const input = buildInput();
    const created = new Exam(
      '1',
      input.roundName,
      input.openAt,
      input.closeAt,
      input.capacity,
      new Date(),
    );
    const create = jest.fn().mockResolvedValue(created);
    const service = new ExamService({ create } as unknown as ExamRepository);

    const result = await service.create(input);

    expect(create).toHaveBeenCalledWith(input);
    expect(result).toBe(created);
  });
});
