# -*- coding: utf-8 -*-
"""체크리스트 v4 — **항목을 10개로 늘리고, 어려운 항목을 일부러 섞는다.**

■ 왜 또 만드는가 (3차에서 배운 것)

  v1 — 문항 지시문만 보고 항목을 뽑았다. 문항당 2개. 정보 천장 0.693.
  v2 — 지어낸 후보 답안이 실패하는 방식으로 뽑았다. 항목 6개. 천장 0.797.
  v3 — 진짜 응시자 답안 8건 + 사람 점수를 보고 겹마다 따로 뽑았다.
       그런데 항목이 **평균 3.5개**밖에 안 나왔고 성적이 오히려 내려갔다(J 0.608).

**v3 가 왜 졌는지는 숫자로 밝혀져 있다.** 항목 통과율이 평균 **65.4%**였고,
281건 중 **95건이 전 항목 통과**였다. 만점을 준 답안이 3분의 1이면 그 시험지는
잘한 사람과 그냥 한 사람을 가르지 못한다. **항목이 쉬우면 못 가른다.**

■ 그래서 v4 가 바꾸는 것은 딱 두 가지다

  ① **항목 수 목표를 10개로 명시한다** (v3 는 상한 8, 실제 3.5개)
  ② **어려운 항목을 최소 3개 넣으라고 못 박는다** — "최소한만 말한 답안은 떨어지고
     충실히 수행한 답안만 통과하는" 항목. 5점과 2점을 가르라고 직접 시킨다.

그리고 그걸 뽑을 재료로 학습 겹 답안을 8건 → **12건**으로 늘린다.
10개를 뽑으려면 볼 것이 더 있어야 하기 때문이다.

■ 바꾸지 않는 것 (앞 실험과 견주기 위해서다)

  · 겹 분리 규약 — 겹 k 의 체크리스트는 겹 k 답안을 **한 건도** 보지 않는다
  · 같은 겹 배정(`assign_folds`), 같은 문항 9종, 같은 281건
  · **생성 모델도 그대로 `gemini-3.1-flash-lite`** — 이번에 바뀌는 것은 항목 수와
    (뒤 단계의) 판정 방식이지 생성기가 아니다. 생성기까지 바꾸면 무엇이 효과를
    냈는지 알 수 없게 된다.

■ 겹 분리는 만든 뒤에 프로그램으로 감사한다

"안 봤다"는 말로는 부족하다. 만들어진 파일에 적힌 `exemplar_ids` 와 실제 겹 배정을
맞대어 **시험 겹 답안이 한 건이라도 섞였는지 세어서 출력한다**(`--audit`).

■ 만들어 둔 것은 덮어쓰지 않는다

`--force` 없이는 이미 만든 (문항, 겹)을 다시 만들지 않는다. 체크리스트가 실행마다
바뀌면 앞서 매긴 점수와 견줄 수 없게 된다.

■ 쓰는 법

    python gen_checklists_v4.py                  # 45벌 전부 생성(이미 있으면 건너뜀)
    python gen_checklists_v4.py --only 2         # 앞 2문항만 (파일럿)
    python gen_checklists_v4.py --report         # 생성하지 않고 항목 수·겹 간 일치도 표만
    python gen_checklists_v4.py --audit          # 겹 분리 감사만(시험 겹 답안 혼입 세기)
    python gen_checklists_v4.py --self-test      # 계산기만 예시 입력으로 점검
"""

from __future__ import annotations

import argparse
import json
import random
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

# v3 의 '닮음 재는 자'와 '부정형 잡아내기'를 그대로 빌려 쓴다.
# 같은 자로 재야 v3 의 0.331 과 v4 의 값을 나란히 놓을 수 있다. (읽기만 한다)
from gen_checklists_v3 import (  # noqa: E402
    NEGATIVE_PATTERNS,
    VALID_CATEGORIES,
    checklist_similarity,
    fold_agreement,
    looks_negative,
    question_similarity,
)

#: v4 체크리스트를 고정해 두는 파일. 뒤의 판정·분석은 이 파일만 읽는다.
CHECKLIST_V4_PATH = OUT_DIR / "checklists_v4.json"

#: 체크리스트 한 벌에 보여 줄 학습 겹 답안 수. v3 는 8건이었다.
#: 12건으로 늘린 이유: 항목 10개를 뽑으라고 시킬 참인데 볼 답안이 8건뿐이면
#: 모델이 같은 이야기를 말만 바꿔 열 번 쓰게 된다. 점수대 네 무리에서 3건씩 본다.
N_EXEMPLARS_V4 = 12

