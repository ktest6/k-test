import { Inject, Injectable } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { IdentityVerificationSession } from '../../domain/entities/identity-verification-session.entity';
import { AttemptResult } from '../../domain/enums/attempt-result.enum';
import { VerificationFailureAction } from '../../domain/enums/verification-failure-action.enum';
import { VerificationStatus } from '../../domain/enums/verification-status.enum';
import { VerificationType } from '../../domain/enums/verification-type.enum';
import {
  IdentityVerificationFailedEvent,
  IdentityVerificationSucceededEvent,
  IDENTITY_VERIFICATION_FAILED_EVENT,
  IDENTITY_VERIFICATION_SUCCEEDED_EVENT,
} from '../../domain/events/identity-verification.events';
import {
  VERIFICATION_FAILURE_POLICY,
  VerificationFailurePolicy,
} from '../../domain/policies/verification-failure-policy.interface';
import {
  IDENTITY_VERIFICATION_ATTEMPT_REPOSITORY,
  IdentityVerificationAttemptRepository,
} from '../../domain/repositories/identity-verification-attempt.repository.interface';
import {
  IDENTITY_VERIFICATION_LOG_REPOSITORY,
  IdentityVerificationLogRepository,
} from '../../domain/repositories/identity-verification-log.repository.interface';
import {
  IDENTITY_VERIFICATION_SESSION_REPOSITORY,
  IdentityVerificationSessionRepository,
} from '../../domain/repositories/identity-verification-session.repository.interface';
import { InitiateVerificationResponseDto } from '../dto/initiate-verification-response.dto';
import { VerificationLogResponseDto } from '../dto/verification-log-response.dto';
import { VerificationResultDto } from '../dto/verification-result.dto';
import { VerificationStatusResponseDto } from '../dto/verification-status-response.dto';
import { VerifyChallengeDto } from '../dto/verify-challenge.dto';
import { VerifyPeriodicDto } from '../dto/verify-periodic.dto';
import { IDENTITY_PROVIDER, IdentityProvider } from '../ports/identity-provider.port';
import { VerificationSchedulerService } from './verification-scheduler.service';

const CHALLENGE_TTL_MS = 5 * 60_000;

