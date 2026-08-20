import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { ProctoringEvent, ProctoringSeverity } from '../../domain/entities/proctoring-event.entity';
import {
  CreateProctoringEventInput,
  ProctoringEventRepository,
} from '../../domain/proctoring-event.repository.interface';

const TABLE = 'tb_proctoring_events';

interface ProctoringEventRow {
  proctoring_events_id: number;
  exam_session_id: number;
  event_type: string;
  severity: ProctoringSeverity;
  meta: Record<string, unknown>;
  created_at: string;
  snapshot_path: string | null;
}

function toDomain(row: ProctoringEventRow): ProctoringEvent {
  return new ProctoringEvent(
    String(row.proctoring_events_id),
    String(row.exam_session_id),
    row.event_type,
    row.severity,
    row.meta,
    new Date(row.created_at),
    row.snapshot_path,
  );
}

@Injectable()
export class SupabaseProctoringEventRepository implements ProctoringEventRepository {
  constructor(private readonly supabaseService: SupabaseService) {}

  async create(input: CreateProctoringEventInput): Promise<ProctoringEvent> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client
      .from(TABLE)
      .insert({
        exam_session_id: Number(input.examSessionId),
        event_type: input.eventType,
        severity: input.severity,
        meta: input.meta,
        snapshot_path: input.snapshotPath ?? null,
      })
      .select()
      .single<ProctoringEventRow>();

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '모니터링 이벤트 기록에 실패했습니다.');
    }
    return toDomain(data);
  }

  async findByExamSessionId(examSessionId: string): Promise<ProctoringEvent[]> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('exam_session_id', Number(examSessionId))
      .is('deleted_at', null)
      .order('created_at', { ascending: false })
      .returns<ProctoringEventRow[]>();

    return (data ?? []).map(toDomain);
  }
}
