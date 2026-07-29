import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { QuestionType } from '../../domain/enums/question-type.enum';

export class QuestionResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  testId: string;

  @ApiProperty({ enum: QuestionType })
  type: QuestionType;

  @ApiProperty()
  content: string;

  @ApiPropertyOptional({ type: [String] })
  choices: string[] | null;

  @ApiPropertyOptional()
  correctAnswer: string | null;

  @ApiProperty()
  points: number;

  @ApiProperty()
  createdAt: Date;
}
