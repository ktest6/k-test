import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { ExamApplication } from '../../domain/entities/exam-application.entity';
import {
  CreateExamApplicationInput,
  ExamApplicationRepository,
} from '../../domain/exam-application.repository.interface';

const TABLE = 'tb_exam_application';

interface ExamApplicationRow {
  exam_application_id: number;
  exam_id: number;
  user_id: number;
  applied_at: string;
}

function toDomain(row: ExamApplicationRow): ExamApplication {
  return new ExamApplication(
    String(row.exam_application_id),
    String(row.exam_id),
    String(row.user_id),
    new Date(row.applied_at),
  );
}

@Injectable()
export class SupabaseExamApplicationRepository implements ExamApplicationRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateExamApplicationInput): Promise<ExamApplication> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({ exam_id: Number(input.examId), user_id: Number(input.userId) })
      .select()
      .single<ExamApplicationRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '회차 신청에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findActiveByExamAndUser(examId: string, userId: string): Promise<ExamApplication | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_id', Number(examId))
      .eq('user_id', Number(userId))
      .is('deleted_at', null)
      .maybeSingle<ExamApplicationRow>();
    return data ? toDomain(data) : null;
  }

  async cancel(applicationId: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    await client
      .from(TABLE)
      .update({ deleted_at: new Date().toISOString() })
      .eq('exam_application_id', Number(applicationId));
  }

  async countActiveByExam(examId: string): Promise<number> {
    const client = this.supabaseService.getAdminClient();
    const { count } = await client
      .from(TABLE)
      .select('*', { count: 'exact', head: true })
      .eq('exam_id', Number(examId))
      .is('deleted_at', null);
    return count ?? 0;
  }
}
