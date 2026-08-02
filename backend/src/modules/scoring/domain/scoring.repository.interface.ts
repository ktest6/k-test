import { Score } from './entities/score.entity';

export interface RecordScoreInput {
  answerId: string;
  rawResponse: Record<string, unknown>;
}

export const SCORING_REPOSITORY = Symbol('SCORING_REPOSITORY');

export interface ScoringRepository {
  record(input: RecordScoreInput): Promise<Score>;
  findByAnswerId(answerId: string): Promise<Score | null>;
}
