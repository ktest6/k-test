import { ApiProperty } from '@nestjs/swagger';

export class EarphoneDetectResponseDto {
  @ApiProperty({
    description: '양쪽 귀를 종합한 최종 이어폰 탐지 여부 — true면 시험 시작 불가',
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

  @ApiProperty({ description: '이어폰 탐지 결과 메시지', example: '이어폰이 탐지되지 않았습니다.' })
  message: string;
}
