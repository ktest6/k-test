"""채점 조각들을 순서대로 실행해 하나의 결과로 묶는 모듈.

역할은 '조립'뿐이다. 계산 규칙은 features/ 와 combine.py 에 있고,
여기서는 그것들을 어떤 순서로 부르고 결과를 어떻게 합칠지만 정한다.

이렇게 나눠 둔 이유:
채점 모델을 바꾸면 features/ 와 combine.py 는 바뀌지만
백엔드가 보는 입출력(schema.py)과 이 조립 순서는 그대로 둘 수 있다.

이 파일이 책임지는 두 가지 조립 규칙:

1) LLM 두 번을 동시에 보낸다.
   오류 자질 추출과 체크리스트 판정은 서로의 결과를 쓰지 않는다.
   차례로 보내면 두 번의 대기 시간을 그대로 더해서 기다리게 되므로 함께 보낸다.

2) 원본 전사와 보정본을 영역마다 다르게 쓴다.
   말하기 답안은 STT(음성을 글자로 옮기는 기계)가 옮겨 적은 글이라 틀린 곳이 있다.
   - 언어 사용(문법·어휘)은 '원본'으로 채점한다. 보정본은 응시자가 틀린 문법까지
     고쳐져 있어서, 그걸로 채점하면 점수가 부풀려진다.
   - 내용·과제 수행은 '보정본'으로 채점한다. 무슨 말을 했는지가 기준이라
     표기가 틀린 것은 방해물일 뿐이다.
   보정 자체는 llm/transcript.py 가 하고, 여기서는 그 결과를 영역별로 나눠 쓴다.
   자세한 근거는 scoring-design 스킬의 'STT 전사본을 채점에 쓰는 방법'에 있다.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..features.checklist import ChecklistJudgeResult, judge_checklist
from ..features.errors import ErrorExtractionResult, extract_error_features
from ..features.lexical import analyze, extract_lexical_features
from ..llm.client import GeminiClient, client_for_errors
from ..llm.transcript import correct_transcript
from .combine import combine, get_weights
from .messages import Notice, emit, join_notices, notice
from .schema import (
    SCORING_VERSION,
    AreaStatus,
    ChecklistResult,
    Evidence,
    FeatureSource,
    FeatureValue,
    Mode,
    Reliability,
    ScoreArea,
    ScoreRequest,
    ScoreResponse,
    ScoringMeta,
    SubScore,
)
from .validity import ValidityReport, check_answer_validity

# 값이 끼지 않는 고정 문구는 한 번만 만들어 두고 돌려 쓴다
_LOW_CONF_REASON = notice("RELIABILITY_LOW_EVIDENCE_DETAIL")
_CORRECTED_FEATURE_NOTE = notice("TRANSCRIPT_CORRECTED_FEATURE_NOTE")
_CONTENT_KEYWORD_FALLBACK = notice("RELIABILITY_CONTENT_KEYWORD_FALLBACK")
_NO_CHECKLIST = notice("RELIABILITY_NO_CHECKLIST")

if TYPE_CHECKING:  # 타입을 적기 위해서만 읽는다. 실행할 때는 speech 를 불러오지 않는다
    from ..speech.intake import AudioResolution
    from ..speech.port import SttPort

# 내용·과제 수행 영역이 쓰는 자질.
# 이 자질들만 보정본 기준으로 다시 계산해서 갈아 끼운다.
# (combine.py 의 content_feature_weights 와 짝을 이루는 목록이다)
CONTENT_AREA_FEATURE_IDS = ("response_length", "words_per_sentence")


@dataclass
class TranscriptContext:
    """STT 전사와 그 보정 결과를 채점 단계로 넘겨 주는 꾸러미.

    텍스트 답안(쓰기)이나 이미 전사된 텍스트를 그대로 채점할 때는 이 값이 없다.
    그때는 원본과 보정본이 같다고 보고 지금까지와 똑같이 동작한다.
    """

    corrected_text: str
    # 원본 전사에서 보정이 일어난 구간들. (시작, 끝) 글자 위치로 적는다.
    corrected_spans: list[tuple[int, int]] = field(default_factory=list)
    nationality: str | None = None
    correction_applied: bool = False
    # 무엇이 무엇으로 바뀌었는지 사람이 읽을 수 있는 근거.
    # 응시자가 "그렇게 말하지 않았다"고 할 때 짚어 줄 자료라 결과에 그대로 실어 보낸다.
    diff_evidence: list[Evidence] = field(default_factory=list)


def _mark_low_confidence_errors(
    features: list[FeatureValue],
    corrected_spans: list[tuple[int, int]],
) -> int:
    """보정이 일어난 자리에서 나온 오류 판정에 '신뢰도 낮음' 표시를 단다.

    왜 필요한가:
    언어 사용은 원본 전사로 채점하기 때문에, STT가 잘못 옮겨 적은 자리가
    응시자의 문법 오류로 잡힐 수 있다. 그 자리가 바로 보정이 일어난 자리다.
    지워 버리면 진짜 오류까지 놓치고, 그냥 두면 없는 잘못을 씌운다.
    그래서 판정은 남기되 '이 지적은 전사 오류일 수 있다'는 꼬리표를 붙인다.
    """
    if not corrected_spans:
        return 0

    marked = 0
    for feature in features:
        # LLM이 찾아낸 오류 자질만 대상이다. 규칙 자질은 세는 방식이 달라 해당 없다
        if feature.source != FeatureSource.LLM or not feature.id.startswith("error_"):
            continue

        low_confidence_here = 0
        for ev in feature.evidence:
            if ev.start is None or ev.end is None:
                continue
            # 오류를 지적한 구간과 보정된 구간이 한 글자라도 겹치는지 본다
            overlaps = any(
                ev.start < span_end and span_start < ev.end
                for span_start, span_end in corrected_spans
            )
            if not overlaps:
                continue

            ev.detail["confidence"] = "low"
            ev.detail["low_confidence_reason"] = _LOW_CONF_REASON.message
            ev.detail["low_confidence_reason_code"] = _LOW_CONF_REASON.code
            # 원래 설명을 겉 문구로 한 번 감싸되, 안쪽 코드도 같이 남긴다
            wrapped = notice(
                "RELIABILITY_LOW_EVIDENCE_WRAP",
                comment=ev.comment,
                commentNotice=ev.notice,
            )
            ev.comment = wrapped.message
            ev.notice = wrapped
            low_confidence_here += 1
            marked += 1

        if low_confidence_here:
            feature.components["low_confidence_error_count"] = float(low_confidence_here)
            low_note = notice("RELIABILITY_LOW_NOTE", count=low_confidence_here)
            feature.note = (
                (feature.note + " / ") if feature.note else ""
            ) + low_note.message
            # 앞에 이미 다른 note 가 있었으면 둘을 묶고, 없으면 이것 하나만 담는다
            feature.notice = (
                join_notices([feature.notice, low_note])
                if feature.notice is not None
                else low_note
            )

    return marked


def _swap_in_content_features(
    features: list[FeatureValue],
    corrected_text: str,
    mode: Mode,
) -> None:
    """내용·과제 수행이 쓰는 자질만 보정본 기준 값으로 갈아 끼운다.

    '얼마나 말했는가'를 재는 자질(응답 길이, 문장당 어절 수)은
    무슨 말을 했는지가 기준이므로 보정본으로 세는 것이 맞다.
    문법·어휘 자질은 손대지 않는다. 그쪽은 원본으로 세야 한다.
    """
    corrected_features = {
        f.id: f for f in extract_lexical_features(corrected_text, mode)
    }

    for index, feature in enumerate(features):
        if feature.id not in CONTENT_AREA_FEATURE_IDS:
            continue
        replacement = corrected_features.get(feature.id)
        if replacement is None:
            continue

        # 근거의 글자 위치가 보정본 기준이라는 것을 반드시 밝혀 둔다.
        # 이 표시가 없으면 나중에 원본에서 그 위치를 찾다가 엉뚱한 데를 짚게 된다
        replacement.note = _CORRECTED_FEATURE_NOTE.message
        replacement.notice = _CORRECTED_FEATURE_NOTE
        for ev in replacement.evidence:
            ev.detail["text_source"] = "corrected"
        features[index] = replacement


def _resolve_transcript(
    request: ScoreRequest,
    client: GeminiClient,
    warnings: list[str],
    notices: list[Notice],
    timings: dict[str, float],
) -> TranscriptContext | None:
    """요청에 담긴 전사 보정 설정을 보고 실제로 보정을 수행한다.

    조립은 여기(pipeline)에서 한다. api.py 는 창구일 뿐이라
    무엇을 어떤 순서로 부를지 정하는 일을 두지 않는다는 규칙 때문이다.

    보정을 안 하기로 하면 None 을 돌려주고, 그러면 채점은 지금까지와
    똑같이 answer_text 하나로만 진행된다.
    """
    # 백엔드가 전사 설정을 안 보냈으면 지금까지와 똑같이 동작한다
    if request.transcript is None or not request.transcript.correct:
        return None

    # 쓰기 답안은 응시자가 직접 친 글이라 보정 대상이 아니다.
    # 여기서 보정하면 응시자가 실제로 틀린 맞춤법까지 지워져 점수가 부풀려진다
    if request.mode != Mode.SPEAKING:
        emit(warnings, notices, "TRANSCRIPT_SKIPPED_FOR_WRITING")
        return None

    started = time.perf_counter()
    correction = correct_transcript(
        request.answer_text,
        nationality=request.transcript.nationality,
        item_prompt=request.item.prompt,
        client=client,
        use_llm=request.options.use_llm,
    )
    timings["transcript_ms"] = round((time.perf_counter() - started) * 1000, 1)

    # 보정을 왜 못 했는지, 무엇을 물렸는지가 결과에 남아야 한다
    warnings.extend(correction.warnings)
    notices.extend(correction.notices)
    if correction.correction_applied:
        emit(warnings, notices, "TRANSCRIPT_APPLIED", count=correction.change_count)

    return TranscriptContext(
        corrected_text=correction.corrected_text,
        corrected_spans=correction.corrected_spans,
        nationality=correction.nationality,
        correction_applied=correction.correction_applied,
        diff_evidence=correction.to_evidence(),
    )


def _stt_meta_fields(audio: "AudioResolution | None") -> dict:
    """음성을 받아썼을 때만 채우는 meta 값들을 만든다.

    음성이 없으면 빈 값이라 응답은 지금까지와 완전히 같다.

    받아쓴 글(stt_transcript)까지 남기는 이유:
    말하기 점수는 응시자가 낸 소리가 아니라 기계가 받아쓴 글에 매겨진다.
    그 글이 남지 않으면 "왜 이 점수인가"에 답할 수 없다.
    """
    if audio is None:
        return {}
    return {
        "stt_provider": audio.provider,
        "stt_model": audio.model,
        "audio_duration_ms": audio.audio_duration_ms,
        "stt_transcript": audio.text,
    }


def _invalid_response(
    request: ScoreRequest,
    report: ValidityReport,
    warnings: list[str],
    notices: list[Notice],
    timings: dict[str, float],
    audio: "AudioResolution | None" = None,
) -> ScoreResponse:
    """가드에 걸린 답안을 '채점 무효'로 돌려준다.

    예외를 던지지 않는 이유:
    백엔드는 답안마다 이 함수를 부르고 결과를 저장한다. 여기서 예외가 나면
    백엔드가 실패 처리를 따로 만들어야 하고, 무효 사유도 전달되지 않는다.
    그래서 형태는 평소와 똑같은 응답을 주되 점수 자리만 비운다.

    점수를 0점으로 두지 않는 것이 중요하다.
    0점은 '한국어로 답했지만 다 틀렸다'는 뜻이고, 무효는 '채점할 수 없다'는 뜻이라
    서로 다른 상태다. 0점으로 때우면 이의 제기에 답할 수 없다.
    """
    # 규칙 자질은 계산해 둔다. LLM을 부르지 않으므로 비용이 들지 않고,
    # 운영자가 나중에 "이 답안이 어떤 글이었나"를 확인할 근거가 된다
    started = time.perf_counter()
    features = extract_lexical_features(request.answer_text, request.mode)
    timings["lexical_ms"] = round((time.perf_counter() - started) * 1000, 1)

    # 어느 영역도 채점하지 않았다는 사실을 영역마다 남긴다.
    # 자리를 없애면 백엔드가 받는 응답 구조가 상황에 따라 달라진다
    labels = [
        (ScoreArea.CONTENT_TASK, "내용 및 과제 수행"),
        (ScoreArea.LANGUAGE_USE, "언어 사용"),
        (ScoreArea.DELIVERY, "발화 전달력"),
    ]
    # 겉 문구와 안쪽 사유(가드가 왜 걸렸는지)를 둘 다 코드로 담는다
    note_notice = notice(
        "VALIDITY_NOT_SCORED_NOTE",
        reason=report.reason,
        reasonNotice=join_notices(report.notices),
    )
    note = note_notice.message
    subscores = [
        SubScore(
            area=area,
            label=label,
            score=None,
            weight=0.0,
            status=AreaStatus.NOT_EVALUATED,
            contributions=[],
            # 왜 무효인지의 근거(원문 어느 자리를 보고 판단했는지)를 함께 싣는다.
            # 영역마다 따로 복사해 둔다(한 곳에서 손댄 것이 다른 영역까지 바뀌면 안 된다)
            evidence=[ev.model_copy(deep=True) for ev in report.evidence[:6]],
            note=note[:300],
            notice=note_notice,
        )
        for area, label in labels
    ]

    meta = ScoringMeta(
        scoring_version=SCORING_VERSION,
        mode=request.mode,
        weights_profile=request.options.weights_profile,
        llm_used=False,
        llm_model=None,
        timings_ms=timings,
        # 채점 자체를 안 했으므로 '온전한 채점'은 아니다.
        # 다만 대체 경로로 때운 것도 아니므로 fallback 이 아니라 partial 로 둔다.
        # 무효라는 사실 자체는 answer_valid 로 따로 읽는다
        reliability=Reliability.PARTIAL,
        reliability_reason=report.reason,
        # 점수가 없으므로 화면에 띄울 것도 없다
        safe_to_show_candidate=False,
        answer_valid=False,
        validity_flags=report.flags,
        validity_reason=report.reason,
        # 음성으로 들어온 답안이 가드에 걸린 경우에도 받아쓴 글을 남긴다.
        # 이 글이 없으면 '응시자가 이상하게 말한 것'인지 '받아쓰기가 실패한 것'인지
        # 나중에 가릴 수 없다
        **_stt_meta_fields(audio),
    )

    return ScoreResponse(
        submission_id=request.submission_id,
        item_id=request.item.item_id,
        mode=request.mode,
        overall_score=None,
        overall_grade=None,
        subscores=subscores,
        features=features,
        checklist_results=[],
        warnings=warnings,
        notices=notices,
        meta=meta,
    )


def _apply_soft_validity_flags(
    subscores: list[SubScore],
    report: ValidityReport,
) -> tuple[list[str], list[Notice]]:
    """무효까지는 아니지만 미덥지 않은 답안에 대해 해당 영역의 상태를 낮춘다.

    점수 숫자는 건드리지 않는다. 손대면 그 숫자가 어디서 왔는지 설명할 수 없게 된다.
    대신 '이 영역 점수는 표본이 부족하다'는 사실을 상태와 note 로 남겨서,
    뒤따르는 신뢰도 판정(assess_reliability)이 partial 로 내려가게 만든다.
    """
    messages: list[str] = []
    made: list[Notice] = []
    by_area = {s.area: s for s in subscores}

    for check in report.soft_failures:
        # 낮출 영역이 정해지지 않은 가드는 경고만 남긴다
        target = by_area.get(check.affected_area) if check.affected_area else None
        emit(
            messages, made, "VALIDITY_SOFT_WRAP",
            reason=check.reason, reasonNotice=check.notice,
        )
        if target is None or target.score is None:
            continue

        # 이미 반쪽으로 계산된 영역이면 상태는 그대로 두고 사유만 덧붙인다
        if target.status == AreaStatus.SCORED:
            target.status = AreaStatus.PARTIAL
        target.note = ((target.note + " / ") if target.note else "") + check.reason
        target.note = target.note[:300]
        # 원래 있던 영역 note 와 이번 가드 사유를 코드 목록으로 묶어 둔다
        if check.notice is not None:
            target.notice = (
                join_notices([target.notice, check.notice])
                if target.notice is not None
                else check.notice
            )
        target.evidence.extend(ev.model_copy(deep=True) for ev in check.evidence[:2])

    return messages, made


def _run_llm_stages_in_parallel(
    language_text: str,
    content_text: str,
    request: ScoreRequest,
    client: GeminiClient,
    error_client: GeminiClient,
    use_llm: bool,
    timings: dict[str, float],
) -> tuple[ErrorExtractionResult, ChecklistJudgeResult]:
    """오류 자질 추출과 체크리스트 판정을 동시에 보낸다.

    둘 다 네트워크 응답을 기다리는 일이라 스레드 두 개로 겹쳐 두면
    기다리는 시간이 '둘의 합'이 아니라 '둘 중 긴 쪽'이 된다.

    두 호출은 **모델도 다르다.** 오류 자질만 error_client(상위 모델)로 보낸다.
    기본 모델이 높임법 오류를 놓치는 것이 실측으로 확인됐기 때문이다.
    체크리스트 판정은 '했는가/안 했는가'라 기본 모델로 충분하다.

    한쪽이 실패해도 다른 쪽 결과는 살려야 한다.
    두 함수는 원래 LLM 실패를 안에서 삼키도록 만들어져 있지만,
    그래도 예상 못 한 예외가 나면 여기서 받아서 채점 전체가 멈추는 것을 막는다.
    """

    def run_errors() -> tuple[ErrorExtractionResult, float]:
        started = time.perf_counter()
        result = extract_error_features(
            language_text,                 # 문법·어휘는 원본으로 센다
            mode=request.mode,
            client=error_client,           # 오류 자질만 상위 모델로 본다
            item_prompt=request.item.prompt,
            use_llm=use_llm,
        )
        return result, round((time.perf_counter() - started) * 1000, 1)

    def run_checklist() -> tuple[ChecklistJudgeResult, float]:
        started = time.perf_counter()
        result = judge_checklist(
            content_text,                  # 무슨 말을 했는지는 보정본으로 본다
            request.item,
            client=client,
            use_llm=use_llm,
        )
        return result, round((time.perf_counter() - started) * 1000, 1)

    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ktest-llm") as pool:
        errors_future = pool.submit(run_errors)
        checklist_future = pool.submit(run_checklist)

        # 한쪽이 터져도 다른 쪽 결과를 버리지 않도록 각각 따로 받는다
        try:
            error_result, errors_ms = errors_future.result()
        except Exception as exc:  # pragma: no cover - 방어용
            error_result = extract_error_features(
                language_text, mode=request.mode, client=error_client,
                item_prompt=request.item.prompt, use_llm=False,
            )
            emit(
                error_result.warnings, error_result.notices,
                "ERRORS_UNEXPECTED_FAILURE", reason=str(exc),
            )
            errors_ms = 0.0

        try:
            checklist_result, checklist_ms = checklist_future.result()
        except Exception as exc:  # pragma: no cover - 방어용
            checklist_result = judge_checklist(
                content_text, request.item, client=client, use_llm=False,
            )
            emit(
                checklist_result.warnings, checklist_result.notices,
                "CHECKLIST_UNEXPECTED_FAILURE", reason=str(exc),
            )
            checklist_ms = 0.0

    # 각 호출이 걸린 시간과, 둘을 겹쳐 실제로 기다린 시간을 따로 남긴다.
    # errors_ms + checklist_ms 가 llm_parallel_ms 보다 큰 것이 정상이다
    # (두 작업이 같은 시간대를 함께 쓰기 때문이다).
    timings["errors_ms"] = errors_ms
    timings["checklist_ms"] = checklist_ms
    timings["llm_parallel_ms"] = round((time.perf_counter() - wall_started) * 1000, 1)

    return error_result, checklist_result


def assess_reliability(
    subscores: list[SubScore],
    checklist_results: list[ChecklistResult],
    had_checklist: bool,
) -> tuple[Reliability, str, Notice | None]:
    """이번 채점을 얼마나 믿을 수 있는지 한 값으로 정리한다.

    왜 이 판단이 필요한가:
    LLM이 죽어도 채점은 멈추지 않도록 만들어 두었는데, 그 덕분에
    **대체 경로로 계산한 점수도 겉보기에는 멀쩡한 숫자로 나온다.**
    실제로 같은 답안이 LLM이 살아 있을 때 70.6점, 대체 경로에서 79.7점이 나왔다.
    경고 문구는 달리지만 숫자만 보는 화면에서는 구별되지 않는다.

    그래서 '경고를 읽어야 아는 것'을 '값 하나만 보면 아는 것'으로 바꾼다.
    """
    # 가장 나쁜 경우부터 본다.
    # 체크리스트를 핵심어 일치로 때웠다면 내용·과제 수행 점수는 사실상 가짜다.
    # (핵심어가 하나만 걸려도 전 항목이 충족으로 잡히기 때문에 점수가 크게 부풀려진다)
    if had_checklist and any(c.source == FeatureSource.KIWI for c in checklist_results):
        return (
            Reliability.FALLBACK,
            _CONTENT_KEYWORD_FALLBACK.message,
            _CONTENT_KEYWORD_FALLBACK,
        )

    # 문항이 체크리스트를 안 준 경우도 내용 영역의 근거가 없는 것은 마찬가지다
    if not had_checklist:
        return (Reliability.PARTIAL, _NO_CHECKLIST.message, _NO_CHECKLIST)

    # 채점은 됐지만 자질 일부가 빠진 경우. 점수는 참고할 수 있으나 온전하지는 않다
    partial_areas = [s.label for s in subscores if s.status == AreaStatus.PARTIAL]
    if partial_areas:
        made = notice("SUBSCORE_PARTIAL_AREAS", areas=", ".join(partial_areas))
        return (Reliability.PARTIAL, made.message, made)

    return Reliability.FULL, "", None


#: 'pronouncer 인자를 안 넘겼다'와 '일부러 None 으로 넘겼다'를 구별하는 표식.
#: 안 넘기면 speech 쪽 기본 발음 평가기를 쓰고, None 을 넘기면 발음을 재지 않는다.
_PRONOUNCER_UNSET = object()


def score_submission(
    request: ScoreRequest,
    client: GeminiClient | None = None,
    transcript: TranscriptContext | None = None,
    stt: "SttPort | None" = None,
    pronouncer=_PRONOUNCER_UNSET,
) -> ScoreResponse:
    """답안 하나를 채점해서 종합 점수 + 영역별 점수 + 근거를 돌려준다.

    LLM을 못 쓰는 상황이어도 예외를 던지지 않는다.
    대신 그 사실이 warnings 와 자질 상태에 남고, 규칙 자질만으로 계산을 이어간다.

    transcript 를 넘기면 STT 원본/보정본을 영역별로 나눠 쓴다.
    직접 넘기지 않아도 요청(request.transcript)에 보정을 켜 두었으면
    여기서 만들어 쓴다. 둘 다 없으면 지금까지와 똑같이 answer_text 하나로만 채점한다.

    맨 앞에서 답안 유효성 가드를 돌린다. 한국어가 아니거나 지시문을 베낀 답안은
    여기서 걸러서 채점 무효(overall_score=None)로 돌려주고 LLM은 부르지 않는다.

    요청에 음성 파일(request.audio)이 붙어 있으면 그보다도 앞에서 받아쓴다.
    **받아쓰기만 예외를 던진다.** 못 알아들은 음성을 그럴듯한 문장으로 지어내면
    응시자가 하지도 않은 말로 점수를 받게 되므로 대체 경로를 두지 않았다
    (요청이 틀렸으면 AudioRequestError, 못 받아썼으면 SttUnavailable 이 올라간다).
    stt 를 넘기면 그것으로 받아쓴다(테스트가 네트워크 없이 도는 자리).
    """
    timings: dict[str, float] = {}
    warnings: list[str] = []
    # warnings 와 짝을 이루는 '코드 + 값' 목록. 두 목록의 길이와 차례는 항상 같다
    notices: list[Notice] = []

    # 키가 없으면 available 이 False 인 클라이언트가 만들어진다(예외는 나지 않는다)
    client = client or GeminiClient()

    # -1단계: 음성 답안이면 채점하기 전에 글로 옮긴다.
    # 채점은 언제나 '글'을 본다는 규칙을 지키려고 여기서 끝내고 answer_text 에 넣는다.
    # (speech 를 이 자리에서 불러오는 이유: 음성을 안 쓰는 채점에서는
    #  내려받기 라이브러리까지 읽을 일이 없게 하려는 것이다)
    audio_resolution: "AudioResolution | None" = None
    if request.audio is not None:
        from ..speech.intake import resolve_audio_answer

        # 발음 평가기는 전사와 따로 정한다. 안 넘겼으면 speech 쪽 기본 규칙에 맡기고
        # (그쪽이 stt 주입 여부까지 보고 판단한다), 명시적으로 넘겼으면 그대로 전달한다
        if pronouncer is _PRONOUNCER_UNSET:
            audio_resolution = resolve_audio_answer(request, stt=stt)
        else:
            audio_resolution = resolve_audio_answer(request, stt=stt, pronouncer=pronouncer)
        if audio_resolution is not None:
            # 받아쓴 글을 answer_text 자리에 넣은 요청으로 바꿔 든다.
            # 원래 요청을 고치지 않고 사본을 만드는 이유는, 부르는 쪽이 넘긴 값이
            # 우리 때문에 바뀌면 그쪽에서 무슨 일이 일어났는지 알 수 없기 때문이다
            request = request.model_copy(update={"answer_text": audio_resolution.text})
            warnings.extend(audio_resolution.warnings)
            notices.extend(audio_resolution.notices)
            timings["stt_ms"] = audio_resolution.elapsed_ms

    # 오류 자질만 상위 모델로 본다. 나머지(전사 보정·체크리스트)는 기본 모델 그대로다
    error_client = client_for_errors(client)
    use_llm = request.options.use_llm

    # 0단계: 답안 유효성 가드. 규칙으로만 판단하며 LLM보다 반드시 앞에 선다.
    # 무효 답안에 LLM 호출을 낭비하지 않기 위해서이고,
    # 전사 보정도 LLM 호출이라 그보다도 앞이어야 한다
    started = time.perf_counter()
    analysis = analyze(request.answer_text)
    validity = check_answer_validity(
        request.answer_text, request.item.prompt, analysis=analysis
    )
    timings["validity_ms"] = round((time.perf_counter() - started) * 1000, 1)

    # 하드 게이트에 걸리면 여기서 끝난다. 점수 대신 무효 사유를 돌려준다
    if not validity.valid:
        for check in validity.hard_failures:
            emit(
                warnings, notices, "VALIDITY_INVALID_WRAP",
                reason=check.reason, reasonNotice=check.notice,
            )
        return _invalid_response(
            request, validity, warnings, notices, timings, audio_resolution
        )

    # 1단계: 전사 보정. 부르는 쪽이 이미 만들어 넘겼으면 그것을 그대로 쓴다
    # (직접 넘긴 값이 항상 우선이다. 테스트와 데모가 보정 결과를 손으로 지정할 수 있어야 한다)
    if transcript is None:
        transcript = _resolve_transcript(request, client, warnings, notices, timings)

    # 어느 글로 무엇을 채점할지 먼저 정한다.
    # 보정본이 없으면 둘 다 원문이라 지금까지와 동작이 같다
    language_text = request.answer_text
    content_text = transcript.corrected_text if transcript else request.answer_text

    # 2단계: 규칙 자질. LLM과 무관하게 항상 계산되는, 채점의 뼈대다
    started = time.perf_counter()
    features = extract_lexical_features(language_text, request.mode)
    if transcript and transcript.correction_applied:
        # 내용·과제 수행이 쓰는 자질만 보정본 기준으로 바꿔 끼운다
        _swap_in_content_features(features, content_text, request.mode)
    timings["lexical_ms"] = round((time.perf_counter() - started) * 1000, 1)

    # 2-1단계: 발음 자질. 음성을 직접 들은 기계(Azure)가 준 값이 있을 때만 붙는다.
    # 이 자질이 붙으면 발화 전달력(delivery) 영역이 채점되고, 없으면 예전처럼
    # 그 영역이 비어 있는 채로 내용·언어 두 영역만으로 종합 점수가 나온다.
    # (발음은 규칙으로도 LLM으로도 셀 수 없어서 features/ 안에 따로 자리를 두었다)
    if audio_resolution is not None and audio_resolution.pronunciation is not None:
        from ..features.pronunciation import extract_pronunciation_features

        features.extend(
            extract_pronunciation_features(
                audio_resolution.pronunciation, request.answer_text
            )
        )

    # 3단계: LLM이 하는 두 가지 일을 동시에 보낸다.
    # 오류 자질은 원본으로, 체크리스트는 보정본으로 각각 다른 글을 본다
    error_result, checklist_result = _run_llm_stages_in_parallel(
        language_text=language_text,
        content_text=content_text,
        request=request,
        client=client,
        error_client=error_client,
        use_llm=use_llm,
        timings=timings,
    )
    features.extend(error_result.features)
    warnings.extend(error_result.warnings)
    notices.extend(error_result.notices)
    warnings.extend(checklist_result.warnings)
    notices.extend(checklist_result.notices)

    # 4단계: 보정이 일어난 자리에서 나온 오류 지적에 신뢰도 표시를 단다
    marked = 0
    if transcript and transcript.corrected_spans:
        marked = _mark_low_confidence_errors(features, transcript.corrected_spans)
        if marked:
            emit(warnings, notices, "TRANSCRIPT_LOW_CONFIDENCE_OVERLAP", count=marked)

    # 5단계: 자질과 판정을 점수로 결합한다
    started = time.perf_counter()
    weights = get_weights(request.options.weights_profile)
    combined = combine(
        features=features,
        checklist_results=checklist_result.results,
        mode=request.mode,
        weights=weights,
    )
    timings["combine_ms"] = round((time.perf_counter() - started) * 1000, 1)
    warnings.extend(combined.warnings)
    notices.extend(combined.notices)

    # 6단계: 무효까지는 아닌 가드(짧은 답안·문장이 덜 갖춰진 답안)를 영역 상태에 반영한다.
    # 결합이 끝난 뒤에 하는 이유는 낮출 대상이 '계산된 영역 점수'이기 때문이다.
    # 여기서 partial 로 내려가면 바로 아래 신뢰도 판정도 따라 내려간다
    soft_messages, soft_notices = _apply_soft_validity_flags(combined.subscores, validity)
    warnings.extend(soft_messages)
    notices.extend(soft_notices)

    # 버려진 인용은 두 단계에서 나올 수 있으므로 합쳐서 보고한다.
    # 이 숫자가 크면 LLM이 답안에 없는 말을 지어내고 있다는 신호다
    dropped = error_result.dropped_citations + checklist_result.dropped_citations

    # 보정을 몇 군데 했는지. 근거 목록이 있으면 그 개수를 쓰고,
    # 근거 없이 구간만 넘어온 경우(부르는 쪽이 손으로 만든 경우)에는 구간 수로 센다
    correction_applied = bool(transcript and transcript.correction_applied)
    if transcript:
        change_count = len(transcript.diff_evidence) or len(transcript.corrected_spans)
    else:
        change_count = 0

    # 이 점수를 화면에 띄워도 되는지를 값 하나로 정리한다.
    # 경고 문구를 읽어서 판단하게 두면 프론트가 그냥 숫자만 띄우게 된다
    reliability, reliability_reason, reliability_notice = assess_reliability(
        combined.subscores,
        checklist_result.results,
        had_checklist=bool(request.item.checklist),
    )
    if reliability != Reliability.FULL and reliability_reason:
        emit(
            warnings, notices, "RELIABILITY_WRAP",
            level=reliability.value,
            reason=reliability_reason,
            reasonNotice=reliability_notice,
        )

    meta = ScoringMeta(
        scoring_version=SCORING_VERSION,
        mode=request.mode,
        weights_provisional=weights.provisional,
        weights_profile=weights.profile,
        llm_used=error_result.llm_used or checklist_result.llm_used,
        llm_model=client.model_name if client.available else None,
        # 문법을 판정한 모델이 따로라는 사실을 남긴다. 이것이 없으면
        # 나중에 같은 답안을 다시 채점했을 때 값이 왜 달라졌는지 설명할 수 없다
        llm_model_errors=(
            error_client.model_name if error_result.llm_used else None
        ),
        dropped_citations=dropped,
        timings_ms=timings,
        reliability=reliability,
        reliability_reason=reliability_reason,
        # 대체 경로로 때운 점수는 숫자가 멀쩡해 보여도 보여주면 안 된다
        safe_to_show_candidate=(reliability != Reliability.FALLBACK),
        # 하드 게이트는 위에서 이미 걸러졌으므로 여기까지 왔다면 채점은 유효하다.
        # 소프트 가드에 걸린 경우에는 표시만 남는다(점수는 그대로 나간다)
        answer_valid=True,
        validity_flags=validity.flags,
        validity_reason=validity.reason,
        # 전사 보정이 있었다면 그 사실과 내역을 반드시 결과에 싣는다.
        # 보정본으로 채점해 놓고 무엇을 고쳤는지 안 밝히면 이의 제기에 답할 수 없다
        transcript_correction_applied=correction_applied,
        transcript_change_count=change_count,
        transcript_low_confidence_errors=marked,
        transcript_corrected_text=(
            transcript.corrected_text if correction_applied else None
        ),
        transcript_diff=list(transcript.diff_evidence) if transcript else [],
        # 음성으로 들어온 답안이면 어느 기계가 무엇으로 받아썼는지를 남긴다.
        # 음성이 없으면 전부 빈 값이라 지금까지의 응답과 똑같다
        **_stt_meta_fields(audio_resolution),
    )

    return ScoreResponse(
        submission_id=request.submission_id,
        item_id=request.item.item_id,
        mode=request.mode,
        overall_score=combined.overall_score,
        overall_grade=combined.overall_grade,
        subscores=combined.subscores,
        features=features,
        checklist_results=checklist_result.results,
        warnings=warnings,
        notices=notices,
        meta=meta,
    )