@Injectable()
export class IdentityVerificationService {
  constructor(
    @Inject(IDENTITY_VERIFICATION_SESSION_REPOSITORY)
    private readonly sessionRepository: IdentityVerificationSessionRepository,
    @Inject(IDENTITY_VERIFICATION_ATTEMPT_REPOSITORY)
    private readonly attemptRepository: IdentityVerificationAttemptRepository,
    @Inject(IDENTITY_VERIFICATION_LOG_REPOSITORY)
    private readonly logRepository: IdentityVerificationLogRepository,
    @Inject(IDENTITY_PROVIDER) private readonly identityProvider: IdentityProvider,
    @Inject(VERIFICATION_FAILURE_POLICY) private readonly failurePolicy: VerificationFailurePolicy,
    private readonly scheduler: VerificationSchedulerService,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  async initiatePreExam(
    submissionId: string,
    userId: string,
  ): Promise<InitiateVerificationResponseDto> {
    const { providerRef } = await this.identityProvider.initiate({ userId, submissionId });
    const expiresAt = new Date(Date.now() + CHALLENGE_TTL_MS);

    const session = await this.sessionRepository.create({
      submissionId,
      userId,
      type: VerificationType.PRE_EXAM,
      providerRef,
      expiresAt,
    });
    await this.logRepository.create({
      sessionId: session.id,
      attemptId: null,
      eventType: 'SESSION_CREATED',
      payload: { type: VerificationType.PRE_EXAM },
    });

    return { sessionId: session.id, providerRef, expiresAt };
  }

  async verifyPreExam(dto: VerifyChallengeDto, userId: string): Promise<VerificationResultDto> {
    const session = await this.sessionRepository.findById(dto.sessionId);
    if (!session) {
      throw new NotFoundDomainException(`Verification session ${dto.sessionId} not found`);
    }
    if (session.userId !== userId) {
      throw new ForbiddenDomainException('This verification session does not belong to you');
    }

    return this.completeVerification(session, dto.payload, dto.forceResult);
  }

  async verifyPeriodic(dto: VerifyPeriodicDto, userId: string): Promise<VerificationResultDto> {
    const { providerRef } = await this.identityProvider.initiate({
      userId,
      submissionId: dto.submissionId,
    });
    const expiresAt = new Date(Date.now() + CHALLENGE_TTL_MS);

    const session = await this.sessionRepository.create({
      submissionId: dto.submissionId,
      userId,
      type: VerificationType.PERIODIC,
      providerRef,
      expiresAt,
    });
    await this.logRepository.create({
      sessionId: session.id,
      attemptId: null,
      eventType: 'SESSION_CREATED',
      payload: { type: VerificationType.PERIODIC },
    });

    return this.completeVerification(session, dto.payload, dto.forceResult);
  }

  async getPeriodicStatus(submissionId: string): Promise<VerificationStatusResponseDto> {
    const latest = await this.sessionRepository.findLatestBySubmissionId(submissionId);

    if (!latest || latest.status !== VerificationStatus.VERIFIED || !latest.nextCheckAt) {
      // Never verified yet (or last check failed) — require verification now.
      return { dueNow: true, nextCheckAt: new Date().toISOString() };
    }

    return {
      dueNow: this.scheduler.isDue(latest.nextCheckAt),
      nextCheckAt: latest.nextCheckAt.toISOString(),
    };
  }

  async getLogs(submissionId: string): Promise<VerificationLogResponseDto[]> {
    const logs = await this.logRepository.findBySubmissionId(submissionId);
    return logs.map((log) => ({
      id: log.id,
      sessionId: log.sessionId,
      attemptId: log.attemptId,
      eventType: log.eventType,
      payload: log.payload,
      createdAt: log.createdAt,
    }));
  }

  private async completeVerification(
    session: IdentityVerificationSession,
    payload: Record<string, unknown> | undefined,
    forceResult: 'SUCCESS' | 'FAILED' | undefined,
  ): Promise<VerificationResultDto> {
    await this.logRepository.create({
      sessionId: session.id,
      attemptId: null,
      eventType: 'PROVIDER_CHALLENGE_SUBMITTED',
      payload: { payload: payload ?? null },
    });

    const result = await this.identityProvider.verify({
      sessionId: session.id,
      userId: session.userId,
      providerRef: session.providerRef,
      payload,
      forceResult,
    });

    const attemptResult = result.success ? AttemptResult.SUCCESS : AttemptResult.FAILED;
    const attempt = await this.attemptRepository.create({
      sessionId: session.id,
      result: attemptResult,
      method: 'MOCK',
      providerRef: result.providerRef,
    });
    await this.logRepository.create({
      sessionId: session.id,
      attemptId: attempt.id,
      eventType: 'RESULT_RECORDED',
      payload: { result: attemptResult },
    });

    if (result.success) {
      const nextCheckAt = this.scheduler.computeNextCheckAt(new Date());
      await this.sessionRepository.updateStatus(
        session.id,
        VerificationStatus.VERIFIED,
        nextCheckAt,
      );
      this.eventEmitter.emit(
        IDENTITY_VERIFICATION_SUCCEEDED_EVENT,
        new IdentityVerificationSucceededEvent(session.submissionId, session.userId, session.id),
      );
      return {
        sessionId: session.id,
        status: VerificationStatus.VERIFIED,
        action: VerificationFailureAction.NONE,
      };
    }

    await this.sessionRepository.updateStatus(session.id, VerificationStatus.FAILED);
    const consecutiveFailures = await this.attemptRepository.countConsecutiveFailures(
      session.submissionId,
    );
    const action = this.failurePolicy.decide(consecutiveFailures);
    await this.logRepository.create({
      sessionId: session.id,
      attemptId: attempt.id,
      eventType: 'FAILURE_ACTION_DECIDED',
      payload: { action, consecutiveFailures },
    });

    if (action !== VerificationFailureAction.NONE) {
      this.eventEmitter.emit(
        IDENTITY_VERIFICATION_FAILED_EVENT,
        new IdentityVerificationFailedEvent(
          session.submissionId,
          session.userId,
          session.id,
          consecutiveFailures,
          action,
        ),
      );
    }

    return {
      sessionId: session.id,
      status: VerificationStatus.FAILED,
      action,
      consecutiveFailures,
    };
  }
}
