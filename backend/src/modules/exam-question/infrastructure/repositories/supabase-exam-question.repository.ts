import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { ExamQuestion } from '../../domain/entities/exam-question.entity';
import {
  CreateExamQuestionInput,
  ExamQuestionRepository,
} from '../../domain/exam-question.repository.interface';

const TABLE = 'tb_exam_question';

interface ExamQuestionRow {
  exam_question_id: number;
  exam_id: number;
  question_id: number;
  assigned_by: number | null;
  created_at: string;
}

function toDomain(row: ExamQuestionRow): ExamQuestion {
  return new ExamQuestion(
    String(row.exam_question_id),
    String(row.exam_id),
    String(row.question_id),
    row.assigned_by !== null ? String(row.assigned_by) : null,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseExamQuestionRepository implements ExamQuestionRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateExamQuestionInput): Promise<ExamQuestion> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        exam_id: Number(input.examId),
        question_id: Number(input.questionId),
        assigned_by: input.assignedBy !== null ? Number(input.assignedBy) : null,
      })
      .select()
      .single<ExamQuestionRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '문항 배정에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findActiveByExamAndQuestion(
    examId: string,
    questionId: string,
  ): Promise<ExamQuestion | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_id', Number(examId))
      .eq('question_id', Number(questionId))
      .is('deleted_at', null)
      .maybeSingle<ExamQuestionRow>();
    return data ? toDomain(data) : null;
  }

  async findActiveByExam(examId: string): Promise<ExamQuestion[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_id', Number(examId))
      .is('deleted_at', null)
      .order('created_at', { ascending: true })
      .returns<ExamQuestionRow[]>();
    return (data ?? []).map(toDomain);
  }

  async unassign(examQuestionId: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client
      .from(TABLE)
      .update({ deleted_at: new Date().toISOString() })
      .eq('exam_question_id', Number(examQuestionId));
  }
}
