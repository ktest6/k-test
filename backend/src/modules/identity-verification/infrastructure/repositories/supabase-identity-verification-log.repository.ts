import { Injectable } from '@nestjs/common';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { IdentityVerificationLog } from '../../domain/entities/identity-verification-log.entity';
import {
  CreateLogInput,
  IdentityVerificationLogRepository,
} from '../../domain/repositories/identity-verification-log.repository.interface';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';

const TABLE = 'identity_verification_logs';

interface LogRow {
  id: string;
  session_id: string;
  attempt_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

function toDomain(row: LogRow): IdentityVerificationLog {
  return new IdentityVerificationLog(
    row.id,
    row.session_id,
    row.attempt_id,
    row.event_type,
    row.payload,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseIdentityVerificationLogRepository implements IdentityVerificationLogRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateLogInput): Promise<IdentityVerificationLog> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        session_id: input.sessionId,
        attempt_id: input.attemptId,
        event_type: input.eventType,
        payload: input.payload,
      })
      .select()
      .single<LogRow>();

    if (error || !data) {
      throw new NotFoundDomainException(error?.message ?? 'Failed to write verification log');
    }
    return toDomain(data);
  }

  async findBySubmissionId(submissionId: string): Promise<IdentityVerificationLog[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*, identity_verification_sessions!inner(submission_id)')
      .eq('identity_verification_sessions.submission_id', submissionId)
      .order('created_at', { ascending: false })
      .returns<LogRow[]>();

    return (data ?? []).map(toDomain);
  }
}