#: **항목 수 목표.** v3 는 "최대 8개"라고만 했고 실제로 3.5개가 나왔다.
#: 이번에는 목표를 숫자로 못 박는다. 다만 억지로 채우라고는 하지 않는다.
TARGET_ITEMS_V4 = 10

#: 항목 수 상한. 목표(10)보다 조금 넉넉하게 둔다 — 11~12개가 나오면 그대로 두고,
#: 그 이상이면 중요도가 높은 것부터 남긴다.
MAX_ITEMS_V4 = 12

#: 어려운 항목 최소 개수. v3 실패의 직접 원인(항목이 쉬워서 다 통과)을 겨냥한 값이다.
MIN_HARD_ITEMS = 3

#: 항목 난이도 표기. 모델이 스스로 신고하는 값이라 '자기 신고'로만 읽어야 하고,
#: 실제로 어려웠는지는 판정 결과의 통과율로 따로 잰다(analyze_v4.py).
VALID_DIFFICULTIES = ("쉬움", "보통", "어려움")


# ─────────────────────────────────────────────────────────────────────────────
# 학습 겹 답안 고르기 — 점수대가 고루 퍼지게 (v3 와 같은 규칙, 건수만 12로)
# ─────────────────────────────────────────────────────────────────────────────
def select_exemplars_v4(train_rows: list[dict], seed_text: str,
                        n: int = N_EXEMPLARS_V4) -> list[dict]:
    """학습 겹 답안 중 **점수대가 고루 퍼지도록** n 건을 고른다.

    v3 의 `select_exemplars` 와 **같은 규칙**이고 건수만 8 → 12 로 늘렸다.
    규칙을 바꾸지 않는 이유: 이번 실험에서 달라지는 것은 '몇 개를 뽑으라고 시켰나'와
    '판정을 확률로 받았나'뿐이어야 한다. 표본 고르는 법까지 같이 바꾸면
    무엇이 효과를 냈는지 갈라 볼 수 없다.

    네 무리에서 3건씩 가져온다.
      · 높은 점수 3 — 무엇을 더 했길래 높은가
      · 낮은 점수 3 — 무엇이 없어서 낮은가
      · 중간 점수 3 — 경계가 어디인가
      · 무작위  3 — 위 아홉 건이 놓친 답안 모양을 메운다

    무작위 몫도 **고정된 씨앗**(문항 이름표 + 겹 번호)에서 뽑으므로 몇 번을 돌려도
    같은 12건이 나온다. 실험 표본이 실행마다 바뀌면 비교가 깨진다.
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

    quota = max(1, n // 4)                    # 무리마다 몇 건씩 (12건이면 3건씩)
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
CHECKLIST_V4_SYSTEM = """\
당신은 한국어 말하기 시험의 문항 검토 전문가다.
응답의 "내용 및 과제 수행"만을 평가하는 이진 체크리스트를 만든다.
실제 응시자 답안과 사람 채점자가 매긴 점수를 함께 보고, **점수를 가르는 것이 무엇인지**
찾아내는 것이 당신의 일이다.

가장 중요한 요구: 이 체크리스트는 **잘한 답안과 최소한만 말한 답안을 갈라야 한다.**
지난 시도에서는 항목이 너무 쉬워서 답안 셋 중 하나가 전 항목을 통과했고, 그래서
2점짜리 답안과 5점짜리 답안이 똑같은 만점을 받았다. 그 실패를 되풀이하지 마라.

반드시 지정된 JSON 형식으로만 답한다."""

CHECKLIST_V4_PROMPT = """\
[문항 지시문]
{prompt_text}

[실제 응시자 답안 {n_exemplars}건 — 사람 채점자가 매긴 내용 점수를 함께 표시했다]
{exemplars_text}

할 일은 두 가지다.

(1) 위 답안들을 견주어, **점수가 높은 답안과 낮은 답안이 무엇이 달랐는지**를 찾아 적어라.
    특히 **5점(또는 가장 높은 점수) 답안과 2점(또는 낮은 점수) 답안의 차이**를 구체적으로 써라.
    "높은 점수를 받은 답안에는 있고 낮은 점수를 받은 답안에는 없던 것"을 하나씩 말로 쓴다.

(2) 그 차이를 **예/아니오 체크리스트 {target_items}개**로 만들어라.
    이 체크리스트로 채점하면 위 답안들의 점수 차이가 재현되어야 한다.

■ 개수와 난이도 — 이번 요구의 핵심이다

