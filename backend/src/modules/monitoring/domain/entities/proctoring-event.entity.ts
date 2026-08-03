export type ProctoringSeverity = 'LOW' | 'MEDIUM' | 'HIGH';

export class ProctoringEvent {
  constructor(
    readonly id: string,
    readonly examSessionId: string,
    /** 모니터링 서비스가 준 값 그대로(FACE_OUT_OF_FRAME, EYE_GAZE_AWAY, PHONE_DETECTED 등) — 자유 문자열. */
    readonly eventType: string,
    readonly severity: ProctoringSeverity,
    /** 모니터링 서비스 응답의 해당 이벤트 details를 그대로 저장. */
    readonly meta: Record<string, unknown>,
    readonly createdAt: Date,
  ) {}
}
