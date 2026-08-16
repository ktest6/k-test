import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IdentityDocumentType } from '../../domain/enums/identity-document-type.enum';

export class UserResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  email: string;

  @ApiProperty({ description: '영문 이름 (여권 표기 기준)' })
  firstName: string;

  @ApiProperty({ description: '영문 성 (여권 표기 기준)' })
  lastName: string;

  @ApiProperty()
  nationality: string;

  @ApiProperty({ description: 'YYYY-MM-DD' })
  birthDate: string;

  @ApiPropertyOptional({ enum: IdentityDocumentType, nullable: true })
  idType: IdentityDocumentType | null;

  @ApiPropertyOptional({ type: String, nullable: true })
  idNumber: string | null;

  @ApiPropertyOptional({ type: String, nullable: true })
  companyCode: string | null;

  @ApiProperty()
  termsAgreedAt: Date;

  @ApiProperty()
  privacyAgreedAt: Date;

  @ApiPropertyOptional({
    type: Date,
    nullable: true,
    description: '여권번호 처리 동의 시각(필수 항목)',
  })
  passportProcessingAgreedAt: Date | null;

  @ApiProperty()
  loginAttempts: number;

  @ApiPropertyOptional({ type: Date, nullable: true })
  lastLoginAt: Date | null;

  @ApiProperty()
  createdAt: Date;

  @ApiPropertyOptional({ type: Date, nullable: true, description: '이메일 인증 완료 시각' })
  emailVerifiedAt: Date | null;

  @ApiPropertyOptional({
    type: Date,
    nullable: true,
    description: '음성 데이터의 AI 모델 학습 활용 동의 시각(선택). 동의 안 했으면 null.',
  })
  voiceDataAiTrainingAgreedAt: Date | null;
}
