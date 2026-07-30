/**
 * 검증 실패에 대해 나머지 시스템(Submission 모듈)이 취해야 할 조치. 인증
 * 타입(id-card, 추후 earphone 등)에 관계없이 공통으로 쓰는 결과 값이라
 * 여기(도메인 최상위)에 둔다.
 */
export enum VerificationFailureAction {
  NONE = 'NONE',
  WARNING = 'WARNING',
  DISQUALIFICATION = 'DISQUALIFICATION',
}
