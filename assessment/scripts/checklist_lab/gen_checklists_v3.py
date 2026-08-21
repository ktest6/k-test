# -*- coding: utf-8 -*-
"""체크리스트 v3 — **실제 답안을 보고** 만든다. 단, 시험 볼 답안은 절대 보지 않는다.

■ 왜 또 만드는가 (1·2차에서 배운 것)

  v1 — 문항 지시문만 보고 항목을 뽑았다. 문항당 2개밖에 안 나왔고 정보 천장이 0.693.
  v2 — 논문(RLCF)대로 **가상의 후보 답안**을 지어낸 뒤 그것들이 실패하는 방식으로
       항목을 뽑았다. 항목이 6개로 늘고 천장이 0.797 로 올랐다.

두 번 모두 **진짜 응시자가 어떻게 답하는지는 한 번도 보지 않았다.** 지어낸 답안은
실제 답안의 갈라지는 지점을 비껴갈 수 있다. 그래서 이번에는 진짜 답안을 보여 준다.

■ 그런데 그냥 보여 주면 부정행위가 된다 — 그래서 겹마다 따로 만든다

시험 볼 답안을 보고 체크리스트를 만들면, 그 답안으로 성적을 재는 순간
**답을 보고 시험지를 만든 것**이 된다. 그러면 나온 숫자는 실력이 아니라 누출이다.

그래서 이렇게 가른다.

    겹 k 의 체크리스트  =  그 문항의 **학습 겹(k 가 아닌 네 겹) 답안만** 보고 만든다
    겹 k 의 답안        =  그 체크리스트로만 채점된다

문항 9종 × 겹 5개 = **45벌**을 만든다. 한 문항에 체크리스트가 다섯 벌 생기는 셈이다.

■ 무엇을 보여 주는가 — 점수를 함께 보여 준다

학습 겹에서 **사람 점수가 고루 퍼지도록 8건**을 뽑아, 각 답안에 사람이 매긴
내용 점수(0~5)를 붙여서 보여 준다. 이번 방식의 요점이 여기다 —
"이 답안은 5점이고 저 답안은 1점인데 **무엇이 달랐는가**"를 보고,
그 차이를 가르는 항목을 뽑게 하는 것이다.

■ 비용: 겹마다 체크리스트가 달라진다

데이터를 보고 만들면 보는 데이터에 따라 결과가 달라진다. 같은 문항인데 겹마다
다른 시험지를 쓰는 셈이라, 그 흔들림 자체가 이 방식이 치르는 값이다.
그래서 만들고 나서 **5벌이 서로 얼마나 닮았는지**를 반드시 숫자로 잰다.

■ 만들어 둔 것은 덮어쓰지 않는다

`--force` 없이는 이미 만든 (문항, 겹)을 다시 만들지 않는다. 체크리스트가 실행마다
바뀌면 앞서 매긴 점수와 견줄 수 없게 된다.

■ 쓰는 법

    python gen_checklists_v3.py                  # 45벌 전부 생성(이미 있으면 건너뜀)
    python gen_checklists_v3.py --only 2         # 앞 2문항만 (파일럿)
    python gen_checklists_v3.py --report         # 생성하지 않고 항목 수·겹 간 일치도 표만
    python gen_checklists_v3.py --self-test      # 계산기만 예시 입력으로 점검
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import (  # noqa: E402
    DEFAULT_RPM,
    JUDGE_MODEL,
    N_FOLDS,
    OUT_DIR,
    CallThrottle,
    assign_folds,
    call_with_retry,
    enable_utf8_output,
    fmt,
    group_by_prompt,
    human_score,
    load_rows,
    make_judge_client,
    print_table,
    use_free_backup_key,
)

#: v3 체크리스트를 고정해 두는 파일. 뒤의 판정·분석은 이 파일만 읽는다.
CHECKLIST_V3_PATH = OUT_DIR / "checklists_v3.json"

#: 체크리스트 한 벌에 보여 줄 학습 겹 답안 수.
#: 8건인 이유: 점수대를 네 무리(높음·중간·낮음·무작위)로 나눠 2건씩 보여 주면
#: "5점과 1점이 무엇이 다른가"를 견줄 최소한의 짝이 생긴다. 더 늘리면 프롬프트가
#: 길어져 모델이 뒤쪽 답안을 흘려보고, 줄이면 점수대가 비어 견줄 짝이 사라진다.
N_EXEMPLARS = 8

#: 항목 수 상한. v2 는 과제 항목 10개까지 허용했지만 실제로 4개가 나왔다.
#: 여기서는 8개로 두되, **개수를 채우라고 시키지 않는다**(억지 항목이 잡음이 된다).
MAX_ITEMS_V3 = 8

#: 항목이 가질 수 있는 갈래. v1 팀원 프롬프트가 정한 세 가지를 그대로 쓴다.
VALID_CATEGORIES = ("정보전달", "행위수행", "상황판단")

#: '부정형 항목'을 걸러 내기 위한 말버릇 목록.
#:
#: 왜 막는가 (2차 실측): "~을 배제했는가", "~을 늘어놓지 않았는가" 같은 항목은
#: 충족했다는 근거를 원문에서 인용할 수가 없다(없는 것을 인용할 수는 없으므로).
#: 우리 규약은 인용이 없으면 충족을 폐기하므로, 부정형 항목은 거의 자동으로
#: 미충족이 된다 — 2차에서 한 항목이 31건 중 10건 폐기됐다.
#: 그래서 프롬프트에서 금지하고, 그래도 나오면 **여기서 잡아 표시**한다.
NEGATIVE_PATTERNS = (
    "않았", "않고", "않은", "않는", "배제", "없이", "빠뜨리지", "벗어나지",
    "하지 말", "아닌 내용", "무관한 내용을 말하지",
)


# ─────────────────────────────────────────────────────────────────────────────
# 학습 겹 답안 고르기 — 점수대가 고루 퍼지게
# ─────────────────────────────────────────────────────────────────────────────
def select_exemplars(train_rows: list[dict], seed_text: str,
                     n: int = N_EXEMPLARS) -> list[dict]:
    """학습 겹 답안 중 **점수대가 고루 퍼지도록** n 건을 고른다.

    왜 층화(고르게 퍼뜨리기)인가:
    그냥 앞에서 8건을 가져오면 그 문항에서 흔한 점수대(대개 2~3점)만 보게 된다.
    그러면 "잘한 답과 못한 답이 무엇이 다른가"를 볼 수가 없고, 결국 v1 처럼
    지시문을 되풀이하는 항목만 나온다.

    네 무리에서 2건씩 가져온다.
      · 높은 점수 2 — 무엇을 더 했길래 높은가
      · 낮은 점수 2 — 무엇이 없어서 낮은가
      · 중간 점수 2 — 경계가 어디인가
      · 무작위  2 — 위 여섯 건이 놓친 답안 모양을 메운다

    무작위 2건도 **고정된 씨앗**(문항 이름표 + 겹 번호)에서 뽑으므로,
    몇 번을 돌려도 같은 8건이 나온다. 실험 표본이 실행마다 바뀌면 비교가 깨진다.
    """
    # 점수 순으로 줄을 세운다(같은 점수면 id 순). 아래 계산이 전부 이 줄을 기준으로 한다
    ordered = sorted(train_rows, key=lambda r: (human_score(r), str(r["id"])))
    if len(ordered) <= n:
        return list(ordered)

    picked: list[dict] = []
    used: set[str] = set()

    def take(candidates: list[dict], how_many: int) -> None:
        """아직 안 뽑힌 것 중에서 앞에서부터 how_many 건을 가져온다."""
        for row in candidates:
            if how_many <= 0:
                return
            rid = str(row["id"])
            if rid in used:
                continue
            used.add(rid)
            picked.append(row)
            how_many -= 1

    quota = max(1, n // 4)                    # 무리마다 몇 건씩 (8건이면 2건씩)
    take(list(reversed(ordered)), quota)      # 높은 점수부터
    take(ordered, quota)                      # 낮은 점수부터
    middle = len(ordered) // 2                # 가운데에서 바깥으로 번갈아
    order_from_middle = sorted(range(len(ordered)), key=lambda i: (abs(i - middle), i))
    take([ordered[i] for i in order_from_middle], quota)

    # 남은 자리는 고정 씨앗 무작위로 채운다(같은 입력이면 늘 같은 결과가 나온다)
    rest = [r for r in ordered if str(r["id"]) not in used]
    random.Random(seed_text).shuffle(rest)
    take(rest, n - len(picked))

    # 보여 주는 순서는 점수와 무관하게 id 순으로 고정한다.
    # 점수 순으로 늘어놓으면 모델이 "앞쪽이 좋은 답"이라는 자리 규칙을 학습해
    # 내용이 아니라 순서를 보고 항목을 만들 수 있다
    picked.sort(key=lambda r: str(r["id"]))
    return picked


def format_exemplars(rows: list[dict]) -> str:
    """보여 줄 답안들을 프롬프트에 넣을 글로 만든다. **사람 점수를 함께 붙인다.**"""
    lines = []
    for i, row in enumerate(rows, 1):
        lines.append(f"[답안 {i}] 사람 채점 점수: {human_score(row)}점 / 5점")
        lines.append("```")
        lines.append((row.get("ref") or "").strip())
        lines.append("```")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 생성 프롬프트
# ─────────────────────────────────────────────────────────────────────────────
CHECKLIST_V3_SYSTEM = """\
당신은 한국어 말하기 시험의 문항 검토 전문가다.
응답의 "내용 및 과제 수행"만을 평가하는 이진 체크리스트를 만든다.
실제 응시자 답안과 사람 채점자가 매긴 점수를 함께 보고, **점수를 가르는 것이 무엇인지**
찾아내는 것이 당신의 일이다. 반드시 지정된 JSON 형식으로만 답한다."""

CHECKLIST_V3_PROMPT = """\
[문항 지시문]
{prompt_text}

