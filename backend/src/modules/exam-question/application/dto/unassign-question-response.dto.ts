import { ApiProperty } from '@nestjs/swagger';

export class UnassignQuestionResponseDto {
  @ApiProperty()
  examId: string;

  @ApiProperty()
  questionId: string;
}