- 항목은 **{target_items}개를 목표로 한다.** 지난 시도에서는 3~4개밖에 만들지 않아
  0~5점을 가를 눈금이 모자랐다. 문항이 요구하는 것을 여러 각도로 쪼개서
  (무엇을·왜·어떻게·얼마나 구체적으로·상대를 고려했는가) {target_items}개를 채워라.
- **난이도를 반드시 섞어라.** 각 항목에 difficulty 를 "쉬움"/"보통"/"어려움" 중 하나로 적는다.
  · 쉬움  = 최소한만 말한 낮은 점수 답안도 통과하는 항목
  · 어려움 = **충실히 수행한 높은 점수 답안만 통과하고, 최소한만 말한 답안은 떨어지는 항목**
- **"어려움" 항목을 최소 {min_hard}개 반드시 포함하라.** 이것이 이번 요구의 핵심이다.
  위 답안 중 5점(가장 높은 점수)과 2점(낮은 점수)을 실제로 가르는 항목을 만들어라.
  예를 들어 "이유를 말했는가"(쉬움)에 그치지 말고 "이유를 두 가지 이상 들었는가",
  "구체적인 사례나 수치를 들어 설명했는가", "상대가 이어서 답할 수 있도록 되물었는가"처럼
  **한 단계 더 요구하는 항목**을 만든다.
- 다만 **뜻이 겹치는 항목을 억지로 채우지는 마라.** 같은 것을 말만 바꿔 두 번 묻느니
  {target_items}개보다 적게 내는 편이 낫다. 실제로 만든 개수를 그대로 낸다.

■ 작성 규칙

- 각 항목은 '예/아니오'로만 답할 수 있어야 하고, **'예'가 항상 더 좋은 응답**을 뜻해야 한다.
- **반드시 긍정형으로 써라.** "~하지 않았는가", "~을 배제했는가", "~이 없는가" 같은
  부정형 항목은 절대 만들지 마라. 우리 채점 규약은 '예' 판정에 답안 원문 근거를
  요구하는데, 없는 것은 근거로 댈 수 없어 그런 항목은 판정 자체가 불가능하다.
- 응답 전사 텍스트만 보고 판정할 수 있어야 한다. 억양·태도·표정을 짐작해서 묻지 마라.
- **발음·억양·속도에 대한 항목, 문법·어휘의 정확성에 대한 항목은 만들지 마라.**
  그 영역은 별도의 자질이 담당하므로 중복 평가가 된다.
- 한 항목은 **한 가지만** 물어야 한다. ("장소와 이유를 말했는가"는 두 항목으로 나눈다)

각 항목에 다음을 표기하라.
- category: "정보전달"(요구된 정보를 말했는가) | "행위수행"(요구된 말하기 행위를 수행했는가)
            | "상황판단"(상황·상대에 맞게 판단했는가) 중 하나
- difficulty: "쉬움" | "보통" | "어려움"
- required: true(이 항목이 충족되지 않으면 과제 실패) | false
- importance: 0~100 사이의 정수. 이 항목이 점수를 얼마나 좌우하는가.
              모든 항목에 같은 값을 주지 마라. 항목 사이의 경중을 실제로 구분하라.
- discriminates: 위 답안 중 이 항목을 충족한 답안의 번호 목록(예: [1, 3, 5]).
              전부이거나 하나도 없으면 그 항목은 점수를 가르지 못한다는 뜻이다.

