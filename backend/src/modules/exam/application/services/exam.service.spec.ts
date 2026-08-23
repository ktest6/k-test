import { Exam } from '../../domain/entities/exam.entity';
import { ExamRepository } from '../../domain/exam.repository.interface';
import { ExamService } from './exam.service';

function buildRepository(latestRoundName: string | null) {
  const findLatestRoundNameForYear = jest.fn().mockResolvedValue(latestRoundName);
  const create = jest
    .fn()
    .mockImplementation((input: { roundName: string }) =>
      Promise.resolve(new Exam('1', input.roundName, new Date())),
    );
  return { create, findLatestRoundNameForYear };
}

describe('ExamService.create', () => {
  it('generates the first round number of the year when none exist yet', async () => {
    const year = new Date().getFullYear();
    const { create, findLatestRoundNameForYear } = buildRepository(null);
    const service = new ExamService({
      create,
      findLatestRoundNameForYear,
    } as unknown as ExamRepository);

    const result = await service.create();

    expect(findLatestRoundNameForYear).toHaveBeenCalledWith(year);
    expect(create).toHaveBeenCalledWith({ roundName: `${year}01` });
    expect(result.roundName).toBe(`${year}01`);
  });

  it('increments the sequence when a round already exists for the year', async () => {
    const year = new Date().getFullYear();
    const { create, findLatestRoundNameForYear } = buildRepository(`${year}05`);
    const service = new ExamService({
      create,
      findLatestRoundNameForYear,
    } as unknown as ExamRepository);

    await service.create();

    expect(create).toHaveBeenCalledWith({ roundName: `${year}06` });
  });

  it('pads single-digit sequence numbers to two digits', async () => {
    const year = new Date().getFullYear();
    const { create, findLatestRoundNameForYear } = buildRepository(`${year}01`);
    const service = new ExamService({
      create,
      findLatestRoundNameForYear,
    } as unknown as ExamRepository);

    await service.create();

    expect(create).toHaveBeenCalledWith({ roundName: `${year}02` });
  });
});