[실제 응시자 답안 {n_exemplars}건 — 사람 채점자가 매긴 내용 점수를 함께 표시했다]
{exemplars_text}

할 일은 두 가지다.

(1) 위 답안들을 견주어, **점수가 높은 답안과 낮은 답안이 무엇이 달랐는지**를 찾아 적어라.
    "높은 점수를 받은 답안에는 있고 낮은 점수를 받은 답안에는 없던 것"을 하나씩 말로 쓴다.

(2) 그 차이를 **예/아니오 체크리스트**로 만들어라.
    이 체크리스트로 채점하면 위 답안들의 점수 차이가 재현되어야 한다.

체크리스트 작성 규칙
- 각 항목은 '예/아니오'로만 답할 수 있어야 하고, **'예'가 항상 더 좋은 응답**을 뜻해야 한다.
- **반드시 긍정형으로 써라.** "~하지 않았는가", "~을 배제했는가", "~이 없는가" 같은
  부정형 항목은 절대 만들지 마라. 우리 채점 규약은 '예' 판정에 답안 원문 인용을
  요구하는데, 없는 것은 인용할 수 없어 그런 항목은 판정 자체가 불가능하다.
- 응답 전사 텍스트만 보고 판정할 수 있어야 한다. 억양·태도·표정을 짐작해서 묻지 마라.
- **발음·억양·속도에 대한 항목, 문법·어휘의 정확성에 대한 항목은 만들지 마라.**
  그 영역은 별도의 자질이 담당하므로 중복 평가가 된다.
