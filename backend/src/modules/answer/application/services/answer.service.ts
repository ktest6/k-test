import { Inject, Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { Answer } from '../../domain/entities/answer.entity';
import {
  ANSWER_REPOSITORY,
  AnswerRepository,
  SaveAnswerInput,
} from '../../domain/answer.repository.interface';
import { AnswerType } from '../../domain/enums/answer-type.enum';

@Injectable()
export class AnswerService {
  constructor(@Inject(ANSWER_REPOSITORY) private readonly answerRepository: AnswerRepository) {}

  async save(input: SaveAnswerInput): Promise<Answer> {
    if (input.type === AnswerType.TEXT && !input.contentText) {
      throw new ConflictDomainException('텍스트 답안은 내용이 필요합니다.');
    }
    if (input.type === AnswerType.AUDIO && !input.audioFileUrl) {
      throw new ConflictDomainException('음성 답안은 파일 경로가 필요합니다.');
    }
    return this.answerRepository.save(input);
  }

  findBySessionAndQuestion(examSessionId: string, questionId: string): Promise<Answer | null> {
    return this.answerRepository.findBySessionAndQuestion(examSessionId, questionId);
  }
}
