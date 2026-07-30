import { ApiProperty } from '@nestjs/swagger';

export class CancelExamApplicationResponseDto {
  @ApiProperty()
  examId: string;
}
