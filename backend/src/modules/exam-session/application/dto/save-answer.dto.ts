import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { IsInt, IsOptional, IsString, Min } from 'class-validator';

/**
 * 모든 문항이 말하기(듣기/말하기 3유형)뿐이라 답안은 음성 하나로 고정된다.
 * 예전엔 쓰기 문항이 있어 type(TEXT|AUDIO)을 함께 받았지만, 이제 항상
 * AUDIO라 그 구분 자체가 의미 없어 필드를 없앴다(서비스에서 고정으로 채움).
 */
export class SaveAnswerDto {
  @ApiProperty({
    description:
      'upload-url 응답의 path를 그대로 전달 (Storage 경로 — 완전한 URL 아님, 조회 응답의 audioFileUrl과 형태가 다름)',
  })
  @IsString()
  audioFileUrl: string;

  @ApiPropertyOptional({
    description:
      '녹음 길이(ms). wav가 아닌 포맷(webm/m4a 등)은 assessment 채점 시 이 값을 보내야 duration이 남는다.',
  })
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  durationMs?: number;
}
