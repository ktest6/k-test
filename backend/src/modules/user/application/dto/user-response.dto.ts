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

  @ApiProperty({ enum: IdentityDocumentType })
  idType: IdentityDocumentType;

  @ApiProperty()
  idNumber: string;

  @ApiPropertyOptional({ nullable: true })
  companyCode: string | null;

  @ApiProperty()
  termsAgreedAt: Date;

  @ApiProperty()
  privacyAgreedAt: Date;

  @ApiProperty()
  loginAttempts: number;

  @ApiPropertyOptional({ nullable: true })
  lastLoginAt: Date | null;

  @ApiProperty()
  createdAt: Date;
}
