import { ApiProperty } from '@nestjs/swagger';

export class InitiateVerificationResponseDto {
  @ApiProperty()
  sessionId: string;

  @ApiProperty({ description: 'Provider가 발급한 챌린지 참조값' })
  providerRef: string;

  @ApiProperty()
  expiresAt: Date;
}
