import { ApiProperty } from '@nestjs/swagger';
import { IsUUID } from 'class-validator';

export class InitiateVerificationDto {
  @ApiProperty({ description: '본인인증 대상 응시(Submission) ID' })
  @IsUUID()
  submissionId: string;
}
