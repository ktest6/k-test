import { Inject, Injectable } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { Answer } from '../../domain/entities/answer.entity';
import {
  ANSWER_REPOSITORY,
  AnswerRepository,
  SaveAnswerInput,
} from '../../domain/answer.repository.interface';
import { AnswerType } from '../../domain/enums/answer-type.enum';
import { ANSWER_SAVED_EVENT, AnswerSavedEvent } from '../../domain/events/answer-saved.event';

@Injectable()
export class AnswerService {
  constructor(
    @Inject(ANSWER_REPOSITORY) private readonly answerRepository: AnswerRepository,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  async save(input: SaveAnswerInput, durationMs: number | null = null): Promise<Answer> {
    if (input.type === AnswerType.TEXT && !input.contentText) {
      throw new ConflictDomainException('A text answer requires content.');
    }
    if (input.type === AnswerType.AUDIO && !input.audioFileUrl) {
      throw new ConflictDomainException('An audio answer requires a file path.');
    }

    const answer = await this.answerRepository.save(input);

    this.eventEmitter.emit(
      ANSWER_SAVED_EVENT,
      new AnswerSavedEvent(
        answer.id,
        answer.questionId,
        answer.type,
        answer.contentText,
        answer.audioFileUrl,
        durationMs,
      ),
    );

    return answer;
  }

  findBySessionAndQuestion(examSessionId: string, questionId: string): Promise<Answer | null> {
    return this.answerRepository.findBySessionAndQuestion(examSessionId, questionId);
  }

  listAnsweredQuestionIds(examSessionId: string): Promise<string[]> {
    return this.answerRepository.listAnsweredQuestionIds(examSessionId);
  }

  listBySession(examSessionId: string): Promise<Answer[]> {
    return this.answerRepository.listBySession(examSessionId);
  }
}
