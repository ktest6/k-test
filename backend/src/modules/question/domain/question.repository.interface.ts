import { Question, QuestionContent } from './entities/question.entity';
import { QuestionSectionType } from './enums/question-section-type.enum';

export interface CreateChecklistItemInput {
  code: string;
  description: string;
  weight: number;
}

export interface CreateQuestionDraftInput {
  part: QuestionSectionType;
  content: QuestionContent;
  checklist: CreateChecklistItemInput[];
}

export const QUESTION_REPOSITORY = Symbol('QUESTION_REPOSITORY');

export interface QuestionRepository {
  /** 문서 하나로 생성된 문항 여러 개(+체크리스트)를 한 번에 만든다. */
  bulkCreateDrafts(documentId: string, items: CreateQuestionDraftInput[]): Promise<Question[]>;
  findByDocumentId(documentId: string): Promise<Question[]>;
  findById(id: string): Promise<Question | null>;
  findByIds(ids: string[]): Promise<Question[]>;
}
