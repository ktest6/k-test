import { Notice, resolveNotice } from '../exceptions/assessment-notice-messages';

interface NoticeCarrier {
  note?: unknown;
  notice?: unknown;
  comment?: unknown;
  evidence?: unknown;
  [key: string]: unknown;
}

function isNotice(value: unknown): value is Notice {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Notice).code === 'string' &&
    typeof (value as Notice).message === 'string'
  );
}

/** Evidence.comment ← Evidence.notice (assessment/src/scoring/schema.py의 Evidence). */
function translateEvidenceList(evidence: unknown): void {
  if (!Array.isArray(evidence)) {
    return;
  }
  for (const item of evidence) {
    if (item && typeof item === 'object') {
      const carrier = item as NoticeCarrier;
      if (isNotice(carrier.notice)) {
        carrier.comment = resolveNotice(carrier.notice);
      }
    }
  }
}

/** {note, notice, evidence} 모양을 공유하는 목록(subscores/features/checklist_results) 공용 처리. */
function translateNotedList(list: unknown): void {
  if (!Array.isArray(list)) {
    return;
  }
  for (const item of list) {
    if (item && typeof item === 'object') {
      const carrier = item as NoticeCarrier;
      if (isNotice(carrier.notice)) {
        carrier.note = resolveNotice(carrier.notice);
      }
      translateEvidenceList(carrier.evidence);
    }
  }
}

/** cross_mode_check처럼 배열이 아니라 객체 하나에 note/notice가 있는 경우. */
function translateSingleNoted(value: unknown): void {
  if (value && typeof value === 'object') {
    const carrier = value as NoticeCarrier;
    if (isNotice(carrier.notice)) {
      carrier.note = resolveNotice(carrier.notice);
    }
  }
}

/**
 * assessment의 POST /score, POST /finalize 응답(rawResponse)을 프런트로 내보내기
 * 직전에 영어로 바꾼다. assessment/src/scoring/schema.py의 ScoreResponse/
 * FinalizeResponse 구조를 그대로 따라간다:
 *
 * - 최상위 warnings[] ← notices[](배열 길이·순서가 항상 같음이 보장된다는 계약)
 * - subscores[] / features[] / checklist_results[] 각각의 note ← notice
 * - 그 안 evidence[]의 comment ← notice
 * - (finalize 전용) cross_mode_check.note ← notice
 *
 * DB에 저장된 rawResponse 원본은 건드리지 않는다(감사 이력 목적, 재완님이 준
 * 그대로 보존) — 이 함수는 깊은 복사본을 만들어 그 복사본만 바꿔서 반환한다.
 * notice가 없는 자리(구버전 응답 등)는 원래 한국어 문구를 그대로 둔다 —
 * 아무것도 안 뜨는 것보다 한국어라도 뜨는 게 낫다는 문서 규칙과 같다.
 */
export function translateAssessmentResponse(raw: Record<string, unknown>): Record<string, unknown> {
  const result = JSON.parse(JSON.stringify(raw)) as Record<string, unknown>;

  if (Array.isArray(result.notices)) {
    result.warnings = (result.notices as unknown[]).map((notice) =>
      isNotice(notice) ? resolveNotice(notice) : notice,
    );
  }

  translateNotedList(result.subscores);
  translateNotedList(result.features);
  translateNotedList(result.checklist_results);
  translateSingleNoted(result.cross_mode_check);

  return result;
}
