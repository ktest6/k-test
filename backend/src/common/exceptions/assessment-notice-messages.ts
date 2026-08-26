import { substituteTemplate } from '../utils/substitute-template.util';

/**
 * assessment 서비스(재완님 담당)가 응답에 실어 보내는 채점/생성 관련 상태·오류
 * 코드(`notices`/`notice`, HTTP 4xx·5xx의 `detail.code`)를 영어 문장으로 바꾸는
 * 카탈로그. assessment/outputs/api_message_codes.md 에서 그대로 옮겼다 —
 * 그 문서가 손으로 쓰지 않는 자동 생성 산출물이므로, assessment 쪽 코드가
 * 바뀌면 그 문서를 다시 뽑아서 이 파일도 같이 갱신해야 한다.
 *
 * 모든 코드가 완전히 같은 모양이라(문장 템플릿 + {placeholder}), 코드 하나하나에
 * 함수를 만들지 않고 문자열 템플릿 하나로 다 처리한다 — resolveNotice()가 치환
 * 자체는 공용 substituteTemplate에 맡기고, 중첩 notice 재귀 해석만 전담한다.
 */

export interface Notice {
  code: string;
  params?: Record<string, unknown>;
  /** assessment가 만든 한국어 원문 — 카탈로그에 없는 코드를 만나면 이 값으로 대체한다. */
  message: string;
}

function isNotice(value: unknown): value is Notice {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Notice).code === 'string' &&
    typeof (value as Notice).message === 'string'
  );
}

/**
 * notice 하나를 최종 영어 문장으로 만든다. params 값이 또 다른 notice(중첩,
 * `xxxNotice` 이름 규칙)이면 그것부터 재귀적으로 문장으로 만든 뒤 끼워 넣는다.
 * 카탈로그에 없는 code면 assessment가 준 한국어 message를 그대로 반환한다 —
 * 아무것도 안 뜨는 것보다 한국어라도 뜨는 게 낫다(문서의 규칙 1).
 */
export function resolveNotice(notice: Notice): string {
  const template = NOTICE_MESSAGES[notice.code];
  if (template === undefined) {
    return notice.message;
  }

  return substituteTemplate(template, notice.params ?? {}, (value) =>
    isNotice(value) ? resolveNotice(value) : undefined,
  );
}

