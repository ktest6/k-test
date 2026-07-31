import { Inject, Injectable } from '@nestjs/common';
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
}
