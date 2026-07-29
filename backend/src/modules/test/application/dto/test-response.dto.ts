import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';

export class TestResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  title: string;

  @ApiPropertyOptional()
  description: string | null;

  @ApiProperty()
  durationMinutes: number;

  @ApiProperty()
  createdBy: string;

  @ApiProperty()
  createdAt: Date;
}
