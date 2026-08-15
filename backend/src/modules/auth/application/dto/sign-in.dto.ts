import { ApiProperty } from '@nestjs/swagger';
import { IsEmail, IsString } from 'class-validator';

export class SignInDto {
  @ApiProperty({ example: 'demo@ktest.local' })
  @IsEmail()
  email: string;

  @ApiProperty({ example: 'DemoTest1234!' })
  @IsString()
  password: string;
}
