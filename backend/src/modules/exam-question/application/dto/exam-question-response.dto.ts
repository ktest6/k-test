import { ApiProperty } from '@nestjs/swagger';

export class ExamQuestionResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  examId: string;

  @ApiProperty()
  questionId: string;

  @ApiProperty()
  createdAt: Date;
}
