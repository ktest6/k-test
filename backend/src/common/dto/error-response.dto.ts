import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';

export class ApiErrorResponseDto {
  @ApiProperty({ example: false })
  success: boolean;

  @ApiProperty({ example: 400 })
  statusCode: number;

  @ApiProperty({ example: '요청 값이 올바르지 않습니다.' })
  message: string;

  @ApiPropertyOptional({ type: () => Object, example: null, nullable: true })
  data: null;

  @ApiProperty({ example: 'VALIDATION_ERROR' })
  code: string;

  @ApiProperty({ example: '/auth/sign-up' })
  path: string;

  @ApiProperty({ example: '2026-07-30T12:00:00.000Z' })
  timestamp: string;
}
