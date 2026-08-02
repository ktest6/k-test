import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsEnum, IsOptional, IsString, MaxLength } from 'class-validator';
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
}
