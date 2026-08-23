import { ApiProperty } from '@nestjs/swagger';

export class ApplyExamResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  examId: string;

  @ApiProperty()
  appliedAt: Date;
}
