# -*- coding: utf-8 -*-
"""체크리스트 v2 — **후보 답안을 먼저 만들고, 그것들이 실패하는 방식으로** 체크리스트를 짠다.

■ 왜 다시 만드는가 (앞 실험의 병목)

8/9 실험에서 체크리스트 채점(QWK 0.510~0.620)이 LLM 직접 채점(0.758~0.787)에
크게 졌다. 기준선을 세워 원인을 캐 보니 결합 방식이 아니라 **체크리스트 항목 자체**가
병목이었다. 9문항 전부 항목이 2개씩이라 점수가 사실상 세 칸(0·3·5)뿐이었고,
항목 2개가 들고 있는 정보의 천장이 QWK 0.693 이었다.

그래서 이번에는 **항목을 어떻게 뽑는가**를 바꾼다.

■ 무엇을 이식했나 (RLCF 논문, arXiv 2507.18624v2 · Apple·CMU)

논문 2절이 체크리스트 생성 방식 둘을 견주고 **후보 기반(candidate-based)** 이
지시문만 보고 뽑는 **직접(direct)** 방식을 이겼다고 보고했다
(원자성 68→90, 포괄성 74→82, 전체 선호 38→56). v1 이 쓴 것이 direct 다.

후보 기반의 절차는 이렇다.
  ① 품질이 서로 다른 후보 답안들을 먼저 만든다
  ② 그 답안들이 **실패하는 모든 방식**(failure modes)을 적게 해서 체크리스트를 만든다
     — 논문의 정의: "요구사항이란, 없으면 응답이 실패하게 되는 모든 측면"
  ③ 항목마다 **중요도(importance) 0~100** 을 함께 매긴다
그리고 모든 체크리스트에 **보편 항목 2개**를 덧붙인다(논문 3.1 Universal criteria).
체크리스트만 최적화하면 장황한 서두 같은 '점수 따먹기'가 생겨서 넣은 안전장치다.

■ 시험지 오염 금지 — 후보 답안은 **지시문만 보고** 지어낸다

논문은 실제 모델 응답을 후보로 쓰지만, 우리는 **실제 응시자 답안을 절대 쓰지 않는다.**
응시자 답안을 보고 체크리스트를 만들면, 그 답안으로 채점 성적을 재는 순간
답을 보고 시험지를 만든 것이 된다(누출). 그래서 1단계는 문항 지시문만 준다.

■ v1 과 달라진 규칙, 그대로 둔 규칙

바꾼 것: 생성 절차(후보 기반), 항목 수 상한 5개 → **10개**, 중요도 부여, 보편 항목 2개.
그대로 둔 것: **발음·억양·속도·문법·어휘 정확성 항목 금지**(그 영역은 다른 자질이
담당하므로 중복 평가), **개수를 채우려고 억지 항목을 만들지 말 것**, 한 항목은 한 가지만.
이 세 가지는 팀원이 쓴 v1 원 프롬프트의 규칙이라 이번에도 지킨다.

■ 만들어 둔 것은 덮어쓰지 않는다

응시자별 실시간 생성 금지 원칙과 같다. 한 번 만들어 파일에 박아 두고 채점은 읽기만 한다.
`--force` 없이는 이미 만든 문항을 다시 만들지 않는다.

■ 쓰는 법

    python gen_checklists_v2.py                 # 대상 문항 전부 생성(이미 있으면 건너뜀)
    python gen_checklists_v2.py --only 2        # 앞 2문항만 (파일럿)
    python gen_checklists_v2.py --force         # 이미 있어도 다시 생성
    python gen_checklists_v2.py --compare       # 생성하지 않고 v1 vs v2 항목 수 표만 출력
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import (  # noqa: E402
    JUDGE_MODEL,
    OUT_DIR,
    call_with_retry,
    enable_utf8_output,
    group_by_prompt,
    load_rows,
    make_judge_client,
    print_table,
    use_free_backup_key,
)
from gen_checklists import load_checklists as load_checklists_v1  # noqa: E402

#: v2 체크리스트를 고정해 두는 파일. 뒤의 판정·분석은 이 파일만 읽는다.
CHECKLIST_V2_PATH = OUT_DIR / "checklists_v2.json"

#: 문항별로 만들 후보 답안의 품질 등급. 논문의 "품질이 서로 다른 후보들"을
#: 우리 시험에 맞게 네 칸으로 고정했다. 등급을 고정하는 이유는 문항마다
#: 후보의 폭이 들쭉날쭉하면 거기서 나온 체크리스트도 문항마다 성격이 달라지기 때문이다.
CANDIDATE_LEVELS = ("모범", "보통", "최소한", "과제 놓침")

#: 과제 고유 항목의 상한. v1 은 5개였고 실제로 2개만 나왔다.
#: 상한을 올린다고 항목이 늘어난다는 보장은 없지만, 적어도 상한이 막고 있지는 않게 한다.
MAX_TASK_ITEMS = 10

#: 원문(v1 팀원 프롬프트)이 정한 세 갈래. 이 밖의 값이 오면 그대로 두되 경고를 남긴다.
VALID_CATEGORIES = ("정보전달", "행위수행", "상황판단")

# ─────────────────────────────────────────────────────────────────────────────
# 보편 항목 2개 (논문 3.1 Universal criteria 를 우리 말하기 시험에 옮긴 것)
#
# 논문 원문은 ① 불필요하거나 주제를 벗어난 정보 없이 요청에 직접 답했는가
#            ② 맥락과 지시가 요구하는 격식·태도에 맞는가
# 이고, 둘의 중요도 합이 100 이다.
#
# 우리는 50/50 으로 **고정**한다. LLM 에게 이 둘의 중요도까지 매기게 하면
# 문항마다 값이 달라져서 "보편 항목"이라는 말이 무색해지고, 보편 항목을 빼고
# 다시 계산하는 비교(ablation)도 문항마다 다른 조건이 된다.
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSAL_ITEMS = (
    {
        "id": "U1",
        "question": "요청받은 것에 직접 답했고, 주제를 벗어난 내용으로 답안을 채우지 않았는가?",
        "category": "행위수행",
        "required": True,
        "importance": 50,
        "universal": True,
    },
    {
        "id": "U2",
        "question": "상황과 듣는 사람에 맞는 말투·격식으로 말했는가?",
        "category": "상황판단",
        "required": False,
        "importance": 50,
        "universal": True,
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# 1단계 — 품질이 다른 가상 답안 4개 만들기
# ─────────────────────────────────────────────────────────────────────────────
CANDIDATE_SYSTEM = """\
당신은 한국어 말하기 시험의 문항 검토 전문가다.
실제 응시자(한국에서 일하는 외국인 노동자, 한국어 학습자)가 이 문항에 어떻게 답할지를
품질별로 미리 그려 보는 일을 한다. 채점을 하지 않는다. 답안만 지어낸다.
반드시 지정된 JSON 형식으로만 답한다."""

CANDIDATE_PROMPT = """\
[문항 지시문]
{prompt_text}

