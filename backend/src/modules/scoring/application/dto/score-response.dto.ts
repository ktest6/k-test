import { ApiProperty } from '@nestjs/swagger';

export class ScoreResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  answerId: string;

  @ApiProperty({ type: Object })
  rawResponse: Record<string, unknown>;

  @ApiProperty()
  createdAt: Date;
}