- 한 항목은 **한 가지만** 물어야 한다. ("장소와 이유를 말했는가"는 두 항목으로 나눈다)
- **점수대를 가르는 항목을 우선하라.** 위 답안이 전부 통과하거나 전부 실패하는 항목은
  점수를 가르지 못하므로 쓸모가 없다. 넣지 마라.
- 난이도를 섞어라. 낮은 점수 답안도 통과하는 쉬운 항목과, 높은 점수 답안만 통과하는
  어려운 항목이 함께 있어야 0~5 의 여러 점수대를 가를 수 있다.
- 관련된 측면을 두루 덮되, **개수를 채우려고 억지 항목이나 자명한 항목을 만들지 마라.**
  최대 {max_items}개이며, 5개로 충분한 문항이면 5개만 출력한다.

각 항목에 다음을 표기하라.
- category: "정보전달"(요구된 정보를 말했는가) | "행위수행"(요구된 말하기 행위를 수행했는가)
            | "상황판단"(상황·상대에 맞게 판단했는가) 중 하나
- required: true(이 항목이 충족되지 않으면 과제 실패) | false
- importance: 0~100 사이의 정수. 이 항목이 점수를 얼마나 좌우하는가.
              모든 항목에 같은 값을 주지 마라. 항목 사이의 경중을 실제로 구분하라.
- discriminates: 위 답안 중 이 항목을 충족한 답안의 번호 목록(예: [1, 3, 5]).
              전부이거나 하나도 없으면 그 항목은 점수를 가르지 못한다는 뜻이다.

