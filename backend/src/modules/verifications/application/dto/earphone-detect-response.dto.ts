import { ApiProperty } from '@nestjs/swagger';

export class EarphoneDetectResponseDto {
  @ApiProperty({
    description:
      '양쪽 귀를 종합한 최종 이어폰 탐지 여부 — inspectionComplete가 true일 때만 신뢰할 수 있다.',
    example: false,
  })
  earphoneDetected: boolean;

  @ApiProperty({ description: '왼쪽 귀 이어폰 탐지 여부', example: false })
  leftEarDetected: boolean;

  @ApiProperty({ description: '오른쪽 귀 이어폰 탐지 여부', example: false })
  rightEarDetected: boolean;

  @ApiProperty({
    type: String,
    nullable: true,
    description: '왼쪽 귀에서 탐지된 AWS Rekognition label',
    example: null,
  })
  leftLabel: string | null;

  @ApiProperty({
    type: String,
    nullable: true,
    description: '오른쪽 귀에서 탐지된 AWS Rekognition label',
    example: null,
  })
  rightLabel: string | null;

  @ApiProperty({ description: '왼쪽 귀 이어폰 탐지 신뢰도', example: 0 })
  leftConfidence: number;

  @ApiProperty({ description: '오른쪽 귀 이어폰 탐지 신뢰도', example: 0 })
  rightConfidence: number;

  @ApiProperty({ description: '이어폰 탐지 판단 기준값', example: 45 })
  threshold: number;

  @ApiProperty({
    description:
      '양쪽 귀가 보이는 자세에서 검사가 끝났는지 여부. false면 얼굴을 더 돌려 다시 촬영해야 ' +
      '한다 — earphoneDetected 값을 이때는 신뢰할 수 없다.',
    example: true,
  })
  inspectionComplete: boolean;

  @ApiProperty({ description: '왼쪽 귀가 보이는 자세 조건을 충족했는지 여부', example: true })
  leftEarVisible: boolean;

  @ApiProperty({ description: '오른쪽 귀가 보이는 자세 조건을 충족했는지 여부', example: true })
  rightEarVisible: boolean;

  @ApiProperty({
    type: Number,
    nullable: true,
    description: '왼쪽 귀 이미지에서 측정한 얼굴 yaw(좌우 회전각). 측정 불가면 null.',
    example: 61.24,
  })
  leftYaw: number | null;

  @ApiProperty({
    type: Number,
    nullable: true,
    description: '오른쪽 귀 이미지에서 측정한 얼굴 yaw(좌우 회전각). 측정 불가면 null.',
    example: -64.15,
  })
  rightYaw: number | null;

  @ApiProperty({ description: '귀 노출 여부를 판단하는 yaw 절댓값 기준', example: 50 })
  yawThreshold: number;

  @ApiProperty({
    description:
      '이어폰 탐지 결과 안내 메시지(영어). inspectionComplete가 false면 어느 쪽 귀를 다시 ' +
      '보여줘야 하는지 안내한다.',
    example: 'No earphone was detected.',
  })
  message: string;
}
