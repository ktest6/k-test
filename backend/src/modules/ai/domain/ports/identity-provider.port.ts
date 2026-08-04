export const IDENTITY_PROVIDER = Symbol('IDENTITY_PROVIDER');

export interface IdentityImageInput {
  buffer: Buffer;
  filename: string;
  contentType: string;
}

export interface VerifyIdentityInput {
  examId: string;
  examineeId: string;
  /** ISO 8601, 타임존 포함. */
  capturedAt: string;
  /** 여권/외국인등록증 이미지. */
  sourceImage: IdentityImageInput;
  /** 시험 시작 전 웹캠 이미지. */
  targetImage: IdentityImageInput;
  firstName: string;
  lastName: string;
  /** ISO date string (YYYY-MM-DD). */
  birthDate: string;
  /** user 모듈의 IdentityDocumentType 값을 그대로 받는다 — 외부 API 형식으로의 변환은 어댑터가 담당(ai 모듈이 user 모듈에 의존하지 않도록). */
  documentType: 'PASSPORT' | 'ARC';
}

export interface VerifyIdentityResult {
  /** 최종 본인인증 성공 여부(얼굴 대조 + 신청 정보 대조 종합). */
  verified: boolean;
  faceVerified: boolean;
  /** 얼굴 유사도 (0~100). */
  similarity: number;
  /** 얼굴 비교 기준값. */
  threshold: number;
  matchedFaceCount: number;
  unmatchedFaceCount: number;
  /** 신청 정보(이름/생년월일 등)와 신분증 인식 결과가 일치하는지. */
  applicantVerified: boolean;
  /** 서비스가 인식한 신분증 종류. */
  documentType: string;
  /** 필드별 일치 여부. */
  fieldMatches: Record<string, unknown>;
  message: string;
  /** 응답 원문 그대로 — 감사/디버깅용으로 저장한다. */
  raw: Record<string, unknown>;
}

/** 신분증(여권/외국인등록증)과 웹캠 얼굴 사진을 대조하는 외부 본인인증 서비스 추상화(FastAPI, 별도 담당). */
export interface IdentityProviderPort {
  verify(input: VerifyIdentityInput): Promise<VerifyIdentityResult>;
}
