import { Inject, Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { Question } from '../../domain/entities/question.entity';
import {
  CreateQuestionDraftInput,
  QUESTION_REPOSITORY,
  QuestionRepository,
} from '../../domain/question.repository.interface';

@Injectable()
export class QuestionService {
  constructor(
    @Inject(QUESTION_REPOSITORY) private readonly questionRepository: QuestionRepository,
  ) {}

  bulkCreateDrafts(documentId: string, items: CreateQuestionDraftInput[]): Promise<Question[]> {
    return this.questionRepository.bulkCreateDrafts(documentId, items);
  }

  findByDocumentId(documentId: string): Promise<Question[]> {
    return this.questionRepository.findByDocumentId(documentId);
  }

  async findById(id: string): Promise<Question> {
    const question = await this.questionRepository.findById(id);
    if (!question) {
      throw new NotFoundDomainException(`문항(${id})을 찾을 수 없습니다.`);
    }
    return question;
  }

  findByIds(ids: string[]): Promise<Question[]> {
    return this.questionRepository.findByIds(ids);
  }
}
