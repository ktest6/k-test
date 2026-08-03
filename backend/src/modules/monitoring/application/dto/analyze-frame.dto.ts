import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Transform, Type } from 'class-transformer';
import { IsBoolean, IsDateString, IsInt, IsOptional, Min } from 'class-validator';

/**
 * multipart/form-data로 온다 — current_image는 컨트롤러에서 @UploadedFile()로
 * 따로 받고, 여기는 나머지 폼 필드만 다룬다. reference_image는 프론트가
 * 보내지 않는다 — 서버가 본인인증 때 저장된 얼굴 사진을 알아서 붙인다
 * (매 프레임마다 같은 기준 이미지를 반복 업로드시키지 않기 위함).
 */
export class AnalyzeFrameDto {
  @ApiProperty({
    description: '웹캠 프레임이 실제로 촬영된 시각 (타임존 정보 필요, 예: +09:00)',
    example: '2026-08-04T13:05:00+09:00',
  })
  @IsDateString()
  capturedAt: string;

  @ApiProperty({
    description: '시험 시작 후 프레임 촬영까지 경과 시간(ms). 0 이상',
    example: 300000,
  })
  @Type(() => Number)
  @IsInt()
  @Min(0)
  elapsedMs: number;

  @ApiProperty({ description: '시험 시작 후 전송된 프레임 순번. 1 이상', example: 60 })
  @Type(() => Number)
  @IsInt()
  @Min(1)
  captureSequence: number;

  @ApiPropertyOptional({
    description:
      '이번 프레임에서 중간 동일인 검사를 실행할지 여부. 기본 false. 얼굴이 정확히 한 명 감지된 프레임에서만 실제로 실행된다(모니터링 서비스 쪽 판단).',
    default: false,
  })
  @IsOptional()
  @Transform(({ value }) => value === 'true' || value === true)
  @IsBoolean()
  runIdentityCheck?: boolean;
}
