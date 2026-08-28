import { substituteTemplate } from '../utils/substitute-template.util';

/**
 * anti-cheat 서비스(도영님 담당)가 4xx/5xx 응답에 실어 보내는 `{detail, code,
 * params?}` 오류를 영어 문장으로 바꾸는 카탈로그. `/Users/yena/Downloads/
 * anti-cheat API 오류 코드 전체 매핑표 (1).xlsx`(2026-08-28 기준, anti-cheat/app·
 * anti-cheat/modules 전수 조사)를 그대로 옮겼다 — anti-cheat 쪽 코드가 바뀌면
 * 그 표를 다시 받아서 이 파일도 같이 갱신해야 한다.
 *
 * detail(한국어)은 그대로 두고 code+params만 보고 영어 문장을 만든다 —
 * assessment-notice-messages.ts와 같은 패턴(치환은 공용 substituteTemplate
 * 사용)이며, anti-cheat 쪽 params에는 중첩 notice가 없어 그 부분만 없다.
 */

export interface AntiCheatError {
  code: string;
  params?: Record<string, unknown>;
  /** anti-cheat가 만든 한국어 원문 — 카탈로그에 없는 코드를 만나면 이 값으로 대체한다. */
  detail: string;
}

/** code → 영어 문장 템플릿. 매핑표의 47개 코드 전부. */
export const ANTI_CHEAT_ERROR_MESSAGES: Record<string, string> = {
  // ── 요청 검증(공통) ──
  REQUEST_FIELD_REQUIRED: "The required field '{field}' is missing.",
  REQUEST_DATETIME_INVALID:
    "The field '{field}' has an invalid date-time format (expected {expectedFormat}).",
  REQUEST_DATE_INVALID:
    "The field '{field}' has an invalid date format (expected {expectedFormat}).",
  REQUEST_INTEGER_INVALID: "The field '{field}' must be an {expectedType}.",
  REQUEST_BOOLEAN_INVALID: "The field '{field}' must be a {expectedType}.",
  REQUEST_NUMBER_INVALID: "The field '{field}' must be a {expectedType}.",
  REQUEST_ENUM_INVALID:
    "The field '{field}' has a value that is not allowed (allowed: {allowedValues}).",
  REQUEST_FILE_INVALID: "The field '{field}' has an invalid file format (expected {expectedType}).",
  REQUEST_FILE_LIST_INVALID:
    "The field '{field}' has an invalid file list format (expected {expectedType}).",
  REQUEST_BODY_INVALID: 'The request body format is invalid ({reason}).',

  // ── 이미지 검증(공통) ──
  IMAGE_DATA_TYPE_INVALID: 'The {imageName} image data must be of type {expectedType}.',
  IMAGE_DATA_EMPTY: 'The {imageName} image data is empty.',

  // ── 모니터링 요청(POST /monitoring/analyze) ──
  PREVIOUS_GAZE_STATE_INVALID: 'The previous_gaze_state JSON format is invalid.',
  ELAPSED_MS_OUT_OF_RANGE: 'elapsed_ms must be at least {min} (got {actual}).',
  CAPTURE_SEQUENCE_OUT_OF_RANGE: 'capture_sequence must be at least {min} (got {actual}).',
  CAPTURED_AT_TIMEZONE_REQUIRED: 'captured_at must include timezone information (e.g. {example}).',

  // ── 모니터링(POST /monitoring/analyze) ──
  IDENTITY_REFERENCE_IMAGE_REQUIRED:
    'A reference image is required for the in-progress identity check.',
  MONITORING_FRAME_ANALYSIS_FAILED: 'An error occurred while analyzing the exam monitoring frame.',
  MONITORING_INTERNAL_ERROR: 'An error occurred while processing exam monitoring.',

  // ── 시선 보정(POST /monitoring/gaze-calibration) ──
  CALIBRATION_IMAGE_REQUIRED: 'At least {minCount} calibration image(s) must be provided.',
  CALIBRATION_EXAM_ID_EMPTY: 'The exam identifier cannot be empty.',
  CALIBRATION_EXAMINEE_ID_EMPTY: 'The examinee identifier cannot be empty.',
  CALIBRATION_FACE_RESULTS_INVALID: 'The face monitoring results must be a non-empty list.',
  CALIBRATION_EYE_CONFIDENCE_OUT_OF_RANGE:
    'The minimum eye-direction confidence must be a number between {min} and {max} (got {actual}).',
  CALIBRATION_MIN_SAMPLE_COUNT_INVALID:
    'The minimum calibration sample count must be an integer of at least {min} (got {actual}).',
  CALIBRATION_SAMPLES_INSUFFICIENT:
    'Not enough valid gaze samples for calibration ({actualCount} of {requiredCount} required).',

  // ── 시선 상태(POST /monitoring/analyze) ──
  GAZE_RESULT_TYPE_INVALID: 'The gaze analysis result must be an {expectedType}.',
  GAZE_ELAPSED_MS_TYPE_INVALID: 'The elapsed exam time must be an {expectedType} (got {actual}).',
  GAZE_ELAPSED_MS_OUT_OF_RANGE: 'The elapsed exam time must be at least {min} (got {actual}).',
  GAZE_CAPTURE_SEQUENCE_TYPE_INVALID:
    'The capture image sequence number must be an {expectedType} (got {actual}).',
  GAZE_CAPTURE_SEQUENCE_OUT_OF_RANGE:
    'The capture image sequence number must be at least {min} (got {actual}).',
  GAZE_PERSISTENT_THRESHOLD_TYPE_INVALID:
    'The persistent gaze-deviation threshold count must be an {expectedType} (got {actual}).',
  GAZE_PERSISTENT_THRESHOLD_OUT_OF_RANGE:
    'The persistent gaze-deviation threshold count must be at least {min} (got {actual}).',
  PREVIOUS_GAZE_STATE_TYPE_INVALID: 'The previous gaze state must be an {expectedType}.',

  // ── 신분증(POST /identity/verify) ──
  DOCUMENT_NOT_DETECTED: 'The {documentType} could not be recognized.',
  DOCUMENT_TYPE_UNSUPPORTED:
    "Unsupported document type '{actualType}' (supported: {supportedTypes}).",
  DOCUMENT_REQUIRED_FIELDS_MISSING:
    'Could not read the following required fields from the document: {fields}.',

  // ── 신청 정보(POST /identity/verify) ──
  APPLICANT_REQUIRED_FIELDS_MISSING:
    'The application information is missing required fields: {fields}.',
  EXTRACTED_DOCUMENT_FIELDS_MISSING:
    'The extracted document information is missing required fields: {fields}.',
  BIRTH_DATE_FORMAT_UNSUPPORTED: "Unsupported date-of-birth format: '{value}'.",

  // ── 외부 API(AWS/Azure) ──
  REKOGNITION_DETECT_FACES_FAILED: 'The AWS Rekognition DetectFaces API call failed.',
  REKOGNITION_COMPARE_FACES_FAILED: 'The AWS Rekognition CompareFaces API call failed.',
  REKOGNITION_OBJECT_DETECTION_FAILED: 'AWS Rekognition object detection failed.',
  REKOGNITION_EARPHONE_DETECTION_FAILED: 'AWS Rekognition earphone detection failed.',
  DOCUMENT_INTELLIGENCE_API_FAILED: 'The Azure Document Intelligence API call failed.',

  // ── 본인 인증(POST /identity/verify) ──
  IDENTITY_VERIFICATION_INTERNAL_ERROR:
    'An unexpected error occurred while processing identity verification.',

  // ── 이어폰 탐지(POST /earphone/detect) ──
  EARPHONE_DETECTION_FAILED: 'Earphone detection processing failed.',
  EARPHONE_DETECTION_INTERNAL_ERROR:
    'An unexpected error occurred while processing earphone detection.',
};

/**
 * anti-cheat 오류 하나를 최종 영어 문장으로 만든다. 카탈로그에 없는 code면
 * anti-cheat가 준 한국어 detail을 그대로 반환한다 — 아무것도 안 뜨는 것보다
 * 한국어라도 뜨는 게 낫다(assessment 쪽과 동일한 원칙).
 */
export function resolveAntiCheatError(error: AntiCheatError): string {
  const template = ANTI_CHEAT_ERROR_MESSAGES[error.code];
  if (template === undefined) {
    return error.detail;
  }
  return substituteTemplate(template, error.params ?? {});
}