이 문항에 대해 **품질이 서로 다른 답안 4개**를 지어내라.
실제 응시자가 말로 답한 것을 그대로 받아 적은 것처럼, 구어체 한 덩어리로 쓴다.

만들 4개는 다음과 같다.
1) level="모범"      — 요구된 것을 빠짐없이 수행하고 내용이 구체적이다.
2) level="보통"      — 요구된 것의 핵심은 말했으나 일부가 빠졌거나 설명이 얕다.
3) level="최소한"    — 문항과 관련은 있으나 한두 마디로 끝냈고 내용이 매우 빈약하다.
4) level="과제 놓침" — 문항이 요구한 것을 하지 않았다. 딴 이야기를 하거나 요구 중 하나를 통째로 빠뜨렸다.

지킬 것
- 실제 응시자 답안을 본 적이 없다고 생각하고, 오직 위 지시문만 보고 지어낸다.
- 한국어 학습자다운 말투로 쓴다. 다만 **문법·발음 오류를 일부러 넣지 마라** —
  이 실험에서 재는 것은 내용과 과제 수행이지 정확성이 아니다.
- 각 답안은 30자 이상 200자 이하로 쓴다.
- 네 개가 서로 확실히 다른 실패·성공 양상을 보이게 한다.

다음 JSON 형식으로만 답하라.
{
  "candidates": [
    {"level": "모범", "text": "..."},
    {"level": "보통", "text": "..."},
    {"level": "최소한", "text": "..."},
    {"level": "과제 놓침", "text": "..."}
  ]
}"""

CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["level", "text"],
            },
        },
    },
    "required": ["candidates"],
}


# ─────────────────────────────────────────────────────────────────────────────
# 2단계 — 후보들이 '실패하는 방식'으로 체크리스트 짜기
# ─────────────────────────────────────────────────────────────────────────────
CHECKLIST_SYSTEM = """\
당신은 한국어 말하기 시험의 문항 검토 전문가다.
응답의 "내용 및 과제 수행"만을 평가하는 이진 체크리스트를 만든다.
요구사항이란, **그것이 없으면 응답이 실패하게 되는 모든 측면**을 말한다.
반드시 지정된 JSON 형식으로만 답한다."""

CHECKLIST_PROMPT = """\
[문항 지시문]
{prompt_text}

