import { Answer } from './entities/answer.entity';
import { AnswerType } from './enums/answer-type.enum';

export interface SaveAnswerInput {
  examSessionId: string;
  questionId: string;
  type: AnswerType;
  contentText: string | null;
  audioFileUrl: string | null;
}

export const ANSWER_REPOSITORY = Symbol('ANSWER_REPOSITORY');

export interface AnswerRepository {
  /** (examSessionId, questionId) 유니크 제약 기준 upsert — 재저장하면 덮어쓴다. */
  save(input: SaveAnswerInput): Promise<Answer>;
  findBySessionAndQuestion(examSessionId: string, questionId: string): Promise<Answer | null>;
}
