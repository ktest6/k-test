"""백엔드가 호출하는 REST 엔드포인트.

이 파일은 '창구'일 뿐이다. 채점 계산은 하나도 여기 두지 않는다.
받은 요청을 파이프라인에 넘기고 결과를 그대로 돌려주기만 한다.

이렇게 하는 이유:
채점 모델을 바꾸거나 자질을 다시 계산해도 백엔드가 보는 주소와 형식이 바뀌면 안 된다.
입출력 형식은 전부 scoring/schema.py 에 있고, 여기서는 그것을 가리키기만 한다.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException

from .auth import API_KEY_HEADER, auth_enabled, require_api_key
from .features.errors import ERROR_TYPES, COMMON_ERROR_TYPES, WRITING_ONLY_ERROR_TYPES
from .features.lexical import (
    KIWI_FEATURE_IDS,
    WRITING_ONLY_KIWI_FEATURE_IDS,
    extract_lexical_features,
    is_default_vocab_list,
)
from .generation.generate import GenerationRequestError, generate_items, verify_items
from .generation.llm import DEFAULT_GENERATION_MODEL
from .generation.schema import (
    GENERATION_VERSION,
    MAX_DOCUMENT_CHARS,
    MIN_DOCUMENT_CHARS,
    GenerateItemsRequest,
    GenerateItemsResponse,
    VerifyItemsRequest,
    VerifyItemsResponse,
)
from .llm.client import GeminiClient, LLMUnavailable, client_for_errors
from .scoring.combine import DEFAULT_WEIGHTS
from .scoring.finalize import finalize_session
from .scoring.pipeline import score_submission
from .scoring.validity import (
    FLAG_NOT_KOREAN,
    FLAG_NOT_SENTENCES,
    FLAG_PROMPT_COPY,
    FLAG_TOO_SHORT,
    MAX_PROMPT_OVERLAP,
    MIN_EOJEOL_COUNT,
    MIN_HANGUL_RATIO,
    MIN_SENTENCE_RATIO_HARD,
    PROMPT_NGRAM_SIZE,
)
from .scoring.schema import (
    SCORING_VERSION,
    FinalizeRequest,
    FinalizeResponse,
    Mode,
    ScoreRequest,
    ScoreResponse,
)
from .speech.audio import (
    DOWNLOAD_TIMEOUT_S,
    FORMAT_TO_MIME,
    MAX_AUDIO_BYTES,
    AudioRequestError,
)
from .speech.gemini_stt import DEFAULT_STT_MODEL, GeminiStt
from .speech.intake import (
    azure_pronunciation_available,
    build_default_stt,
    choose_stt_provider,
)
from .speech.port import SttUnavailable

# 서버가 켜질 때 예열한 결과를 적어 두는 곳. /health 에서 확인할 수 있게 남긴다.
_warmup_info: dict = {"done": False, "elapsed_ms": None}


def warm_up() -> float:
    """Kiwi 형태소 분석기를 미리 한 번 돌려 놓는다.

    왜 필요한가:
    Kiwi 는 처음 쓸 때 사전 파일을 통째로 읽어 들이느라 2초 넘게 걸리고,
    그 뒤로는 수 밀리초면 끝난다. 예열하지 않으면 그날의 첫 응시자만
    유독 오래 기다리게 된다. 서버가 켜질 때 미리 치러 두는 비용이다.
    """
    started = time.perf_counter()
    # 실제 채점과 같은 경로를 한 번 태워야 사전 적재와 문장 분리가 모두 예열된다.
    # 쓰기 모드로 도는 이유는 띄어쓰기 교정기까지 함께 데워 두기 위해서다
    extract_lexical_features("안전모를 착용하고 작업을 시작했습니다.", Mode.WRITING)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    _warmup_info["done"] = True
    _warmup_info["elapsed_ms"] = elapsed_ms
    return elapsed_ms


def _active_stt():
    """이 서버에 실제로 꽂혀 있는 받아쓰기 하나를 만들어 돌려준다.

    상태 정보(GET /health, GET /schema)에 '무엇이 꽂혀 있는지'를 그대로 적기 위한 것이다.
    이름을 손으로 적어 두면 실제로 도는 것과 어긋나도 아무도 모른다.
    """
    return build_default_stt()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버가 켜질 때와 꺼질 때 할 일.

    켜질 때 예열을 한 번 하고, 끌 때는 따로 정리할 것이 없다.
    """
    warm_up()
    yield