/** code → 영어 문장 템플릿. assessment/outputs/api_message_codes.md 의 '영어 초안' 그대로. */
export const NOTICE_MESSAGES: Record<string, string> = {
  // ── 공통(모든 POST) — 인증 ──
  AUTH_API_KEY_MISSING: 'The {header} header is missing. Put your scoring API key in this header.',
  AUTH_API_KEY_INVALID: 'The value of the {header} header is not valid.',

  // ── POST /score ──
  AUDIO_FORMAT_UNSUPPORTED: "Audio format '{format}' cannot be transcribed (accepted: {allowed}).",
  AUDIO_FORMAT_UNKNOWN:
    'The audio format could not be determined. Send it again with audio.format set (accepted: {allowed}).',
  AUDIO_URL_SCHEME_INVALID:
    'The audio file URL must use http or https (server-local file paths are not accepted).',
  AUDIO_FETCH_HTTP_ERROR:
    'The audio file could not be downloaded (the URL answered with {statusCode}). Check the URL and its access permissions.',
  AUDIO_FILE_TOO_LARGE: 'The audio file is {actualMb}MB, which is too large (maximum {maxMb}MB).',
  AUDIO_FILE_TOO_LARGE_STREAM: 'The audio file exceeds the maximum of {maxMb}MB.',
  AUDIO_FILE_EMPTY: 'The audio file is empty (0 bytes).',
  AUDIO_NOT_ALLOWED_FOR_WRITING:
    'A writing answer cannot carry an audio file. Send mode=speaking to have audio scored.',
  AUDIO_TEXT_AND_AUDIO_BOTH:
    'Both answer_text and audio were sent, so it is unclear which one to score. Leave answer_text empty to have the audio scored.',
  AUDIO_DOWNLOAD_TIMEOUT:
    'The audio file could not be downloaded within {timeoutSec} seconds. Check that the storage URL is reachable.',

  // ── POST /score ──
  STT_EMPTY_TRANSCRIPT_FINAL:
    'No speech at all could be transcribed from the audio. Check the recording.',
  STT_EMPTY_TRANSCRIPT:
    'No speech at all could be transcribed from the audio. Check whether the recording is empty or too quiet.',
  STT_SILENT_AUDIO:
    'No sound was found in the audio (the recording is silent). Check whether the microphone was off or the recording failed. Measurements: {loudness}',
  STT_TOO_QUIET:
    'A transcript was produced, but the recording is too quiet to be human speech, so it is not scored (the transcript may be fabricated). Measurements: {loudness} / Transcript preview: "{preview}"',

  // ── POST /score ──
  AUDIO_LOUDNESS_DESCRIBE:
    'Loudest 0.1s window {peak}, overall average {mean} (scale 0-{scaleMax}; measured human speech is above 8,500)',

  // ── POST /score ──
  STT_CLIENT_UNAVAILABLE: 'The audio cannot be transcribed. {reason}',
  STT_CALL_FAILED: 'The audio could not be transcribed. {reason}',
  STT_LORA_URL_NOT_SET:
    'The audio cannot be transcribed. The LoRA transcription server URL ({envVar}) is not set.',
  STT_LORA_TIMEOUT:
    'The audio could not be transcribed. The LoRA server did not answer within {timeoutSec} seconds.',
  STT_LORA_UNREACHABLE:
    'The audio could not be transcribed. The LoRA transcription server could not be reached (check the URL and whether the server is running).',
  STT_LORA_HTTP_ERROR:
    'The audio could not be transcribed. The LoRA server answered with {statusCode}.',
  STT_LORA_BAD_JSON: 'The LoRA server response could not be read (it is not JSON).',
  STT_AZURE_WAV_OPEN_FAILED:
    'The audio file could not be opened. Check that it really is a wav file.',
  STT_AZURE_WAV_NOT_16BIT:
    'This audio is {bits}-bit wav and cannot be sent for pronunciation assessment (record it as 16-bit wav).',
  STT_AZURE_KEY_NOT_SET:
    'The audio cannot be transcribed. The Azure Speech credentials (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION) are not set.',
  STT_AZURE_FORMAT_NOT_WAV:
    "Format '{format}' cannot be sent to Azure pronunciation assessment (only wav is supported for now).",
  STT_AZURE_SDK_MISSING:
    'The Azure Speech SDK required for pronunciation assessment is not installed (pip install azure-cognitiveservices-speech).',
  STT_AZURE_CALL_FAILED:
    'The audio could not be transcribed. The call to the Azure Speech service failed.',
  STT_AZURE_TIMEOUT: 'Pronunciation assessment did not finish within {timeoutSec} seconds.',
  STT_AZURE_REQUEST_CANCELED:
    'The audio could not be transcribed. The Azure Speech service rejected the request.',

  // ── POST /score, /generate-items, /finalize 공용 — LLM 실패 사유 ──
  LLM_FREE_TEXT: '{text}',

  // ── POST /score ──
  VALIDITY_INVALID_WRAP: '[Not scored] {reason}',
  VALIDITY_SOFT_WRAP: '[Answer validity] {reason}',
  VALIDITY_NOT_SCORED_NOTE: 'Not scored because the answer failed a validity guard: {reason}',
  VALIDITY_HANGUL_RATIO:
    'The Korean-script ratio of the answer is {ratio}, below the threshold of {threshold}, so it cannot be treated as a Korean answer. Scoring was voided.',
  VALIDITY_TOO_SHORT:
    "The answer is {words} words long, shorter than the minimum of {minWords}, so the error features cannot be trusted. With so few chances to make a mistake, 'zero errors' is not evidence of ability.",
  VALIDITY_PROMPT_OVERLAP:
    "{ratio} of the answer's characters are copied verbatim from the prompt (threshold {threshold}), so it cannot be treated as the test taker's own writing. Scoring was voided.",
  VALIDITY_NO_SENTENCE_HARD:
    'Only {sentences} of {total} segments carry a sentence ending, so the answer reads as a list of words. There is no sentence to score, so it was voided.',
  VALIDITY_NO_SENTENCE_SOFT:
    'Only {sentences} of {total} segments carry a sentence ending, so the answer is hard to read as complete sentences.',

  // ── POST /score, /finalize 공용 ──
  RELIABILITY_CONTENT_KEYWORD_FALLBACK:
    'The LLM was unavailable, so content/task fulfilment was judged by keyword matching only. This score is not the result of a content judgement and must not be shown to the test taker.',
  RELIABILITY_NO_CHECKLIST:
    'The item has no checklist, so content/task fulfilment could not be judged.',

  // ── POST /score ──
  SUBSCORE_PARTIAL_AREAS: 'The {areas} area(s) were computed with some features missing.',
  SUBSCORE_NO_FEATURES: 'There is not a single feature available to compute a score from.',
  SUBSCORE_NO_SCORABLE_AREA: 'No area could be scored, so no overall score was produced.',
  SUBSCORE_AREA_PARTIAL: "The '{label}' area was computed with some features missing: {note}",
  SUBSCORE_AREA_FAILED: "The '{label}' area could not be scored: {note}",
  SUBSCORE_NOTE_LIST: '{notes}',
  SUBSCORE_DELIVERY_NO_PRONUNCIATION:
    'No pronunciation assessment result, so this area was not scored (excluded from the overall score). This happens for writing answers, or when transcription was done by a provider that cannot measure pronunciation.',
  SUBSCORE_CHECKLIST_FALLBACK:
    'The checklist was judged by the provisional fallback (keyword matching).',
  SUBSCORE_CHECKLIST_MISSING:
    'There is no checklist, so the fulfilment rate could not be reflected.',
  SUBSCORE_FEATURE_EXCLUDED:
    "Feature '{featureId}' is unavailable, so the weights were redistributed.",
  SUBSCORE_BANMAL_UNAVAILABLE:
    'The count of casual-speech intrusions could not be determined, so the weights were redistributed.',
  SUBSCORE_FEATURES_EXCLUDED_GROUP: '{count} feature(s) excluded ({featureIds}) - {reason}',

  // ── POST /score ──
  TRANSCRIPT_SKIPPED_FOR_WRITING:
    'STT transcript correction is not applied to writing answers. The text was typed by the test taker, so correcting it would erase real errors.',
  TRANSCRIPT_APPLIED:
    'STT transcript correction was applied in {count} place(s). The corrected text is used only for content/task fulfilment; grammar and vocabulary were scored on the raw transcript.',

  // ── POST /score ──
  ERRORS_UNEXPECTED_FAILURE: 'Error-feature extraction failed unexpectedly: {reason}',

  // ── POST /score ──
  CHECKLIST_UNEXPECTED_FAILURE: 'Checklist judging failed unexpectedly: {reason}',

  // ── POST /score ──
  TRANSCRIPT_LOW_CONFIDENCE_OVERLAP:
    '{count} error finding(s) overlap a corrected region of the transcript and were marked low-confidence. They may be transcription errors miscounted as grammar errors, so check them before using them to deduct points.',

  // ── POST /score ──
  STT_SCORED_FROM_TRANSCRIPT:
    'The audio was transcribed by {provider} ({model}) and that text was scored. The transcript may differ from what the test taker actually said, so check meta.stt_transcript together with the original recording if it is disputed.',
  STT_PRONUNCIATION_UNAVAILABLE:
    'Pronunciation could not be assessed, so delivery was not scored (transcription by {provider} succeeded).',
  STT_PRONUNCIATION_SEPARATE:
    'Delivery was scored separately by {pronouncer} pronunciation assessment (transcription was done by {sttProvider}).',

  // ── POST /score ──
  AUDIO_DURATION_UNMEASURABLE:
    'The duration of a {format} file cannot be measured from the file itself. If the recording length is needed, send it as audio.duration_ms.',

  // ── POST /score ──
  AZURE_READALOUD_REFERENCE_USED:
    'This is a read-aloud item, so the given passage was used as the reference text for pronunciation assessment. The transcript may have been pulled toward that passage, so check it before using it as evidence for grammar scoring.',
  AZURE_NO_PROSODY_SCORE:
    'No ProsodyScore was returned, so intonation was not scored within delivery.',
  AZURE_COMPLETENESS_UNUSED:
    'This is free speech, so there is no reference text to read. Completeness was not used in scoring.',

  // ── POST /score ──
  ERRORS_LLM_DISABLED:
    'LLM use is turned off, so the error features (particles, endings, word choice, honorifics) could not be computed.',
  ERRORS_API_KEY_MISSING:
    'GEMINI_API_KEY is missing, so the error features could not be computed. The language-use score is a provisional result computed from rule-based features only.',
  ERRORS_EXTRACTION_FAILED:
    'LLM error-feature extraction failed (continuing with rule-based features only): {reason}',
  ERRORS_NO_ERRORS_LIST:
    "The LLM response has no 'errors' list, so the error count was treated as zero.",

  // ── POST /score ──
  CITATION_DISCARDED_WRAP: "Citation discarded: '{quote}' - {reason}",
  CITATION_EMPTY: 'The citation is empty',
  CITATION_TOO_SHORT:
    'The citation is too short to count as evidence (minimum {minLength} characters)',
  CITATION_ITEM_MALFORMED: 'The item is not in a valid format',
  CITATION_FIELD_MISSING: 'The citation field is missing',
  CITATION_NOT_FOUND: 'The citation cannot be found in the original answer (discarded)',

  // ── POST /score ──
  TRANSCRIPT_REASON_DISCARDED: "Transcript correction reason discarded: '{claimed}' - {reason}",
  TRANSCRIPT_NO_CORRECTED_TEXT:
    'The correction response has no corrected_text, so the raw transcript is used as is.',
  TRANSCRIPT_NOTHING_TO_FIX:
    'The correction found nothing to fix, so the raw transcript is used as is.',
  TRANSCRIPT_OVERCORRECTION_DISCARDED:
    '*** Correction discarded *** {changedRatio} of the transcript was changed, which counts as over-correction (limit {maxRatio}). Scoring proceeds on the raw transcript.',
  TRANSCRIPT_SOURCE_EMPTY: 'The raw transcript is empty, so no correction was made.',
  TRANSCRIPT_LLM_DISABLED:
    'LLM use is turned off, so no STT transcript correction was made. Content/task fulfilment is also scored on the raw transcript.',
  TRANSCRIPT_API_KEY_MISSING:
    'GEMINI_API_KEY is missing, so no STT transcript correction could be made. Content/task fulfilment is fully exposed to transcription errors.',
  TRANSCRIPT_FAILED:
    'STT transcript correction failed (scoring proceeds on the raw transcript): {reason}',

  // ── POST /score ──
  CHECKLIST_NO_RESULTS_LIST:
    "The LLM response has no 'results' list, so every checklist item was treated as unmet.",
  CHECKLIST_ITEM_MISSING_VERDICT:
    "There is no LLM verdict for checklist item '{itemId}', so it was scored 0.",
  CHECKLIST_CITATION_DISCARDED:
    "Checklist item '{itemId}': the citation backing the 'met' verdict is not in the original answer, so it was discarded and the item was lowered to unmet (0) - {reason}",
  CHECKLIST_FALLBACK_USED:
    '*** Provisional *** The LLM was unavailable, so the checklist was judged by keyword matching only. This is a fallback value, not a content judgement, and must not be used for operational scoring.',
  CHECKLIST_NONE: 'The item has no checklist, so content/task fulfilment cannot be judged.',
  CHECKLIST_LLM_UNUSED_WRAP: 'Reason the LLM was not used: {reason}',
  CHECKLIST_LLM_DISABLED_OPTION: 'LLM use was turned off in the options',
  CHECKLIST_API_KEY_MISSING: 'GEMINI_API_KEY is missing',
  CHECKLIST_JUDGE_FAILED: 'LLM checklist judging failed: {reason}',
  CHECKLIST_COMMENT_NO_VERDICT: 'The LLM did not judge this item, so it was treated as unmet.',
  CHECKLIST_NOTE_NO_VERDICT: 'LLM response missing',
  CHECKLIST_COMMENT_UNMET_FALLBACK: 'This content was not found in the answer.',
  CHECKLIST_COMMENT_CITATION_DISCARDED:
    'The LLM judged this met, but the supporting citation is not in the original answer, so it was discarded. ({reason})',
  CHECKLIST_NOTE_CITATION_DISCARDED: 'Marked unmet because the supporting citation was discarded',
  CHECKLIST_COMMENT_MET_FALLBACK: 'This content was confirmed in the answer.',
  CHECKLIST_COMMENT_FALLBACK_MET:
    "*** Provisional verdict *** the keyword '{keyword}' appears in the answer",
  CHECKLIST_NOTE_FALLBACK:
    '*** Provisional *** fallback verdict based on keyword matching (LLM not used)',
  CHECKLIST_COMMENT_FALLBACK_UNMET:
    '*** Provisional verdict *** no related keyword was found in the answer',
  CHECKLIST_MET: 'Met',
  CHECKLIST_UNMET: 'Unmet',
  CHECKLIST_EVIDENCE_WRAP: '[{mark}] {description} - {comment}',

  // ── POST /score ──
  VALIDITY_EVIDENCE_NON_HANGUL_RUN: 'A run of non-Korean characters',
  VALIDITY_EVIDENCE_HEAD:
    'Beginning of the answer ({hangul} Korean characters out of {counted} counted)',
  VALIDITY_EVIDENCE_WORD_COUNT: '{words} words in the whole answer',
  VALIDITY_EVIDENCE_PROMPT_COPY: 'A run copied verbatim from the prompt',
  VALIDITY_EVIDENCE_NO_ENDING: 'A fragment with no predicate ending, hard to read as a sentence',

  // ── POST /score ──
  TRANSCRIPT_EVIDENCE_WRAP: 'STT transcript correction: {change} - {reason}',
  TRANSCRIPT_EVIDENCE_NO_REASON: 'STT transcript correction: {change}',

  // ── POST /score, /finalize 공용 ──
  RELIABILITY_LOW_EVIDENCE_WRAP: '[Low confidence] {comment}',
  RELIABILITY_LOW_EVIDENCE_DETAIL:
    'This span is where the STT transcript was corrected. It may be a transcription error rather than a grammar error by the test taker.',
  RELIABILITY_LOW_NOTE:
    '{count} of these findings come from a corrected span of the transcript and are therefore low-confidence (they may be transcription errors).',

  // ── POST /score ──
  TRANSCRIPT_CORRECTED_FEATURE_NOTE:
    'This feature feeds the content/task area, so it was computed on the corrected transcript. The character offsets in the evidence also refer to the corrected transcript.',

  // ── POST /score ──
  SCORE_PROVISIONAL_WEIGHTS:
    '*** Provisional *** The combination weights and grade cutoffs are hand-set values, not learned ones. Do not use them as absolute grades; use them only to compare answers.', // 내부용 — 응시자 화면에 노출 안 함

  // ── POST /score, /generate-items, /finalize 공용 — LLM 실패 사유 ──
  LLM_QUOTA_EXHAUSTED:
    'The daily LLM request quota is used up (429). Wait for the quota to reset or enable billing.',
  LLM_MODEL_NOT_FOUND:
    'The requested LLM model is not available (404). Check GEMINI_MODEL in .env.',
  LLM_PERMISSION_DENIED: 'Access to the LLM was denied (403). Check that the API key is correct.',
  LLM_UNAUTHENTICATED: 'LLM authentication failed (401). Check the API key.',
  LLM_TIMEOUT: 'The LLM did not answer within the time limit.',
  LLM_SERVER_ERROR: 'The LLM server is temporarily not responding.',
  LLM_CONNECTION_FAILED: 'Could not connect to the LLM server. Check the network.',
  LLM_CALL_FAILED: 'The LLM call failed ({excType}).',
  LLM_API_KEY_MISSING:
    'GEMINI_API_KEY is not set. Put the key in the .env file or an environment variable.',
  LLM_RESPONSE_TRUNCATED:
    'The LLM answer was cut off by the length limit (the answer budget was too small).',
  LLM_RESPONSE_TRUNCATED_RETRIED:
    'The LLM answer was cut off by the length limit (it was still cut off after retrying with a larger budget).',
  LLM_EMPTY_RESPONSE:
    'The LLM returned an empty response (it was blocked by a safety filter or produced no answer).',
  LLM_JSON_PARSE_FAILED: 'The LLM response could not be parsed as JSON.',
  LLM_JSON_NOT_OBJECT: 'The top level of the LLM response is not a JSON object.',

  // ── POST /finalize ──
  FINALIZE_EVIDENCE_WRAP: '[Item {itemId}] {comment}',
  FINALIZE_EXCLUDED_PENDING:
    '{count} item(s) whose scoring has not finished were excluded: {itemIds}',
  FINALIZE_EXCLUDED_MISSING: '{count} item(s) whose results never arrived were excluded: {itemIds}',
  FINALIZE_EXCLUDED_FAILED: '{count} item(s) that failed scoring were excluded: {itemIds}',
  FINALIZE_RELIABILITY_REASON:
    'The scoring of {count} item(s) ({itemIds}) is not intact - {worstReason}',
  FINALIZE_RELIABILITY_REASON_PLAIN: 'The scoring of {count} item(s) ({itemIds}) is not intact',
  FINALIZE_GRADE_WITHHELD:
    'The final grade was withheld because too few items were scored ({scored}/{total} items, weight {weight}). Requirement: at least {minItems} items and weight {minWeight} or more. *** These thresholds are provisional. ***',
  FINALIZE_CROSS_CHECK_WRAP: 'Cross-check signal: {note}',
  FINALIZE_CROSS_CHECK_GAP:
    'Speaking {speaking} / writing {writing} - a gap of {gap} grade(s) ({higher} is higher). A human review is recommended. *** This is only a review hint, not a cheating verdict. The threshold of {threshold} grade(s) is provisional. ***',
  FINALIZE_CROSS_CHECK_OK:
    'Speaking {speaking} / writing {writing}, a gap of {gap} grade(s), within the threshold of {threshold} grade(s).',
  FINALIZE_CROSS_CHECK_ONE_MODE_MISSING:
    'One of speaking and writing was not scored, so the cross-check could not be done.',
  FINALIZE_CROSS_CHECK_UNKNOWN_GRADE:
    'A value outside the grade table arrived, so the cross-check could not be done.',
  FINALIZE_CROSS_CHECK_TOO_FEW_ITEMS: 'Too few items were scored, so the cross-check was not done.',
  FINALIZE_AREA_DELIVERY_NOT_INTRODUCED:
    'Azure pronunciation assessment is not in place yet, so this area is out of scope and not scored (excluded from the overall score).',
  FINALIZE_AREA_NO_ITEMS: 'No item scored this area, so no final score could be produced.',
  FINALIZE_AREA_WEIGHTED_MEAN: 'The per-item scores were averaged using the item weights.',
  FINALIZE_AREA_PARTIAL:
    'Some items were scored with features missing, so the final score is a partial result too.',
  FINALIZE_PROVISIONAL_WEIGHTS:
    '*** Provisional *** The combination weights are not learned, the grade cutoffs do not come from expert-confirmed anchor answers, and the percentile comes from a provisional conversion table rather than a real test-taker distribution. Do not report this as a confirmed grade.', // 내부용 — 응시자 화면에 노출 안 함

  // ── POST /score, /finalize 공용 ──
  RELIABILITY_WRAP: '[Reliability: {level}] {reason}',

  // ── POST /generate-items ──
  GEN_SPEAKING_NOT_SUPPORTED:
    'Only writing items can be generated for now. Speaking item generation does not exist yet.',
  GEN_DOCUMENT_TOO_SHORT:
    'The document is {chars} characters long, too short to generate items from (minimum {minChars}).',
  GEN_DOCUMENT_TOO_LONG:
    'The document is {chars} characters long, too long (maximum {maxChars}). Split it into chapters or sections and send them separately.',
  GEN_KEYWORD_REMOVED:
    '[{itemId}] Removed the keyword(s) {keywords} that do not appear in the document (so the fallback scoring used when the LLM is unavailable does not misfire).',
  GEN_NO_ITEMS_PRODUCED:
    'The model produced no items at all. Check the document content and try again.',
  GEN_ALL_DROPPED:
    'All {count} generated item(s) were dropped at the validation gates. Items without traceable evidence are never released. Try again with a different document.',
  GEN_FEWER_THAN_REQUESTED:
    'Only {passed} of the {requested} requested items passed the gates. Ask again with a larger item count if you need more.',
  GEN_TYPE_SKEWED:
    "{count} items are concentrated in the '{itemType}' type. Check that the test is not asking about only one situation.",
  GEN_DUPLICATE_ITEM:
    'The prompt largely overlaps the previous item, so it is effectively the same item.',
  GEN_MEMORIZATION_SUSPECT:
    "[{itemId}] The prompt contains '{marker}', which may make it look like a memorization question. A human should check it before approval.",

  // ── POST /generate-items, /verify-items 공용 ──
  DROP_NOT_OBJECT: 'The item is not shaped like a JSON object.',
  DROP_REQUIRED_FIELD_MISSING: "The required field '{key}' is empty or is not a string.",
  DROP_CHECKLIST_NOT_LIST: "'checklist' is not a list.",
  DROP_ITEM_TYPE_INVALID: "Item type '{itemType}' is not a usable type (allowed: {allowed}).",
  DROP_REGISTER_INVALID: "Register '{register}' is neither formal nor polite.",
  DROP_CHECKLIST_COUNT: 'The checklist has {count} entries (allowed {min}-{max}).',
  DROP_CHECKLIST_ENTRY_NOT_OBJECT: 'Checklist entry #{index} is not an object.',
  DROP_CHECKLIST_ENTRY_NO_DESCRIPTION: 'Checklist entry #{index} has no description.',
  DROP_CHECKLIST_WEIGHT_NOT_NUMBER: 'The weight of checklist entry #{index} is not a number.',
  DROP_CHECKLIST_WEIGHT_OUT_OF_RANGE:
    'The weight of checklist entry #{index} is {weight}, outside the allowed range ({min}-{max}).',
  DROP_PROMPT_LENGTH: 'The prompt is {chars} characters long (allowed {min}-{max}).',
  DROP_PROMPT_NO_NUMBERING:
    'The prompt has none of the numbering markers {markers}, so what to write is not broken out into parts.',
  DROP_PROMPT_RUNON:
    'The prompt has a run of {chars} characters with no space (limit {maxChars}). It looks like text that lost its spacing in the document leaked through.',
  DROP_PROMPT_NO_WRITING_VERB:
    'The prompt contains no instruction to write (write, fill in, notify, ...). It reads as a knowledge question rather than a writing task.',
  DROP_EVIDENCE_EMPTY: 'The supporting citation is empty.',
  DROP_EVIDENCE_CROSSES_CHUNK:
    'The citation crosses a boundary where the document was split. These sentences are not contiguous in the real document.',
  DROP_EVIDENCE_JOINER:
    "The citation contains the joiner '{marker}', so it looks like several passages stitched together.",
  DROP_EVIDENCE_TOO_SHORT:
    'The citation is {chars} characters long, too short to count as evidence (minimum {minChars}).',
  DROP_EVIDENCE_TOO_LONG:
    'The citation is {chars} characters long, too long (maximum {maxChars}). Only a short passage should be cited so a human can check what it was based on.',
  DROP_EVIDENCE_WRAP: '{label}: {detail}',
  DROP_LABEL_ITEM_EVIDENCE: 'Item evidence',
  DROP_LABEL_CHECKLIST_EVIDENCE: 'Checklist #{index} evidence',
  DROP_EVIDENCE_NOT_FOUND:
    '{label}: this citation cannot be found in the document (treated as fabricated evidence and dropped).',
  DROP_ANSWER_IN_PROMPT:
    "{ratio} of the prompt's characters overlap the evidence passage verbatim (threshold {threshold}). The answer is inside the question.",
  DROP_TRIPS_COPY_GUARD:
    "An answer that copies the evidence passage verbatim would trip the scorer's 'prompt copying' guard. An honest test taker could be voided to zero on this item.",
  DROP_CONVERT_FAILED: 'The item could not be converted into the scoring API format ({type}).',

  // ── POST /verify-items ──
  VERIFY_DOCUMENT_MISMATCH:
    'The document sent differs from the one the items were generated from. Citation offsets may not line up, so check the document again.',
  VERIFY_DUPLICATE_ITEM:
    "The prompt largely overlaps item '{itemId}', so it has become effectively the same item.",
};
