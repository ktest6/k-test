"""채점기의 품질을 숫자로 재는 검증 실험 스크립트.

심사에서 나올 세 가지 질문에 실측으로 답하기 위해 만든 것이다.

    실험 1  재현성    같은 답안을 세 번 채점하면 같은 점수가 나오는가
    실험 2  오류 탐지  일부러 심어 둔 문법 오류를 실제로 잡아내는가
    실험 3  채점 시간  한 답안을 채점하는 데 얼마나 걸리는가

세 실험 모두 **진짜 LLM을 부른다.** 가짜 응답으로는 재현성도 탐지율도 잴 수 없기 때문이다.

쓰는 법:
    python scripts/verify_quality.py                # 오늘 날짜로 전체 실험 실행
    python scripts/verify_quality.py --date 20260731
    python scripts/verify_quality.py --dry-run      # LLM 없이 자료 검증만 (공짜)
    python scripts/verify_quality.py --only 1       # 실험 1만

결과는 두 개의 파일로 남는다.
    outputs/quality_report_<날짜>.md    사람이 읽는 보고서
    outputs/quality_raw_<날짜>.json     재실행 비교용 원자료

운영 규칙 (중요):
- 429(호출 한도 초과)가 나도 **모델을 절대 바꾸지 않는다.** 다른 모델의 점수를 섞으면
  실험 자체가 무의미해지기 때문이다. 대신 같은 모델로 잠시 쉬었다 다시 부른다.
  그래도 안 되면 그 회차를 무효로 적고, 연속으로 두 번 막히면 남은 회차를 포기하고
  여기까지의 결과를 저장한다. 한도가 풀린 뒤 같은 명령을 다시 돌리면 된다.
- 신뢰도(meta.reliability)가 full 이 아닌 회차도 무효로 적는다.
  대체 경로로 계산된 점수가 섞이면 '불일치'가 아니라 '측정 실패'이기 때문이다.

호출 한도에 대하여 (2026-07-31 실측으로 알게 된 것):
오류 자질 모델(gemini-3-flash 계열)의 무료 등급에는 한도가 **두 겹**으로 걸려 있다.
  - 분당 5회  : 1초 간격으로 돌렸더니 19번째 채점에서 막혔다. --sleep 으로 푼다.
  - 하루 20회 : 이건 기다려도 안 풀린다. 하루에 20답안까지만 채점할 수 있다는 뜻이다.
50회짜리 실험은 하루에 다 못 끝낸다. 그래서 **이어 돌리기**를 넣었다.
같은 날짜로 다시 실행하면 이미 성공한 회차는 건너뛰고 남은 것만 채운다.
(--fresh 를 주면 처음부터 새로 돌린다)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.llm.citation import normalize_for_match
from src.llm.client import GeminiClient, client_for_errors
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    ChecklistItem,
    FeatureSource,
    FeatureStatus,
    ItemInfo,
    Mode,
    Reliability,
    ScoreOptions,
    ScoreRequest,
    ScoreResponse,
)
from src.scoring.validity import check_answer_validity

ROOT = pathlib.Path(__file__).resolve().parent.parent
ITEMS_PATH = ROOT / "items" / "writing_v0.json"
OUTPUT_DIR = ROOT / "outputs"

# 오류 종류의 영문 키 -> 사람이 읽는 이름. 보고서 표의 행 이름이 된다.
ERROR_TYPE_LABELS = {
    "josa": "조사 오류",
    "conjugation": "어미 활용 오류",
    "honorific": "높임법 오류",
    "spelling": "맞춤법 오류",
}


# ===========================================================================
# 실험 1 자료 — 재현성 측정용 답안 10개
#
# 확정 문항 5개마다 두 종류를 짝지어 둔다.
#   full     문항의 체크리스트 항목을 모두 채운 충실한 답안
#   partial  일부러 몇 항목을 빠뜨린 답안 (expected_unmet 에 무엇을 뺐는지 적어 둔다)
#
# 두 종류를 함께 넣는 이유: 점수가 높은 답안만 세 번 돌려서는
# '늘 만점이라 늘 같았다'는 결과가 나올 수 있어 재현성의 증거가 되지 못한다.
# 판정이 갈리는 답안에서도 세 번 같은 값이 나와야 재현성이라 할 수 있다.
#
# expected_unmet 은 채점기가 맞혔는지 보는 참고용이지 실험 1의 채점 기준이 아니다.
# 실험 1이 보는 것은 오직 '세 번이 서로 같은가'다.
# ===========================================================================

REPRO_ANSWERS: list[dict] = [
    {
        "answer_id": "R01-WRT-001-full",
        "item_id": "WRT-001",
        "variant": "full",
        "expected_unmet": [],
        "text": (
            "오늘 오전에 이번 라인에서 부품 포장 작업을 했습니다. "
            "오후에 포장 기계의 벨트가 끊어져서 작업이 삼십 분 동안 멈췄습니다. "
            "바로 반장님께 보고했고 정비 담당자가 와서 벨트를 새것으로 교체했습니다. "
            "그 후에 작업을 다시 시작해서 오늘 목표 수량을 모두 채웠습니다."
        ),
    },
    {
        "answer_id": "R02-WRT-001-partial",
        "item_id": "WRT-001",
        "variant": "partial",
        # 문제(c2)와 그 처리(c3)를 통째로 빼고 한 일만 적은 답안이다
        "expected_unmet": ["c2", "c3"],
        "text": (
            "오늘 오전에 이번 라인에서 부품 포장 작업을 했습니다. "
            "오후에도 같은 자리에서 상자를 정리했습니다. "
            "상자는 모두 창고 삼번 칸에 옮겨 놓았습니다. "
            "내일도 같은 작업을 계속할 예정입니다."
        ),
    },
    {
        "answer_id": "R03-WRT-002-full",
        "item_id": "WRT-002",
        "variant": "full",
        "expected_unmet": [],
        "text": (
            "반장님, 안녕하세요. 어제저녁부터 열이 많이 나고 몸살이 심합니다. "
            "그래서 내일은 출근하지 못하겠습니다. 오늘 병원에 가서 진료를 받겠습니다. "
            "모레 아침에는 꼭 나오겠습니다. 갑자기 말씀드려서 죄송합니다."
        ),
    },
    {
        "answer_id": "R04-WRT-002-partial",
        "item_id": "WRT-002",
        "variant": "partial",
        # 못 나온다는 사실(c1)과 높임(c4)만 있고, 이유(c2)와 복귀 시점(c3)이 없다
        "expected_unmet": ["c2", "c3"],
        "text": (
            "반장님, 내일은 회사에 나가지 못하겠습니다. 죄송합니다. "
            "다른 분들께도 전해 주시면 감사하겠습니다. 오늘은 일찍 쉬겠습니다."
        ),
    },
    {
        "answer_id": "R05-WRT-003-full",
        "item_id": "WRT-003",
        "variant": "full",
        "expected_unmet": [],
        "text": (
            "안전 관리자님께 알려 드립니다. "
            "창고 안쪽 삼번 통로에 있는 철제 선반이 왼쪽으로 많이 기울었습니다. "
            "맨 위 칸에 무거운 부품 상자가 여러 개 있어서 지나가는 사람 위로 떨어질 것 같습니다. "
            "오늘 작업이 끝나기 전에 선반을 고정하고 상자를 아래 칸으로 옮겨 주시기 바랍니다."
        ),
    },
    {
        "answer_id": "R06-WRT-003-partial",
        "item_id": "WRT-003",
        "variant": "partial",
        # 무엇이 위험한지(c1)만 있고 위치(c2)와 조치 요청(c3)이 없다
        "expected_unmet": ["c2", "c3"],
        "text": (
            "안전 관리자님께 알려 드립니다. "
            "철제 선반이 많이 기울어서 위에 있는 상자가 곧 떨어질 것 같습니다. "
            "어제보다 더 많이 기울었습니다. 아침에 지나가다가 보고 많이 놀랐습니다."
        ),
    },
    {
        "answer_id": "R07-WRT-004-full",
        "item_id": "WRT-004",
        "variant": "full",
        "expected_unmet": [],
        "text": (
            "다음 근무자님께 알립니다. "
            "오늘 이번 라인 포장 작업과 작업장 청소는 모두 끝냈습니다. "
            "다만 완제품 라벨 붙이기는 절반만 해서 상자 스무 개가 그대로 남아 있습니다. "
            "그리고 삼번 기계에서 가끔 큰 소리가 나니까 켜기 전에 벨트를 꼭 확인해 주십시오."
        ),
    },
    {
        "answer_id": "R08-WRT-004-partial",
        "item_id": "WRT-004",
        "variant": "partial",
        # 끝낸 일(c1)만 있고 남은 일(c2)과 주의사항(c3)이 없다
        "expected_unmet": ["c2", "c3"],
        "text": (
            "다음 근무자님께 알립니다. "
            "오늘은 이번 라인에서 포장 작업을 했고 작업장 청소도 모두 끝냈습니다. "
            "자재는 창고 이번 칸에 정리해 두었습니다. 오늘 하루도 고생 많으셨습니다."
        ),
    },
    {
        "answer_id": "R09-WRT-005-full",
        "item_id": "WRT-005",
        "variant": "full",
        "expected_unmet": [],
        "text": (
            "사무실에 요청드립니다. "
            "작업용 면장갑이 거의 다 떨어져서 지금 세 켤레만 남아 있습니다. "
            "우리 조는 하루에 열 켤레 정도 쓰기 때문에 오십 켤레가 필요합니다. "
            "다음 주 월요일 오전까지 창고로 보내 주시면 감사하겠습니다."
        ),
    },
    {
        "answer_id": "R10-WRT-005-partial",
        "item_id": "WRT-005",
        "variant": "partial",
        # 무엇이 필요한지(c1)만 있고 수량(c2)과 기한(c3)이 없다
        "expected_unmet": ["c2", "c3"],
        "text": (
            "사무실에 요청드립니다. 작업용 면장갑이 거의 다 떨어졌습니다. "
            "장갑이 없으면 손을 다칠 수 있어서 걱정됩니다. "
            "확인해 주시면 감사하겠습니다. 부탁드립니다."
        ),
    },
]


# ===========================================================================
# 실험 2 자료 — 오류를 일부러 심은 답안 20개와 그 정답표
#
# planted 가 정답표다. expr 는 **답안 원문에 그대로 있는 글자**여야 하고,
# 스크립트를 돌리기 전에 validate_data() 가 그것을 확인한다.
# 확인이 필요한 이유: 정답표의 글자가 답안에 없으면 검출률이
# 채점기의 성능이 아니라 자료의 오타 때문에 0%가 되기 때문이다.
#
# 답안 하나에 오류는 한두 개만 심고 나머지는 자연스러운 문장으로 채웠다.
# 오류투성이 답안은 어느 지적이 어느 오류를 잡은 것인지 짝지을 수 없다.
# ===========================================================================

ERROR_ANSWERS: list[dict] = [
    # --- 조사 오류 5개 -----------------------------------------------------
    {
        "answer_id": "E01-josa",
        "item_id": "WRT-001",
        "text": (
            "오늘 이번 라인에서 상자를 포장했습니다. "
            "상자가 너무 무거워서 허리를 아팠습니다. "
            "그래서 동료하고 같이 들었습니다. 작업은 다섯 시에 끝났습니다."
        ),
        "planted": [{"expr": "허리를 아팠습니다", "type": "josa", "correction": "허리가 아팠습니다"}],
    },
    {
        "answer_id": "E02-josa",
        "item_id": "WRT-002",
        "text": (
            "반장님, 죄송합니다. 어제부터 열이 나고 몸이 많이 아픕니다. "
            "그래서 내일은 회사를 못 갑니다. "
            "병원에 갔다가 모레 아침에 다시 출근하겠습니다."
        ),
        "planted": [{"expr": "회사를 못 갑니다", "type": "josa", "correction": "회사에 못 갑니다"}],
    },
    {
        "answer_id": "E03-josa",
        "item_id": "WRT-003",
        "text": (
            "안전 관리자님께 알려 드립니다. 창고 안쪽 선반이 왼쪽으로 기울었습니다. "
            "위에 있는 상자가 떨어지면 사람에 다칠 수 있습니다. "
            "오늘 안에 선반을 고쳐 주시기 바랍니다."
        ),
        "planted": [{"expr": "사람에 다칠 수 있습니다", "type": "josa", "correction": "사람이 다칠 수 있습니다"}],
    },
    {
        "answer_id": "E04-josa",
        "item_id": "WRT-004",
        "text": (
            "다음 근무자님께 알립니다. 오늘 이번 라인 청소와 자재 정리를 끝냈습니다. "
            "삼번 기계 점검은 아직 못 했습니다. "
            "그 기계 소리를 조금 이상하니까 조심해 주십시오."
        ),
        "planted": [
            {"expr": "소리를 조금 이상하니까", "type": "josa", "correction": "소리가 조금 이상하니까"}
        ],
    },
    {
        "answer_id": "E05-josa",
        "item_id": "WRT-005",
        "text": (
            "사무실에 요청드립니다. 작업용 장갑이 거의 다 떨어졌습니다. "
            "우리 팀에 장갑을 삼십 켤레가 필요합니다. "
            "다음 주 월요일까지 보내 주시면 감사하겠습니다."
        ),
        "planted": [
            {"expr": "장갑을 삼십 켤레가 필요합니다", "type": "josa", "correction": "장갑이 삼십 켤레 필요합니다"}
        ],
    },
    # --- 어미 활용 오류 5개 -------------------------------------------------
    # 불규칙 활용을 규칙 활용처럼 쓴 형태만 골랐다.
    # ('없어습니다' 같은 형태는 맞춤법 오류로도 볼 수 있어 짝짓기가 흐려진다)
    {
        "answer_id": "E06-conjugation",
        "item_id": "WRT-001",
        "text": (
            "오늘 창고에서 부품 상자를 옮겼습니다. "
            "상자가 무거워서 동료가 저를 돕아서 같이 들었습니다. "
            "그래서 작업을 시간 안에 끝냈습니다. 다친 사람은 없었습니다."
        ),
        "planted": [{"expr": "저를 돕아서 같이", "type": "conjugation", "correction": "저를 도와서 같이"}],
    },
    {
        "answer_id": "E07-conjugation",
        "item_id": "WRT-002",
        "text": (
            "반장님, 어제 저녁부터 열이 나고 몸도 춥어서 잠을 못 잤습니다. "
            "그래서 내일은 출근하지 못합니다. 죄송합니다. "
            "모레 아침에는 꼭 나오겠습니다."
        ),
        "planted": [{"expr": "몸도 춥어서 잠을", "type": "conjugation", "correction": "몸도 추워서 잠을"}],
    },
    {
        "answer_id": "E08-conjugation",
        "item_id": "WRT-003",
        "text": (
            "안전 관리자님, 창고 뒤쪽 선반이 오른쪽으로 기울었습니다. "
            "위에 있는 무거운 상자가 곧 떨어질 것 같습니다. "
            "어제 이상한 소리를 듣어서 확인해 보았습니다. "
            "오늘 중에 조치해 주시기 바랍니다."
        ),
        "planted": [{"expr": "소리를 듣어서 확인해", "type": "conjugation", "correction": "소리를 들어서 확인해"}],
    },
    {
        "answer_id": "E09-conjugation",
        "item_id": "WRT-004",
        "text": (
            "다음 근무자님, 오늘 포장 작업은 다 끝냈습니다. "
            "그런데 라벨 붙이기는 아직 남아 있습니다. "
            "삼번 기계에 기름을 바르어야 하니까 잊지 마십시오. "
            "밤에는 온도를 자주 확인해 주십시오."
        ),
        "planted": [{"expr": "기름을 바르어야 하니까", "type": "conjugation", "correction": "기름을 발라야 하니까"}],
    },
    {
        "answer_id": "E10-conjugation",
        "item_id": "WRT-005",
        "text": (
            "사무실에 요청드립니다. 작업용 장갑이 다 떨어져서 지금 두 켤레만 남아 있습니다. "
            "장갑이 없으면 일하기가 어렵어서 곤란합니다. "
            "오십 켤레를 이번 주 금요일까지 보내 주시기 바랍니다."
        ),
        "planted": [
            {"expr": "일하기가 어렵어서 곤란합니다", "type": "conjugation", "correction": "일하기가 어려워서 곤란합니다"}
        ],
    },
    # --- 높임법 오류 5개 ----------------------------------------------------
    # 세 갈래를 섞었다: 상급자를 안 높임 / 자기를 높임 / 사물을 높임.
    {
        "answer_id": "E11-honorific",
        "item_id": "WRT-001",
        "text": (
            "오늘 이번 라인에서 검사 작업을 했습니다. "
            "아침에 반장님이 오늘 목표를 말했습니다. "
            "불량품이 세 개 나와서 따로 빼 두었습니다. "
            "오후에는 문제없이 작업을 끝냈습니다."
        ),
        "planted": [
            {"expr": "반장님이 오늘 목표를 말했습니다", "type": "honorific", "correction": "반장님께서 목표를 말씀하셨습니다"}
        ],
    },
    {
        "answer_id": "E12-honorific",
        "item_id": "WRT-002",
        "text": (
            "반장님, 제가 어제부터 몸이 아파서 내일은 출근하지 못합니다. "
            "오늘 병원에 가 보겠습니다. "
            "제가 반장님께 이렇게 말씀하셔서 죄송합니다. 모레는 꼭 나오겠습니다."
        ),
        "planted": [
            {"expr": "제가 반장님께 이렇게 말씀하셔서", "type": "honorific", "correction": "제가 반장님께 이렇게 말씀드려서"}
        ],
    },
    {
        "answer_id": "E13-honorific",
        "item_id": "WRT-003",
        "text": (
            "안전 관리자님께 알립니다. 창고 안쪽 선반이 왼쪽으로 기울었습니다. "
            "상자가 떨어지면 사람이 다칠 수 있습니다. "
            "어제 사장님이 그 선반을 봤습니다. 오늘 중으로 고쳐 주시기 바랍니다."
        ),
        "planted": [
            {"expr": "사장님이 그 선반을 봤습니다", "type": "honorific", "correction": "사장님께서 그 선반을 보셨습니다"}
        ],
    },
    {
        "answer_id": "E14-honorific",
        "item_id": "WRT-004",
        "text": (
            "다음 근무자님, 오늘 포장 작업과 청소는 끝냈습니다. "
            "라벨 붙이기는 아직 남아 있습니다. "
            "기계가 조금 시끄러우니까 조심하십시오. 그리고 부품이 다 떨어지셨습니다."
        ),
        "planted": [
            {"expr": "부품이 다 떨어지셨습니다", "type": "honorific", "correction": "부품이 다 떨어졌습니다"}
        ],
    },
    {
        "answer_id": "E15-honorific",
        "item_id": "WRT-005",
        "text": (
            "사무실에 요청드립니다. 작업용 장갑이 거의 다 떨어졌습니다. "
            "지금 다섯 켤레만 남아 있어서 내일부터 부족합니다. "
            "장갑 오십 켤레가 다음 주 월요일까지 필요하십니다."
        ),
        "planted": [
            {"expr": "월요일까지 필요하십니다", "type": "honorific", "correction": "월요일까지 필요합니다"}
        ],
    },
    # --- 맞춤법 오류 5개 ----------------------------------------------------
    # 한국어 학습자와 원어민이 모두 자주 틀리는 표기를 골랐다.
    {
        "answer_id": "E16-spelling",
        "item_id": "WRT-001",
        "text": (
            "오늘 이번 라인에서 포장 작업을 했습니다. "
            "오후에 기계가 멈춰서 작업이 안 됬습니다. "
            "반장님께 보고해서 정비 담당자가 고쳐 주었습니다. "
            "그 후에 작업을 다시 시작했습니다."
        ),
        "planted": [{"expr": "작업이 안 됬습니다", "type": "spelling", "correction": "작업이 안 됐습니다"}],
    },
    {
        "answer_id": "E17-spelling",
        "item_id": "WRT-002",
        "text": (
            "반장님, 어제부터 감기에 걸려서 열이 많이 납니다. "
            "그래서 내일은 출근하지 안습니다. "
            "오늘 병원에 가 보고 약을 먹겠습니다. 모레 아침에는 꼭 나오겠습니다."
        ),
        "planted": [{"expr": "출근하지 안습니다", "type": "spelling", "correction": "출근하지 않습니다"}],
    },
    {
        "answer_id": "E18-spelling",
        "item_id": "WRT-003",
        "text": (
            "안전 관리자님께 알립니다. 창고 뒤쪽 선반이 왼쪽으로 기울었습니다. "
            "몇일 전부터 상자가 조금씩 밀려 나왔습니다. "
            "사람이 다치기 전에 오늘 중으로 고쳐 주시기 바랍니다."
        ),
        "planted": [{"expr": "몇일 전부터", "type": "spelling", "correction": "며칠 전부터"}],
    },
    {
        "answer_id": "E19-spelling",
        "item_id": "WRT-004",
        "text": (
            "다음 근무자님, 오늘 포장 작업은 다 끝냈습니다. "
            "라벨 붙이기는 아직 남아 있으니까 이따가 해 주십시오. "
            "삼번 기계는 오랫만에 청소했습니다. 밤에는 온도를 자주 확인해 주십시오."
        ),
        "planted": [{"expr": "오랫만에 청소했습니다", "type": "spelling", "correction": "오랜만에 청소했습니다"}],
    },
    {
        "answer_id": "E20-spelling",
        "item_id": "WRT-005",
        "text": (
            "사무실에 요청드립니다. 작업용 장갑이 거의 다 떨어져서 지금 세 켤레만 남았습니다. "
            "장갑 오십 켤레를 다음 주 화요일까지 보내 주시기 바램니다. 부탁드립니다."
        ),
        "planted": [{"expr": "보내 주시기 바램니다", "type": "spelling", "correction": "보내 주시기 바랍니다"}],
    },
]


# ===========================================================================
# 문항 불러오기와 자료 사전 검증
# ===========================================================================


def load_items() -> dict[str, ItemInfo]:
    """확정 문항 파일을 읽어 채점 요청에 넣을 수 있는 형태로 바꾼다."""
    raw = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))

    items: dict[str, ItemInfo] = {}
    for entry in raw["items"]:
        items[entry["item_id"]] = ItemInfo(
            item_id=entry["item_id"],
            prompt=entry["prompt"],
            item_type=entry.get("item_type", "free_response"),
            expected_register=entry.get("expected_register", "formal"),
            checklist=[
                ChecklistItem(id=c["id"], description=c["description"], weight=c.get("weight", 1.0))
                for c in entry.get("checklist", [])
            ],
            reference_keywords=entry.get("reference_keywords", []),
        )
    return items


def validate_data(items: dict[str, ItemInfo]) -> list[str]:
    """실험 자료가 실험을 할 수 있는 상태인지 LLM을 부르기 전에 확인한다.

    여기서 걸러야 하는 세 가지 사고:
      1) 정답표에 적은 표현이 답안에 없다 -> 검출률이 자료 오타 때문에 0%가 된다
      2) 같은 표현이 답안에 두 번 나온다 -> 어느 자리를 잡은 것인지 짝지을 수 없다
      3) 답안이 유효성 가드에 걸린다   -> 채점 자체가 무효라 실험이 성립하지 않는다

    LLM 호출은 돈과 하루 한도를 쓰므로, 이 확인이 끝나기 전에는 한 번도 부르지 않는다.
    문제를 찾으면 사람이 읽을 문장으로 모아 돌려준다.
    """
    problems: list[str] = []

    for entry in REPRO_ANSWERS + ERROR_ANSWERS:
        answer_id = entry["answer_id"]
        text = entry["text"]

        # 문항 번호가 확정 문항 파일에 실제로 있는지 본다
        if entry["item_id"] not in items:
            problems.append(f"{answer_id}: 문항 {entry['item_id']} 이 items 파일에 없다")
            continue

        # 정답표의 표현이 답안에 정확히 한 번만 나오는지 본다
        for planted in entry.get("planted", []):
            occurrences = text.count(planted["expr"])
            if occurrences == 0:
                problems.append(
                    f"{answer_id}: 정답표의 '{planted['expr']}' 가 답안 원문에 없다"
                )
            elif occurrences > 1:
                problems.append(
                    f"{answer_id}: 정답표의 '{planted['expr']}' 가 답안에 {occurrences}번 나와 "
                    "어느 자리를 잡았는지 짝지을 수 없다"
                )

        # 답안이 채점 가드를 통과하는지 본다. 하드 가드에 걸리면 점수가 아예 안 나온다
        report = check_answer_validity(text, items[entry["item_id"]].prompt)
        for check in report.hard_failures:
            problems.append(f"{answer_id}: 유효성 가드(하드)에 걸린다 — {check.reason}")
        for check in report.soft_failures:
            # 소프트 가드는 채점은 되지만 신뢰도가 partial 로 내려가서
            # 실험 1의 모든 회차가 '무효'로 빠져 버린다. 그래서 이것도 막아야 한다
            problems.append(f"{answer_id}: 유효성 가드(소프트)에 걸린다 — {check.reason}")

    return problems


# ===========================================================================
# 채점 한 번 돌리기 + 결과를 기록용으로 줄이기
# ===========================================================================


@dataclass
class RunOutcome:
    """채점 한 회차의 결과와, 그 회차를 믿어도 되는지에 대한 판정."""

    record: dict
    valid: bool
    invalid_reasons: list[str] = field(default_factory=list)
    quota_blocked: bool = False
    #: 잠시 뒤 같은 모델로 다시 부르면 될 만한 실패인지(분당 한도·서버 혼잡·시간 초과).
    #: 모델을 바꾸는 것이 아니라 '기다렸다 같은 조건으로 재시도'하는 데만 쓴다.
    retryable: bool = False


def build_request(answer_id: str, item: ItemInfo, text: str, attempt: int) -> ScoreRequest:
    """채점 요청 하나를 만든다.

    쓰기 답안이므로 전사 보정은 켜지 않는다.
    (응시자가 직접 친 글이라 보정하면 실제 맞춤법 오류가 지워진다)
    """
    return ScoreRequest(
        submission_id=f"{answer_id}#{attempt}",
        mode=Mode.WRITING,
        answer_text=text,
        item=item,
        options=ScoreOptions(use_llm=True),
    )


def _evidence_records(evidence_list) -> list[dict]:
    """근거 목록을 원자료에 남길 형태로 줄인다.

    인용이 비어 있는 근거는 뺀다. '오류가 없었다'는 자리 채우기용이라
    검출률이나 오탐 계산의 대상이 아니기 때문이다.
    """
    records = []
    for ev in evidence_list:
        if not ev.quote:
            continue
        records.append(
            {
                "quote": ev.quote,
                "start": ev.start,
                "end": ev.end,
                "comment": ev.comment,
            }
        )
    return records


def make_record(
    answer_id: str,
    attempt: int,
    response: ScoreResponse,
    wall_ms: float,
) -> dict:
    """채점 응답에서 실험에 쓸 값만 뽑아 원자료 한 줄로 만든다.

    응답 전체를 그대로 저장하면 파일이 지나치게 커져서 사람이 열어 보기 어렵다.
    그래서 실험 세 개가 실제로 보는 값(점수·체크리스트·오류 근거·시간)만 남긴다.
    """
    meta = response.meta

    # 오류 자질만 따로 모은다. 실험 2의 검출률과 오탐이 전부 여기서 나온다
    error_features = [
        {
            "id": f.id,
            "name": f.name,
            "status": f.status.value,
            "value": f.value,
            "error_count": f.components.get("error_count"),
            "evidence": _evidence_records(f.evidence),
        }
        for f in response.features
        if f.id.startswith("error_")
    ]

    return {
        "answer_id": answer_id,
        "attempt": attempt,
        "overall_score": response.overall_score,
        "overall_grade": response.overall_grade,
        "subscores": [
            {"area": s.area.value, "score": s.score, "status": s.status.value}
            for s in response.subscores
        ],
        "checklist": [
            {
                "id": c.id,
                "met": c.met,
                "source": c.source.value,
                "quotes": [ev.quote for ev in c.evidence if ev.quote],
            }
            for c in response.checklist_results
        ],
        "error_features": error_features,
        "timings_ms": dict(meta.timings_ms),
        "wall_ms": round(wall_ms, 1),
        "meta": {
            "reliability": meta.reliability.value,
            "reliability_reason": meta.reliability_reason,
            "llm_used": meta.llm_used,
            "llm_model": meta.llm_model,
            "llm_model_errors": meta.llm_model_errors,
            "dropped_citations": meta.dropped_citations,
            "answer_valid": meta.answer_valid,
            "validity_flags": meta.validity_flags,
        },
        "warnings": list(response.warnings),
    }


def judge_run(record: dict) -> RunOutcome:
    """이 회차를 실험 자료로 써도 되는지 판정한다.

    무효로 보는 경우:
      - 신뢰도가 full 이 아니다        : 대체 경로 점수가 섞였다는 뜻
      - 오류 자질을 하나라도 못 구했다  : LLM 오류 추출이 실패했다는 뜻
      - 체크리스트를 핵심어로 때웠다    : LLM 판정이 아니라 규칙 대체 판정이다
      - 429 가 경고에 남았다           : 하루 호출 한도에 막혔다

    이 판정이 왜 중요한가: 대체 경로로 계산된 점수도 겉보기에는 멀쩡한 숫자다.
    그것을 섞어 놓고 '세 번이 달랐다'고 세면 재현성이 없다는 잘못된 결론이 나온다.
    """
    reasons: list[str] = []

    if record["meta"]["reliability"] != Reliability.FULL.value:
        reasons.append(
            f"신뢰도가 {record['meta']['reliability']} (사유: {record['meta']['reliability_reason']})"
        )

    # 오류 자질이 하나라도 '못 구함'이면 LLM 문법 판정이 실패한 회차다
    unavailable = [
        f["id"] for f in record["error_features"] if f["status"] == FeatureStatus.UNAVAILABLE.value
    ]
    if unavailable:
        reasons.append(f"오류 자질을 못 구했다: {', '.join(unavailable)}")

    # 체크리스트가 규칙(핵심어)으로 판정됐다면 내용 점수는 LLM 판정의 결과가 아니다
    if any(c["source"] == FeatureSource.KIWI.value for c in record["checklist"]):
        reasons.append("체크리스트를 핵심어 일치로 대체 판정했다")

    # 호출 한도에 막힌 경우는 따로 표시해서, 실험을 계속할지 정하는 데 쓴다.
    # 무료 등급에서는 '분당 한도'와 '하루 한도'가 둘 다 429로 오기 때문에
    # 여기서는 어느 쪽인지 단정하지 않는다
    quota_blocked = any(("429" in w) or ("호출 한도" in w) for w in record["warnings"])
    if quota_blocked:
        reasons.append("LLM 호출 한도(429)에 막혔다")

    # 서버 혼잡(503)·시간 초과·네트워크 끊김은 모델 문제가 아니라 그때의 사정이다.
    # 잠시 뒤 같은 모델로 다시 부르면 되는 실패라 따로 표시해 둔다
    transient = any(
        ("일시적으로 응답하지 않는다" in w)
        or ("제한 시간 안에 오지 않았다" in w)
        or ("연결하지 못했다" in w)
        for w in record["warnings"]
    )
    if transient:
        reasons.append("LLM 서버가 일시적으로 응답하지 않았다")

    return RunOutcome(
        record=record,
        valid=not reasons,
        invalid_reasons=reasons,
        quota_blocked=quota_blocked,
        retryable=quota_blocked or transient,
    )


def run_once(
    answer_id: str,
    item: ItemInfo,
    text: str,
    attempt: int,
    client: GeminiClient,
    retries: int = 2,
    retry_wait: float = 65.0,
) -> RunOutcome:
    """답안 하나를 실제로 한 번 채점하고 결과를 기록한다.

    분당 한도나 서버 혼잡으로 실패하면 **같은 모델 그대로** 잠시 쉬었다 다시 부른다.
    모델을 바꾸지 않는 것이 핵심이다. 재현성 실험 도중에 판정 모델이 바뀌면
    '같은 조건에서 같은 값이 나오는가'라는 질문 자체가 성립하지 않는다.

    기본 대기 시간을 65초로 둔 이유: 분당 한도는 1분이 지나면 풀리는데,
    서버가 알려 주는 재시도 권장 시간이 55~58초였다. 거기에 여유를 조금 더 뒀다.
    """
    outcome: RunOutcome | None = None

    for try_no in range(retries + 1):
        request = build_request(answer_id, item, text, attempt)

        # 벽시계 시간도 잰다. meta.timings_ms 는 단계별 시간이라
        # '응시자가 실제로 기다리는 시간'과는 다르기 때문이다
        started = time.perf_counter()
        response = score_submission(request, client=client)
        wall_ms = (time.perf_counter() - started) * 1000

        outcome = judge_run(make_record(answer_id, attempt, response, wall_ms))
        # 몇 번 만에 성공했는지는 원자료에 남긴다(시간 분석에서 재시도분을 구별하기 위해)
        outcome.record["retry_count"] = try_no

        # 성공했거나, 다시 불러도 소용없는 실패거나, 마지막 시도였으면 여기서 끝낸다
        if outcome.valid or not outcome.retryable or try_no == retries:
            return outcome

        print(
            f"      일시적 실패({'; '.join(outcome.invalid_reasons)}) — "
            f"{retry_wait:.0f}초 쉬고 같은 모델로 다시 시도한다",
            flush=True,
        )
        time.sleep(retry_wait)

    return outcome  # 여기 오지 않지만 형식을 맞춰 둔다


# ===========================================================================
# 실험 1 — 재현성
# ===========================================================================


def repro_signature(record: dict) -> dict:
    """재현성을 판정할 때 비교할 값만 뽑는다.

    비교 대상은 세 가지다: 종합 점수, 영역별 점수, 체크리스트 충족 여부.
    시간이나 경고 문구는 매번 달라지는 것이 당연하므로 비교하지 않는다.
    """
    return {
        "overall_score": record["overall_score"],
        "subscores": {s["area"]: s["score"] for s in record["subscores"]},
        "checklist": {c["id"]: c["met"] for c in record["checklist"]},
    }


def compare_signatures(signatures: list[dict]) -> list[str]:
    """여러 회차의 비교값을 견줘 '어디가 달랐는지'를 사람이 읽을 문장으로 만든다."""
    if len(signatures) < 2:
        return []

    diffs: list[str] = []
    first = signatures[0]

    # 종합 점수부터 본다. 여기가 다르면 응시자에게 보이는 숫자가 달라진 것이다
    scores = [s["overall_score"] for s in signatures]
    if len(set(scores)) > 1:
        diffs.append(f"종합 점수: {scores}")

    # 영역별 점수는 어느 영역이 흔들렸는지가 원인 추적의 단서가 된다
    for area in first["subscores"]:
        values = [s["subscores"].get(area) for s in signatures]
        if len(set(values)) > 1:
            diffs.append(f"영역 점수({area}): {values}")

    # 체크리스트는 LLM의 0/1 판정이라 흔들릴 여지가 가장 큰 자리다
    for check_id in first["checklist"]:
        values = [s["checklist"].get(check_id) for s in signatures]
        if len(set(values)) > 1:
            diffs.append(f"체크리스트({check_id}) 판정: {values}")

    return diffs


def run_experiment_1(
    items: dict[str, ItemInfo],
    client: GeminiClient,
    repeats: int,
    sleep_sec: float,
    state: dict,
    save,
    done: dict[tuple[str, int], dict],
    retries: int = 2,
    retry_wait: float = 65.0,
) -> dict:
    """답안 10개를 각각 세 번씩 채점해서 결과가 같은지 본다.

    done 에 들어 있는 회차(지난 실행에서 이미 성공한 것)는 다시 부르지 않는다.
    하루 호출 한도 때문에 여러 날에 나눠 채워야 하기 때문이다.
    """
    results: list[dict] = []
    aborted_at: str | None = None

    for entry in REPRO_ANSWERS:
        item = items[entry["item_id"]]
        runs: list[dict] = []

        for attempt in range(1, repeats + 1):
            key = (entry["answer_id"], attempt)

            # 지난 실행에서 이미 성공한 회차는 그 결과를 그대로 쓴다(호출하지 않는다)
            if key in done:
                runs.append(
                    {
                        "attempt": attempt,
                        "status": "ok",
                        "invalid_reasons": [],
                        "record": done[key],
                        "reused": True,
                    }
                )
                continue

            # 앞에서 한도에 막혀 중단하기로 했으면 남은 회차는 아예 돌리지 않는다
            if aborted_at:
                runs.append(
                    {"attempt": attempt, "status": "not_run", "reason": "하루 호출 한도(429)로 중단"}
                )
                continue

            print(f"  [실험1] {entry['answer_id']} {attempt}/{repeats} 채점 중...", flush=True)
            outcome = run_once(
                entry["answer_id"], item, entry["text"], attempt, client,
                retries=retries, retry_wait=retry_wait,
            )

            runs.append(
                {
                    "attempt": attempt,
                    "status": "ok" if outcome.valid else "invalid",
                    "invalid_reasons": outcome.invalid_reasons,
                    "record": outcome.record,
                }
            )
            state["all_records"].append(outcome.record)
            save()

            # 재시도(1분 넘게 기다렸다 다시 부르기)까지 했는데도 한도에 막혔다면
            # 그것은 분당 한도가 아니라 하루 한도다. 기다려도 안 풀리므로 즉시 멈춘다.
            # 모델을 바꿔서 이어 돌리지 않는다. 다른 모델의 값을 섞으면 실험이 무의미해진다
            if outcome.quota_blocked:
                aborted_at = f"{entry['answer_id']} {attempt}회차"
                print(
                    "      하루 호출 한도로 판단해 남은 회차를 중단한다. "
                    "한도가 풀린 뒤 같은 명령을 다시 돌리면 여기서부터 이어진다.",
                    flush=True,
                )
                continue

            if sleep_sec:
                time.sleep(sleep_sec)

        # 유효한 회차만 모아 비교한다. 무효 회차를 섞으면 '불일치'가 부풀려진다
        valid_runs = [r for r in runs if r["status"] == "ok"]
        signatures = [repro_signature(r["record"]) for r in valid_runs]
        diffs = compare_signatures(signatures)

        # 세 번 모두 유효하고 세 번이 서로 같을 때만 '일치'로 센다
        if len(valid_runs) < repeats:
            verdict = "측정불가"
        elif diffs:
            verdict = "불일치"
        else:
            verdict = "일치"

        results.append(
            {
                "answer_id": entry["answer_id"],
                "item_id": entry["item_id"],
                "variant": entry["variant"],
                "text": entry["text"],
                "expected_unmet": entry["expected_unmet"],
                "verdict": verdict,
                "valid_run_count": len(valid_runs),
                "runs": runs,
                "diffs": diffs,
                # 참고값: 유효한 첫 회차의 점수와 체크리스트 판정
                "sample": signatures[0] if signatures else None,
            }
        )

    measurable = [r for r in results if r["verdict"] != "측정불가"]
    identical = [r for r in results if r["verdict"] == "일치"]

    return {
        "repeats": repeats,
        "answer_count": len(results),
        "measurable_count": len(measurable),
        "identical_count": len(identical),
        "identical_ratio": (len(identical) / len(measurable)) if measurable else None,
        "aborted_at": aborted_at,
        "answers": results,
    }


# ===========================================================================
# 실험 2 — 오류 탐지율
# ===========================================================================


def find_span(text: str, expr: str) -> tuple[int, int]:
    """정답표의 표현이 답안 원문 어디에 있는지 글자 위치로 찾는다."""
    start = text.find(expr)
    return (start, start + len(expr))


def evidence_hits_span(ev: dict, span: tuple[int, int], text: str) -> bool:
    """채점기가 지적한 자리와 우리가 심은 자리가 겹치는지 본다.

    글자 위치로 겹치는지 보는 것이 기본이다. 인용 검증 단계에서 이미
    '원문 몇 번째 글자'까지 구해 두었기 때문에 그 값을 그대로 쓸 수 있다.
    위치가 없는 근거(있으면 안 되지만)를 만나면 글자를 직접 대조한다.
    """
    if ev.get("start") is not None and ev.get("end") is not None:
        return ev["start"] < span[1] and span[0] < ev["end"]

    # 위치가 없을 때의 대비책: 공백·문장부호를 뗀 형태로 서로 들어 있는지 본다
    norm_quote, _ = normalize_for_match(ev.get("quote", ""))
    norm_span, _ = normalize_for_match(text[span[0] : span[1]])
    if not norm_quote or not norm_span:
        return False
    return norm_quote in norm_span or norm_span in norm_quote


def analyze_detection(entry: dict, record: dict) -> dict:
    """답안 하나에서 '심은 오류를 잡았는지'와 '안 심은 곳을 지적했는지'를 가른다.

    판정은 세 갈래다.
      정확검출  심은 자리를, 심은 유형의 자질이 잡았다
      유형오인  심은 자리를 잡기는 했는데 다른 유형으로 분류했다
      미검출    그 자리를 아무도 지적하지 않았다

    유형오인을 미검출과 따로 세는 이유: 오류를 못 본 것과 이름을 잘못 붙인 것은
    채점에 미치는 영향이 다르다. 둘 다 감점은 되지만, 응시자에게 주는
    피드백의 정확도가 다르므로 구별해서 보고해야 한다.
    """
    text = entry["text"]

    # 자질 id('error_josa')에서 유형 키('josa')를 되찾아 쓰기 쉽게 정리해 둔다
    by_type = {
        f["id"].replace("error_", ""): f
        for f in record["error_features"]
        if f["status"] == FeatureStatus.OK.value
    }

    planted_results = []
    # 오탐을 세려면 '심은 자리'를 모두 알아야 한다. 그 자리와 겹치는 지적은 오탐이 아니다
    planted_spans: list[tuple[int, int]] = []

    for planted in entry["planted"]:
        span = find_span(text, planted["expr"])
        planted_spans.append(span)

        # 1) 심은 유형의 자질이 그 자리를 잡았는지
        same_type_hits = [
            ev
            for ev in by_type.get(planted["type"], {}).get("evidence", [])
            if evidence_hits_span(ev, span, text)
        ]

        # 2) 못 잡았다면 다른 유형이 그 자리를 잡았는지 (유형오인)
        other_type_hits = []
        if not same_type_hits:
            for type_key, feature in by_type.items():
                if type_key == planted["type"]:
                    continue
                for ev in feature["evidence"]:
                    if evidence_hits_span(ev, span, text):
                        other_type_hits.append({"detected_as": type_key, **ev})

        if same_type_hits:
            verdict = "정확검출"
        elif other_type_hits:
            verdict = "유형오인"
        else:
            verdict = "미검출"

        planted_results.append(
            {
                "expr": planted["expr"],
                "type": planted["type"],
                "correction": planted["correction"],
                "span": list(span),
                "verdict": verdict,
                "hits": same_type_hits or other_type_hits,
            }
        )

    # 심은 자리와 하나도 안 겹치는 지적은 오탐 후보다.
    # '후보'라고 부르는 이유: 우리가 안 심었어도 실제로 어색한 표현일 수 있다.
    # 그래서 자동으로 오답 처리하지 않고 지적 내용을 그대로 남겨 사람이 판단하게 한다
    false_positives = []
    for type_key, feature in by_type.items():
        for ev in feature["evidence"]:
            if any(evidence_hits_span(ev, span, text) for span in planted_spans):
                continue
            false_positives.append(
                {
                    "detected_as": type_key,
                    "type_label": ERROR_TYPE_LABELS.get(type_key, type_key),
                    "quote": ev["quote"],
                    "comment": ev["comment"],
                }
            )

    return {"planted_results": planted_results, "false_positives": false_positives}


def run_experiment_2(
    items: dict[str, ItemInfo],
    client: GeminiClient,
    sleep_sec: float,
    state: dict,
    save,
    done: dict[tuple[str, int], dict],
    retries: int = 2,
    retry_wait: float = 65.0,
) -> dict:
    """오류를 심은 답안 20개를 한 번씩 채점해서 검출률과 오탐을 센다.

    실험 1과 마찬가지로, 지난 실행에서 이미 성공한 답안은 다시 부르지 않는다.
    """
    answers: list[dict] = []
    aborted_at: str | None = None

    for entry in ERROR_ANSWERS:
        key = (entry["answer_id"], 1)
        reused = key in done

        if reused:
            # 지난 실행의 채점 결과를 그대로 다시 해석한다(호출하지 않는다)
            record = done[key]
            outcome = RunOutcome(record=record, valid=True)
        elif aborted_at:
            answers.append(
                {
                    "answer_id": entry["answer_id"],
                    "status": "not_run",
                    "reason": "하루 호출 한도(429)로 중단",
                }
            )
            continue
        else:
            print(f"  [실험2] {entry['answer_id']} 채점 중...", flush=True)
            item = items[entry["item_id"]]
            outcome = run_once(
                entry["answer_id"], item, entry["text"], 1, client,
                retries=retries, retry_wait=retry_wait,
            )
            state["all_records"].append(outcome.record)

        # 무효 회차는 탐지율 계산에서 뺀다. 오류 자질을 못 구한 회차를
        # '못 잡았다'로 세면 모델의 성능이 아니라 호출 실패를 재는 셈이 된다
        if outcome.valid:
            detection = analyze_detection(entry, outcome.record)
            status = "ok"
        else:
            detection = {"planted_results": [], "false_positives": []}
            status = "invalid"

        answers.append(
            {
                "answer_id": entry["answer_id"],
                "item_id": entry["item_id"],
                "text": entry["text"],
                "status": status,
                "reused": reused,
                "invalid_reasons": outcome.invalid_reasons,
                "planted": entry["planted"],
                **detection,
                "record": outcome.record,
            }
        )
        save()

        if reused:
            continue

        # 재시도까지 하고도 한도에 막혔으면 하루 한도다. 기다려도 안 풀리므로 즉시 멈춘다
        if outcome.quota_blocked:
            aborted_at = entry["answer_id"]
            print(
                "      하루 호출 한도로 판단해 남은 답안을 중단한다. "
                "한도가 풀린 뒤 같은 명령을 다시 돌리면 여기서부터 이어진다.",
                flush=True,
            )
            continue

        if sleep_sec:
            time.sleep(sleep_sec)

    # 유형별로 세 갈래 판정을 집계한다
    by_type: dict[str, dict] = {
        key: {"planted": 0, "정확검출": 0, "유형오인": 0, "미검출": 0}
        for key in ERROR_TYPE_LABELS
    }
    for answer in answers:
        for result in answer.get("planted_results", []):
            bucket = by_type[result["type"]]
            bucket["planted"] += 1
            bucket[result["verdict"]] += 1

    for bucket in by_type.values():
        planted = bucket["planted"]
        # 검출률 = 심은 유형 그대로 잡아낸 비율. 유형오인은 여기 넣지 않는다
        bucket["detection_rate"] = (bucket["정확검출"] / planted) if planted else None
        # 관대한 기준(유형은 틀려도 그 자리를 지적하기는 한 비율)도 함께 낸다
        bucket["lenient_rate"] = (
            (bucket["정확검출"] + bucket["유형오인"]) / planted if planted else None
        )

    false_positives = [
        {"answer_id": a["answer_id"], **fp}
        for a in answers
        for fp in a.get("false_positives", [])
    ]

    total_planted = sum(b["planted"] for b in by_type.values())
    total_exact = sum(b["정확검출"] for b in by_type.values())

    return {
        "answer_count": len(answers),
        "scored_count": sum(1 for a in answers if a.get("status") == "ok"),
        "total_planted": total_planted,
        "total_exact": total_exact,
        "overall_detection_rate": (total_exact / total_planted) if total_planted else None,
        "by_type": by_type,
        "false_positives": false_positives,
        "aborted_at": aborted_at,
        "answers": answers,
    }


# ===========================================================================
# 이어 돌리기 — 지난 실행에서 성공한 회차를 다시 부르지 않기 위한 준비
# ===========================================================================


def load_previous_runs(raw_path: pathlib.Path) -> dict[tuple[str, int], dict]:
    """지난 실행의 원자료에서 '성공한 회차'만 골라 온다.

    왜 필요한가:
    오류 자질 모델의 무료 등급 하루 한도가 20회라서, 50회짜리 실험은
    하루에 끝나지 않는다. 다시 돌릴 때마다 처음부터 하면 영원히 못 끝낸다.
    그래서 이미 제대로 채점된 회차는 그 결과를 그대로 물려받는다.

    무효였던 회차는 물려받지 않는다. 그 회차야말로 다시 채워야 할 자리다.
    """
    if not raw_path.exists():
        return {}

    try:
        previous = json.loads(raw_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 지난 파일이 깨졌으면 없는 셈 치고 처음부터 돌린다(멈추지 않는다)
        return {}

    done: dict[tuple[str, int], dict] = {}
    for record in previous.get("all_records", []):
        # 저장된 기록을 지금 기준으로 다시 판정한다.
        # 판정 규칙이 바뀌었으면 예전에 통과한 회차도 여기서 걸러진다
        if judge_run(record).valid:
            done[(record["answer_id"], record["attempt"])] = record
    return done


# ===========================================================================
# 실험 3 — 채점 시간 분포
# ===========================================================================

# 보고서에 낼 단계와 그 설명.
# llm_parallel_ms 는 오류 추출과 체크리스트를 겹쳐서 실제로 기다린 시간이다.
# errors_ms + checklist_ms 보다 작은 것이 정상이며, 그것이 병렬 처리의 효과다.
TIMING_STAGES = [
    ("validity_ms", "유효성 가드(규칙)"),
    ("lexical_ms", "Kiwi 규칙 자질"),
    ("errors_ms", "LLM 오류 자질"),
    ("checklist_ms", "LLM 체크리스트 판정"),
    ("llm_parallel_ms", "LLM 두 호출을 겹친 실제 대기"),
    ("combine_ms", "점수 결합"),
    ("wall_ms", "전체(응시자가 기다리는 시간)"),
]


def summarize_timings(records: list[dict]) -> dict:
    """모든 회차의 단계별 소요 시간을 모아 평균·중앙값·최대를 낸다.

    LLM을 실제로 부른 회차만 센다. 호출이 실패한 회차의 시간은
    '채점에 걸리는 시간'이 아니라 '실패를 확인하는 데 걸린 시간'이라 성격이 다르다.
    """
    usable = [r for r in records if r["meta"]["llm_used"]]

    stages = {}
    for key, label in TIMING_STAGES:
        # wall_ms 는 기록의 최상위에 있고 나머지는 timings_ms 안에 있다
        values = [
            (r["wall_ms"] if key == "wall_ms" else r["timings_ms"].get(key))
            for r in usable
        ]
        values = [v for v in values if v is not None]
        if not values:
            continue
        stages[key] = {
            "label": label,
            "count": len(values),
            "mean_ms": round(statistics.mean(values), 1),
            "median_ms": round(statistics.median(values), 1),
            "max_ms": round(max(values), 1),
            "min_ms": round(min(values), 1),
        }

    # 체크리스트 판정이 13초 걸린 사례가 있었다. 재발했는지 눈으로 확인할 수 있게
    # 가장 느렸던 다섯 회차를 답안 길이와 함께 남긴다
    slowest = sorted(
        usable, key=lambda r: r["timings_ms"].get("checklist_ms", 0), reverse=True
    )[:5]
    slowest_checklist = [
        {
            "answer_id": r["answer_id"],
            "attempt": r["attempt"],
            "checklist_ms": r["timings_ms"].get("checklist_ms"),
            "errors_ms": r["timings_ms"].get("errors_ms"),
            "wall_ms": r["wall_ms"],
        }
        for r in slowest
    ]

    return {
        "run_count": len(usable),
        "stages": stages,
        "slowest_checklist": slowest_checklist,
    }


# ===========================================================================
# 보고서 만들기
# ===========================================================================


def _ms(value) -> str:
    """밀리초 값을 초 단위로 읽기 좋게 바꾼다."""
    if value is None:
        return "—"
    return f"{value / 1000:.2f}초"


def _pct(value) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def build_report(state: dict) -> str:
    """세 실험의 결과를 사람이 읽는 보고서(마크다운)로 만든다."""
    lines: list[str] = []
    add = lines.append

    exp1 = state.get("experiment_1")
    exp2 = state.get("experiment_2")
    exp3 = state.get("experiment_3")
    env = state["environment"]

    add(f"# K-TEST 채점기 품질 검증 보고서 ({state['date']})")
    add("")
    add("실호출로 측정한 값이다. 세 가지를 잰다: 같은 답안을 다시 채점해도 같은 점수가")
    add("나오는가(재현성), 일부러 심어 둔 문법 오류를 잡아내는가(탐지율), 얼마나 걸리는가(시간).")
    add("")

    # --- 실행 조건 ---------------------------------------------------------
    add("## 실행 조건")
    add("")
    add("| 항목 | 값 |")
    add("|---|---|")
    add(f"| 실행 시각 | {env['started_at']} |")
    add(f"| 채점기 버전 | {env['scoring_version']} |")
    add(f"| 기본 모델(체크리스트) | `{env['model']}` |")
    add(f"| 오류 자질 모델 | `{env['model_errors']}` |")
    add("| temperature | 0 (client.py 에서 고정) |")
    add(f"| 채점 기록 수 | {len(state['all_records'])}회 |")
    add(f"| 그중 지난 실행에서 물려받은 것 | {env.get('reused_run_count', 0)}회 |")
    add("| 문항 | items/writing_v0.json 확정 5문항 (쓰기) |")
    add("")

    # 실험이 중간에 끊겼으면 그 사실을 맨 위에 못 박는다.
    # 표만 보고 '이게 최종 수치'라고 읽어 가면 안 되기 때문이다
    aborts = [
        (name, (state.get(key) or {}).get("aborted_at"))
        for name, key in (("실험 1", "experiment_1"), ("실험 2", "experiment_2"))
    ]
    aborts = [(name, where) for name, where in aborts if where]
    if aborts:
        add("> **이 보고서는 완성되지 않은 측정이다.**")
        add(">")
        for name, where in aborts:
            add(f"> - {name}이 `{where}` 에서 LLM 호출 한도(429)에 막혀 중단됐다.")
        add(">")
        add("> 오류 자질 모델의 무료 등급 한도는 **하루 20회**다. 50회짜리 실험은")
        add("> 하루에 끝나지 않는다. 한도가 풀린 뒤 같은 명령을 다시 돌리면")
        add("> 이미 성공한 회차는 건너뛰고 남은 자리만 채운다.")
        add("> **막혔다고 해서 모델을 바꾸지 않았다.** 다른 모델의 점수를 섞으면")
        add("> 재현성 실험 자체가 성립하지 않기 때문이다.")
        add("")

    # --- 실험 1 -----------------------------------------------------------
    add("## 실험 1 — 재현성")
    add("")
    if not exp1:
        add("(실행하지 않음)")
        add("")
    else:
        add(f"답안 10개를 각각 {exp1['repeats']}회씩 채점하고, 종합 점수·영역별 점수·체크리스트")
        add("판정이 모두 같은지 보았다. 셋 중 하나라도 다르면 불일치로 센다.")
        add("")
        add("| 지표 | 값 |")
        add("|---|---|")
        add(f"| 측정한 답안 | {exp1['answer_count']}개 |")
        add(f"| 유효 측정된 답안 | {exp1['measurable_count']}개 |")
        add(f"| {exp1['repeats']}회 완전 동일 | {exp1['identical_count']}개 |")
        add(f"| **재현율** | **{_pct(exp1['identical_ratio'])}** |")
        if exp1["aborted_at"]:
            add(f"| 429로 중단된 지점 | {exp1['aborted_at']} |")
        add("")

        add("### 답안별 결과")
        add("")
        add("| 답안 | 문항 | 종류 | 판정 | 유효 회차 | 종합 점수 | 체크리스트 |")
        add("|---|---|---|---|---|---|---|")
        for answer in exp1["answers"]:
            sample = answer["sample"]
            score = "—" if not sample else f"{sample['overall_score']}"
            checks = (
                "—"
                if not sample
                else " ".join(
                    f"{k}={'O' if v else 'X'}" for k, v in sample["checklist"].items()
                )
            )
            add(
                f"| {answer['answer_id']} | {answer['item_id']} | {answer['variant']} | "
                f"{answer['verdict']} | {answer['valid_run_count']}/{exp1['repeats']} | "
                f"{score} | {checks} |"
            )
        add("")

        # 불일치와 무효 회차는 전문을 남긴다. 요약만으로는 원인을 못 찾기 때문이다
        problems = [a for a in exp1["answers"] if a["verdict"] != "일치"]
        add("### 불일치·측정불가 사례 전문")
        add("")
        if not problems:
            add("불일치와 측정불가가 한 건도 없었다.")
            add("")
        for answer in problems:
            add(f"#### {answer['answer_id']} — {answer['verdict']}")
            add("")
            add("답안 전문:")
            add("")
            add(f"> {answer['text']}")
            add("")
            if answer["diffs"]:
                add("무엇이 달랐나:")
                add("")
                for diff in answer["diffs"]:
                    add(f"- {diff}")
                add("")
            for run in answer["runs"]:
                if run["status"] == "ok":
                    continue
                reasons = run.get("invalid_reasons") or [run.get("reason", "")]
                add(f"- {run['attempt']}회차 무효: {'; '.join(r for r in reasons if r)}")
            add("")

    # --- 실험 2 -----------------------------------------------------------
    add("## 실험 2 — 오류 탐지율")
    add("")
    if not exp2:
        add("(실행하지 않음)")
        add("")
    else:
        add("오류를 일부러 심은 답안 20개(유형별 5개)를 한 번씩 채점했다.")
        add("심은 자리와 채점기가 지적한 자리가 글자 위치로 겹치면 검출로 센다.")
        add("")
        add("| 오류 유형 | 심은 수 | 정확검출 | 유형오인 | 미검출 | **검출률** | 관대 기준 |")
        add("|---|---|---|---|---|---|---|")
        for key, label in ERROR_TYPE_LABELS.items():
            bucket = exp2["by_type"][key]
            add(
                f"| {label} | {bucket['planted']} | {bucket['정확검출']} | "
                f"{bucket['유형오인']} | {bucket['미검출']} | "
                f"**{_pct(bucket['detection_rate'])}** | {_pct(bucket['lenient_rate'])} |"
            )
        add(
            f"| **합계** | {exp2['total_planted']} | {exp2['total_exact']} | | | "
            f"**{_pct(exp2['overall_detection_rate'])}** | |"
        )
        add("")
        add("- 정확검출 = 심은 유형 그대로 잡음 / 유형오인 = 자리는 잡았으나 다른 유형으로 분류")
        add("- 관대 기준 = 정확검출 + 유형오인 (그 자리를 어떻게든 지적한 비율)")
        if exp2["aborted_at"]:
            add(f"- 429로 중단된 지점: {exp2['aborted_at']}")
        add("")

        add("### 답안별 상세")
        add("")
        add("| 답안 | 심은 표현 | 심은 유형 | 판정 | 채점기가 인용한 부분 |")
        add("|---|---|---|---|---|")
        for answer in exp2["answers"]:
            if answer.get("status") != "ok":
                # 429로 아예 돌리지 못한 답안과, 돌렸으나 무효였던 답안을 구별해 적는다
                note = "; ".join(answer.get("invalid_reasons", [])) or answer.get(
                    "reason", ""
                )
                label = "미실행" if answer.get("status") == "not_run" else "무효"
                add(f"| {answer['answer_id']} | — | — | {label} | {note} |")
                continue
            for result in answer["planted_results"]:
                hits = result["hits"]
                if hits:
                    quoted = "; ".join(
                        f"“{h['quote']}”"
                        + (f" (→{ERROR_TYPE_LABELS.get(h['detected_as'], h['detected_as'])}로 분류)"
                           if h.get("detected_as") else "")
                        for h in hits[:2]
                    )
                else:
                    quoted = "지적 없음"
                add(
                    f"| {answer['answer_id']} | {result['expr']} | "
                    f"{ERROR_TYPE_LABELS[result['type']]} | {result['verdict']} | {quoted} |"
                )
        add("")

        # 미검출 사례는 전문을 남긴다. 어떤 오류를 놓치는지가 다음 개선의 출발점이다
        missed = [
            (a, r)
            for a in exp2["answers"]
            for r in a.get("planted_results", [])
            if r["verdict"] == "미검출"
        ]
        add("### 미검출 사례 전문")
        add("")
        if not missed:
            add("미검출이 한 건도 없었다.")
            add("")
        for answer, result in missed:
            add(f"#### {answer['answer_id']} — 심은 오류 '{result['expr']}' ({ERROR_TYPE_LABELS[result['type']]})")
            add("")
            add(f"> {answer['text']}")
            add("")
            add(f"- 올바른 형태: {result['correction']}")
            other = [
                f"{ERROR_TYPE_LABELS.get(fp['detected_as'], fp['detected_as'])}: “{fp['quote']}”"
                for fp in answer.get("false_positives", [])
            ]
            add(f"- 이 답안에서 채점기가 지적한 다른 곳: {', '.join(other) if other else '없음'}")
            add("")

        add("### 오탐 후보 (사람이 최종 판단할 것)")
        add("")
        add("우리가 심지 않은 자리에 대한 지적이다. **자동으로 오답 처리하지 않았다.**")
        add("심지 않았어도 실제로 어색한 표현일 수 있으므로 지적 내용을 그대로 옮겨 둔다.")
        add("")
        if not exp2["false_positives"]:
            add("오탐 후보가 한 건도 없었다.")
            add("")
        else:
            add(f"총 {len(exp2['false_positives'])}건.")
            add("")
            add("| 답안 | 분류된 유형 | 인용 | 채점기의 설명 |")
            add("|---|---|---|---|")
            for fp in exp2["false_positives"]:
                comment = fp["comment"].replace("|", "/").replace("\n", " ")
                add(
                    f"| {fp['answer_id']} | {fp['type_label']} | “{fp['quote']}” | {comment} |"
                )
            add("")

    # --- 실험 3 -----------------------------------------------------------
    add("## 실험 3 — 채점 시간 분포")
    add("")
    if not exp3:
        add("(실행하지 않음)")
        add("")
    else:
        add(f"위 실험에서 실제로 LLM을 부른 {exp3['run_count']}회의 단계별 소요 시간이다.")
        add("")
        add("| 단계 | 평균 | 중앙값 | 최대 | 최소 |")
        add("|---|---|---|---|---|")
        for key, _label in TIMING_STAGES:
            stage = exp3["stages"].get(key)
            if not stage:
                continue
            add(
                f"| {stage['label']} (`{key}`) | {_ms(stage['mean_ms'])} | "
                f"{_ms(stage['median_ms'])} | {_ms(stage['max_ms'])} | {_ms(stage['min_ms'])} |"
            )
        add("")
        add("주의: `validity_ms` 의 최대값에는 Kiwi(형태소 분석기)를 처음 불러오는 시간이")
        add("한 번 섞여 있다. 서버가 떠 있는 동안에는 처음 한 번만 드는 비용이고,")
        add("두 번째 채점부터는 중앙값 쪽이 실제 값이다.")
        add("")
        add("### 체크리스트 판정이 느렸던 회차")
        add("")
        add("이전에 체크리스트 판정 한 번이 13초 걸린 사례가 있어서 재발 여부를 따로 본다.")
        add("")
        add("| 답안 | 회차 | 체크리스트 | 오류 자질 | 전체 |")
        add("|---|---|---|---|---|")
        for row in exp3["slowest_checklist"]:
            add(
                f"| {row['answer_id']} | {row['attempt']} | {_ms(row['checklist_ms'])} | "
                f"{_ms(row['errors_ms'])} | {_ms(row['wall_ms'])} |"
            )
        add("")

    # --- 결론 -------------------------------------------------------------
    add("## 결론")
    add("")
    for line in state.get("conclusions", []):
        add(f"- {line}")
    add("")
    add("---")
    add("")
    add(f"원자료: `outputs/quality_raw_{state['date']}.json`")
    add(f"재실행: `python scripts/verify_quality.py --date {state['date']}`")
    add("")

    return "\n".join(lines)


def build_conclusions(state: dict) -> list[str]:
    """세 실험에서 한 줄씩 결론을 뽑는다. 심사에서 그대로 말할 수 있는 문장이다."""
    conclusions: list[str] = []

    exp1 = state.get("experiment_1")
    if exp1 and exp1["measurable_count"]:
        if exp1["identical_ratio"] == 1.0:
            conclusions.append(
                f"재현성: 답안 {exp1['measurable_count']}개를 각 {exp1['repeats']}회 채점해 "
                "종합 점수·영역 점수·체크리스트 판정이 100% 동일했다 "
                "(temperature 0 + 규칙 자질 분리의 효과)."
            )
        else:
            failed = [a["answer_id"] for a in exp1["answers"] if a["verdict"] == "불일치"]
            conclusions.append(
                f"재현성: {exp1['measurable_count']}개 중 {exp1['identical_count']}개"
                f"({_pct(exp1['identical_ratio'])})가 {exp1['repeats']}회 완전 동일했다. "
                f"흔들린 답안: {', '.join(failed)}."
            )

    exp2 = state.get("experiment_2")
    if exp2 and exp2["total_planted"]:
        per_type = ", ".join(
            f"{label} {_pct(exp2['by_type'][key]['detection_rate'])}"
            for key, label in ERROR_TYPE_LABELS.items()
        )
        conclusions.append(
            f"오류 탐지: 심은 오류 {exp2['total_planted']}건 중 "
            f"{exp2['total_exact']}건을 같은 유형으로 잡아 전체 검출률 "
            f"{_pct(exp2['overall_detection_rate'])}다 ({per_type})."
        )

    exp3 = state.get("experiment_3")
    if exp3 and exp3.get("stages", {}).get("wall_ms"):
        wall = exp3["stages"]["wall_ms"]
        conclusions.append(
            f"채점 시간: 답안 한 개당 평균 {_ms(wall['mean_ms'])}, 최대 {_ms(wall['max_ms'])}다 "
            "(LLM 두 호출을 병렬로 보낸 결과)."
        )

    return conclusions


# ===========================================================================
# 진입점
# ===========================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="채점기의 재현성·오류 탐지율·소요 시간을 실측해서 보고서를 남긴다.",
    )
    parser.add_argument(
        "--date", default=datetime.now().strftime("%Y%m%d"),
        help="출력 파일 이름에 붙일 날짜 (기본: 오늘)",
    )
    parser.add_argument("--repeats", type=int, default=3, help="실험 1의 반복 채점 횟수")
    parser.add_argument(
        "--only", choices=["1", "2"], default=None,
        help="실험 하나만 돌린다 (1=재현성, 2=오류 탐지)",
    )
    parser.add_argument(
        "--sleep", type=float, default=13.0,
        help=(
            "호출 사이에 쉬는 시간(초). 오류 자질 모델의 무료 등급 한도가 분당 5회라서 "
            "기본값을 넉넉히 두었다. 줄이면 실험이 중간에 429로 끊긴다"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="LLM을 부르지 않고 자료 검증만 한다(공짜). 답안·정답표를 고친 뒤 확인용",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="지난 실행 결과를 물려받지 않고 처음부터 다시 채점한다",
    )
    parser.add_argument(
        "--retries", type=int, default=2,
        help=(
            "분당 한도·서버 혼잡으로 실패했을 때 같은 모델로 다시 시도할 횟수. "
            "0 으로 두면 재시도하지 않는다(한도가 이미 바닥난 것을 아는 날에 쓴다)"
        ),
    )
    parser.add_argument(
        "--retry-wait", type=float, default=65.0,
        help="재시도 전에 쉬는 시간(초). 분당 한도는 1분이면 풀린다",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    items = load_items()

    # 1) 자료 검증. 여기서 걸리면 LLM은 한 번도 부르지 않고 끝낸다
    print("자료 검증 중...")
    problems = validate_data(items)
    if problems:
        print(f"\n자료에 문제가 {len(problems)}건 있어 실험을 시작하지 않는다:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"  통과: 재현성 답안 {len(REPRO_ANSWERS)}개, 오류 답안 {len(ERROR_ANSWERS)}개, "
        f"심은 오류 {sum(len(e['planted']) for e in ERROR_ANSWERS)}건"
    )

    if args.dry_run:
        print("\n--dry-run 이므로 여기서 끝낸다(LLM 호출 없음).")
        return 0

    client = GeminiClient()
    if not client.available:
        print("GEMINI_API_KEY 가 없어 실호출 실험을 할 수 없다. .env 를 확인하라.")
        return 1

    from src.scoring.schema import SCORING_VERSION

    state: dict = {
        "date": args.date,
        "environment": {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "scoring_version": SCORING_VERSION,
            "model": client.model_name,
            "model_errors": client_for_errors(client).model_name,
            "temperature": 0,
            "repeats": args.repeats,
        },
        "all_records": [],
    }

    raw_path = OUTPUT_DIR / f"quality_raw_{args.date}.json"

    # 지난 실행에서 성공한 회차를 물려받는다. 하루 호출 한도 때문에
    # 여러 번 나눠 돌려야 하므로, 이미 채운 자리를 다시 부르지 않는 것이 중요하다
    done = {} if args.fresh else load_previous_runs(raw_path)
    if done:
        print(f"  지난 실행에서 성공한 {len(done)}회차를 물려받는다(다시 부르지 않는다).")
        # 물려받은 기록도 원자료에 그대로 남겨야 시간 분석의 표본이 유지된다
        state["all_records"].extend(done.values())
    state["environment"]["reused_run_count"] = len(done)

    def save() -> None:
        """중간 결과를 그때그때 파일에 쓴다.

        50회 호출 중간에 한도에 막히거나 프로그램이 멈춰도
        여기까지의 자료는 남아야 다시 돌릴지 판단할 수 있다.
        """
        raw_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    total_calls = (0 if args.only == "2" else len(REPRO_ANSWERS) * args.repeats) + (
        0 if args.only == "1" else len(ERROR_ANSWERS)
    )
    print(f"\n채점 {total_calls}회 중 {total_calls - len(done)}회를 실호출한다 "
          f"(모델: {client.model_name} / {client_for_errors(client).model_name})\n")

    if args.only != "2":
        state["experiment_1"] = run_experiment_1(
            items, client, args.repeats, args.sleep, state, save, done,
            retries=args.retries, retry_wait=args.retry_wait,
        )
        save()

    if args.only != "1":
        state["experiment_2"] = run_experiment_2(
            items, client, args.sleep, state, save, done,
            retries=args.retries, retry_wait=args.retry_wait,
        )
        save()

    # 실험 3은 새 호출 없이 앞의 두 실험이 남긴 시간 기록만 모아서 낸다
    state["experiment_3"] = summarize_timings(state["all_records"])
    state["conclusions"] = build_conclusions(state)
    state["environment"]["finished_at"] = datetime.now().isoformat(timespec="seconds")
    save()

    report_path = OUTPUT_DIR / f"quality_report_{args.date}.md"
    report_path.write_text(build_report(state), encoding="utf-8")

    print("\n" + "=" * 60)
    for line in state["conclusions"]:
        print(f"  {line}")
    print("=" * 60)
    print(f"\n보고서: {report_path}")
    print(f"원자료: {raw_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
