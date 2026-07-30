import { ApiPropertyOptional } from '@nestjs/swagger';

export class VerifyIdCardResponseDto {
  @ApiPropertyOptional({
    nullable: true,
    example: null,
    description: 'FastAPI 얼굴 대조 서비스가 아직 연동되지 않아 현재는 항상 null.',
  })
  matched: boolean | null;

  @ApiPropertyOptional({ nullable: true, example: null })
  confidence: number | null;
}
