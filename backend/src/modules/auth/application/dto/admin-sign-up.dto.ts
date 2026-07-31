import { ApiProperty } from '@nestjs/swagger';
import { IsEmail, IsString, MaxLength, MinLength } from 'class-validator';

export class AdminSignUpDto {
  @ApiProperty({ example: 'admin1@test.com', description: '로그인 ID로 사용' })
  @IsEmail()
  email: string;

  @ApiProperty({ example: '12341234!!' })
  @IsString()
  @MinLength(8)
  password: string;

  @ApiProperty({ example: 'GILDONG', description: '영문 이름' })
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  firstName: string;

  @ApiProperty({ example: 'HONG', description: '영문 성' })
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  lastName: string;

  @ApiProperty({
    description:
      '관리자 계정 생성을 허용하는 공유 비밀값 (서버 env ADMIN_SIGNUP_SECRET과 일치해야 함)',
  })
  @IsString()
  @MinLength(1)
  adminSecret: string;
}
