import { ApiProperty } from '@nestjs/swagger';
import { IsEmail } from 'class-validator';

export class CheckEmailQueryDto {
  @ApiProperty({ example: 'student@example.com' })
  @IsEmail()
  email: string;
}
