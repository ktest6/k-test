import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { SubmissionStatus } from '../../domain/enums/submission-status.enum';

export class SubmissionResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  testId: string;

  @ApiProperty()
  userId: string;

  @ApiProperty({ enum: SubmissionStatus })
  status: SubmissionStatus;

  @ApiProperty()
  warningCount: number;

  @ApiProperty()
  startedAt: Date;

  @ApiPropertyOptional()
  submittedAt: Date | null;

  @ApiProperty()
  createdAt: Date;
}
