import { Submission } from './entities/submission.entity';
import { SubmissionStatus } from './enums/submission-status.enum';

export interface CreateSubmissionInput {
  testId: string;
  userId: string;
}

export const SUBMISSION_REPOSITORY = Symbol('SUBMISSION_REPOSITORY');

export interface SubmissionRepository {
  create(input: CreateSubmissionInput): Promise<Submission>;
  findById(id: string): Promise<Submission | null>;
  updateStatus(
    id: string,
    status: SubmissionStatus,
    extra?: { warningCount?: number; submittedAt?: Date },
  ): Promise<Submission>;
  listByUserId(userId: string): Promise<Submission[]>;
}
