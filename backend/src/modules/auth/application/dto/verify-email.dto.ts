import { ApiProperty } from '@nestjs/swagger';
import { IsEmail, IsString, Length } from 'class-validator';

export class VerifyEmailDto {
  @ApiProperty({ example: 'student@example.com' })
  @IsEmail()
  email: string;

  @ApiProperty({ example: '123456', description: '이메일로 받은 6자리 인증번호' })
  @IsString()
  @Length(6, 6)
  code: string;
}
