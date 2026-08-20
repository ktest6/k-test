/**
 * AI 모니터링(analyze)과 별개로, 프런트가 브라우저 이벤트로 직접 감지해서
 * 보고하는 부정행위 신호. 프런트 부정행위 방지 플로우의 "시험 진행 중 —
 * 브라우저 실시간 감지" 목록과 대응한다(웹캠 스냅샷 감지는 이미 analyze로
 * 커버되므로 제외).
 */
export enum ClientViolationType {
  /** visibilitychange — 다른 탭으로 이동. */
  TAB_SWITCH = 'TAB_SWITCH',
  /** blur — 다른 앱/창으로 포커스 이동. */
  BLUR = 'BLUR',
  /** beforeunload — 시험 창을 닫으려는 시도. */
  WINDOW_CLOSE_ATTEMPT = 'WINDOW_CLOSE_ATTEMPT',
  /** mouseleave — 마우스가 시험 화면 밖으로 이탈. */
  MOUSE_LEAVE = 'MOUSE_LEAVE',
  /** paste 이벤트 — 답안에 붙여넣기. */
  PASTE = 'PASTE',
  /** isExtended — 듀얼 모니터 감지. 누적 2회부터 자동 실격. */
  DUAL_MONITOR = 'DUAL_MONITOR',
}
