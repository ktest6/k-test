import { Module } from '@nestjs/common';
import { VERIFICATION_FAILURE_POLICY } from './domain/policies/verification-failure-policy.interface';
import { IDENTITY_VERIFICATION_ATTEMPT_REPOSITORY } from './domain/repositories/identity-verification-attempt.repository.interface';
import { IDENTITY_VERIFICATION_LOG_REPOSITORY } from './domain/repositories/identity-verification-log.repository.interface';
import { IDENTITY_VERIFICATION_SESSION_REPOSITORY } from './domain/repositories/identity-verification-session.repository.interface';
import { IdentityVerificationService } from './application/services/identity-verification.service';
import { VerificationSchedulerService } from './application/services/verification-scheduler.service';
import { IDENTITY_PROVIDER } from './application/ports/identity-provider.port';
import { DefaultVerificationFailurePolicy } from './infrastructure/policies/default-verification-failure-policy';
import { MockIdentityProviderAdapter } from './infrastructure/providers/mock-identity-provider.adapter';
import { SupabaseIdentityVerificationAttemptRepository } from './infrastructure/repositories/supabase-identity-verification-attempt.repository';
import { SupabaseIdentityVerificationLogRepository } from './infrastructure/repositories/supabase-identity-verification-log.repository';
import { SupabaseIdentityVerificationSessionRepository } from './infrastructure/repositories/supabase-identity-verification-session.repository';
import { IdentityVerificationController } from './presentation/identity-verification.controller';

@Module({
  controllers: [IdentityVerificationController],
  providers: [
    IdentityVerificationService,
    VerificationSchedulerService,
    {
      provide: IDENTITY_VERIFICATION_SESSION_REPOSITORY,
      useClass: SupabaseIdentityVerificationSessionRepository,
    },
    {
      provide: IDENTITY_VERIFICATION_ATTEMPT_REPOSITORY,
      useClass: SupabaseIdentityVerificationAttemptRepository,
    },
    {
      provide: IDENTITY_VERIFICATION_LOG_REPOSITORY,
      useClass: SupabaseIdentityVerificationLogRepository,
    },
    { provide: IDENTITY_PROVIDER, useClass: MockIdentityProviderAdapter },
    { provide: VERIFICATION_FAILURE_POLICY, useClass: DefaultVerificationFailurePolicy },
  ],
})
export class IdentityVerificationModule {}
