import { ApiProperty } from '@nestjs/swagger';

export class AiHealthResponseDto {
  @ApiProperty()
  provider: string;

  @ApiProperty()
  available: boolean;
}
