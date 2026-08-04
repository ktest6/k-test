import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { IsEnum, IsInt, IsOptional, IsString, MaxLength, Min } from 'class-validator';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';

export class SaveAnswerDto {
  @ApiProperty({ enum: AnswerType })
  @IsEnum(AnswerType)
  type: AnswerType;

  @ApiPropertyOptional({ description: 'TEXT 답안일 때 필수', maxLength: 1000 })
  @IsOptional()
  @IsString()
  @MaxLength(1000)
  contentText?: string;

  @ApiPropertyOptional({ description: 'AUDIO 답안일 때 필수 (Supabase Storage 경로)' })
  @IsOptional()
  @IsString()
  audioFileUrl?: string;

  @ApiPropertyOptional({
    description:
      'AUDIO 답안일 때 녹음 길이(ms). wav가 아닌 포맷(webm/m4a 등)은 assessment 채점 시 이 값을 보내야 duration이 남는다.',
  })
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  durationMs?: number;
}
