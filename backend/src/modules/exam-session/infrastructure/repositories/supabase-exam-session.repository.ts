import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { operationFailed } from '../../../../common/exceptions/error-messages';
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
      .insert({ user_id: Number(input.userId) })
      .select()
      .single<ExamSessionRow>();

    if (error || !data) {
      throw new ConflictDomainException(
        error?.message ?? operationFailed('create the exam session'),
      );
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

  async findInProgressByUser(userId: string): Promise<ExamSession | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('user_id', Number(userId))
      .eq('status', SessionStatus.INPROGRESS)
      .is('deleted_at', null)
      .maybeSingle<ExamSessionRow>();
    return data ? toDomain(data) : null;
  }

  async findAllByUser(userId: string): Promise<ExamSession[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('user_id', Number(userId))
      .is('deleted_at', null)
      .order('created_at', { ascending: false })
      .returns<ExamSessionRow[]>();
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
      throw new ConflictDomainException(
        error?.message ?? operationFailed('update the exam session'),
      );
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
      throw new ConflictDomainException(
        error?.message ?? operationFailed('update the exam session'),
      );
    }
    return toDomain(data);
  }

  async markSubmitted(id: string): Promise<ExamSession> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .update({ status: SessionStatus.SUBMITTED, submitted_at: new Date().toISOString() })
      .eq('exam_session_id', Number(id))
      .select()
      .single<ExamSessionRow>();

    if (error || !data) {
      throw new ConflictDomainException(
        error?.message ?? operationFailed('update the exam session'),
      );
    }
    return toDomain(data);
  }

  async findAllSubmitted(): Promise<ExamSession[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('status', SessionStatus.SUBMITTED)
      .is('deleted_at', null);
    return (data ?? []).map((row: ExamSessionRow) => toDomain(row));
  }

  async findAllInProgress(): Promise<ExamSession[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('status', SessionStatus.INPROGRESS)
      .is('deleted_at', null);
    return (data ?? []).map((row: ExamSessionRow) => toDomain(row));
  }
}
