import { ApiProperty } from '@nestjs/swagger';

export class ChecklistItemResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty({ description: '체크리스트 코드 (c1, c2, ...)' })
  code: string;

  @ApiProperty()
  description: string;

  @ApiProperty()
  weight: number;
}
