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
  /** 이 세션에서 이미 답안이 저장된 문항 id 목록 — 재접속 시 다음 문항을 찾는 데 쓴다. */
  listAnsweredQuestionIds(examSessionId: string): Promise<string[]>;
}
