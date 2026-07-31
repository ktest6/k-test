import { ApiProperty } from '@nestjs/swagger';

export class VerifyIdCardResponseDto {
  @ApiProperty({
    description: 'FastAPI 대조 결과 — 신분증/얼굴이 동일인으로 판정됐는지',
    example: true,
  })
  matched: boolean;

  @ApiProperty({
    description: '대조 신뢰도 (0~1). FastAPI의 similarity(0~100)를 100으로 나눈 값',
    example: 0.999,
  })
  confidence: number;
}
