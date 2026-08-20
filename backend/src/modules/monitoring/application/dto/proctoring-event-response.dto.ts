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

  @ApiProperty({
    type: String,
    nullable: true,
    description:
      'Storage(proctoring-snapshots, 비공개 버킷) 상 이 이벤트가 감지된 웹캠 프레임 경로. 스냅샷 업로드에 실패했으면 null.',
    example: null,
  })
  snapshotPath: string | null;
}