[이 문항에 대한 후보 답안 4개 — 품질이 서로 다르다]
{candidates_text}

할 일은 두 가지다.

(1) 위 후보 답안들이 **실패하는 방식**(failure modes)을 전부 찾아 적어라.
    "이 답안은 무엇이 없어서 좋은 답이 되지 못했는가"를 하나씩 말로 쓴다.

(2) 그 실패 방식들을 뒤집어 **예/아니오 체크리스트**로 만들어라.
    항목이 전부 '예'이면 그 답안은 이 문항의 요구를 충족한 것이어야 한다.

체크리스트 작성 규칙
- 각 항목은 '예/아니오'로만 답할 수 있어야 하고, '예'가 항상 더 좋은 응답을 뜻해야 한다.
- 한 항목은 **한 가지만** 물어야 한다. ("위치와 이유를 말했는가"는 두 항목으로 나눈다)
- 응답 전사 텍스트만 보고 판정할 수 있어야 한다. 억양이나 태도를 짐작해서 묻지 마라.
- **발음·억양·속도에 대한 항목, 문법·어휘의 정확성에 대한 항목은 만들지 마라.**
  그 영역은 별도의 자질이 담당하므로 중복 평가가 된다.
- 관련된 측면을 두루 덮되, **개수를 채우려고 억지 항목이나 자명한 항목을 만들지 마라.**
  최대 {max_items}개이며, 5개로 충분한 문항이면 5개만 출력한다.
- 난이도를 섞어라. 최소한을 말한 응답도 통과하는 항목과, 충실히 수행한 응답만
  통과하는 항목이 함께 있어야 한다.

각 항목에 다음을 표기하라.
- category: "정보전달"(요구된 정보를 말했는가) | "행위수행"(요구된 말하기 행위를 수행했는가)
            | "상황판단"(상황·상대에 맞게 판단했는가) 중 하나
- required: true(이 항목이 충족되지 않으면 과제 실패) | false
- importance: 0~100 사이의 정수. 이 항목이 응답의 좋고 나쁨을 얼마나 좌우하는가.
              모든 항목에 같은 값을 주지 마라. 항목 사이의 경중을 실제로 구분하라.

