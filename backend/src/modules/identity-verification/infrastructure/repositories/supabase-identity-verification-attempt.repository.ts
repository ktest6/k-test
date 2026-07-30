import { Injectable } from '@nestjs/common';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { IdentityVerificationAttempt } from '../../domain/entities/identity-verification-attempt.entity';
import { AttemptResult } from '../../domain/enums/attempt-result.enum';
import {
  CreateAttemptInput,
  IdentityVerificationAttemptRepository,
} from '../../domain/repositories/identity-verification-attempt.repository.interface';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';

const TABLE = 'identity_verification_attempts';

interface AttemptRow {
  id: string;
  session_id: string;
  result: AttemptResult;
  method: string;
  provider_ref: string | null;
  created_at: string;
}

function toDomain(row: AttemptRow): IdentityVerificationAttempt {
  return new IdentityVerificationAttempt(
    row.id,
    row.session_id,
    row.result,
    row.method,
    row.provider_ref,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseIdentityVerificationAttemptRepository implements IdentityVerificationAttemptRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateAttemptInput): Promise<IdentityVerificationAttempt> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        session_id: input.sessionId,
        result: input.result,
        method: input.method,
        provider_ref: input.providerRef,
      })
      .select()
      .single<AttemptRow>();

    if (error || !data) {
      throw new NotFoundDomainException(error?.message ?? '본인인증 시도 기록에 실패했습니다.');
    }
    return toDomain(data);
  }

  async countConsecutiveFailures(submissionId: string): Promise<number> {
    const attempts = await this.findAttemptsForSubmission(submissionId);

    let count = 0;
    for (const attempt of attempts) {
      if (attempt.result !== AttemptResult.FAILED) {
        break;
      }
      count += 1;
    }
    return count;
  }

  async findLatestSuccessAt(submissionId: string): Promise<Date | null> {
    const attempts = await this.findAttemptsForSubmission(submissionId);
    const latestSuccess = attempts.find((attempt) => attempt.result === AttemptResult.SUCCESS);
    return latestSuccess ? latestSuccess.createdAt : null;
  }

  /** Attempts across every session belonging to this submission, most recent first. */
  private async findAttemptsForSubmission(
    submissionId: string,
  ): Promise<IdentityVerificationAttempt[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*, identity_verification_sessions!inner(submission_id)')
      .eq('identity_verification_sessions.submission_id', submissionId)
      .order('created_at', { ascending: false })
      .returns<AttemptRow[]>();

    return (data ?? []).map(toDomain);
  }
}
