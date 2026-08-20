import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsEnum, IsObject, IsOptional } from 'class-validator';
import { ClientViolationType } from '../../domain/enums/client-violation-type.enum';

export class ReportViolationDto {
  @ApiProperty({
    enum: ClientViolationType,
    description: '프런트가 브라우저 이벤트로 직접 감지한 부정행위 신호 종류',
  })
  @IsEnum(ClientViolationType)
  violationType: ClientViolationType;

  @ApiPropertyOptional({
    type: Object,
    description: '위반 상세 정보(선택) — 예: DUAL_MONITOR면 감지된 화면 배치 등',
  })
  @IsOptional()
  @IsObject()
  meta?: Record<string, unknown>;
}
