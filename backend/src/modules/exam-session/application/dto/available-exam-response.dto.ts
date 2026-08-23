import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { SessionStatus } from '../../domain/enums/session-status.enum';

/** "지금 응시 가능한 시험" 한 줄 — 전체 회차 목록 + 이 사용자의 세션 상태. */
export class AvailableExamResponseDto {
  @ApiProperty()
  examId: string;

  @ApiProperty()
  roundName: string;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '이 회차를 시작한 적 없으면 null.',
  })
  examSessionId: string | null;

  @ApiPropertyOptional({
    enum: SessionStatus,
    nullable: true,
    description: '이 회차를 시작한 적 없으면 null.',
  })
  sessionStatus: SessionStatus | null;

  @ApiPropertyOptional({
    type: Boolean,
    nullable: true,
    description:
      '지금 이 회차를 새로 시작할 수 있는지. 이미 이 회차 세션이 있거나(재개는 SESSION-01을 ' +
      '그대로 다시 호출하면 되고 이 필드와 무관) 다른 회차가 이미 진행중(INPROGRESS)이면 false. ' +
      '비로그인이면 판단할 수 없어 null.',
  })
  canStart: boolean | null;
}
