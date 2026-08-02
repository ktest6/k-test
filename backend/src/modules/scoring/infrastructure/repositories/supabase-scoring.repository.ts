import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { Score } from '../../domain/entities/score.entity';
import { RecordScoreInput, ScoringRepository } from '../../domain/scoring.repository.interface';

const TABLE = 'tb_score';

interface ScoreRow {
  score_id: number;
  answer_id: number;
  raw_response: Record<string, unknown>;
  created_at: string;
}

function toDomain(row: ScoreRow): Score {
  return new Score(
    String(row.score_id),
    String(row.answer_id),
    row.raw_response,
    new Date(row.created_at),
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
        { answer_id: Number(input.answerId), raw_response: input.rawResponse },
        { onConflict: 'answer_id' },
      )
      .select()
      .single<ScoreRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '채점 결과 등록에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findByAnswerId(answerId: string): Promise<Score | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('answer_id', Number(answerId))
      .is('deleted_at', null)
      .maybeSingle<ScoreRow>();
    return data ? toDomain(data) : null;
  }
}
