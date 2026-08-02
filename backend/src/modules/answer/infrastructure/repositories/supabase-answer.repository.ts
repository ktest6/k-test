import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { AnswerRepository, SaveAnswerInput } from '../../domain/answer.repository.interface';
import { Answer } from '../../domain/entities/answer.entity';
import { AnswerStatus } from '../../domain/enums/answer-status.enum';
import { AnswerType } from '../../domain/enums/answer-type.enum';

const TABLE = 'tb_answers';

interface AnswerRow {
  answer_id: number;
  exam_session_id: number;
  question_id: number;
  type: AnswerType;
  content_text: string | null;
  audio_file_url: string | null;
  status: AnswerStatus;
  modified_at: string;
}

function toDomain(row: AnswerRow): Answer {
  return new Answer(
    String(row.answer_id),
    String(row.exam_session_id),
    String(row.question_id),
    row.type,
    row.content_text,
    row.audio_file_url,
    row.status,
    new Date(row.modified_at),
  );
}

@Injectable()
export class SupabaseAnswerRepository implements AnswerRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async save(input: SaveAnswerInput): Promise<Answer> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .upsert(
        {
          exam_session_id: Number(input.examSessionId),
          question_id: Number(input.questionId),
          type: input.type,
          content_text: input.contentText,
          audio_file_url: input.audioFileUrl,
          status: AnswerStatus.DRAFT,
          modified_at: new Date().toISOString(),
        },
        { onConflict: 'exam_session_id,question_id' },
      )
      .select()
      .single<AnswerRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '답안 저장에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findBySessionAndQuestion(
    examSessionId: string,
    questionId: string,
  ): Promise<Answer | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_session_id', Number(examSessionId))
      .eq('question_id', Number(questionId))
      .is('deleted_at', null)
      .maybeSingle<AnswerRow>();
    return data ? toDomain(data) : null;
  }
}
