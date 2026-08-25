import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { ExamResult } from '../../domain/entities/exam-result.entity';
import {
  ExamResultRepository,
  RecordExamResultInput,
} from '../../domain/exam-result.repository.interface';

const TABLE = 'tb_exam_results';

interface ExamResultRow {
  exam_results_id: number;
  exam_session_id: number;
  final_grade: string;
  percentile: number | null;
  domain_scores: Record<string, unknown> | null;
  cross_validation_signals: Record<string, unknown> | null;
  raw_response: Record<string, unknown>;
  created_at: string;
}

function toDomain(row: ExamResultRow): ExamResult {
  return new ExamResult(
    String(row.exam_results_id),
    String(row.exam_session_id),
    row.final_grade,
    row.percentile,
    row.domain_scores,
    row.cross_validation_signals,
    row.raw_response,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseExamResultRepository implements ExamResultRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async record(input: RecordExamResultInput): Promise<ExamResult> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .upsert(
        {
          exam_session_id: Number(input.examSessionId),
          final_grade: input.finalGrade,
          percentile: input.percentile,
          domain_scores: input.domainScores,
          cross_validation_signals: input.crossValidationSignals,
          raw_response: input.rawResponse,
          modified_at: new Date().toISOString(),
        },
        { onConflict: 'exam_session_id' },
      )
      .select()
      .single<ExamResultRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '최종 결과 저장에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<ExamResult | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_results_id', Number(id))
      .is('deleted_at', null)
      .maybeSingle<ExamResultRow>();
    return data ? toDomain(data) : null;
  }

  async findByExamSessionId(examSessionId: string): Promise<ExamResult | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_session_id', Number(examSessionId))
      .is('deleted_at', null)
      .maybeSingle<ExamResultRow>();
    return data ? toDomain(data) : null;
  }

  async listExamSessionIdsWithResult(): Promise<string[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client.from(TABLE).select('exam_session_id').is('deleted_at', null);
    return (data ?? []).map((row: { exam_session_id: number }) => String(row.exam_session_id));
  }
}
