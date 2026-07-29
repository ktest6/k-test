import { Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { Score } from '../../domain/entities/score.entity';
import { RecordScoreInput, ScoringRepository } from '../../domain/scoring.repository.interface';

const TABLE = 'scores';

interface ScoreRow {
  id: string;
  submission_id: string;
  total_score: number;
  max_score: number;
  graded_at: string;
}

function toDomain(row: ScoreRow): Score {
  return new Score(
    row.id,
    row.submission_id,
    row.total_score,
    row.max_score,
    new Date(row.graded_at),
  );
}

@Injectable()
export class SupabaseScoringRepository implements ScoringRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async record(input: RecordScoreInput): Promise<Score> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .upsert(
        {
          submission_id: input.submissionId,
          total_score: input.totalScore,
          max_score: input.maxScore,
          graded_at: new Date().toISOString(),
        },
        { onConflict: 'submission_id' },
      )
      .select()
      .single<ScoreRow>();

    if (error || !data) {
      throw new NotFoundDomainException(error?.message ?? 'Failed to record score');
    }
    return toDomain(data);
  }

  async findBySubmissionId(submissionId: string): Promise<Score | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('submission_id', submissionId)
      .maybeSingle<ScoreRow>();
    return data ? toDomain(data) : null;
  }
}
