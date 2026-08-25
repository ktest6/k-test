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
  ValidateIf,
} from 'class-validator';
import { mustAgreeTo } from '../../../../common/exceptions/error-messages';
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
  @ApiProperty({ example: 'GILDONG', description: '영문 이름 (여권 표기 기준)' })
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  firstName: string;

  @ApiProperty({ example: 'HONG', description: '영문 성 (여권 표기 기준)' })
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  lastName: string;

  @ApiProperty({ example: 'KOR', description: '국적' })
  @IsString()
  @MinLength(1)
  @MaxLength(100)
  nationality: string;

  @ApiProperty({ example: '1995-05-20', description: '생년월일 (YYYY-MM-DD)' })
  @IsDateString()
  birthDate: string;

  @ApiPropertyOptional({
    enum: IdentityDocumentType,
    description: '신분증 종류 (여권/외국인등록증) — 선택 입력. 가입 후 별도로 등록할 수 있다.',
  })
  @IsOptional()
  @IsEnum(IdentityDocumentType)
  idType?: IdentityDocumentType;

  @ApiPropertyOptional({
    example: 'M12345678',
    description:
      'idType을 선택했다면 필수 — 신분증 종류만 있고 번호가 없는 상태는 허용하지 않는다.',
  })
  @ValidateIf((dto: SignUpDto) => dto.idType !== undefined)
  @IsString()
  @MinLength(1)
  @MaxLength(50)
  idNumber?: string;

  // 소속 (선택, B2B)
  @ApiPropertyOptional({ description: '소속 기업 코드 (B2B, 추후 관리자 매칭용)' })
  @IsOptional()
  @IsString()
  @MaxLength(50)
  companyCode?: string;

  // 동의 (필수, 타임스탬프 기록)
  @ApiProperty({ description: '이용약관 동의 여부 (필수)' })
  @IsBoolean()
  @Equals(true, { message: mustAgreeTo('Terms of Service') })
  agreedToTerms: boolean;

  @ApiProperty({ description: '개인정보처리방침 동의 여부 (필수)' })
  @IsBoolean()
  @Equals(true, { message: mustAgreeTo('Privacy Policy') })
  agreedToPrivacyPolicy: boolean;

  @ApiProperty({ description: '여권번호 처리 동의 여부 (필수)' })
  @IsBoolean()
  @Equals(true, { message: mustAgreeTo('passport information processing policy') })
  agreedToPassportProcessing: boolean;

  @ApiPropertyOptional({ description: '음성 데이터의 AI 모델 학습 활용 동의 여부 (선택)' })
  @IsOptional()
  @IsBoolean()
  agreedToVoiceDataAiTraining?: boolean;
}
