import { SkippedQuestion } from './entities/skipped-question.entity';

export const SKIPPED_QUESTION_REPOSITORY = Symbol('SKIPPED_QUESTION_REPOSITORY');

export interface SkippedQuestionRepository {
  /** (examSessionId, questionId) 유니크 제약 기준 upsert — 이미 건너뛴 문항에 다시 호출해도 안전하다(멱등). */
  create(examSessionId: string, questionId: string): Promise<SkippedQuestion>;
  /** 이 세션에서 건너뛴 문항 id 목록. */
  listSkippedQuestionIds(examSessionId: string): Promise<string[]>;
  /** 건너뛴 문항에 나중에 답안을 저장하면(마음을 바꾸면) 스킵 기록을 지운다. 없어도 안전(no-op). */
  deleteBySessionAndQuestion(examSessionId: string, questionId: string): Promise<void>;
}