다음 JSON 형식으로만 답하라.
{
  "score_differences": ["5점 답안에는 ...가 있었고 2점 답안에는 없었다", "..."],
  "checklist": [
    {"id": 1, "question": "...", "category": "정보전달", "difficulty": "쉬움",
     "required": true, "importance": 90, "discriminates": [1, 3]},
    {"id": 2, "question": "...", "category": "행위수행", "difficulty": "어려움",
     "required": false, "importance": 40, "discriminates": [1]}
  ]
}"""

CHECKLIST_V4_SCHEMA = {
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
                    "difficulty": {"type": "string"},
                    "required": {"type": "boolean"},
                    "importance": {"type": "integer"},
                    "discriminates": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["id", "question", "category", "difficulty", "required",
                             "importance", "discriminates"],
            },
        },
    },
    "required": ["score_differences", "checklist"],
}


def build_checklist_v4_prompt(prompt_text: str, exemplars: list[dict]) -> str:
    """생성 지시문을 만든다.

    `.format()` 을 쓰지 않는다 — 출력 예시의 중괄호가 그대로 들어 있어서
    `.format()` 을 쓰면 그 부분이 깨진다(v1·v2·v3 와 같은 이유·같은 방식이다).
    """
    return (CHECKLIST_V4_PROMPT
            .replace("{prompt_text}", prompt_text)
            .replace("{n_exemplars}", str(len(exemplars)))
            .replace("{exemplars_text}", format_exemplars(exemplars))
            .replace("{target_items}", str(TARGET_ITEMS_V4))
            .replace("{min_hard}", str(MIN_HARD_ITEMS)))


def normalize_items_v4(payload: dict, n_exemplars: int) -> tuple[list[dict], list[str], list[str]]:
    """생성 응답을 쓸 수 있는 모양으로 다듬는다.

    v3 의 `normalize_items_v3` 에 **난이도 처리 한 가지가 더 붙은 것**이다.
    다듬는 것:
      ① 질문이 비어 있는 항목은 버린다(판정할 수 없다)
      ② 중요도를 0~100 정수로 누른다. 못 읽으면 50 으로 두고 경고를 남긴다
      ③ **난이도**를 쉬움/보통/어려움 중 하나로 맞춘다. 못 읽으면 "보통"으로 두고 경고
      ④ **부정형 항목**을 표시한다(버리지는 않는다 — 조용히 버리면 체크리스트가 통째로
         비는 문항이 생길 수 있고, 무엇이 규칙을 어겼는지도 결과에 남지 않는다)
      ⑤ `discriminates`(이 항목을 충족한 예시 답안 번호)를 정리하고, 전부 통과하거나
         전부 실패하는 항목을 표시해 둔다(모델의 자기 신고값이다)
      ⑥ 상한(12개)을 넘으면 중요도가 높은 것부터 남긴다
      ⑦ **'어려움' 항목이 {MIN_HARD_ITEMS}개에 못 미치면 경고를 남긴다.** 버리거나 고치지는
         않는다 — 시킨 대로 안 나온 사실 자체가 이번 실험의 결과이기 때문이다

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

        # 난이도. 모델이 "상/중/하" 처럼 다른 말로 적어 보내는 경우가 있어 넉넉히 받는다
        difficulty = str(entry.get("difficulty", "")).strip()
        if difficulty not in VALID_DIFFICULTIES:
            mapped = {"상": "어려움", "하": "쉬움", "중": "보통",
                      "어렵": "어려움", "쉬": "쉬움", "hard": "어려움",
                      "easy": "쉬움", "medium": "보통"}.get(difficulty.lower())
            if mapped:
                difficulty = mapped
            else:
                warnings.append(f"난이도를 읽지 못해 '보통'으로 뒀다: {difficulty!r}")
                difficulty = "보통"

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
            "difficulty": difficulty,
            "required": required,
            "importance": importance,
            "negative": negative,
            # 예시 답안 12건 중 몇 건이 통과했는지. 0건이거나 12건이면 점수를 못 가른다
            "exemplar_hits": hits,
            "discriminating": 0 < len(hits) < n_exemplars,
        })

    if len(items) > MAX_ITEMS_V4:
        warnings.append(f"항목이 {len(items)}개로 상한({MAX_ITEMS_V4})을 넘어 "
                        "중요도가 높은 것부터 남겼다")
        items.sort(key=lambda it: (-it["importance"], str(it["id"])))
        items = items[:MAX_ITEMS_V4]

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

    # 시킨 대로 나왔는지 확인만 하고 고치지는 않는다. 안 나왔으면 그 사실이 결과다
    n_hard = sum(1 for it in items if it["difficulty"] == "어려움")
    if items and n_hard < MIN_HARD_ITEMS:
        warnings.append(f"어려움 항목이 {n_hard}개로 요구({MIN_HARD_ITEMS}개)에 못 미친다")
    if items and len(items) < TARGET_ITEMS_V4:
        warnings.append(f"항목이 {len(items)}개로 목표({TARGET_ITEMS_V4}개)에 못 미친다")

    if not items:
        warnings.append("쓸 수 있는 항목이 하나도 남지 않았다")
    return items, warnings, differences


