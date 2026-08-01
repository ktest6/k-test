"""문항 생성에 쓰는 프롬프트 전문과 응답 형식표.

프롬프트를 고치면 PROMPT_VERSION 을 올린다. 그 값이 응답 meta 에 실려 나가므로
"이 문항은 어떤 프롬프트로 만들어졌나"를 나중에 되짚을 수 있다.

규칙 1(인용 규칙)은 문구를 임의로 다듬지 않는다.
이 규칙이 없을 때 모델은 여러 구절을 '...' 으로 이어붙였고 검증기가 전부 걸러내
**폐기율 100%** 가 나왔다. 규칙을 넣은 뒤 **폐기율 0%** 가 됐다(실제 KOSHA 문서 실측).
지금 문구는 그 실측을 통과한 문구다.

다만 프롬프트는 부탁이고 코드는 강제다. 모델을 바꾸면 부탁은 다시 무시될 수 있으므로
같은 규칙을 validate.py 의 관문에서 한 번 더 확인한다.
"""

from __future__ import annotations

from .preprocess import CUT_MARKER
from .schema import GeneratedItemType

# 프롬프트 판(版) 번호. 문구를 고치면 올린다.
PROMPT_VERSION = "gen_writing_v1"


# ---------------------------------------------------------------------------
# 시스템 지시문 — 모델이 지켜야 할 규칙
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = f"""\
당신은 외국인 노동자용 한국어 직무 시험의 문항 설계 도구다.
주어진 안전 문서의 내용으로만 쓰기 문항을 만든다.

반드시 지킬 규칙:

1. [근거] 문서에 없는 내용으로 문항을 만들지 않는다.
   문항마다, 그리고 체크리스트 항목마다 근거가 된 문서 구절을 quote 로 첨부한다.
   quote 규칙:
   - 문서에서 이어진 한 구절만 그대로 복사한다 (띄어쓰기는 달라도 된다)
   - 10~40자의 짧은 구절이면 충분하다
   - 여러 곳의 구절을 합치거나 "...", 생략, 요약을 쓰면 절대 안 된다
   - {CUT_MARKER} 기호가 들어간 구절은 쓰지 않는다. 문서에서 잘라낸 자리 표시다
   - 이 규칙을 어기면 그 문항은 통째로 폐기된다

2. [유형] item_type 은 다음 다섯 가지 중 하나만 쓴다. 새 유형을 만들지 않는다.
   - work_log          작업일지: 오늘 한 작업을 기록한다
   - messenger_report  메신저 보고: 윗사람에게 상황을 알린다
   - hazard_report     위험 보고: 위험한 것을 안전 담당자에게 알린다
   - handover_memo     인수인계 메모: 다음 근무자에게 남긴다
   - supply_request    물품 요청: 필요한 것을 사무실에 요청한다

3. [지시문] 응시자는 한국어를 배우는 중인 외국인 노동자다.
   - 쉬운 낱말과 짧은 문장으로 쓴다. 문서의 어려운 문장을 그대로 옮기지 않는다
   - 써야 할 내용을 ① ② ③ 세 가지로 반드시 나눠 적는다
   - 전체 길이는 30자 이상 200자 이하로 한다
   - "쓰세요", "작성하세요", "알리세요" 처럼 쓰기를 시키는 말로 맺는다
   - 답이 지시문 안에 들어 있으면 안 된다. 상황만 주고,
     문서의 수치·절차·순서를 지시문에 옮겨 적지 않는다

4. [체크리스트] '관련성'이 아니라 '완수' 기준으로 3~4개를 만든다.
   - 현장에서 그 정보가 빠지면 사고로 이어지는 항목일수록 weight 를 높인다
   - weight 는 0.5 이상 1.5 이하만 쓴다
   - "무엇이 / 어디서 / 어떤 조치가" 처럼 전달되어야 할 정보 단위로 쪼갠다
   - 문법이 아니라 내용이 전달되었는지를 묻는 문장으로 쓴다

5. [금지] 지식 암기 문제를 만들지 않는다.
   - "~은 무엇입니까?", "~는 몇 개입니까?", "~의 정의를 쓰시오" 같은 문항 금지
   - 문서를 외웠는지가 아니라, 현장 상황을 한국어로 전달할 수 있는지를 잰다

6. [핵심어] reference_keywords 는 문서에 실제로 나오는 낱말만 3~5개 고른다.

7. 지정된 JSON 형식으로만 답한다. 설명 문장을 덧붙이지 않는다.
"""


