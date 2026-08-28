import { ApiProperty } from '@nestjs/swagger';
import { ProctoringEventResponseDto } from './proctoring-event-response.dto';

export class MonitoringAnalyzeResponseDto {
  @ApiProperty({
    enum: ['NORMAL', 'LOW', 'MEDIUM', 'HIGH'],
    description: '이번 프레임의 최종 위험도',
  })
  severity: string;

  @ApiProperty({
    enum: ['NONE', 'RECORD_EVENT', 'CREATE_CLIP'],
    description: '모니터링 서비스의 처리 판단',
  })
  decision: string;

  @ApiProperty({
    description: '영상 클립 생성이 필요한 상황인지 — 클립 업로드는 아직 별도 구현 안 됨',
  })
  createClip: boolean;

  @ApiProperty({ description: '이번 프레임에서 탐지된 의심 행동 개수' })
  eventCount: number;

  @ApiProperty({
    type: [ProctoringEventResponseDto],
    description: 'tb_proctoring_events에 실제로 저장된 이벤트 목록',
  })
  recordedEvents: ProctoringEventResponseDto[];

  @ApiProperty({ description: '이번 요청에서 동일인 검사(run_identity_check)를 요청했는지' })
  identityCheckRequested: boolean;

  @ApiProperty({
    description:
      '동일인 검사가 실제로 실행됐는지. requested가 true인데 이 값이 false면(얼굴 0명 또는 ' +
      '여러 명 등으로 실행 불가) 다음 프레임 요청에도 runIdentityCheck:true를 다시 보내야 한다.',
  })
  identityCheckExecuted: boolean;
}
