import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Role } from '../../../../common/enums/role.enum';
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

  @ApiProperty({ enum: Role })
  role: Role;

  @ApiPropertyOptional({ nullable: true, description: '응시자(USER)만 값 있음, 관리자는 null' })
  nationality: string | null;

  @ApiPropertyOptional({ nullable: true, description: 'YYYY-MM-DD. 응시자(USER)만 값 있음' })
  birthDate: string | null;

  @ApiPropertyOptional({ enum: IdentityDocumentType, nullable: true })
  idType: IdentityDocumentType | null;

  @ApiPropertyOptional({ nullable: true })
  idNumber: string | null;

  @ApiPropertyOptional({ nullable: true })
  companyCode: string | null;

  @ApiPropertyOptional({ nullable: true })
  termsAgreedAt: Date | null;

  @ApiPropertyOptional({ nullable: true })
  privacyAgreedAt: Date | null;

  @ApiProperty()
  loginAttempts: number;

  @ApiPropertyOptional({ nullable: true })
  lastLoginAt: Date | null;

  @ApiProperty()
  createdAt: Date;
}
