import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { Exam } from '../../domain/entities/exam.entity';
import { ExamRepository } from '../../domain/exam.repository.interface';
import { ExamService } from './exam.service';

function buildInput(overrides: Partial<{ openAt: Date; closeAt: Date }> = {}) {
  return {
    openAt: new Date('2026-08-01T00:00:00.000Z'),
    closeAt: new Date('2026-08-14T23:59:59.000Z'),
    capacity: 100,
    ...overrides,
  };
}

function buildRepository(latestRoundName: string | null) {
  const findLatestRoundNameForYear = jest.fn().mockResolvedValue(latestRoundName);
  const create = jest
    .fn()
    .mockImplementation(
      (input: { roundName: string; openAt: Date; closeAt: Date; capacity: number }) =>
        Promise.resolve(
          new Exam('1', input.roundName, input.openAt, input.closeAt, input.capacity, new Date()),
        ),
    );
  return { create, findLatestRoundNameForYear };
}

describe('ExamService.create', () => {
  it('rejects when closeAt is before openAt, without touching the repository', async () => {
    const { create, findLatestRoundNameForYear } = buildRepository(null);
    const service = new ExamService({
      create,
      findLatestRoundNameForYear,
    } as unknown as ExamRepository);

    const input = buildInput({
      openAt: new Date('2026-08-14T00:00:00.000Z'),
      closeAt: new Date('2026-08-01T00:00:00.000Z'),
    });

    await expect(service.create(input)).rejects.toThrow(ConflictDomainException);
    expect(create).not.toHaveBeenCalled();
    expect(findLatestRoundNameForYear).not.toHaveBeenCalled();
  });

  it('rejects when closeAt equals openAt', async () => {
    const { create, findLatestRoundNameForYear } = buildRepository(null);
    const service = new ExamService({
      create,
      findLatestRoundNameForYear,
    } as unknown as ExamRepository);

    const sameInstant = new Date('2026-08-01T00:00:00.000Z');
    const input = buildInput({ openAt: sameInstant, closeAt: sameInstant });

    await expect(service.create(input)).rejects.toThrow(ConflictDomainException);
    expect(create).not.toHaveBeenCalled();
  });

  it('generates the first round number of the year when none exist yet', async () => {
    const year = new Date().getFullYear();
    const { create, findLatestRoundNameForYear } = buildRepository(null);
    const service = new ExamService({
      create,
      findLatestRoundNameForYear,
    } as unknown as ExamRepository);

    const result = await service.create(buildInput());

    expect(findLatestRoundNameForYear).toHaveBeenCalledWith(year);
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ roundName: `${year}01` }));
    expect(result.roundName).toBe(`${year}01`);
  });

  it('increments the sequence when a round already exists for the year', async () => {
    const year = new Date().getFullYear();
    const { create, findLatestRoundNameForYear } = buildRepository(`${year}05`);
    const service = new ExamService({
      create,
      findLatestRoundNameForYear,
    } as unknown as ExamRepository);

    await service.create(buildInput());

    expect(create).toHaveBeenCalledWith(expect.objectContaining({ roundName: `${year}06` }));
  });

  it('pads single-digit sequence numbers to two digits', async () => {
    const year = new Date().getFullYear();
    const { create, findLatestRoundNameForYear } = buildRepository(`${year}01`);
    const service = new ExamService({
      create,
      findLatestRoundNameForYear,
    } as unknown as ExamRepository);

    await service.create(buildInput());

    expect(create).toHaveBeenCalledWith(expect.objectContaining({ roundName: `${year}02` }));
  });
});