다음 JSON 형식으로만 답하라.
{
  "score_differences": ["높은 점수 답안에는 ...가 있었고 낮은 점수 답안에는 없었다", "..."],
  "checklist": [
    {"id": 1, "question": "...", "category": "정보전달", "required": true,
     "importance": 90, "discriminates": [1, 3]},
    {"id": 2, "question": "...", "category": "행위수행", "required": false,
     "importance": 40, "discriminates": [1, 2, 5]}
  ]
}"""

CHECKLIST_V3_SCHEMA = {
    "type": "object",
    "properties": {
        "score_differences": {"type": "array", "items": {"type": "string"}},
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
                    "discriminates": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["id", "question", "category", "required",
                             "importance", "discriminates"],
            },
        },
    },
    "required": ["score_differences", "checklist"],
}


def build_checklist_v3_prompt(prompt_text: str, exemplars: list[dict]) -> str:
    """생성 지시문을 만든다.

    `.format()` 을 쓰지 않는다 — 출력 예시의 중괄호가 그대로 들어 있어서
    `.format()` 을 쓰면 그 부분이 깨진다(v1·v2 와 같은 이유·같은 방식이다).
    """
    return (CHECKLIST_V3_PROMPT
            .replace("{prompt_text}", prompt_text)
            .replace("{n_exemplars}", str(len(exemplars)))
            .replace("{exemplars_text}", format_exemplars(exemplars))
            .replace("{max_items}", str(MAX_ITEMS_V3)))


def looks_negative(question: str) -> bool:
    """항목 문구가 부정형인지 본다(인용으로 근거를 댈 수 없는 항목을 잡아내려는 것)."""
    text = str(question)
    return any(pattern in text for pattern in NEGATIVE_PATTERNS)


def normalize_items_v3(payload: dict, n_exemplars: int) -> tuple[list[dict], list[str], list[str]]:
    """생성 응답을 쓸 수 있는 모양으로 다듬는다.

    다듬는 것:
      ① 질문이 비어 있는 항목은 버린다(판정할 수 없다)
      ② 중요도를 0~100 정수로 누른다. 못 읽으면 50 으로 두고 경고를 남긴다
      ③ **부정형 항목**을 표시한다. 프롬프트에서 금지했지만 그래도 나오면
         `negative: true` 를 붙여 두고 경고를 남긴다 — 버리지는 않는다.
         조용히 버리면 체크리스트가 통째로 비는 문항이 생길 수 있고,
         무엇이 규칙을 어겼는지도 결과에 남지 않기 때문이다
      ④ `discriminates`(이 항목을 충족한 예시 답안 번호)를 정리하고,
         **전부 통과하거나 전부 실패**하는 항목은 표시만 해 둔다(모델의 자기 신고값이다)
      ⑤ 상한(8개)을 넘으면 중요도가 높은 것부터 남긴다

    돌려주는 값은 (항목, 경고, 점수 차이 설명)이다. 점수 차이 설명을 함께 남기는 이유:
    "이 항목이 왜 생겼는가"가 곧 체크리스트의 근거이고, 근거 없는 산출물은 남기지 않는다.
    """
    warnings: list[str] = []
    differences = [str(d).strip() for d in (payload.get("score_differences") or [])
                   if str(d).strip()]

    raw = payload.get("checklist")
    if not isinstance(raw, list):
        return [], ["응답에 checklist 배열이 없다"], differences

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

        required = str(entry.get("required", False)).strip().lower() in ("true", "1", "yes")

        try:
            importance = int(round(float(entry.get("importance"))))
        except (TypeError, ValueError):
            importance = 50
            warnings.append(f"중요도를 숫자로 읽지 못해 50 으로 뒀다: {entry.get('importance')!r}")
        importance = max(0, min(100, importance))

        # 모델이 스스로 신고한 '이 항목을 충족한 예시 답안 번호'. 범위 밖 번호는 버린다
        hits = []
        for value in (entry.get("discriminates") or []):
            try:
                num = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= num <= n_exemplars and num not in hits:
                hits.append(num)
        hits.sort()

        negative = looks_negative(question)
        if negative:
            warnings.append(f"부정형으로 보이는 항목이 나왔다(금지했는데도): {question[:40]}")

        items.append({
            "id": str(entry.get("id", len(items) + 1)).strip() or str(len(items) + 1),
            "question": question,
            "category": category,
            "required": required,
            "importance": importance,
            "negative": negative,
            # 예시 답안 8건 중 몇 건이 통과했는지. 0건이거나 8건이면 점수를 못 가른다
            "exemplar_hits": hits,
            "discriminating": 0 < len(hits) < n_exemplars,
        })

    if len(items) > MAX_ITEMS_V3:
        warnings.append(f"항목이 {len(items)}개로 상한({MAX_ITEMS_V3})을 넘어 "
                        "중요도가 높은 것부터 남겼다")
        items.sort(key=lambda it: (-it["importance"], str(it["id"])))
        items = items[:MAX_ITEMS_V3]

    if items and all(it["importance"] == 0 for it in items):
        warnings.append("중요도가 전부 0이라 가중 평균을 낼 수 없어 전부 50 으로 되돌렸다")
        for it in items:
            it["importance"] = 50

    # id 가 겹치면 판정 결과를 항목에 짝지을 수 없다. 겹치면 뒤에 번호를 덧붙인다
    seen: set[str] = set()
    for it in items:
        if it["id"] in seen:
            new_id = f"{it['id']}b"
            warnings.append(f"항목 id '{it['id']}' 가 겹쳐 '{new_id}' 로 바꿨다")
            it["id"] = new_id
        seen.add(it["id"])

    if not items:
        warnings.append("쓸 수 있는 항목이 하나도 남지 않았다")
    return items, warnings, differences


# ─────────────────────────────────────────────────────────────────────────────
# 겹 사이 항목이 얼마나 닮았는가 — 이 방식이 치르는 값
# ─────────────────────────────────────────────────────────────────────────────
def _bigrams(text: str) -> set[str]:
    """글자를 두 개씩 묶은 조각 집합으로 만든다(문구를 견주기 위한 준비).

    띄어쓰기와 문장부호를 떼고, '~했는가' 같은 공통 꼬리말도 지운다.
    그렇게 하지 않으면 뜻이 전혀 다른 두 항목이 꼬리말만으로 닮아 보인다.
    """
    cleaned = re.sub(r"[^가-힣a-zA-Z0-9]", "", str(text))
    cleaned = re.sub(r"(했는가|하였는가|는가|했나|했는지)$", "", cleaned)
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)} or {cleaned}


def question_similarity(a: str, b: str) -> float:
    """두 항목 문구가 얼마나 닮았는지 0~1 로 잰다(자카드 = 겹친 조각 / 전체 조각).

    뜻을 아는 계산이 아니라 글자 겹침을 세는 것이라, 같은 뜻을 다른 말로 쓴 두 항목은
    낮게 나온다. 그래서 이 값은 '닮음의 하한'으로 읽어야 한다.
    """
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def checklist_similarity(items_a: list[dict], items_b: list[dict],
                         threshold: float = 0.5) -> dict:
    """체크리스트 두 벌이 얼마나 닮았는지 잰다.

    방법: 한쪽 항목마다 반대쪽에서 **가장 닮은 짝**을 찾아 그 값을 쓴다(그리디 짝짓기).
    한 번 짝지어진 항목은 다시 쓰지 않는다 — 그러지 않으면 한쪽의 항목 하나가
    반대쪽 여러 항목의 짝이 되어 닮음이 부풀려진다.

    돌려주는 값 두 가지:
      · mean_best  — 짝지은 값들의 평균(0~1). 문구가 얼마나 비슷한가
      · matched    — 0.5 이상으로 짝지어진 항목의 비율. "같은 항목이 몇 개 겹치나"
    """
    if not items_a or not items_b:
        return {"mean_best": 0.0, "matched": 0.0, "n_a": len(items_a), "n_b": len(items_b)}

    # 짝짓기 후보를 닮은 순으로 줄 세운 뒤 위에서부터 확정한다
    pairs = sorted(
        ((question_similarity(x["question"], y["question"]), i, j)
         for i, x in enumerate(items_a) for j, y in enumerate(items_b)),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    used_a: set[int] = set()
    used_b: set[int] = set()
    scores: list[float] = []
    for sim, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        scores.append(sim)

    # 짝을 못 찾은 항목(개수가 다를 때 남는 쪽)은 닮음 0 으로 센다
    scores += [0.0] * (max(len(items_a), len(items_b)) - len(scores))
    matched = sum(1 for s in scores if s >= threshold)
    return {
        "mean_best": sum(scores) / len(scores),
        "matched": matched / len(scores),
        "n_a": len(items_a),
        "n_b": len(items_b),
    }


def fold_agreement(entry_by_fold: dict[str, dict]) -> dict:
    """한 문항의 다섯 벌이 서로 얼마나 닮았는지, 열 쌍을 모두 재서 평균한다."""
    folds = sorted(entry_by_fold)
    sims, matches = [], []
    for i, ka in enumerate(folds):
        for kb in folds[i + 1:]:
            a = entry_by_fold[ka].get("items", [])
            b = entry_by_fold[kb].get("items", [])
            result = checklist_similarity(a, b)
            sims.append(result["mean_best"])
            matches.append(result["matched"])
    if not sims:
        return {"n_pairs": 0, "mean_similarity": float("nan"), "matched_rate": float("nan")}
    return {
        "n_pairs": len(sims),
        "mean_similarity": sum(sims) / len(sims),
        "matched_rate": sum(matches) / len(matches),
        "min_similarity": min(sims),
        "max_similarity": max(sims),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 저장·읽기
# ─────────────────────────────────────────────────────────────────────────────
def load_checklists_v3(path: Path = CHECKLIST_V3_PATH) -> dict:
    """고정해 둔 v3 체크리스트를 읽는다. 없으면 빈 것을 돌려준다.

    모양: {문항 이름표: {"prompt": ..., "folds": {"0": {...}, "1": {...}, ...}}}
    """
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_checklists_v3(data: dict, path: Path = CHECKLIST_V3_PATH) -> None:
    """v3 체크리스트를 파일에 고정한다. 사람이 눈으로 검수할 수 있게 들여쓴다."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def items_for(checklists: dict, pkey: str, fold: int) -> list[dict]:
    """(문항, 겹)에 고정된 항목 목록을 꺼낸다. 없으면 빈 목록."""
    entry = (checklists.get(pkey, {}).get("folds", {}) or {}).get(str(fold), {})
    return entry.get("items", []) if entry.get("status") == "ok" else []