# ─────────────────────────────────────────────────────────────────────────────
# 겹 분리 감사 — "안 봤다"를 프로그램으로 확인한다
# ─────────────────────────────────────────────────────────────────────────────
def audit_leakage(data: dict, fold_of: dict[str, int]) -> dict:
    """만들어진 체크리스트에 **시험 겹 답안이 섞였는지** 세어 본다.

    겹 k 의 체크리스트를 만들 때 본 답안 목록(`exemplar_ids`)을 실제 겹 배정과
    맞대어, 그중 겹이 k 인 답안이 하나라도 있으면 누출이다.

    말로 "안 봤다"고 적는 것과 파일을 보고 세는 것은 다르다. 누출이 있으면
    이 실험의 숫자는 전부 무효이므로, 결과에 **0건임을 숫자로** 남긴다.
    """
    total_exemplars, leaked = 0, []
    checked_sets = 0
    for pkey, entry in sorted(data.items()):
        for fold_str, fold_entry in sorted((entry.get("folds") or {}).items()):
            if fold_entry.get("status") != "ok":
                continue
            checked_sets += 1
            fold = int(fold_str)
            for rid in fold_entry.get("exemplar_ids", []):
                total_exemplars += 1
                # 겹 배정에 없는 id 는 '모르는 답안'이라 누출보다 더 나쁜 신호다
                if str(rid) not in fold_of:
                    leaked.append({"prompt": pkey, "fold": fold, "id": str(rid),
                                   "reason": "겹 배정에 없는 답안 id"})
                elif fold_of[str(rid)] == fold:
                    leaked.append({"prompt": pkey, "fold": fold, "id": str(rid),
                                   "reason": "시험 겹 답안을 보고 만들었다"})
    return {
        "n_checklists_checked": checked_sets,
        "n_exemplars_checked": total_exemplars,
        "n_leaked": len(leaked),
        "leaked_examples": leaked[:10],
        "clean": len(leaked) == 0,
        "설명": "겹 k 의 체크리스트가 겹 k 답안을 보고 만들어졌는지 세었다. 0이어야 한다.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 저장·읽기
# ─────────────────────────────────────────────────────────────────────────────
def load_checklists_v4(path: Path = CHECKLIST_V4_PATH) -> dict:
    """고정해 둔 v4 체크리스트를 읽는다. 없으면 빈 것을 돌려준다.

    모양: {문항 이름표: {"prompt": ..., "folds": {"0": {...}, "1": {...}, ...}}}
    """
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_checklists_v4(data: dict, path: Path = CHECKLIST_V4_PATH) -> None:
    """v4 체크리스트를 파일에 고정한다. 사람이 눈으로 검수할 수 있게 들여쓴다."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def items_for_v4(checklists: dict, pkey: str, fold: int) -> list[dict]:
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
            build_checklist_v4_prompt(prompt_text, exemplars),
            system_instruction=CHECKLIST_V4_SYSTEM,
            response_schema=CHECKLIST_V4_SCHEMA,
        ),
        throttle=throttle,
        label="v4 체크리스트 생성",
    )
    if result["status"] != "ok":
        return {"status": result["status"], "reason": result.get("reason", ""), "items": []}

    items, warnings, differences = normalize_items_v4(result["value"], len(exemplars))
    if not items:
        return {"status": "empty", "reason": "; ".join(warnings), "items": []}

    return {
        "status": "ok",
        "items": items,
        "n_items": len(items),
        "n_hard": sum(1 for it in items if it["difficulty"] == "어려움"),
        "n_easy": sum(1 for it in items if it["difficulty"] == "쉬움"),
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

    existing = load_checklists_v4()
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
            exemplars = select_exemplars_v4(train_rows, seed_text=f"{pkey}|{fold}")
            jobs.append({"pkey": pkey, "prompt": prompt_text, "fold": fold,
                         "exemplars": exemplars})

    print(f"\n=== 만들 것 {len(jobs)}벌 "
          f"(문항 {len(targets)}종 × 겹 {N_FOLDS}개, 이미 있는 것 제외) ===")
    print(f"  목표 항목 {TARGET_ITEMS_V4}개 · 어려움 최소 {MIN_HARD_ITEMS}개 · "
          f"보여 줄 학습 답안 {N_EXEMPLARS_V4}건")
    if not jobs:
        print("만들 것이 없다. 이미 전부 고정돼 있다.")
        print_reports(existing, fold_of)
        return 0

    made, failed = 0, 0
    lock_note = []

    def one(index: int, job: dict) -> None:
        nonlocal made, failed
        result = generate_one(client, job["prompt"], job["exemplars"], throttle)
        record = {"fold": job["fold"],
                  "n_train_answers_seen": len(job["exemplars"]),
                  "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "method": (f"실제 학습 겹 답안 {N_EXEMPLARS_V4}건 + 사람 점수를 보고 생성"
                             f"(겹 분리) · 목표 {TARGET_ITEMS_V4}개 · 난이도 혼합 요구"),
                  **result}
        existing[job["pkey"]]["folds"][str(job["fold"])] = record
        if result["status"] == "ok":
            made += 1
            print(f"   [{index:3d}/{len(jobs)}] {job['pkey']} 겹{job['fold']} — "
                  f"항목 {result['n_items']}개 "
                  f"(어려움 {result['n_hard']} · 쉬움 {result['n_easy']}"
                  f" · 부정형 {sum(1 for it in result['items'] if it['negative'])})")
        else:
            failed += 1
            lock_note.append(f"{job['pkey']}/겹{job['fold']}: {result['status']}")
            print(f"   [{index:3d}/{len(jobs)}] {job['pkey']} 겹{job['fold']} — "
                  f"실패({result['status']}): {str(result.get('reason'))[:70]}")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-cl4gen") as pool:
        futures = [pool.submit(one, i, job) for i, job in enumerate(jobs, 1)]
        for fut in futures:
            try:
                fut.result()
            except Exception as exc:
                print(f"   일꾼에서 예외: {type(exc).__name__}: {str(exc)[:150]}")
    elapsed = time.perf_counter() - started

    save_checklists_v4(existing)
    print(f"\n=== 생성 {made}벌 · 실패 {failed}벌 · {elapsed:.0f}초 ===")
    if lock_note:
        print("  실패 목록: " + ", ".join(lock_note))
    print(f"저장: {CHECKLIST_V4_PATH}")

    print_reports(existing, fold_of)
    return 0 if failed == 0 else 1


# ─────────────────────────────────────────────────────────────────────────────
# 표 출력
# ─────────────────────────────────────────────────────────────────────────────
def print_reports(data: dict, fold_of: dict[str, int] | None = None) -> None:
    """겹별·문항별 항목 수, 난이도 구성, 겹 사이 닮음, 누출 감사를 표로 낸다."""
    print(f"\n=== 겹별·문항별 v4 항목 수 (목표 {TARGET_ITEMS_V4}개) ===")
    rows = []
    all_counts = []
    for pkey in sorted(data):
        folds = data[pkey].get("folds", {})
        counts = []
        for k in range(N_FOLDS):
            entry = folds.get(str(k), {})
            counts.append(str(entry.get("n_items", "-")) if entry.get("status") == "ok" else "실패")
        numeric = [int(c) for c in counts if c.isdigit()]
        all_counts.extend(numeric)
        rows.append([
            pkey, (data[pkey].get("prompt") or "")[:22], *counts,
            f"{sum(numeric) / len(numeric):.1f}" if numeric else "-",
            f"{min(numeric)}~{max(numeric)}" if numeric else "-",
        ])
    print_table(["문항", "지시문", "겹0", "겹1", "겹2", "겹3", "겹4", "평균", "폭"], rows)
    if all_counts:
        print(f"  전체 {len(all_counts)}벌 평균 {sum(all_counts) / len(all_counts):.2f}개 "
              f"(v3 는 3.5개였다) · 목표 {TARGET_ITEMS_V4}개 달성 벌 "
              f"{sum(1 for c in all_counts if c >= TARGET_ITEMS_V4)}/{len(all_counts)}")

    # 난이도 구성 — v3 실패 원인('항목이 쉬웠다')을 겨냥한 표다
    print("\n=== 난이도 구성 (모델의 자기 신고값이다. 실제 난이도는 판정 통과율로 따로 잰다) ===")
    diff_rows = []
    totals = {d: 0 for d in VALID_DIFFICULTIES}
    for pkey in sorted(data):
        counter = {d: 0 for d in VALID_DIFFICULTIES}
        n_sets, n_meet = 0, 0
        for entry in (data[pkey].get("folds") or {}).values():
            if entry.get("status") != "ok":
                continue
            n_sets += 1
            hard = 0
            for it in entry.get("items", []):
                counter[it.get("difficulty", "보통")] = counter.get(it.get("difficulty", "보통"), 0) + 1
                if it.get("difficulty") == "어려움":
                    hard += 1
            if hard >= MIN_HARD_ITEMS:
                n_meet += 1
        for d in VALID_DIFFICULTIES:
            totals[d] += counter[d]
        diff_rows.append([pkey, (data[pkey].get("prompt") or "")[:22],
                          counter["쉬움"], counter["보통"], counter["어려움"],
                          f"{n_meet}/{n_sets}"])
    print_table(["문항", "지시문", "쉬움", "보통", "어려움", f"어려움 {MIN_HARD_ITEMS}개 이상인 벌"],
                diff_rows)
    grand = sum(totals.values())
    if grand:
        print(f"  전체 항목 {grand}개 — 쉬움 {totals['쉬움']}({totals['쉬움'] / grand:.0%}) · "
              f"보통 {totals['보통']}({totals['보통'] / grand:.0%}) · "
              f"어려움 {totals['어려움']}({totals['어려움'] / grand:.0%})")

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
          "(닮음의 하한으로 읽어야 한다). v3 는 0.331 이었다.")

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

    # 누출 감사 — 겹 배정을 넘겨받았을 때만
    if fold_of is not None:
        audit = audit_leakage(data, fold_of)
        print(f"\n=== 겹 분리 감사 ===")
        print(f"  체크리스트 {audit['n_checklists_checked']}벌 · "
              f"본 답안 {audit['n_exemplars_checked']}건을 겹 배정과 맞댔다")
        print(f"  → 시험 겹 답안 혼입 **{audit['n_leaked']}건**"
              f" ({'깨끗하다' if audit['clean'] else '누출이 있다 — 이 실험의 숫자는 무효다'})")
        if not audit["clean"]:
            for bad in audit["leaked_examples"]:
                print(f"     {bad['prompt']} 겹{bad['fold']} {bad['id']}: {bad['reason']}")


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

    print("=== 계산기 자체 점검 (gen_checklists_v4) ===")

    # ① 층화 표본 — 12건, 점수대가 고루 퍼지는가, 늘 같은 표본이 나오는가
    sample = [{"id": f"R{i:03d}", "evals": {"content": i % 6}, "ref": "가"} for i in range(40)]
    picked = select_exemplars_v4(sample, "테스트", N_EXEMPLARS_V4)
    scores = sorted(human_score(r) for r in picked)
    check("표본 개수", len(picked), N_EXEMPLARS_V4)
    check("가장 높은 점수 포함", max(scores), 5)
    check("가장 낮은 점수 포함", min(scores), 0)
    check("두 번 뽑으면 같은 표본",
          [r["id"] for r in select_exemplars_v4(sample, "테스트", N_EXEMPLARS_V4)],
          [r["id"] for r in picked])
    rows.append(["뽑힌 점수대", str(scores), "0과 5가 모두 들어감",
                 "통과" if (0 in scores and 5 in scores) else "실패"])

    # ② 항목 다듬기 — 난이도·상한·경고
    payload = {"score_differences": ["차이 설명"], "checklist": [
        {"id": i, "question": f"항목 {i} 를 말했는가?", "category": "정보전달",
         "difficulty": "어려움" if i <= 3 else "쉬움",
         "required": False, "importance": 100 - i, "discriminates": [1, 2]}
        for i in range(1, 11)
    ]}
    items, warns, diffs = normalize_items_v4(payload, N_EXEMPLARS_V4)
    check("항목 10개가 그대로 남는다", len(items), 10)
    check("어려움 항목 3개", sum(1 for it in items if it["difficulty"] == "어려움"), 3)
    check("점수 차이 설명을 함께 돌려준다", diffs, ["차이 설명"])
    check("요구를 채우면 어려움 경고 없음", any("어려움 항목이" in w for w in warns), False)

    # 상한을 넘으면 중요도 높은 것부터 남긴다
    payload_big = {"score_differences": [], "checklist": [
        {"id": i, "question": f"항목 {i}?", "category": "정보전달", "difficulty": "보통",
         "required": False, "importance": 100 - i, "discriminates": [1]}
        for i in range(1, 20)
    ]}
    big, warns_big, _ = normalize_items_v4(payload_big, N_EXEMPLARS_V4)
    check("상한 12개로 자른다", len(big), MAX_ITEMS_V4)
    check("중요도 높은 것부터 남는다", big[0]["importance"], 99)
    check("상한 초과 경고", any("상한" in w for w in warns_big), True)

    # 어려움이 모자라거나 개수가 모자라면 경고가 남는다(고치지는 않는다)
    payload_easy = {"score_differences": [], "checklist": [
        {"id": 1, "question": "말했는가?", "category": "정보전달", "difficulty": "쉬움",
         "required": True, "importance": 50, "discriminates": list(range(1, 13))},
    ]}
    easy, warns_easy, _ = normalize_items_v4(payload_easy, N_EXEMPLARS_V4)
    check("어려움 부족 경고", any("어려움 항목이" in w for w in warns_easy), True)
    check("개수 부족 경고", any("목표" in w for w in warns_easy), True)
    check("전부 통과한 항목은 변별 못 함으로 표시", easy[0]["discriminating"], False)

    # 난이도를 '상/중/하'로 적어 보내도 받아 준다
    payload_alt = {"score_differences": [], "checklist": [
        {"id": 1, "question": "말했는가?", "category": "정보전달", "difficulty": "상",
         "required": True, "importance": 50, "discriminates": [1]},
    ]}
    alt, _, _ = normalize_items_v4(payload_alt, N_EXEMPLARS_V4)
    check("'상' 을 '어려움' 으로 읽는다", alt[0]["difficulty"], "어려움")

    # ③ 부정형 잡아내기 (v3 의 자를 그대로 쓴다)
    check("부정형 탐지(배제했는가)", looks_negative("불필요한 정보를 배제했는가?"), True)
    check("부정형 탐지(긍정형)", looks_negative("쇼핑 장소를 말했는가?"), False)

    # ④ 누출 감사 — 섞였을 때 잡아내는가
    clean_data = {"P1": {"folds": {
        "0": {"status": "ok", "exemplar_ids": ["a", "b"], "items": []},
        "1": {"status": "ok", "exemplar_ids": ["c"], "items": []}}}}
    fold_of = {"a": 1, "b": 2, "c": 0}
    audit_clean = audit_leakage(clean_data, fold_of)
    check("깨끗하면 혼입 0", audit_clean["n_leaked"], 0)
    check("깨끗 판정", audit_clean["clean"], True)

    dirty_data = {"P1": {"folds": {
        "0": {"status": "ok", "exemplar_ids": ["a", "c"], "items": []}}}}
    audit_dirty = audit_leakage(dirty_data, fold_of)
    check("시험 겹 답안이 섞이면 잡아낸다", audit_dirty["n_leaked"], 1)
    check("모르는 id 도 잡아낸다",
          audit_leakage({"P1": {"folds": {"0": {"status": "ok",
                                                "exemplar_ids": ["zzz"], "items": []}}}},
                        fold_of)["n_leaked"], 1)

    # ⑤ 닮음 재는 자 (v3 것을 빌려 쓰므로 잘 불러와졌는지만 확인)
    same = question_similarity("쇼핑 장소를 말했는가?", "쇼핑 장소를 말했는가?")
    rows.append(["같은 문구 닮음", f"{same:.2f}", "1.00", "통과" if same > 0.99 else "실패"])
    ok &= same > 0.99
    half = checklist_similarity([{"question": "장소를 말했는가?"}, {"question": "이유를 말했는가?"}],
                                [{"question": "장소를 말했는가?"}, {"question": "색을 묘사했는가?"}])
    rows.append(["한 항목만 같은 두 벌", f"{half['matched']:.2f}", "0.50",
                 "통과" if abs(half["matched"] - 0.5) < 1e-9 else "실패"])
    ok &= abs(half["matched"] - 0.5) < 1e-9

    print_table(["항목", "나온 값", "기대", "판정"], rows)
    print("\n" + ("모두 통과" if ok else "실패한 항목이 있다"))
    return 0 if ok else 1


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(
        description="학습 겹 실제 답안 12건을 보고 문항×겹마다 체크리스트 v4(목표 10항목)를 만든다")
    ap.add_argument("--force", action="store_true",
                    help="이미 만든 (문항,겹)도 다시 생성한다(점수 비교가 깨지므로 평소엔 쓰지 않는다)")
    ap.add_argument("--only", type=int, default=0, metavar="문항수",
                    help="앞에서 이 개수만큼의 문항만 만든다(파일럿)")
    ap.add_argument("--report", action="store_true",
                    help="생성하지 않고 항목 수·난이도·겹 간 일치도 표만 출력한다")
    ap.add_argument("--audit", action="store_true",
                    help="겹 분리 감사만 돌린다(시험 겹 답안 혼입 세기)")
    ap.add_argument("--self-test", action="store_true",
                    help="계산기만 예시 입력으로 점검하고 끝낸다")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rpm", type=int, default=DEFAULT_RPM)
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.report or args.audit:
        rows, _ = load_rows()
        fold_of, _ = assign_folds(rows, N_FOLDS)
        data = load_checklists_v4()
        if args.audit:
            audit = audit_leakage(data, fold_of)
            print(json.dumps(audit, ensure_ascii=False, indent=2))
            return 0 if audit["clean"] else 1
        print_reports(data, fold_of)
        return 0

    print(use_free_backup_key())
    print(f"생성 모델: {JUDGE_MODEL} (온도 0) · 분당 {args.rpm}회 · 동시 {args.workers}개")
    print("※ 생성 모델은 v1~v3 와 같다. 이번에 바뀌는 것은 항목 수와 판정 방식이다.\n")
    return run_generate(args.force, args.only, args.workers, args.rpm)


if __name__ == "__main__":
    raise SystemExit(main())
