import { ApiProperty } from '@nestjs/swagger';
import { IsInt, IsUUID, Min } from 'class-validator';

export class CreateScoreDto {
  @ApiProperty()
  @IsUUID()
  submissionId: string;

  @ApiProperty()
  @IsInt()
  @Min(0)
  totalScore: number;

  @ApiProperty()
  @IsInt()
  @Min(0)
  maxScore: number;
}
