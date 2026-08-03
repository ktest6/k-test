import { ApiProperty } from '@nestjs/swagger';

export class ProctoringEventResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty({
    description:
      '모니터링 서비스가 준 이벤트 타입 (예: FACE_OUT_OF_FRAME, EYE_GAZE_AWAY, PHONE_DETECTED)',
  })
  eventType: string;

  @ApiProperty({ enum: ['LOW', 'MEDIUM', 'HIGH'] })
  severity: string;

  @ApiProperty({ type: Object, description: '모니터링 서비스가 준 해당 이벤트의 상세 정보' })
  meta: Record<string, unknown>;

  @ApiProperty()
  createdAt: Date;
}
