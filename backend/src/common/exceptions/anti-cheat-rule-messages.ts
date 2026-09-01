/**
 * anti-cheat 모니터링(POST /monitoring/analyze)이 감지 이벤트마다 실어 보내는
 * `message`(한국어 원문)를 영어 문장으로 바꾸는 카탈로그. 이 message는 HTTP
 * 오류 응답이 아니라 200 정상 응답 안의 이벤트 상세라서 anti-cheat-error-messages.ts
 * (4xx/5xx 오류 전용)로 커버되지 않는다 — 지금까지 번역 없이 그대로
 * tb_proctoring_events.meta.message에 저장되고 /monitoring/analyze 응답으로도
 * 그대로 나가고 있었다(예: PHONE_DETECTED "시험 화면에서 휴대폰이 탐지되었습니다.").
 *
 * anti-cheat/modules/cheating_detection/rule_engine.py의 실제 message 문자열을
 * 그대로 옮겼다 — anti-cheat 쪽 문구가 바뀌면 이 파일도 같이 갱신해야 한다.
 */

export const ANTI_CHEAT_RULE_MESSAGES: Record<string, string> = {
  RULE_FACE_OUT_OF_FRAME: "The candidate's face could not be detected on screen.",
  RULE_MULTIPLE_FACES: 'Multiple faces were detected on the exam screen.',
  RULE_EYE_GAZE_AWAY: "The candidate's gaze moved outside the normal range.",
  RULE_HEAD_POSE_AWAY: "The candidate's head pose moved outside the normal range.",
  RULE_IDENTITY_MISMATCH:
    'The current user does not match the user registered at the start of the exam.',
  RULE_PHONE_DETECTED: 'A phone was detected on the exam screen.',
  RULE_EARPHONE_DETECTED: 'Earphones were detected on the exam screen.',
};

/**
 * ruleId로 영어 문장을 찾는다. 카탈로그에 없는 ruleId(새 룰 추가 등)면 anti-cheat가
 * 준 한국어 원문을 그대로 반환한다 — 아무것도 안 뜨는 것보다 한국어라도 뜨는 게 낫다
 * (anti-cheat-error-messages.ts와 같은 원칙).
 */
export function resolveAntiCheatRuleMessage(
  ruleId: string | undefined,
  koreanMessage: string,
): string {
  if (!ruleId) {
    return koreanMessage;
  }
  return ANTI_CHEAT_RULE_MESSAGES[ruleId] ?? koreanMessage;
}
