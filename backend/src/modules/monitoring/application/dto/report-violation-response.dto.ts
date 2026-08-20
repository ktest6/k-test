import { ApiProperty } from '@nestjs/swagger';
import { SessionStatus } from '../../../exam-session/domain/enums/session-status.enum';
import { ProctoringEventResponseDto } from './proctoring-event-response.dto';

export class ReportViolationResponseDto extends ProctoringEventResponseDto {
  @ApiProperty({
    enum: SessionStatus,
    description:
      '이 위반 신고를 처리한 직후의 세션 상태. DUAL_MONITOR가 누적 2회가 되어 방금 자동 실격됐다면 ' +
      'DISQUALIFIED로 내려온다 — 프런트는 이 값만 보고 바로 결과 화면(실격 상태)으로 전환하면 되고, ' +
      '상태를 다시 조회할 필요는 없다.',
  })
  sessionStatus: SessionStatus;
}
