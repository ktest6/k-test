import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  Equals,
  IsBoolean,
  IsDateString,
  IsEmail,
  IsEnum,
  IsOptional,
  IsString,
  MaxLength,
  MinLength,
} from 'class-validator';
import { IdentityDocumentType } from '../../../user/domain/enums/identity-document-type.enum';

export class SignUpDto {
  // 계정
  @ApiProperty({ example: 'student@example.com', description: '로그인 ID로 사용' })
  @IsEmail()
  email: string;

  @ApiProperty({ example: '12341234!!' })
  @IsString()
  @MinLength(8)
  password: string;

  // 신원 (응시 당일 신분증 대조용 — 최소 항목만 수집)
  @ApiProperty({ example: 'GILDONG HONG', description: '영문성명 (여권 표기 기준)' })
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  name: string;

  @ApiProperty({ example: 'KOR', description: '국적' })
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  nationality: string;

  @ApiProperty({ example: '1995-05-20', description: '생년월일 (YYYY-MM-DD)' })
  @IsDateString()
  birthDate: string;

  @ApiProperty({ enum: IdentityDocumentType, description: '신분증 종류 (여권/외국인등록증)' })
  @IsEnum(IdentityDocumentType)
  idType: IdentityDocumentType;

  @ApiProperty({ example: 'M12345678' })
  @IsString()
  @MinLength(1)
  @MaxLength(50)
  idNumber: string;

  // 소속 (선택, B2B)
  @ApiPropertyOptional({ description: '소속 기업 코드 (B2B, 추후 관리자 매칭용)' })
  @IsOptional()
  @IsString()
  @MaxLength(50)
  companyCode?: string;

  // 동의 (필수, 타임스탬프 기록)
  @ApiProperty({ description: '이용약관 동의 여부 (필수)' })
  @IsBoolean()
  @Equals(true, { message: '이용약관에 동의해야 가입할 수 있습니다.' })
  agreedToTerms: boolean;

  @ApiProperty({ description: '개인정보처리방침 동의 여부 (필수)' })
  @IsBoolean()
  @Equals(true, { message: '개인정보처리방침에 동의해야 가입할 수 있습니다.' })
  agreedToPrivacyPolicy: boolean;
}
