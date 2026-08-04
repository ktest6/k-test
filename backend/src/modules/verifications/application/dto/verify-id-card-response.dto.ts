import { ApiProperty } from '@nestjs/swagger';

export class VerifyIdCardResponseDto {
  @ApiProperty({
    description: 'FastAPI 대조 결과 — 최종 본인인증 성공 여부(얼굴 대조 + 신청 정보 대조 종합)',
    example: true,
  })
  matched: boolean;

  @ApiProperty({
    description: '대조 신뢰도 (0~1). FastAPI의 similarity(0~100)를 100으로 나눈 값',
    example: 0.924,
  })
  confidence: number;

  @ApiProperty({ description: '얼굴만 놓고 봤을 때 대조 성공 여부', example: true })
  faceVerified: boolean;

  @ApiProperty({ description: '얼굴 유사도 (0~100)', example: 92.4 })
  similarity: number;

  @ApiProperty({ description: '얼굴 비교 기준값', example: 80 })
  threshold: number;

  @ApiProperty({ description: '일치한 얼굴 수', example: 1 })
  matchedFaceCount: number;

  @ApiProperty({ description: '불일치한 얼굴 수', example: 0 })
  unmatchedFaceCount: number;

  @ApiProperty({
    description: '신청 정보(이름/생년월일 등)와 신분증 인식 결과가 일치하는지',
    example: true,
  })
  applicantVerified: boolean;

  @ApiProperty({ description: 'FastAPI가 인식한 신분증 종류', example: 'passport' })
  documentType: string;

  @ApiProperty({ type: Object, description: '필드별 일치 여부 (성/이름/생년월일 등)' })
  fieldMatches: Record<string, unknown>;

  @ApiProperty({ description: '결과 메시지', example: '본인인증 성공' })
  message: string;
}
