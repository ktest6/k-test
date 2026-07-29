import { ApiPropertyOptional, ApiProperty } from '@nestjs/swagger';
import { IsIn, IsObject, IsOptional, IsUUID } from 'class-validator';

export class VerifyPeriodicDto {
  @ApiProperty({ description: '본인인증 대상 응시(Submission) ID' })
  @IsUUID()
  submissionId: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsObject()
  payload?: Record<string, unknown>;

  @ApiPropertyOptional({
    enum: ['SUCCESS', 'FAILED'],
    description: 'Mock provider 강제 결과 지정 (개발/테스트 전용, production에서는 무시됨).',
  })
  @IsOptional()
  @IsIn(['SUCCESS', 'FAILED'])
  forceResult?: 'SUCCESS' | 'FAILED';
}
