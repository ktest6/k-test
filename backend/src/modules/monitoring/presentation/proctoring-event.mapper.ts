import { ProctoringEvent } from '../domain/entities/proctoring-event.entity';
import { ProctoringEventResponseDto } from '../application/dto/proctoring-event-response.dto';

export function toEventDto(event: ProctoringEvent): ProctoringEventResponseDto {
  return {
    id: event.id,
    eventType: event.eventType,
    severity: event.severity,
    meta: event.meta,
    createdAt: event.createdAt,
    snapshotPath: event.snapshotPath,
  };
}