# ---------------------------------------------------------------------------
# 사용자 프롬프트 — 실제 문서와 요청 내용이 들어가는 자리
# ---------------------------------------------------------------------------

USER_PROMPT_TEMPLATE = """\
아래 안전 문서를 읽고, 이 사업장 노동자에게 낼 쓰기 문항 {item_count}개를 만들어라.
{workplace_line}
문항끼리 상황이 겹치지 않게 하고, 가능하면 서로 다른 item_type 을 쓴다.
쓸 수 있는 item_type: {allowed_types}

[문서 제목] {document_title}

[안전 문서]
```
{document}
```

다음 JSON 형식으로만 답하라.
{{
  "items": [
    {{
      "item_id": "GEN-001",
      "item_type": "work_log | messenger_report | hazard_report | handover_memo | supply_request 중 하나",
      "prompt": "응시자에게 보여줄 지시문 (쉬운 한국어, ①②③ 형식)",
      "expected_register": "formal 또는 polite",
      "checklist": [
        {{"id": "c1", "description": "…했는가", "weight": 1.0,
         "quote": "이 항목의 근거가 된 문서 구절 (그대로 복사)"}}
      ],
      "reference_keywords": ["핵심어", "3~5개"],
      "source_quote": "이 문항 전체의 근거가 된 문서 구절 (그대로 복사)"
    }}
  ]
}}
"""


def build_user_prompt(
    document: str,
    item_count: int,
    allowed_types: list[GeneratedItemType] | None = None,
    document_title: str = "",
    workplace_name: str = "",
) -> str:
    """문서와 요청 내용을 넣어 실제로 보낼 프롬프트를 만든다.

    모델이 적어 내는 item_id 는 쓰지 않고 우리가 다시 붙인다.
    같은 id 를 중복 발급하는 일이 있고, 문서가 다른데 id 가 같으면 백엔드에서 충돌하기 때문이다.
    """
    # 유형을 지정하지 않았으면 다섯 가지 전부 허용한다
    types = allowed_types or list(GeneratedItemType)
    allowed = ", ".join(t.value for t in types)

    # 사업장 이름은 있을 때만 한 줄로 넣는다. 없으면 그 자리를 아예 비운다
    workplace_line = ""
    if workplace_name.strip():
        workplace_line = (
            f'이 사업장 이름은 "{workplace_name.strip()}" 이다. 지시문에 이 이름을 써도 된다.'
        )

    return USER_PROMPT_TEMPLATE.format(
        item_count=item_count,
        workplace_line=workplace_line,
        allowed_types=allowed,
        document_title=document_title or "(제목 없음)",
        document=document,
    )


# ---------------------------------------------------------------------------
# 응답 형식표
# ---------------------------------------------------------------------------

#: Gemini 쪽에서 응답 구조를 강제하는 표.
#: required 를 빠짐없이 적는 것이 중요하다 — 형식표를 안 붙였을 때
#: 모델이 닫는 괄호를 하나 더 붙여 응답 해석이 통째로 실패한 적이 있다(채점 쪽 실측).
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "item_type": {"type": "string"},
                    "prompt": {"type": "string"},
                    "expected_register": {"type": "string"},
                    "checklist": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "description": {"type": "string"},
                                "weight": {"type": "number"},
                                "quote": {"type": "string"},
                            },
                            "required": ["id", "description", "weight", "quote"],
                        },
                    },
                    "reference_keywords": {"type": "array", "items": {"type": "string"}},
                    "source_quote": {"type": "string"},
                },
                "required": [
                    "item_id",
                    "item_type",
                    "prompt",
                    "expected_register",
                    "checklist",
                    "reference_keywords",
                    "source_quote",
                ],
            },
        },
    },
    "required": ["items"],
}
