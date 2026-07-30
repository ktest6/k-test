import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { Exam } from '../../domain/entities/exam.entity';
import { CreateExamInput, ExamRepository } from '../../domain/exam.repository.interface';

const TABLE = 'tb_exam';

interface ExamRow {
  exam_id: number;
  round_name: string;
  open_at: string;
  close_at: string;
  capacity: number;
  created_at: string;
}

function toDomain(row: ExamRow): Exam {
  return new Exam(
    String(row.exam_id),
    row.round_name,
    new Date(row.open_at),
    new Date(row.close_at),
    row.capacity,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseExamRepository implements ExamRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateExamInput): Promise<Exam> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        round_name: input.roundName,
        open_at: input.openAt.toISOString(),
        close_at: input.closeAt.toISOString(),
        capacity: input.capacity,
      })
      .select()
      .single<ExamRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '시험 회차 생성에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<Exam | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_id', Number(id))
      .is('deleted_at', null)
      .maybeSingle<ExamRow>();
    return data ? toDomain(data) : null;
  }

  async list(): Promise<Exam[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .is('deleted_at', null)
      .order('open_at', { ascending: false })
      .returns<ExamRow[]>();
    return (data ?? []).map(toDomain);
  }
}
