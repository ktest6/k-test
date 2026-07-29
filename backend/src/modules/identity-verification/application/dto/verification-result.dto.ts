import { ApiProperty } from '@nestjs/swagger';
import { VerificationFailureAction } from '../../domain/enums/verification-failure-action.enum';
import { VerificationStatus } from '../../domain/enums/verification-status.enum';

export class VerificationResultDto {
  @ApiProperty()
  sessionId: string;

  @ApiProperty({ enum: VerificationStatus })
  status: VerificationStatus;

  @ApiProperty({ enum: VerificationFailureAction })
  action: VerificationFailureAction;

  @ApiProperty({ required: false })
  consecutiveFailures?: number;
}
