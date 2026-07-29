import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { VerificationFailureAction } from '../../../identity-verification/domain/enums/verification-failure-action.enum';
import {
  IdentityVerificationFailedEvent,
  IDENTITY_VERIFICATION_FAILED_EVENT,
} from '../../../identity-verification/domain/events/identity-verification.events';
import { SubmissionService } from '../services/submission.service';

/**
 * Reacts to Identity Verification's failure events instead of being called
 * directly — Identity Verification never imports Submission, so this is the
 * only place that has to change if the policy → action mapping changes.
 */
@Injectable()
export class IdentityVerificationFailedListener {
  private readonly logger = new Logger(IdentityVerificationFailedListener.name);

  constructor(private readonly submissionService: SubmissionService) {}

  @OnEvent(IDENTITY_VERIFICATION_FAILED_EVENT)
  async handle(event: IdentityVerificationFailedEvent): Promise<void> {
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