app = FastAPI(
    title="K-TEST 채점 API",
    version=SCORING_VERSION,
    description=(
        "외국인 노동자 대상 한국어 직무 소통 시험의 텍스트 채점 API. "
        "말하기(STT 전사 텍스트)와 쓰기가 이 엔드포인트를 함께 쓴다. "
        "문항이 끝날 때마다 POST /score 로 채점하고, 시험이 끝나면 "
        "POST /finalize 로 최종 등급을 낸다. "
        "점수는 언제나 근거(evidence)와 함께 반환된다. "
        "관리자가 올린 안전 문서로 쓰기 문항 초안을 만들려면 POST /generate-items 를 쓴다. "
        "만들어진 문항은 전부 문서 인용 근거를 달고 나오며, 근거를 대지 못한 문항은 "
        "응답에 실리지 않고 폐기 수로만 보고된다. "
        "서버에 API 키가 설정돼 있으면 모든 POST 요청에 X-API-Key 헤더가 필요하다."
    ),
    lifespan=lifespan,
)


@app.get("/health", summary="서버와 LLM 사용 가능 여부 확인")
def health() -> dict:
    """채점 서버가 살아 있는지, LLM을 쓸 수 있는 상태인지 알려준다.

    배포한 뒤 키가 제대로 들어갔는지 확인하는 용도다.

    받아쓰기(stt_available)는 짐작으로 적지 않는다. provider=lora 일 때는
    추론 서버의 /health 를 짧은 시간(2초) 안에 실제로 두드려 보고 그 결과를 적는다.
    주소만 보고 '있다'고 적으면 서버가 꺼져 있어 말하기 채점이 전부 503 인 상태를
    '정상'이라고 보고하게 되기 때문이다. 못 쓰는 이유는 stt_detail 에 한 문장으로 담고,
    정상이면 null 이다.
    """
    # 키가 없어도 객체는 만들어진다. available 만 False 가 된다
    client = GeminiClient()

    # 받아쓰기 상태를 여기서 한 번만 만들어 쓴다(아래에서 여러 번 물어보므로).
    stt = _active_stt()
    stt_available = getattr(stt, "available", False)
    # 왜 못 쓰는지. 정상이면 null 로 나간다
    stt_detail = None

    # provider=lora 는 available 이 '주소가 적혀 있다'는 뜻뿐이라, 추론 서버가
    # 꺼져 있어도 참이 된다. 그대로 내보내면 말하기 채점이 전부 503 인 상태를
    # '정상'이라고 보고하게 되므로, 이때만 서버에 직접 물어본 결과로 바꿔 적는다.
    # (azure·gemini 는 열쇠 유무로 판정하는 지금 방식을 그대로 둔다)
    ping = getattr(stt, "ping", None)
    if getattr(stt, "provider_name", "") == "lora" and callable(ping):
        lora_health = ping()
        stt_available = lora_health.alive
        stt_detail = lora_health.detail

    return {
        "status": "ok",
        "scoring_version": SCORING_VERSION,
        "llm_available": client.available,
        "llm_model": client.model_name,
        # 오류 자질(조사·어미·어휘·높임법)만 다른 모델로 돌린다.
        # 배포한 뒤 GEMINI_MODEL_ERRORS 가 제대로 들어갔는지 여기서 확인한다
        "llm_model_errors": client_for_errors(client).model_name,
        # 임시값을 쓰고 있는지 한눈에 보이게 함께 알려준다
        "weights_profile": DEFAULT_WEIGHTS.profile,
        "weights_provisional": DEFAULT_WEIGHTS.provisional,
        "vocab_list_provisional": is_default_vocab_list(),
        # 문항 생성 모듈이 어떤 모델을 쓰는지. 채점 모델과 다르다
        "generation_version": GENERATION_VERSION,
        "llm_model_generation": DEFAULT_GENERATION_MODEL,
        # 음성 답안을 받아쓰는 쪽. 이 서버에서 실제로 꽂혀 있는 것을 그대로 알려 준다.
        # lora  : 우리가 학습한 Whisper LoRA(아직 검증 전이라 임시). 글자만 받아쓴다
        # azure : 받아쓰기 + 발음을 한 번에 한다
        # gemini: 글자만 준다
        "stt_provider": stt.provider_name,
        "stt_model": stt.model_name,
        # lora 일 때는 추론 서버를 실제로 두드려 본 결과다(주소만 보고 판단하지 않는다).
        # false 면 말하기 채점이 503 이 된다는 뜻이므로 그대로 믿고 봐도 된다
        "stt_available": stt_available,
        # 못 쓰는 이유 한 문장. 정상이면 null 이다.
        # **새로 추가된 필드다** — 기존 필드의 이름과 뜻은 하나도 바뀌지 않았다
        "stt_detail": stt_detail,
        # azure 만 '원래 계획하던 것'이라 임시가 아니다. lora·gemini 는 임시로 본다
        # (lora 는 골든셋 검증 전, gemini 는 Azure 자리에 임시로 꽂아 둔 것)
        "stt_provisional": choose_stt_provider() != "azure",
        # 발음(발화 전달력)을 재는지. **전사 제공자와 별개다** — Azure 열쇠만 있으면
        # lora·gemini 로 받아써도 발음은 Azure 로 따로 채점돼 delivery 에 점수가 들어온다
        "pronunciation_scoring": azure_pronunciation_available(),
        "pronunciation_provider": "azure" if azure_pronunciation_available() else None,
        # 인증이 켜져 있는지. False 면 개발 모드라 POST 가 전부 열려 있다는 뜻이다.
        # 운영 서버에서 이 값이 false 로 보이면 키가 안 들어간 것이다
        "auth_enabled": auth_enabled(),
        "auth_header": API_KEY_HEADER,
        # 예열이 끝났는지. False 인데 채점이 느리다면 예열이 안 걸린 것이다
        "warmed_up": _warmup_info["done"],
        "warmup_ms": _warmup_info["elapsed_ms"],
    }