# ─────────────────────────────────────────────────────────────────────────────
# 생성 실행
# ─────────────────────────────────────────────────────────────────────────────
def generate_one(client, prompt_text: str, exemplars: list[dict], throttle) -> dict:
    """(문항, 겹) 하나에 대한 체크리스트를 만든다. LLM 호출은 1회다."""
    result = call_with_retry(
        lambda: client.generate_json(
            build_checklist_v3_prompt(prompt_text, exemplars),
            system_instruction=CHECKLIST_V3_SYSTEM,
            response_schema=CHECKLIST_V3_SCHEMA,
        ),
        throttle=throttle,
        label="v3 체크리스트 생성",
    )
    if result["status"] != "ok":
        return {"status": result["status"], "reason": result.get("reason", ""), "items": []}

    items, warnings, differences = normalize_items_v3(result["value"], len(exemplars))
    if not items:
        return {"status": "empty", "reason": "; ".join(warnings), "items": []}

    return {
        "status": "ok",
        "items": items,
        "n_items": len(items),
        "score_differences": differences,
        # 어떤 답안을 보고 만들었는지 남긴다. 나중에 "시험 겹 답안이 섞였나"를
        # 파일만 보고도 확인할 수 있어야 한다(누출 감사의 근거다)
        "exemplar_ids": [str(r["id"]) for r in exemplars],
        "exemplar_scores": [human_score(r) for r in exemplars],
        "warnings": warnings,
        "model": client.model_name,
        "elapsed_sec": result["elapsed_sec"],
        "attempts": result["attempts"],
    }


