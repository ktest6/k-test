import { EventEmitter2 } from '@nestjs/event-emitter';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { Answer } from '../../domain/entities/answer.entity';
import { AnswerRepository } from '../../domain/answer.repository.interface';
import { AnswerStatus } from '../../domain/enums/answer-status.enum';
import { AnswerType } from '../../domain/enums/answer-type.enum';
import { ANSWER_SAVED_EVENT } from '../../domain/events/answer-saved.event';
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

function buildEventEmitter(overrides: Partial<{ emit: jest.Mock }> = {}) {
  return { emit: jest.fn(), ...overrides } as unknown as EventEmitter2;
}

describe('AnswerService.save', () => {
  it('rejects a TEXT answer with no content', async () => {
    const repository = buildRepository();
    const eventEmitter = buildEventEmitter();
    const service = new AnswerService(repository, eventEmitter);

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
    const eventEmitter = buildEventEmitter();
    const service = new AnswerService(repository, eventEmitter);

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

  it('saves a valid TEXT answer and emits answer.saved', async () => {
    const saved = buildAnswer();
    const repository = buildRepository({ save: jest.fn().mockResolvedValue(saved) });
    const emit = jest.fn();
    const eventEmitter = buildEventEmitter({ emit });
    const service = new AnswerService(repository, eventEmitter);
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
    expect(emit).toHaveBeenCalledWith(
      ANSWER_SAVED_EVENT,
      expect.objectContaining({
        answerId: saved.id,
        questionId: saved.questionId,
        type: saved.type,
        contentText: saved.contentText,
        audioFileUrl: saved.audioFileUrl,
      }),
    );
  });

  it('passes durationMs through to the emitted event when provided', async () => {
    const saved = buildAnswer();
    const repository = buildRepository({ save: jest.fn().mockResolvedValue(saved) });
    const emit = jest.fn();
    const eventEmitter = buildEventEmitter({ emit });
    const service = new AnswerService(repository, eventEmitter);
    const input = {
      examSessionId: '1',
      questionId: '1',
      type: AnswerType.AUDIO,
      contentText: null,
      audioFileUrl: '1/1/1.webm',
    };

    await service.save(input, 11760);

    expect(repository.save).toHaveBeenCalledWith(input);
    expect(emit).toHaveBeenCalledWith(
      ANSWER_SAVED_EVENT,
      expect.objectContaining({ durationMs: 11760 }),
    );
  });
});

describe('AnswerService.findBySessionAndQuestion', () => {
  it('delegates to the repository', async () => {
    const repository = buildRepository();
    const eventEmitter = buildEventEmitter();
    const service = new AnswerService(repository, eventEmitter);

    await service.findBySessionAndQuestion('1', '2');

    expect(repository.findBySessionAndQuestion).toHaveBeenCalledWith('1', '2');
  });
});
