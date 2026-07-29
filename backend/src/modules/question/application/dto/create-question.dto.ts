import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  IsArray,
  IsEnum,
  IsInt,
  IsOptional,
  IsPositive,
  IsString,
  MinLength,
} from 'class-validator';
import { QuestionType } from '../../domain/enums/question-type.enum';

export class CreateQuestionDto {
  @ApiProperty({ enum: QuestionType })
  @IsEnum(QuestionType)
  type: QuestionType;

  @ApiProperty()
  @IsString()
  @MinLength(1)
  content: string;

  @ApiPropertyOptional({ type: [String], description: 'MULTIPLE_CHOICE 유형일 때 선택지' })
  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  choices?: string[];

  @ApiPropertyOptional({ description: '자동 채점용 정답 (MULTIPLE_CHOICE / SHORT_ANSWER)' })
  @IsOptional()
  @IsString()
  correctAnswer?: string;

  @ApiProperty()
  @IsInt()
  @IsPositive()
  points: number;
}