다음 JSON 형식으로만 답하라.
{
  "failure_modes": ["...", "..."],
  "checklist": [
    {"id": 1, "question": "...", "category": "정보전달", "required": true, "importance": 90},
    {"id": 2, "question": "...", "category": "행위수행", "required": false, "importance": 40}
  ]
}"""

CHECKLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "failure_modes": {"type": "array", "items": {"type": "string"}},
        "checklist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "question": {"type": "string"},
                    "category": {"type": "string"},
                    "required": {"type": "boolean"},
                    "importance": {"type": "integer"},
                },
                "required": ["id", "question", "category", "required", "importance"],
            },
        },
    },
    "required": ["failure_modes", "checklist"],
}


def build_candidate_prompt(prompt_text: str) -> str:
    """1단계 지시문에 문항 지시문을 끼워 넣는다.

    `.format()` 을 쓰지 않는 이유는 출력 예시의 중괄호가 그대로 들어 있기 때문이다
    (`.format()` 을 쓰면 그 부분이 깨진다). v1 과 같은 이유·같은 방식이다.
    """
    return CANDIDATE_PROMPT.replace("{prompt_text}", prompt_text)


def format_candidates(candidates: list[dict]) -> str:
    """후보 답안 4개를 2단계 지시문에 넣을 글로 만든다."""
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(f"후보 {i} (품질: {c.get('level', '?')})")
        lines.append("```")
        lines.append(str(c.get("text", "")).strip())
        lines.append("```")
    return "\n".join(lines)


def build_checklist_prompt(prompt_text: str, candidates: list[dict]) -> str:
    """2단계 지시문을 만든다. 후보 답안과 항목 수 상한을 끼워 넣는다."""
    return (CHECKLIST_PROMPT
            .replace("{prompt_text}", prompt_text)
            .replace("{candidates_text}", format_candidates(candidates))
            .replace("{max_items}", str(MAX_TASK_ITEMS)))


def normalize_candidates(payload: dict) -> tuple[list[dict], list[str]]:
    """1단계 응답을 다듬는다. 빈 답안은 버리고, 몇 개가 왔는지 확인한다."""
    warnings: list[str] = []
    raw = payload.get("candidates")
    if not isinstance(raw, list):
        return [], ["응답에 candidates 배열이 없다"]

    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            warnings.append(f"후보 형식이 올바르지 않아 버렸다: {str(entry)[:40]}")
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            warnings.append("본문이 비어 있는 후보를 버렸다")
            continue
        out.append({"level": str(entry.get("level", "")).strip() or "미표기", "text": text})

    # 네 칸을 다 못 채워도 멈추지 않는다. 다만 몇 개로 만들었는지는 반드시 남긴다 —
    # 후보가 적으면 거기서 나온 체크리스트가 덜 촘촘할 수 있기 때문이다
    if len(out) != len(CANDIDATE_LEVELS):
        warnings.append(f"후보가 {len(out)}개다(기대 {len(CANDIDATE_LEVELS)}개)")
    return out, warnings


def normalize_items_v2(payload: dict) -> tuple[list[dict], list[str], list[str]]:
    """2단계 응답을 쓸 수 있는 모양으로 다듬는다.

    다듬는 것:
      ① 항목 번호(id)를 문자열로 통일한다 — 판정 결과와 짝지을 열쇠가 된다.
         보편 항목이 U1·U2 를 쓰므로, 과제 항목이 그 이름을 쓰면 뒤에 표를 붙여 피한다
      ② 질문이 비어 있는 항목은 버린다(판정할 수 없다)
      ③ 중요도를 0~100 정수로 누른다. 값이 없거나 이상하면 50 으로 두고 경고를 남긴다
      ④ 상한(10개)을 넘으면 **중요도가 높은 것부터** 남긴다.
         v1 은 앞에서부터 잘랐는데, 중요도가 생긴 이상 앞뒤 순서보다 경중이 낫다
      ⑤ 중요도가 전부 0이면 나눗셈이 성립하지 않으므로 전부 50 으로 되돌린다

    돌려주는 값은 (항목, 경고, 실패 방식 목록)이다. 실패 방식을 함께 돌려주는 이유:
    "이 항목이 왜 생겼는가"가 곧 체크리스트의 근거이고, 근거 없는 산출물을 남기지 않는다.
    """
    warnings: list[str] = []
    failure_modes = [str(m).strip() for m in (payload.get("failure_modes") or [])
                     if str(m).strip()]

    raw = payload.get("checklist")
    if not isinstance(raw, list):
        return [], ["응답에 checklist 배열이 없다"], failure_modes

    reserved = {u["id"] for u in UNIVERSAL_ITEMS}
    items: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            warnings.append(f"항목 형식이 올바르지 않아 버렸다: {str(entry)[:40]}")
            continue
        question = str(entry.get("question", "")).strip()
        if not question:
            warnings.append("질문이 비어 있는 항목을 버렸다")
            continue

        category = str(entry.get("category", "")).strip()
        if category not in VALID_CATEGORIES:
            warnings.append(f"정해진 갈래가 아닌 category='{category}' (그대로 둠)")

        # required 는 true/false 로 오게 돼 있지만 문자열로 오는 경우까지 받아 준다
        required = str(entry.get("required", False)).strip().lower() in ("true", "1", "yes")

        # 중요도는 0~100 정수. 못 읽으면 50(중간)으로 두되 그 사실을 남긴다
        try:
            importance = int(round(float(entry.get("importance"))))
        except (TypeError, ValueError):
            importance = 50
            warnings.append(f"중요도를 숫자로 읽지 못해 50 으로 뒀다: {entry.get('importance')!r}")
        if importance < 0 or importance > 100:
            warnings.append(f"중요도 {importance} 가 0~100 밖이라 눌렀다")
            importance = max(0, min(100, importance))

        cid = str(entry.get("id", len(items) + 1)).strip() or str(len(items) + 1)
        if cid in reserved:
            # 보편 항목의 이름과 부딪히면 판정 결과를 짝지을 수 없게 된다
            cid = f"T{cid}"
            warnings.append(f"보편 항목과 같은 id 가 와서 '{cid}' 로 바꿨다")

        items.append({
            "id": cid,
            "question": question,
            "category": category,
            "required": required,
            "importance": importance,
            "universal": False,
        })

    if len(items) > MAX_TASK_ITEMS:
        warnings.append(f"항목이 {len(items)}개로 상한({MAX_TASK_ITEMS})을 넘어 "
                        "중요도가 높은 것부터 남겼다")
        items.sort(key=lambda it: (-it["importance"], it["id"]))
        items = items[:MAX_TASK_ITEMS]

    if items and all(it["importance"] == 0 for it in items):
        # 전부 0이면 중요도 가중 평균의 분모가 0이 되어 계산 자체가 불가능하다
        warnings.append("중요도가 전부 0이라 가중 평균을 낼 수 없어 전부 50 으로 되돌렸다")
        for it in items:
            it["importance"] = 50

    if not items:
        warnings.append("쓸 수 있는 항목이 하나도 남지 않았다")
    return items, warnings, failure_modes


def attach_universal(items: list[dict]) -> list[dict]:
    """과제 고유 항목 뒤에 보편 항목 2개를 붙인다(논문 3.1).

    보편 항목에는 `universal: true` 표시를 남긴다. 분석에서 **이 둘을 빼고도**
    점수를 다시 계산해 봐야 하기 때문이다(보편 항목이 도움인지 잡음인지 확인).
    """
    return list(items) + [dict(u) for u in UNIVERSAL_ITEMS]


def generate_one(client, prompt_text: str) -> dict:
    """문항 하나에 대해 1단계(후보) → 2단계(체크리스트)를 이어서 돈다.

    두 단계를 한 번의 호출로 합치지 않는 이유: 논문의 절차가 '후보를 먼저 만들고,
    그것을 **보면서** 실패 방식을 찾는' 것이라서다. 한 호출로 시키면 모델이
    후보를 대충 적고 곧장 결론으로 뛰는 일이 생겨 절차의 이식이 아니게 된다.
    """
    # ── 1단계: 품질이 다른 가상 답안 4개 ────────────────────────────────────
    step1 = call_with_retry(
        lambda: client.generate_json(
            build_candidate_prompt(prompt_text),
            system_instruction=CANDIDATE_SYSTEM,
            response_schema=CANDIDATE_SCHEMA,
        ),
        label="후보 답안 생성",
    )
    if step1["status"] != "ok":
        return {"status": step1["status"], "reason": step1.get("reason", ""), "items": []}

    candidates, cand_warnings = normalize_candidates(step1["value"])
    if not candidates:
        return {"status": "empty_candidates", "reason": "; ".join(cand_warnings), "items": []}

    # ── 2단계: 후보들이 실패하는 방식 → 체크리스트 ──────────────────────────
    step2 = call_with_retry(
        lambda: client.generate_json(
            build_checklist_prompt(prompt_text, candidates),
            system_instruction=CHECKLIST_SYSTEM,
            response_schema=CHECKLIST_SCHEMA,
        ),
        label="체크리스트 생성",
    )
    if step2["status"] != "ok":
        return {"status": step2["status"], "reason": step2.get("reason", ""), "items": []}

    task_items, warnings, failure_modes = normalize_items_v2(step2["value"])
    if not task_items:
        return {"status": "empty", "reason": "; ".join(warnings), "items": [],
                "candidates": candidates}

    return {
        "status": "ok",
        "items": attach_universal(task_items),
        "n_task_items": len(task_items),
        "n_universal_items": len(UNIVERSAL_ITEMS),
        "failure_modes": failure_modes,
        "candidates": candidates,
        "warnings": cand_warnings + warnings,
        "model": client.model_name,
        "elapsed_sec": round(step1["elapsed_sec"] + step2["elapsed_sec"], 2),
        "attempts": step1["attempts"] + step2["attempts"],
    }


def load_checklists_v2(path: Path = CHECKLIST_V2_PATH) -> dict:
    """고정해 둔 v2 체크리스트를 읽는다. 없으면 빈 것을 돌려준다."""
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_checklists_v2(data: dict, path: Path = CHECKLIST_V2_PATH) -> None:
    """v2 체크리스트를 파일에 고정한다. 사람이 눈으로 검수할 수 있게 들여쓴다."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def print_compare_table(v1: dict, v2: dict) -> None:
    """v1 과 v2 의 문항별 항목 수를 나란히 놓는다. 이번 실험의 출발점이 되는 표다."""
    rows = []
    for pkey in sorted(set(v1) | set(v2)):
        e1, e2 = v1.get(pkey, {}), v2.get(pkey, {})
        n1 = len(e1.get("items", [])) if e1.get("status") == "ok" else 0
        task = e2.get("n_task_items", 0) if e2.get("status") == "ok" else 0
        univ = e2.get("n_universal_items", 0) if e2.get("status") == "ok" else 0
        # 중요도 폭 — 항목마다 경중을 실제로 구분했는지 한눈에 보려는 것
        imps = [it.get("importance", 0) for it in e2.get("items", []) if not it.get("universal")]
        spread = f"{min(imps)}~{max(imps)}" if imps else "-"
        rows.append([
            pkey,
            (e1.get("prompt") or e2.get("prompt") or "")[:26],
            n1,
            task,
            univ,
            task + univ,
            f"{(task + univ) - n1:+d}",
            spread,
        ])
    print_table(
        ["문항", "지시문", "v1 항목", "v2 과제항목", "v2 보편항목", "v2 합계", "증감", "중요도 폭"],
        rows,
    )


