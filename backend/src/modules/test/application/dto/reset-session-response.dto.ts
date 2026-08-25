import { ApiProperty } from '@nestjs/swagger';

export class ResetSessionResponseDto {
  @ApiProperty({ example: 3, description: 'INPROGRESS로 리셋된 세션 수' })
  resetCount: number;
}
