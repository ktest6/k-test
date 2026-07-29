import { ApiProperty } from '@nestjs/swagger';

export class VerificationStatusResponseDto {
  @ApiProperty({ description: '지금 재인증이 필요한지 여부' })
  dueNow: boolean;

  @ApiProperty({
    description:
      '서버가 계산한 다음 재인증 시점(ISO timestamp). 클라이언트는 이 값을 기준으로 다음 폴링을 예약한다.',
  })
  nextCheckAt: string;
}