def run_generate(force: bool, only: int) -> int:
    """대상 문항 전부에 대해 v2 체크리스트를 만들어 파일에 고정한다."""
    rows, counts = load_rows()
    buckets = group_by_prompt(rows)
    print("=== 대상 고르기 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])

    targets = list(buckets.items())
    if only:
        targets = targets[:only]
        print(f"\n※ 파일럿: 앞 {len(targets)}문항만 만든다")

    client = make_judge_client()
    if not client.available:
        print("\n[중단] GEMINI_API_KEY 가 없다. assessment/.env 를 확인하라.")
        return 1

    existing = load_checklists_v2()
    made, skipped, failed = 0, 0, 0

    for pkey, items in targets:
        prompt_text = items[0].get("prompt") or ""
        # 이미 만들어 둔 것은 건드리지 않는다. 체크리스트가 실행마다 바뀌면
        # 앞서 매긴 점수와 견줄 수 없게 된다(응시자별 실시간 생성 금지와 같은 원칙)
        if not force and existing.get(pkey, {}).get("status") == "ok":
            skipped += 1
            continue

        print(f"\n── [{pkey}] {prompt_text[:44]} (답안 {len(items)}건)")
        result = generate_one(client, prompt_text)
        if result["status"] != "ok":
            failed += 1
            print(f"   실패({result['status']}): {str(result.get('reason'))[:90]}")
            existing[pkey] = {"prompt_key": pkey, "prompt": prompt_text, **result}
            save_checklists_v2(existing)
            continue

        made += 1
        existing[pkey] = {
            "prompt_key": pkey,
            "prompt": prompt_text,
            "n_answers": len(items),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "method": "candidate-based (RLCF arXiv 2507.18624v2 §2 이식)",
            **result,
        }
        # 후보 답안과 실패 방식을 먼저 보여 준다 — 항목이 어디서 나왔는지가 근거다
        for c in result["candidates"]:
            print(f"   [후보/{c['level']}] {c['text'][:52]}")
        for m in result["failure_modes"][:6]:
            print(f"   [실패방식] {m[:64]}")
        for it in result["items"]:
            mark = "필수" if it["required"] else "선택"
            tag = "보편" if it.get("universal") else "과제"
            print(f"   {it['id']}. [{tag}/{it['category']}/{mark}/중요도 {it['importance']}] "
                  f"{it['question']}")
        if result["warnings"]:
            print(f"   경고: {'; '.join(result['warnings'])}")
        # 한 문항이 끝날 때마다 저장한다 — 중간에 끊겨도 앞의 것이 살아남는다
        save_checklists_v2(existing)

    save_checklists_v2(existing)
    print(f"\n=== 생성 {made}문항 · 건너뜀 {skipped}문항 · 실패 {failed}문항 ===")
    print(f"저장: {CHECKLIST_V2_PATH}")

    print("\n=== v1 vs v2 항목 수 ===")
    print_compare_table(load_checklists_v1(), existing)
    return 0 if failed == 0 else 1


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(
        description="후보 답안 기반으로 문항별 체크리스트 v2 를 만들어 파일로 고정한다")
    ap.add_argument("--force", action="store_true",
                    help="이미 만들어 둔 문항도 다시 생성한다(점수 비교가 깨지므로 평소엔 쓰지 않는다)")
    ap.add_argument("--only", type=int, default=0, metavar="문항수",
                    help="앞에서 이 개수만큼의 문항만 만든다(파일럿)")
    ap.add_argument("--compare", action="store_true",
                    help="생성하지 않고 v1 vs v2 항목 수 표만 출력한다")
    args = ap.parse_args()

    if args.compare:
        print("=== v1 vs v2 항목 수 ===")
        print_compare_table(load_checklists_v1(), load_checklists_v2())
        return 0

    print(use_free_backup_key())
    print(f"생성 모델: {JUDGE_MODEL} (온도 0)\n")
    return run_generate(args.force, args.only)


if __name__ == "__main__":
    raise SystemExit(main())
