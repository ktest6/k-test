import { ApiProperty } from '@nestjs/swagger';
import { IsUUID } from 'class-validator';

export class CreateSubmissionDto {
  @ApiProperty()
  @IsUUID()
  testId: string;
}
