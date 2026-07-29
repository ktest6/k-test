import { ApiPropertyOptional, ApiProperty } from '@nestjs/swagger';
import { IsIn, IsObject, IsOptional, IsUUID } from 'class-validator';

export class VerifyChallengeDto {
  @ApiProperty({ description: '본인인증 세션 ID (pre-exam/initiate 응답에서 발급)' })
  @IsUUID()
  sessionId: string;

  @ApiPropertyOptional({ description: '인증 수단별 응답 payload (예: 얼굴 이미지 참조, OTP 등)' })
  @IsOptional()
  @IsObject()
  payload?: Record<string, unknown>;

  @ApiPropertyOptional({
    enum: ['SUCCESS', 'FAILED'],
    description:
      'Mock provider 강제 결과 지정 (개발/테스트 전용, production에서는 무시됨). ' +
      '정책(WARNING → DISQUALIFICATION) 시나리오 테스트에 사용.',
  })
  @IsOptional()
  @IsIn(['SUCCESS', 'FAILED'])
  forceResult?: 'SUCCESS' | 'FAILED';
}