@app.get("/features", summary="채점에 쓰는 자질 목록")
def feature_catalog() -> dict:
    """어떤 자질을 어디서(규칙/LLM) 계산하는지 목록으로 알려준다.

    백엔드나 프론트가 자질 이름을 코드에 베껴 넣지 않아도 되도록 API로 노출한다.
    """
    # 규칙 자질과 LLM 자질을 나눠서 보여 준다. 이 경계가 재현성의 근거이기 때문이다
    kiwi_common = [{"id": fid, "source": "kiwi", "scope": "common"} for fid in KIWI_FEATURE_IDS]
    kiwi_writing = [
        {"id": fid, "source": "kiwi", "scope": "writing_only"}
        for fid in WRITING_ONLY_KIWI_FEATURE_IDS
    ]
    llm_common = [
        {"id": ERROR_TYPES[k][0], "source": "llm", "scope": "common"}
        for k in COMMON_ERROR_TYPES
    ]
    llm_writing = [
        {"id": ERROR_TYPES[k][0], "source": "llm", "scope": "writing_only"}
        for k in WRITING_ONLY_ERROR_TYPES
    ]

    common = kiwi_common + llm_common
    return {
        "scoring_version": SCORING_VERSION,
        "common_feature_count": len(common),
        "features": common + kiwi_writing + llm_writing,
        "areas": [
            {"area": "content_task", "label": "내용 및 과제 수행", "scored": True},
            {"area": "language_use", "label": "언어 사용", "scored": True},
            {
                "area": "delivery",
                "label": "발화 전달력",
                # Azure 열쇠가 있어 발음을 잴 수 있으면 채점된다. **전사 제공자와 별개라**
                # lora·gemini 로 받아써도 발음은 Azure 가 따로 재서 여기에 점수가 들어온다.
                # 글로 보낸 답안과 쓰기 답안은 지금까지처럼 자리만 남는다
                "scored": azure_pronunciation_available(),
                "note": (
                    "Azure 발음평가로 음성을 채점한 경우에만 점수가 나온다"
                    "(비중 0.20, 임시값). 받아쓰기를 lora·gemini 가 했어도 발음은 Azure 가 "
                    "따로 잰다. 발음 점수가 없으면 status=not_evaluated · "
                    "weight=0 으로 남고 나머지 두 영역이 예전 비율(0.45:0.55)로 계산된다."
                ),
            },
        ],
        # 어느 영역이 원본 전사를 보고 어느 영역이 보정본을 보는지 알려 준다.
        # 이 구분을 모르면 백엔드가 보정본으로 문법 점수를 설명하는 실수를 하게 된다
        "transcript_correction": {
            "request_field": "transcript",
            "enabled_by": "transcript.correct = true (말하기 답안에만 적용)",
            "original_text_from": "answer_text (전사 원문을 따로 보내지 않는다)",
            "uses_corrected_text": ["content_task"],
            "uses_original_text": ["language_use"],
            "diff_in_response": "meta.transcript_diff (start/end 는 전사 원문 기준 글자 위치)",
            "note": (
                "보정 구간과 겹치는 오류 지적에는 신뢰도 낮음 표시가 붙고 "
                "그 건수가 meta.transcript_low_confidence_errors 에 나온다."
            ),
        },
        # 채점 전에 돌리는 답안 유효성 가드. 어떤 표시가 나올 수 있는지 미리 알려 준다.
        # 프론트가 무효 사유 문구를 코드에 베껴 넣지 않고 flag 로 분기할 수 있게 하려는 것이다
        "answer_validity": {
            "checked_before_llm": True,
            "rule_based_only": True,
            "meta_fields": ["answer_valid", "validity_flags", "validity_reason"],
            "guards": [
                {
                    "flag": FLAG_NOT_KOREAN,
                    "label": "한글 비율",
                    "effect": "invalid",
                    "threshold": MIN_HANGUL_RATIO,
                    "unit": "공백·숫자·문장부호를 뺀 글자 중 한글 비율",
                },
                {
                    "flag": FLAG_TOO_SHORT,
                    "label": "최소 길이",
                    "effect": "language_use_partial",
                    "threshold": MIN_EOJEOL_COUNT,
                    "unit": "어절",
                },
                {
                    "flag": FLAG_PROMPT_COPY,
                    "label": "지시문 겹침",
                    "effect": "invalid",
                    "threshold": MAX_PROMPT_OVERLAP,
                    "unit": f"지시문과 그대로 겹치는 글자 비율({PROMPT_NGRAM_SIZE}글자 단위)",
                },
                {
                    "flag": FLAG_NOT_SENTENCES,
                    "label": "문장 성립",
                    "effect": "invalid_or_content_partial",
                    "threshold": MIN_SENTENCE_RATIO_HARD,
                    "unit": "어미가 붙은 문장의 비율",
                },
            ],
            "note": (
                "invalid 이면 overall_score 와 overall_grade 가 null 이고 "
                "meta.answer_valid 가 false 다. 기준값은 전부 임시값이다."
            ),
        },
        # 말하기 음성 입력(POST /score 의 audio 필드) 계약.
        # 백엔드가 크기·형식 한도를 코드에 베껴 넣지 않고 여기서 읽어 쓸 수 있게 열어 둔다
        "speech_input": {
            "request_field": "audio",
            "enabled_by": "audio.url (말하기 답안에만 적용)",
            "answer_text_must_be_empty": True,
            "allowed_formats": sorted(FORMAT_TO_MIME),
            "max_bytes": MAX_AUDIO_BYTES,
            "download_timeout_s": DOWNLOAD_TIMEOUT_S,
            "url_schemes": ["http", "https"],
            "provider": _active_stt().provider_name,
            "model": _active_stt().model_name,
            "provider_provisional": choose_stt_provider() != "azure",
            # 어느 것을 쓸지는 서버의 KTEST_STT_PROVIDER 환경변수로 정한다.
            # 안 정해 두면 Azure 열쇠가 있을 때 azure, 없으면 gemini 다.
            # lora 는 LORA_STT_URL(추론 서버 주소)이 함께 있어야 고를 수 있다
            "provider_options": ["lora", "azure", "gemini"],
            # 발음(발화 전달력)은 전사 제공자와 별개로, Azure 열쇠가 있으면 채점된다
            "pronunciation_provider": "azure" if azure_pronunciation_available() else None,
            "meta_fields": [
                "stt_provider",
                "stt_model",
                "audio_duration_ms",
                "stt_transcript",
            ],
            "failure_codes": {
                "400": "요청이 성립하지 않는다(쓰기에 음성 첨부 / 글과 음성이 함께 옴 / 형식·크기 위반)",
                "503": "받아쓰지 못했다. 대체 경로가 없다",
            },
            "note": (
                "발음(delivery)은 전사 제공자와 별개로, Azure 열쇠가 있으면 채점된다"
                "(정확도·유창성·완전성, 낱말별 근거 포함). 즉 lora·gemini 로 받아써도 "
                "발음은 Azure 가 따로 잰다. 받아쓰기가 학습자 오류를 표준형으로 "
                "고쳐 적는 경우가 실측됐으므로 문법 점수가 실제보다 높게 나올 수 있다. "
                "Azure 발음 경로는 지금 wav 만 처리한다. "
                "lora 는 우리가 학습한 Whisper 어댑터로, 아직 골든셋 검증 전이라 임시다."
            ),
        },
        # 문항 생성(POST /generate-items)의 문서 길이 한계.
        # 백엔드가 이 숫자를 코드에 베껴 넣지 않고 여기서 읽어 쓸 수 있게 열어 둔다.
        # 길이를 넘긴 문서는 조용히 잘리지 않고 400 으로 거절된다
        "item_generation": {
            "generation_version": GENERATION_VERSION,
            "min_document_chars": MIN_DOCUMENT_CHARS,
            "max_document_chars": MAX_DOCUMENT_CHARS,
            "measured_after": "전처리(머리글·쪽번호 제거) 후 글자 수",
            "long_document_policy": "자르지 않고 400 으로 거절한다",
            "status_of_generated_items": "draft",
            "requires_human_approval": True,
        },
        # 등급 커트라인을 백엔드가 알 필요는 없지만, 확인용으로 열어 둔다.
        # 이 값들은 앵커 답안 기반이 아니라 임시값이다
        "grade_cutoffs": {grade: cutoff for cutoff, grade in DEFAULT_WEIGHTS.grade_cutoffs},
        "grade_cutoffs_provisional": True,
    }


