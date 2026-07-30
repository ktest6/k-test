import { ApiProperty } from '@nestjs/swagger';

/**
 * Swagger 문서용 성공 응답 봉투. `data` 필드는 일부러 클래스에 넣지 않는다 —
 * 프로퍼티가 있으면(@ApiProperty 없이 놔둬도) swagger가 타입 추론을 시도하다
 * 순환 참조 오류를 내므로, `ApiStandardResponse` 데코레이터가 allOf 두 번째
 * 항목으로 실제 응답 DTO 스키마를 합성해서 채워 넣는 방식으로만 다룬다.
 */
export class ApiSuccessResponseDto {
  @ApiProperty({ example: true })
  success: boolean;

  @ApiProperty({ example: 200 })
  statusCode: number;

  @ApiProperty({ example: 'OK' })
  message: string;

  @ApiProperty({ example: '/users/me' })
  path: string;

  @ApiProperty({ example: '2026-07-30T12:00:00.000Z' })
  timestamp: string;
}
