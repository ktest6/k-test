import { ProctoringEvent, ProctoringSeverity } from './entities/proctoring-event.entity';

export interface CreateProctoringEventInput {
  examSessionId: string;
  eventType: string;
  severity: ProctoringSeverity;
  meta: Record<string, unknown>;
  snapshotPath?: string | null;
}

export const PROCTORING_EVENT_REPOSITORY = Symbol('PROCTORING_EVENT_REPOSITORY');

export interface ProctoringEventRepository {
  create(input: CreateProctoringEventInput): Promise<ProctoringEvent>;
  findByExamSessionId(examSessionId: string): Promise<ProctoringEvent[]>;
}
