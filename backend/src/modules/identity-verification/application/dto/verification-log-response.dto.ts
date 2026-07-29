import { ApiProperty } from '@nestjs/swagger';

export class VerificationLogResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  sessionId: string;

  @ApiProperty({ nullable: true })
  attemptId: string | null;

  @ApiProperty()
  eventType: string;

  @ApiProperty()
  payload: Record<string, unknown>;

  @ApiProperty()
  createdAt: Date;
}
