import { Inject, Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { Question } from '../../domain/entities/question.entity';
import {
  CreateQuestionInput,
  QUESTION_REPOSITORY,
  QuestionRepository,
  UpdateQuestionInput,
} from '../../domain/question.repository.interface';

@Injectable()
export class QuestionService {
  constructor(
    @Inject(QUESTION_REPOSITORY) private readonly questionRepository: QuestionRepository,
  ) {}

  create(input: CreateQuestionInput): Promise<Question> {
    return this.questionRepository.create(input);
  }

  async findById(id: string): Promise<Question> {
    const question = await this.questionRepository.findById(id);
    if (!question) {
      throw new NotFoundDomainException(`Question ${id} not found`);
    }
    return question;
  }

  update(id: string, input: UpdateQuestionInput): Promise<Question> {
    return this.questionRepository.update(id, input);
  }

  delete(id: string): Promise<void> {
    return this.questionRepository.delete(id);
  }

  listByTestId(testId: string): Promise<Question[]> {
    return this.questionRepository.listByTestId(testId);
  }
}
