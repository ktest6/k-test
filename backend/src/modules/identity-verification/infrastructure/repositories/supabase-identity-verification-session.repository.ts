import { Injectable } from '@nestjs/common';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { IdentityVerificationSession } from '../../domain/entities/identity-verification-session.entity';
import { VerificationStatus } from '../../domain/enums/verification-status.enum';
import { VerificationType } from '../../domain/enums/verification-type.enum';
import {
  CreateSessionInput,
  IdentityVerificationSessionRepository,
} from '../../domain/repositories/identity-verification-session.repository.interface';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';

const TABLE = 'identity_verification_sessions';

interface SessionRow {
  id: string;
  submission_id: string;
  user_id: string;
  type: VerificationType;
  status: VerificationStatus;
  provider_ref: string | null;
  created_at: string;
  expires_at: string;
  next_check_at: string | null;
}

function toDomain(row: SessionRow): IdentityVerificationSession {
  return new IdentityVerificationSession(
    row.id,
    row.submission_id,
    row.user_id,
    row.type,
    row.status,
    row.provider_ref,
    new Date(row.created_at),
    new Date(row.expires_at),
    row.next_check_at ? new Date(row.next_check_at) : null,
  );
}

@Injectable()
export class SupabaseIdentityVerificationSessionRepository implements IdentityVerificationSessionRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateSessionInput): Promise<IdentityVerificationSession> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        submission_id: input.submissionId,
        user_id: input.userId,
        type: input.type,
        status: VerificationStatus.PENDING,
        provider_ref: input.providerRef,
        expires_at: input.expiresAt.toISOString(),
      })
      .select()
      .single<SessionRow>();

    if (error || !data) {
      throw new NotFoundDomainException(error?.message ?? '본인인증 세션 생성에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<IdentityVerificationSession | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client.from(TABLE).select('*').eq('id', id).maybeSingle<SessionRow>();
    return data ? toDomain(data) : null;
  }

  async updateStatus(
    id: string,
    status: VerificationStatus,
    nextCheckAt?: Date | null,
  ): Promise<IdentityVerificationSession> {
    const client = this.supabaseService.getAdminClient();
    const update: Record<string, unknown> = { status };
    if (nextCheckAt !== undefined) {
      update.next_check_at = nextCheckAt ? nextCheckAt.toISOString() : null;
    }

    const { data, error } = await client
      .from(TABLE)
      .update(update)
      .eq('id', id)
      .select()
      .single<SessionRow>();

    if (error || !data) {
      throw new NotFoundDomainException(`본인인증 세션(${id})을 찾을 수 없습니다.`);
    }
    return toDomain(data);
  }

  async findLatestBySubmissionId(
    submissionId: string,
  ): Promise<IdentityVerificationSession | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('submission_id', submissionId)
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle<SessionRow>();
    return data ? toDomain(data) : null;
  }
}
