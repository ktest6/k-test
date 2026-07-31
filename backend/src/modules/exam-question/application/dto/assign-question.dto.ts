import { ApiProperty } from '@nestjs/swagger';
import { IsString, MinLength } from 'class-validator';

export class AssignQuestionDto {
  @ApiProperty({ description: '이 회차에 배정할 문항 ID' })
  @IsString()
  @MinLength(1)
  questionId: string;
}
