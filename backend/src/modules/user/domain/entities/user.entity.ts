import { IdentityDocumentType } from '../enums/identity-document-type.enum';

/** tb_user는 응시자 전용이다 — 관리자는 tb_admin에서 별도로 관리한다. */
export class User {
  constructor(
    readonly id: string,
    readonly email: string,
    /** 영문 이름/성 (여권 표기 기준) — 응시 당일 신분증 대조용. */
    readonly firstName: string,
    readonly lastName: string,
    readonly nationality: string,
    /** ISO date string (YYYY-MM-DD). */
    readonly birthDate: string,
    /** 가입 시 선택 입력 — 등록 전이면 null. */
    readonly idType: IdentityDocumentType | null,
    readonly idNumber: string | null,
    readonly companyCode: string | null,
    readonly termsAgreedAt: Date,
    readonly privacyAgreedAt: Date,
    readonly loginAttempts: number,
    readonly lastLoginAt: Date | null,
    readonly createdAt: Date,
  ) {}
}
