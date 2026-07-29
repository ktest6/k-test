import { Role } from '../../../../common/enums/role.enum';
import { IdentityDocumentType } from '../enums/identity-document-type.enum';

export class User {
  constructor(
    readonly id: string,
    readonly email: string,
    /** 영문성명 (여권 표기 기준) — 응시 당일 신분증 대조용. */
    readonly name: string,
    readonly role: Role,
    readonly nationality: string,
    /** ISO date string (YYYY-MM-DD). */
    readonly birthDate: string,
    readonly idType: IdentityDocumentType,
    readonly idNumber: string,
    readonly companyCode: string | null,
    readonly termsAgreedAt: Date,
    readonly privacyAgreedAt: Date,
    readonly loginAttempts: number,
    readonly lastLoginAt: Date | null,
    readonly createdAt: Date,
  ) {}
}
