import { Question } from './entities/question.entity';
import { QuestionType } from './enums/question-type.enum';

export interface CreateQuestionInput {
  testId: string;
  type: QuestionType;
  content: string;
  choices?: string[];
  correctAnswer?: string;
  points: number;
}

export interface UpdateQuestionInput {
  content?: string;
  choices?: string[];
  correctAnswer?: string;
  points?: number;
}

export const QUESTION_REPOSITORY = Symbol('QUESTION_REPOSITORY');

export interface QuestionRepository {
  create(input: CreateQuestionInput): Promise<Question>;
  findById(id: string): Promise<Question | null>;
  update(id: string, input: UpdateQuestionInput): Promise<Question>;
  delete(id: string): Promise<void>;
  listByTestId(testId: string): Promise<Question[]>;
}
