import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { SkippedQuestion } from '../../domain/entities/skipped-question.entity';
import { SkippedQuestionRepository } from '../../domain/skipped-question.repository.interface';

const TABLE = 'tb_skipped_questions';

interface SkippedQuestionRow {
  id: string;
  exam_session_id: number;
  question_id: number;
  skipped_at: string;
}

function toDomain(row: SkippedQuestionRow): SkippedQuestion {
  return new SkippedQuestion(
    row.id,
    String(row.exam_session_id),
    String(row.question_id),
    new Date(row.skipped_at),
  );
}

@Injectable()
export class SupabaseSkippedQuestionRepository implements SkippedQuestionRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(examSessionId: string, questionId: string): Promise<SkippedQuestion> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .upsert(
        { exam_session_id: Number(examSessionId), question_id: Number(questionId) },
        { onConflict: 'exam_session_id,question_id' },
      )
      .select()
      .single<SkippedQuestionRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '문항 건너뛰기 저장에 실패했습니다.');
    }
    return toDomain(data);
  }

  async listSkippedQuestionIds(examSessionId: string): Promise<string[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('question_id')
      .eq('exam_session_id', Number(examSessionId));
    return (data ?? []).map((row: { question_id: number }) => String(row.question_id));
  }

  async deleteBySessionAndQuestion(examSessionId: string, questionId: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client
      .from(TABLE)
      .delete()
      .eq('exam_session_id', Number(examSessionId))
      .eq('question_id', Number(questionId));
  }
}
