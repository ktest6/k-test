import { Role } from '../../../../common/enums/role.enum';
import { IdentityDocumentType } from '../enums/identity-document-type.enum';

export class User {
  constructor(
    readonly id: string,
    readonly email: string,
    /** 영문 이름/성 (여권 표기 기준) — 응시 당일 신분증 대조용. */
    readonly firstName: string,
    readonly lastName: string,
    readonly role: Role,
    /** 아래 신원/약관동의 필드는 응시자(USER) 전용 — 관리자(ADMIN)는 전부 null. */
    readonly nationality: string | null,
    /** ISO date string (YYYY-MM-DD). */
    readonly birthDate: string | null,
    readonly idType: IdentityDocumentType | null,
    readonly idNumber: string | null,
    readonly companyCode: string | null,
    readonly termsAgreedAt: Date | null,
    readonly privacyAgreedAt: Date | null,
    readonly loginAttempts: number,
    readonly lastLoginAt: Date | null,
    readonly createdAt: Date,
  ) {}
}
