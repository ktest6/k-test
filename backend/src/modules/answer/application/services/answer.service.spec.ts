import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { Answer } from '../../domain/entities/answer.entity';
import { AnswerRepository } from '../../domain/answer.repository.interface';
import { AnswerStatus } from '../../domain/enums/answer-status.enum';
import { AnswerType } from '../../domain/enums/answer-type.enum';
import { AnswerService } from './answer.service';

function buildAnswer(): Answer {
  return new Answer('1', '1', '1', AnswerType.TEXT, '내용', null, AnswerStatus.DRAFT, new Date());
}

function buildRepository(overrides: Partial<AnswerRepository> = {}) {
  return {
    save: jest.fn().mockResolvedValue(buildAnswer()),
    findBySessionAndQuestion: jest.fn().mockResolvedValue(null),
    ...overrides,
  };
}

describe('AnswerService.save', () => {
  it('rejects a TEXT answer with no content', async () => {
    const repository = buildRepository();
    const service = new AnswerService(repository);

    await expect(
      service.save({
        examSessionId: '1',
        questionId: '1',
        type: AnswerType.TEXT,
        contentText: null,
        audioFileUrl: null,
      }),
    ).rejects.toThrow(ConflictDomainException);
    expect(repository.save).not.toHaveBeenCalled();
  });

  it('rejects an AUDIO answer with no file url', async () => {
    const repository = buildRepository();
    const service = new AnswerService(repository);

    await expect(
      service.save({
        examSessionId: '1',
        questionId: '1',
        type: AnswerType.AUDIO,
        contentText: null,
        audioFileUrl: null,
      }),
    ).rejects.toThrow(ConflictDomainException);
    expect(repository.save).not.toHaveBeenCalled();
  });

  it('saves a valid TEXT answer', async () => {
    const saved = buildAnswer();
    const repository = buildRepository({ save: jest.fn().mockResolvedValue(saved) });
    const service = new AnswerService(repository);
    const input = {
      examSessionId: '1',
      questionId: '1',
      type: AnswerType.TEXT,
      contentText: '내용',
      audioFileUrl: null,
    };

    const result = await service.save(input);

    expect(repository.save).toHaveBeenCalledWith(input);
    expect(result).toBe(saved);
  });
});

describe('AnswerService.findBySessionAndQuestion', () => {
  it('delegates to the repository', async () => {
    const repository = buildRepository();
    const service = new AnswerService(repository);

    await service.findBySessionAndQuestion('1', '2');

    expect(repository.findBySessionAndQuestion).toHaveBeenCalledWith('1', '2');
  });
});
