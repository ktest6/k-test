import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { Score } from '../../domain/entities/score.entity';
import { ScoringRepository } from '../../domain/scoring.repository.interface';
import { ScoringService } from './scoring.service';

function buildScore(): Score {
  return new Score('1', '1', { total: 90 }, new Date());
}

function buildRepository(overrides: Partial<ScoringRepository> = {}) {
  return {
    record: jest.fn(),
    findByAnswerId: jest.fn().mockResolvedValue(null),
    ...overrides,
  };
}

describe('ScoringService.getByAnswerId', () => {
  it('throws when no score exists for the answer', async () => {
    const repository = buildRepository();
    const service = new ScoringService(repository);

    await expect(service.getByAnswerId('1')).rejects.toThrow(NotFoundDomainException);
  });

  it('returns the score when it exists', async () => {
    const score = buildScore();
    const repository = buildRepository({ findByAnswerId: jest.fn().mockResolvedValue(score) });
    const service = new ScoringService(repository);

    const result = await service.getByAnswerId('1');

    expect(result).toBe(score);
  });
});

describe('ScoringService.findByAnswerId', () => {
  it('returns null instead of throwing when no score exists', async () => {
    const repository = buildRepository();
    const service = new ScoringService(repository);

    const result = await service.findByAnswerId('1');

    expect(result).toBeNull();
  });
});