def run_generate(force: bool, only: int, workers: int, rpm: int) -> int:
    """문항 9종 × 겹 5개 = 45벌을 만들어 파일에 고정한다."""
    rows, counts = load_rows()
    fold_of, diag = assign_folds(rows, N_FOLDS)
    buckets = group_by_prompt(rows)

    print("=== 대상 고르기 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])
    print(f"겹 나누기: 화자 단위 {N_FOLDS}겹 · 겹을 넘나든 화자 {diag['speaker_leak_count']}명 "
          f"(앞 실험과 같은 함수·같은 배정)")

    targets = list(buckets.items())
    if only:
        targets = targets[:only]
        print(f"\n※ 파일럿: 앞 {len(targets)}문항만 만든다")

    client = make_judge_client()
    if not client.available:
        print("\n[중단] GEMINI_API_KEY 가 없다. assessment/.env 를 확인하라.")
        return 1

    existing = load_checklists_v3()
    throttle = CallThrottle(workers, rpm=rpm)

    # 할 일 목록: (문항, 겹) 짝. 이미 만든 것은 --force 없이는 건드리지 않는다
    jobs = []
    for pkey, items in targets:
        prompt_text = items[0].get("prompt") or ""
        entry = existing.setdefault(pkey, {"prompt_key": pkey, "prompt": prompt_text,
                                           "n_answers": len(items), "folds": {}})
        entry.setdefault("folds", {})
        for fold in range(N_FOLDS):
            if not force and entry["folds"].get(str(fold), {}).get("status") == "ok":
                continue
            # ★ 핵심: 시험 겹(fold) 답안은 절대 넣지 않는다
            train_rows = [r for r in items if fold_of[str(r["id"])] != fold]
            exemplars = select_exemplars(train_rows, seed_text=f"{pkey}|{fold}")
            jobs.append({"pkey": pkey, "prompt": prompt_text, "fold": fold,
                         "exemplars": exemplars})

    print(f"\n=== 만들 것 {len(jobs)}벌 "
          f"(문항 {len(targets)}종 × 겹 {N_FOLDS}개, 이미 있는 것 제외) ===")
    if not jobs:
        print("만들 것이 없다. 이미 전부 고정돼 있다.")
        print_reports(existing)
        return 0

    made, failed = 0, 0
    lock_note = []

    def one(index: int, job: dict) -> None:
        nonlocal made, failed
        result = generate_one(client, job["prompt"], job["exemplars"], throttle)
        record = {"fold": job["fold"],
                  "n_train_answers_seen": len(job["exemplars"]),
                  "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "method": "실제 학습 겹 답안 + 사람 점수를 보고 생성(겹 분리)",
                  **result}
        existing[job["pkey"]]["folds"][str(job["fold"])] = record
        if result["status"] == "ok":
            made += 1
            print(f"   [{index:3d}/{len(jobs)}] {job['pkey']} 겹{job['fold']} — "
                  f"항목 {result['n_items']}개 "
                  f"(변별 표시 {sum(1 for it in result['items'] if it['discriminating'])}개"
                  f" · 부정형 {sum(1 for it in result['items'] if it['negative'])}개)")
        else:
            failed += 1
            lock_note.append(f"{job['pkey']}/겹{job['fold']}: {result['status']}")
            print(f"   [{index:3d}/{len(jobs)}] {job['pkey']} 겹{job['fold']} — "
                  f"실패({result['status']}): {str(result.get('reason'))[:70]}")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-cl3gen") as pool:
        futures = [pool.submit(one, i, job) for i, job in enumerate(jobs, 1)]
        for fut in futures:
            try:
                fut.result()
            except Exception as exc:
                print(f"   일꾼에서 예외: {type(exc).__name__}: {str(exc)[:150]}")
    elapsed = time.perf_counter() - started

    save_checklists_v3(existing)
    print(f"\n=== 생성 {made}벌 · 실패 {failed}벌 · {elapsed:.0f}초 ===")
    if lock_note:
        print("  실패 목록: " + ", ".join(lock_note))
    print(f"저장: {CHECKLIST_V3_PATH}")

    print_reports(existing)
    return 0 if failed == 0 else 1


# ─────────────────────────────────────────────────────────────────────────────
# 표 출력
# ─────────────────────────────────────────────────────────────────────────────
def print_reports(data: dict) -> None:
    """겹별·문항별 항목 수와, 겹 사이 항목이 얼마나 닮았는지를 표로 낸다."""
    print("\n=== 겹별·문항별 v3 항목 수 ===")
    rows = []
    for pkey in sorted(data):
        folds = data[pkey].get("folds", {})
        counts = []
        for k in range(N_FOLDS):
            entry = folds.get(str(k), {})
            counts.append(str(entry.get("n_items", "-")) if entry.get("status") == "ok" else "실패")
        numeric = [int(c) for c in counts if c.isdigit()]
        rows.append([
            pkey, (data[pkey].get("prompt") or "")[:22], *counts,
            f"{sum(numeric) / len(numeric):.1f}" if numeric else "-",
            f"{min(numeric)}~{max(numeric)}" if numeric else "-",
        ])
    print_table(["문항", "지시문", "겹0", "겹1", "겹2", "겹3", "겹4", "평균", "폭"], rows)

    print("\n=== 같은 문항의 다섯 벌은 서로 얼마나 닮았나 (이 방식이 치르는 값) ===")
    rows = []
    for pkey in sorted(data):
        folds = {k: v for k, v in (data[pkey].get("folds") or {}).items()
                 if v.get("status") == "ok"}
        agree = fold_agreement(folds)
        rows.append([pkey, (data[pkey].get("prompt") or "")[:22], agree["n_pairs"],
                     fmt(agree["mean_similarity"]), fmt(agree.get("matched_rate", float("nan"))),
                     fmt(agree.get("min_similarity", float("nan"))),
                     fmt(agree.get("max_similarity", float("nan")))])
    print_table(["문항", "지시문", "쌍 수", "문구 닮음(평균)", "짝지어진 비율",
                 "가장 안 닮은 쌍", "가장 닮은 쌍"], rows)
    print("  ※ '문구 닮음'은 글자 겹침으로 재므로, 같은 뜻을 다른 말로 쓴 항목은 낮게 나온다"
          "(닮음의 하한으로 읽어야 한다).")
    print("  ※ '짝지어진 비율'은 닮음 0.5 이상으로 맞짝이 생긴 항목의 비율이다.")

    # 규칙 위반 점검 — 부정형 항목이 나왔는지, 변별 못 하는 항목이 얼마나 되는지
    total, negative, nondiscriminating = 0, 0, 0
    for pkey in data:
        for entry in (data[pkey].get("folds") or {}).values():
            for it in entry.get("items", []):
                total += 1
                negative += int(bool(it.get("negative")))
                nondiscriminating += int(not it.get("discriminating"))
    if total:
        print(f"\n항목 전체 {total}개 중 — 부정형 {negative}개({negative / total:.1%}) · "
              f"예시 답안을 못 가른다고 스스로 신고한 항목 {nondiscriminating}개"
              f"({nondiscriminating / total:.1%})")


# ─────────────────────────────────────────────────────────────────────────────
# 자체 점검
# ─────────────────────────────────────────────────────────────────────────────
def self_test() -> int:
    """계산기들이 맞게 도는지 답을 아는 예시로 확인한다(네트워크·파일 안 건드림)."""
    ok = True
    rows = []

    def check(label, got, want):
        nonlocal ok
        passed = got == want
        ok &= passed
        rows.append([label, str(got), str(want), "통과" if passed else "실패"])

    print("=== 계산기 자체 점검 (gen_checklists_v3) ===")

    # ① 층화 표본 — 점수대가 고루 퍼지는가, 그리고 늘 같은 8건이 나오는가
    sample = [{"id": f"R{i:03d}", "evals": {"content": i % 6}, "ref": "가"} for i in range(30)]
    picked = select_exemplars(sample, "테스트", 8)
    scores = sorted(human_score(r) for r in picked)
    check("표본 개수", len(picked), 8)
    check("가장 높은 점수 포함", max(scores), 5)
    check("가장 낮은 점수 포함", min(scores), 0)
    check("두 번 뽑으면 같은 표본",
          [r["id"] for r in select_exemplars(sample, "테스트", 8)],
          [r["id"] for r in picked])
    rows.append(["뽑힌 점수대", str(scores), "0과 5가 모두 들어감",
                 "통과" if (0 in scores and 5 in scores) else "실패"])

    # ② 부정형 잡아내기
    check("부정형 탐지(배제했는가)", looks_negative("불필요한 정보를 배제했는가?"), True)
    check("부정형 탐지(긍정형)", looks_negative("쇼핑 장소를 말했는가?"), False)

    # ③ 문구 닮음 — 같은 문구는 1, 전혀 다른 문구는 낮게
    same = question_similarity("쇼핑 장소를 말했는가?", "쇼핑 장소를 말했는가?")
    diff = question_similarity("쇼핑 장소를 말했는가?", "옷 색깔을 묘사했는가?")
    rows.append(["같은 문구 닮음", f"{same:.2f}", "1.00", "통과" if same > 0.99 else "실패"])
    ok &= same > 0.99
    rows.append(["다른 문구 닮음", f"{diff:.2f}", "0.3 미만", "통과" if diff < 0.3 else "실패"])
    ok &= diff < 0.3

    # ④ 체크리스트 닮음 — 두 벌이 완전히 같으면 1, 겹치는 항목이 하나면 절반쯤
    a = [{"question": "장소를 말했는가?"}, {"question": "이유를 말했는가?"}]
    b = [{"question": "장소를 말했는가?"}, {"question": "옷 색깔을 묘사했는가?"}]
    full = checklist_similarity(a, a)
    half = checklist_similarity(a, b)
    rows.append(["같은 두 벌의 짝지어진 비율", f"{full['matched']:.2f}", "1.00",
                 "통과" if full["matched"] > 0.99 else "실패"])
    ok &= full["matched"] > 0.99
    rows.append(["한 항목만 같은 두 벌", f"{half['matched']:.2f}", "0.50",
                 "통과" if abs(half["matched"] - 0.5) < 1e-9 else "실패"])
    ok &= abs(half["matched"] - 0.5) < 1e-9

    # ⑤ 항목 다듬기 — 상한, 중요도, 부정형 표시
    payload = {"score_differences": ["차이 설명"], "checklist": [
        {"id": i, "question": f"항목 {i} 를 말했는가?", "category": "정보전달",
         "required": False, "importance": 100 - i, "discriminates": [1, 2]}
        for i in range(1, 12)
    ]}
    items, warns, diffs = normalize_items_v3(payload, 8)
    check("상한 8개로 자른다", len(items), MAX_ITEMS_V3)
    check("중요도 높은 것부터 남는다", items[0]["importance"], 99)
    check("점수 차이 설명을 함께 돌려준다", diffs, ["차이 설명"])
    check("상한 초과 경고", any("상한" in w for w in warns), True)

    payload2 = {"score_differences": [], "checklist": [
        {"id": 1, "question": "불필요한 말을 배제했는가?", "category": "상황판단",
         "required": True, "importance": "높음", "discriminates": [1, 2, 3, 4, 5, 6, 7, 8]},
    ]}
    items2, warns2, _ = normalize_items_v3(payload2, 8)
    check("부정형 표시", items2[0]["negative"], True)
    check("중요도 못 읽으면 50", items2[0]["importance"], 50)
    check("전부 통과한 항목은 변별 못 함으로 표시", items2[0]["discriminating"], False)
    check("경고가 남는다", len(warns2) >= 2, True)

    print_table(["항목", "나온 값", "기대", "판정"], rows)
    print("\n" + ("모두 통과" if ok else "실패한 항목이 있다"))
    return 0 if ok else 1


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(
        description="학습 겹 실제 답안을 보고 문항×겹마다 체크리스트 v3 를 만들어 고정한다")
    ap.add_argument("--force", action="store_true",
                    help="이미 만든 (문항,겹)도 다시 생성한다(점수 비교가 깨지므로 평소엔 쓰지 않는다)")
    ap.add_argument("--only", type=int, default=0, metavar="문항수",
                    help="앞에서 이 개수만큼의 문항만 만든다(파일럿)")
    ap.add_argument("--report", action="store_true",
                    help="생성하지 않고 항목 수·겹 간 일치도 표만 출력한다")
    ap.add_argument("--self-test", action="store_true",
                    help="계산기만 예시 입력으로 점검하고 끝낸다")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rpm", type=int, default=DEFAULT_RPM)
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.report:
        print_reports(load_checklists_v3())
        return 0

    print(use_free_backup_key())
    print(f"생성 모델: {JUDGE_MODEL} (온도 0) · 분당 {args.rpm}회 · 동시 {args.workers}개\n")
    return run_generate(args.force, args.only, args.workers, args.rpm)


if __name__ == "__main__":
    raise SystemExit(main())
