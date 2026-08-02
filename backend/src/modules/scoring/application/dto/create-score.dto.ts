import { ApiProperty } from '@nestjs/swagger';
import { IsObject, IsString, MinLength } from 'class-validator';

export class CreateScoreDto {
  @ApiProperty({ description: '채점 대상 답안 ID (tb_answers.answer_id)', example: '1' })
  @IsString()
  @MinLength(1)
  answerId: string;

  @ApiProperty({ description: '채점 서비스 응답 원본 (형식 미고정)', type: Object })
  @IsObject()
  rawResponse: Record<string, unknown>;
}
