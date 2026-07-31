import { ApiProperty } from '@nestjs/swagger';
import { SessionStatus } from '../../domain/enums/session-status.enum';

export class StartExamSessionResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  examId: string;

  @ApiProperty({ enum: SessionStatus })
  status: SessionStatus;

  @ApiProperty()
  startedAt: Date;
}
