import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { ExamSession } from '../../domain/entities/exam-session.entity';
import { SessionStatus } from '../../domain/enums/session-status.enum';
import {
  CreateExamSessionInput,
  ExamSessionRepository,
} from '../../domain/exam-session.repository.interface';

const TABLE = 'tb_exam_session';

interface ExamSessionRow {
  exam_session_id: number;
  exam_id: number;
  user_id: number;
  status: SessionStatus;
  resume_count: number;
  started_at: string;
  current_question_id: number | null;
  last_saved_at: string | null;
  submitted_at: string | null;
  created_at: string;
}

function toDomain(row: ExamSessionRow): ExamSession {
  return new ExamSession(
    String(row.exam_session_id),
    String(row.exam_id),
    String(row.user_id),
    row.status,
    row.resume_count,
    new Date(row.started_at),
    row.current_question_id !== null ? String(row.current_question_id) : null,
    row.last_saved_at ? new Date(row.last_saved_at) : null,
    row.submitted_at ? new Date(row.submitted_at) : null,
    new Date(row.created_at),
  );
}

@Injectable()
export class SupabaseExamSessionRepository implements ExamSessionRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateExamSessionInput): Promise<ExamSession> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({ exam_id: Number(input.examId), user_id: Number(input.userId) })
      .select()
      .single<ExamSessionRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '응시 세션 생성에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findById(id: string): Promise<ExamSession | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_session_id', Number(id))
      .is('deleted_at', null)
      .maybeSingle<ExamSessionRow>();
    return data ? toDomain(data) : null;
  }

  async findByUserAndExam(userId: string, examId: string): Promise<ExamSession | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('user_id', Number(userId))
      .eq('exam_id', Number(examId))
      .is('deleted_at', null)
      .maybeSingle<ExamSessionRow>();
    return data ? toDomain(data) : null;
  }

  async findAllInProgress(): Promise<ExamSession[]> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .select('*')
      .eq('status', SessionStatus.INPROGRESS)
      .is('deleted_at', null);

    if (error) {
      throw new ConflictDomainException(error.message ?? '진행중 세션 조회에 실패했습니다.');
    }
    return (data ?? []).map(toDomain);
  }

  async updateResumeCount(id: string, resumeCount: number): Promise<ExamSession> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .update({ resume_count: resumeCount })
      .eq('exam_session_id', Number(id))
      .select()
      .single<ExamSessionRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '응시 세션 갱신에 실패했습니다.');
    }
    return toDomain(data);
  }

  async updateStatus(id: string, status: SessionStatus): Promise<ExamSession> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .update({ status })
      .eq('exam_session_id', Number(id))
      .select()
      .single<ExamSessionRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '응시 세션 갱신에 실패했습니다.');
    }
    return toDomain(data);
  }
}
