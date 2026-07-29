import { ApiProperty } from '@nestjs/swagger';

export class ScoreResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  submissionId: string;

  @ApiProperty()
  totalScore: number;

  @ApiProperty()
  maxScore: number;

  @ApiProperty()
  gradedAt: Date;
}
