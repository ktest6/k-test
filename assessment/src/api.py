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

from fastapi import FastAPI

from .features.errors import ERROR_TYPES, COMMON_ERROR_TYPES, WRITING_ONLY_ERROR_TYPES
from .features.lexical import (
    KIWI_FEATURE_IDS,
    WRITING_ONLY_KIWI_FEATURE_IDS,
    extract_lexical_features,
    is_default_vocab_list,
)
from .llm.client import GeminiClient, client_for_errors
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
        "점수는 언제나 근거(evidence)와 함께 반환된다."
    ),
    lifespan=lifespan,
)


@app.get("/health", summary="서버와 LLM 사용 가능 여부 확인")
def health() -> dict:
    """채점 서버가 살아 있는지, LLM을 쓸 수 있는 상태인지 알려준다.

    배포한 뒤 키가 제대로 들어갔는지 확인하는 용도다.
    """
    # 키가 없어도 객체는 만들어진다. available 만 False 가 된다
    client = GeminiClient()
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
                "scored": False,
                "note": "Azure 발음평가 도입 전이라 채점하지 않고 자리만 남긴다.",
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
        # 등급 커트라인을 백엔드가 알 필요는 없지만, 확인용으로 열어 둔다.
        # 이 값들은 앵커 답안 기반이 아니라 임시값이다
        "grade_cutoffs": {grade: cutoff for cutoff, grade in DEFAULT_WEIGHTS.grade_cutoffs},
        "grade_cutoffs_provisional": True,
    }


@app.post("/score", response_model=ScoreResponse, summary="문항 하나 채점")
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
    """
    # 계산도 조립도 전부 파이프라인에 맡긴다. 이 창구에는 채점 규칙을 두지 않는다
    # (전사 보정을 부를지 말지도 요청을 보고 파이프라인이 정한다)
    return score_submission(request)


@app.post("/finalize", response_model=FinalizeResponse, summary="시험 전체 최종 등급")
def finalize(request: FinalizeRequest) -> FinalizeResponse:
    """문항별 채점 결과를 모아 시험 하나의 최종 등급과 백분위를 낸다.

    백엔드는 /score 응답을 그대로 모아 보내기만 하면 된다.
    가중치나 등급 커트라인을 백엔드가 알 필요가 없도록 여기서 전부 계산한다.

    마지막 문항의 채점이 아직 안 끝났어도 오류를 내지 않는다.
    빠진 문항은 warnings 와 item_coverage 에 남기고 남은 문항으로 다시 계산한다.
    """
    return finalize_session(request)