def _detail(exc: Exception) -> dict:
    """오류 하나를 백엔드가 영어로 바꿀 수 있는 모양으로 만든다.

    지금까지는 `detail` 에 한국어 문장 하나만 담아 보냈다. 그런데 응시자 화면에는
    영어가 떠야 하므로, 백엔드가 영어 문장을 고를 열쇠(`code`)와 그 문장에 끼울
    값(`params`)이 필요하다. 그래서 셋을 함께 담는다.

        {"code": "AUDIO_FILE_TOO_LARGE",
         "params": {"actualMb": 25.3, "maxMb": 20},
         "message": "음성 파일이 25.3MB 로 너무 크다(최대 20MB)."}

    `message` 는 지금까지 나가던 그 한국어 문장 그대로다. 백엔드가 아직 영어 문장을
    안 만든 코드가 있어도 화면이 비지 않게 하려고 함께 보낸다.
    코드를 안 달고 올라온 옛 예외는 code 가 빈 글자가 된다.
    """
    made = getattr(exc, "notice", None)
    if made is not None:
        return made.model_dump()
    return {"code": "", "params": {}, "message": str(exc)}


@app.post(
    "/score",
    response_model=ScoreResponse,
    summary="문항 하나 채점",
    # 서버에 API 키가 설정돼 있을 때만 잠긴다. 없으면 지금까지처럼 그냥 열린다
    dependencies=[Depends(require_api_key)],
)
def score(request: ScoreRequest) -> ScoreResponse:
    """답안 텍스트와 문항 정보를 받아 종합 점수·영역별 점수·근거를 돌려준다.

    문항이 끝날 때마다 백엔드가 백그라운드로 부른다.
    LLM을 쓸 수 없는 상황이어도 오류를 내지 않는다.
    규칙 자질만으로 계산하고, 무엇이 빠졌는지는 warnings 에 담아 보낸다.

    말하기 답안에서 transcript.correct 를 켜서 보내면
    STT 전사 보정을 거친 뒤 채점한다. 이때도 문법·어휘는 보정 전 원문으로 채점하고,
    보정 내역은 meta.transcript_diff 에 근거 형태로 함께 나간다.

    ※ 점수를 화면에 띄우기 전에 meta.safe_to_show_candidate 를 반드시 확인할 것 ※
    LLM을 못 쓰면 대체 경로로 계산하는데, 그때도 점수는 멀쩡한 숫자로 나온다.
    실제로 같은 답안이 LLM이 살아 있을 때 70.58점, 대체 경로에서 79.66점이었다.
    warnings 를 읽어서 판단하지 말고 이 값 하나만 보면 된다.
    (자세한 사유는 meta.reliability 와 meta.reliability_reason 에 있다)

    말하기 답안은 글 대신 음성 파일 주소(audio.url)를 보낼 수 있다.
    그러면 우리가 받아써서 그 글을 채점하고, 받아쓴 글과 쓴 모델을 meta 에 남긴다.

    실패 처리 (받아쓰기만 예외를 던진다)
      400  쓰기 답안에 음성을 붙였다 / answer_text 와 audio 를 둘 다 보냈다 /
           읽을 수 없는 형식이거나 파일이 너무 크다
      503  음성을 글자로 옮기지 못했다. **채점과 달리 대체 경로가 없다** —
           못 알아들은 말을 지어내면 응시자가 하지 않은 말로 점수를 받게 된다
    """
    # 계산도 조립도 전부 파이프라인에 맡긴다. 이 창구에는 채점 규칙을 두지 않는다
    # (전사 보정을 부를지 말지, 음성을 받아쓸지 말지도 요청을 보고 파이프라인이 정한다)
    try:
        return score_submission(request)
    except AudioRequestError as exc:
        # 요청 자체가 성립하지 않는다. 다시 보내도 같은 결과이므로 400 이다
        raise HTTPException(status_code=400, detail=_detail(exc)) from exc
    except SttUnavailable as exc:
        # 받아쓰기에는 대체 경로가 없다. 잘못된 글로 채점하느니 못 했다고 알린다
        raise HTTPException(status_code=503, detail=_detail(exc)) from exc


