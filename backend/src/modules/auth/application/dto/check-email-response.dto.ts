import { ApiProperty } from '@nestjs/swagger';

export class CheckEmailResponseDto {
  @ApiProperty({ description: '가입 가능 여부 (사용 중이면 false)' })
  available: boolean;
}
