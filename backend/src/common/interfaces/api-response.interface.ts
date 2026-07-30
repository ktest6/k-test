/**
 * 프론트로 나가는 모든 응답이 공통으로 따르는 봉투(envelope) 형태.
 * 성공/에러 모두 같은 필드 집합을 쓰므로 프론트에서 하나의 타입으로 처리 가능하다.
 */
export interface ApiResponse<T = unknown> {
  success: boolean;
  statusCode: number;
  message: string;
  data: T | null;
  /** 에러일 때만 채워짐 (예: NOT_FOUND, VALIDATION_ERROR). */
  code?: string;
  path: string;
  timestamp: string;
}