@app.post(
    "/finalize",
    response_model=FinalizeResponse,
    summary="시험 전체 최종 등급",
    dependencies=[Depends(require_api_key)],
)
def finalize(request: FinalizeRequest) -> FinalizeResponse:
    """문항별 채점 결과를 모아 시험 하나의 최종 등급과 백분위를 낸다.

    백엔드는 /score 응답을 그대로 모아 보내기만 하면 된다.
    가중치나 등급 커트라인을 백엔드가 알 필요가 없도록 여기서 전부 계산한다.

    마지막 문항의 채점이 아직 안 끝났어도 오류를 내지 않는다.
    빠진 문항은 warnings 와 item_coverage 에 남기고 남은 문항으로 다시 계산한다.
    """
    return finalize_session(request)


# ---------------------------------------------------------------------------
# 문항 생성 (관리자가 올린 안전 문서 -> 쓰기 문항 초안)
#
# 시험 중에 부르는 창구가 아니다. 시험 전에 관리자가 한 번 부르고,
# 만들어진 문항은 사람이 승인해야 시험에 쓸 수 있다.
# ---------------------------------------------------------------------------


@app.post(
    "/generate-items",
    response_model=GenerateItemsResponse,
    summary="안전 문서에서 쓰기 문항 초안 만들기",
    dependencies=[Depends(require_api_key)],
)
def generate_items_endpoint(request: GenerateItemsRequest) -> GenerateItemsResponse:
    """관리자가 올린 안전 문서 텍스트로 쓰기 문항 초안을 만든다.

    무상태다. 문서를 요청에 담아 받고 우리는 아무것도 저장하지 않는다.
    파일 저장과 PDF → 텍스트 추출은 파일을 가진 백엔드가 하고, 여기는 텍스트만 받는다.

    ※ 응답의 문항은 전부 status="draft"(초안)다 ※
    기계 관문 다섯 개는 통과했지만 사람이 아직 보지 않았다는 뜻이다.
    관리자 승인 없이 시험에 내면 안 된다.

    ※ 응답을 저장할 때 필드를 지우지 말 것 ※
    citation 을 버리면 승인 화면에서 근거를 보여 줄 수 없고,
    그 순간 이 기능은 'AI 가 만든 문제를 그냥 믿는 서비스'가 된다.
    source_text 도 함께 보관해야 한다. 인용 위치(start/end)의 기준이 되는 글이다.

    실패 처리
      400  문서가 너무 짧거나 길다 / 말하기 문항을 요청했다
      503  LLM 을 쓸 수 없다. **채점과 달리 대체 경로가 없다** —
           규칙만으로 문항을 지어낼 수는 없으므로 죽으면 죽었다고 말한다
      200  문항이 0개여도 오류가 아니다. items=[] 와 폐기 사유를 돌려준다
    """
    try:
        return generate_items(request)
    except GenerationRequestError as exc:
        # 요청 자체가 성립하지 않는 경우. 문항을 하나도 만들지 않고 즉시 막는다
        raise HTTPException(status_code=400, detail=_detail(exc)) from exc
    except LLMUnavailable as exc:
        # 생성에는 대체 경로가 없다. 잘못된 문항을 내놓느니 못 만들었다고 알린다
        raise HTTPException(status_code=503, detail=_detail(exc)) from exc


@app.post(
    "/verify-items",
    response_model=VerifyItemsResponse,
    summary="관리자가 고친 문항 재검증",
    dependencies=[Depends(require_api_key)],
)
def verify_items_endpoint(request: VerifyItemsRequest) -> VerifyItemsResponse:
    """승인 화면에서 관리자가 고친 문항이 아직 검증을 통과하는지 다시 확인한다.

    **LLM 을 부르지 않는다.** 관문은 전부 규칙 계산이라 몇 번을 눌러도 같은 답이 나온다.
    관리자가 체크리스트 문구를 고치면 인용 근거가 깨질 수 있는데,
    재검증할 자리가 없으면 '승인자가 손대는 순간 근거 보장이 사라진다'는 말이 맞아 버린다.

    백엔드 사용 규칙: `ok` 가 false 인 문항은 시험에 낼 수 있는 상태로 바꾸지 않는다.
    """
    return verify_items(request)
