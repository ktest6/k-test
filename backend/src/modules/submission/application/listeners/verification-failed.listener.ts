import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { VerificationFailureAction } from '../../../verifications/domain/enums/verification-failure-action.enum';
import {
  VerificationFailedEvent,
  VERIFICATION_FAILED_EVENT,
} from '../../../verifications/domain/events/verification-failed.event';
import { SubmissionService } from '../services/submission.service';

/**
 * Reacts to Verifications' failure events instead of being called directly
 * — Verifications never imports Submission, so this is the only place that
 * has to change if the policy → action mapping changes.
 */
@Injectable()
export class VerificationFailedListener {
  private readonly logger = new Logger(VerificationFailedListener.name);

  constructor(private readonly submissionService: SubmissionService) {}

  @OnEvent(VERIFICATION_FAILED_EVENT)
  async handle(event: VerificationFailedEvent): Promise<void> {
    switch (event.action) {
      case VerificationFailureAction.WARNING:
        await this.submissionService.applyWarning(event.submissionId);
        break;
      case VerificationFailureAction.DISQUALIFICATION:
        await this.submissionService.disqualify(event.submissionId);
        break;
      case VerificationFailureAction.NONE:
        break;
      default:
        this.logger.warn(`Unhandled verification failure action: ${String(event.action)}`);
    }
  }
}
