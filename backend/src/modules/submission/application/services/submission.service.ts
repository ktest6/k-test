import { Inject, Injectable, Logger } from '@nestjs/common';
import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { notFound } from '../../../../common/exceptions/error-messages';
import { Submission } from '../../domain/entities/submission.entity';
import { SubmissionStatus } from '../../domain/enums/submission-status.enum';
import {
  CreateSubmissionInput,
  SUBMISSION_REPOSITORY,
  SubmissionRepository,
} from '../../domain/submission.repository.interface';

@Injectable()
export class SubmissionService {
  private readonly logger = new Logger(SubmissionService.name);

  constructor(
    @Inject(SUBMISSION_REPOSITORY) private readonly submissionRepository: SubmissionRepository,
  ) {}

  async start(input: CreateSubmissionInput): Promise<Submission> {
    const submission = await this.submissionRepository.create(input);
    return this.submissionRepository.updateStatus(submission.id, SubmissionStatus.IN_PROGRESS);
  }

  async findById(id: string): Promise<Submission> {
    const submission = await this.submissionRepository.findById(id);
    if (!submission) {
      throw new NotFoundDomainException(notFound('Submission', id));
    }
    return submission;
  }

  async submit(id: string): Promise<Submission> {
    return this.submissionRepository.updateStatus(id, SubmissionStatus.SUBMITTED, {
      submittedAt: new Date(),
    });
  }

  listMine(userId: string): Promise<Submission[]> {
    return this.submissionRepository.listByUserId(userId);
  }

  /** Called by the verification-failed listener on a WARNING action. */
  async applyWarning(id: string): Promise<Submission> {
    const submission = await this.findById(id);
    if (submission.status === SubmissionStatus.DISQUALIFIED) {
      this.logger.warn(`Ignoring warning for already-disqualified submission ${id}`);
      return submission;
    }
    return this.submissionRepository.updateStatus(id, SubmissionStatus.WARNED, {
      warningCount: submission.warningCount + 1,
    });
  }

  /** Called by the Scoring module once a score has been recorded. */
  async markGraded(id: string): Promise<Submission> {
    await this.findById(id);
    return this.submissionRepository.updateStatus(id, SubmissionStatus.GRADED);
  }

  /** Called by the verification-failed listener on a DISQUALIFICATION action, and by the admin override endpoint. */
  async disqualify(id: string): Promise<Submission> {
    const submission = await this.findById(id);
    if (submission.status === SubmissionStatus.DISQUALIFIED) {
      return submission;
    }
    if (
      submission.status === SubmissionStatus.SUBMITTED ||
      submission.status === SubmissionStatus.GRADED
    ) {
      throw new ConflictDomainException(
        `Submission (${id}) has already ended and cannot be disqualified.`,
      );
    }
    return this.submissionRepository.updateStatus(id, SubmissionStatus.DISQUALIFIED);
  }
}
