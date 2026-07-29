import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Role } from '../../../../common/enums/role.enum';
import { IdentityDocumentType } from '../../domain/enums/identity-document-type.enum';

export class UserResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  email: string;

  @ApiProperty({ description: '영문성명 (여권 표기 기준)' })
  name: string;

  @ApiProperty({ enum: Role })
  role: Role;

  @ApiProperty()
  nationality: string;

  @ApiProperty({ description: 'YYYY-MM-DD' })
  birthDate: string;

  @ApiProperty({ enum: IdentityDocumentType })
  idType: IdentityDocumentType;

  @ApiProperty()
  idNumber: string;

  @ApiPropertyOptional()
  companyCode: string | null;

  @ApiProperty()
  termsAgreedAt: Date;

  @ApiProperty()
  privacyAgreedAt: Date;

  @ApiProperty()
  loginAttempts: number;

  @ApiPropertyOptional()
  lastLoginAt: Date | null;

  @ApiProperty()
  createdAt: Date;
}
