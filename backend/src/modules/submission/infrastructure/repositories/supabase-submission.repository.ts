import { Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { Submission } from '../../domain/entities/submission.entity';
import { SubmissionStatus } from '../../domain/enums/submission-status.enum';
import {
  CreateSubmissionInput,
  SubmissionRepository,
} from '../../domain/submission.repository.interface';

const TABLE = 'submissions';

interface SubmissionRow {
  id: string;
  test_id: string;
  user_id: string;
  status: SubmissionStatus;
  warning_count: number;
  started_at: string;
  submitted_at: string | null;
  created_at: string;
}

function toDomain(row: SubmissionRow): Submission {
  return new Submission(
    row.id,
    row.test_id,
    row.user_id,
    row.status,
    row.warning_count,
    new Date(row.started_at),
    row.submitted_at ? new Date(row.submitted_at) : null,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseSubmissionRepository implements SubmissionRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateSubmissionInput): Promise<Submission> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        test_id: input.testId,
        user_id: input.userId,
        status: SubmissionStatus.NOT_STARTED,
        warning_count: 0,
        started_at: new Date().toISOString(),
      })
      .select()
      .single<SubmissionRow>();

    if (error || !data) {
      throw new NotFoundDomainException(error?.message ?? 'Failed to create submission');
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<Submission | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client.from(TABLE).select('*').eq('id', id).maybeSingle<SubmissionRow>();
    return data ? toDomain(data) : null;
  }

  async updateStatus(
    id: string,
    status: SubmissionStatus,
    extra?: { warningCount?: number; submittedAt?: Date },
  ): Promise<Submission> {
    const client = this.supabaseService.getAdminClient();
    const update: Record<string, unknown> = { status };
    if (extra?.warningCount !== undefined) update.warning_count = extra.warningCount;
    if (extra?.submittedAt !== undefined) update.submitted_at = extra.submittedAt.toISOString();

    const { data, error } = await client
      .from(TABLE)
      .update(update)
      .eq('id', id)
      .select()
      .single<SubmissionRow>();

    if (error || !data) {
      throw new NotFoundDomainException(`Submission ${id} not found`);
    }
    return toDomain(data);
  }

  async listByUserId(userId: string): Promise<Submission[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('user_id', userId)
      .returns<SubmissionRow[]>();
    return (data ?? []).map(toDomain);
  }
}
