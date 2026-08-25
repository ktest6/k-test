import { ExamResult } from './entities/exam-result.entity';

export interface RecordExamResultInput {
  examSessionId: string;
  finalGrade: string;
  percentile: number | null;
  domainScores: Record<string, unknown> | null;
  crossValidationSignals: Record<string, unknown> | null;
  rawResponse: Record<string, unknown>;
}

export const EXAM_RESULT_REPOSITORY = Symbol('EXAM_RESULT_REPOSITORY');

export interface ExamResultRepository {
  /** examSessionId 유니크 기준 upsert — 같은 세션에 다시 finalize가 불려도 마지막 결과로 덮어쓴다. */
  record(input: RecordExamResultInput): Promise<ExamResult>;
  findById(id: string): Promise<ExamResult | null>;
  findByExamSessionId(examSessionId: string): Promise<ExamResult | null>;
  /** 최종 리포트 제출 재시도 배치용 — 이미 결과가 저장된 세션 id 전체(가벼운 조회, 결과 내용은 안 담음). */
  listExamSessionIdsWithResult(): Promise<string[]>;
}
