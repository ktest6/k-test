import { Score } from './entities/score.entity';

export interface RecordScoreInput {
  submissionId: string;
  totalScore: number;
  maxScore: number;
}

export const SCORING_REPOSITORY = Symbol('SCORING_REPOSITORY');

export interface ScoringRepository {
  record(input: RecordScoreInput): Promise<Score>;
  findBySubmissionId(submissionId: string): Promise<Score | null>;
}
