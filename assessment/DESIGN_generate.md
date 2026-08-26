# B2 설계 — 안전문서 → 쓰기 문항 자동 생성

> 상태: **설계 확정 (2026-08-01).** 구현은 8/2~8/3 (`PLAN.md` B2).
> 근거 실험: B1 타당성 실험 (실제 KOSHA 화학설비 정비·보수 지침 C-2-2025).
> 이 문서 하나만 보고 구현할 수 있게 쓴다. 여기 없는 것은 구현하지 않는다.

---

## 0. 한 줄 요약

관리자가 올린 안전문서 텍스트를 받아 **쓰기 문항 초안(draft)** 을 만들어 돌려주는
무상태 API 하나를 추가한다. 만들어진 문항은 전부 문서 인용 근거를 달고 나오며,
근거를 대지 못한 문항은 **응답에 실리지 않고 폐기 수로만 보고**된다.
채점 파이프라인(`src/scoring/`)은 한 줄도 바뀌지 않는다.

---

## 1. 양보 불가 제약 (설계 판단이 갈릴 때 여기로 돌아온다)

| # | 제약 | 코드에서 어떻게 지키나 |
|---|---|---|
| 1 | 응시자별 실시간 생성 금지 | 응답 status 가 언제나 `draft`. `confirmed` 를 만드는 코드 자체가 없다. 시험 중 호출되는 경로(`/score`)에서 생성 모듈을 import 하지 않는다 |
| 2 | 인용 근거 없는 문항은 응답에 없다 | 관문 G2·G3 통과 실패 시 `items` 가 아니라 `dropped` 로 간다. **인용 검증을 끄는 옵션을 만들지 않는다** |
| 3 | 채점 파이프라인 무변경 | `src/generation/` → `src/scoring/` 단방향 import. 역방향 import 를 금지하는 테스트를 넣는다 |
| 4 | 이미지 생성 금지 | 이번 API 는 `document_text`(문자열)만 받는다. 이미지 필드가 없다 |

제약 2의 부연: "인용 검증을 옵션으로 끌 수 있게 해 달라"는 요청이 반드시 온다
(데모가 급할 때). 옵션을 만드는 순간 이 제약은 제약이 아니라 기본값이 된다.
만들지 않는다.

---

## 2. 무엇이 우리 몫이고 무엇이 아닌가

```
[관리자] 문서 업로드
   │
   │  (백엔드) 파일 저장 · PDF → 텍스트 추출 · document_id 발급
   ▼
POST /generate-items      ◀── 우리 몫 (이 문서가 설계하는 것)
   │  전처리 → 생성 1회 → 관문 5개 → draft 문항 + 폐기 보고
   ▼
   │  (백엔드) draft 저장
   │  (프론트) 승인 화면 — 문항 + 근거 인용 하이라이트
   │  (관리자) 승인 클릭
   │  (백엔드) status = confirmed, 시험 세트에 편성
   ▼
[응시자] 시험 → POST /score → POST /finalize   ◀── 기존 그대로. 변경 없음
```

| 하는 일 | 누구 | 비고 |
|---|---|---|
| 파일 저장, PDF → 텍스트 추출 | 백엔드 | 파일을 가진 쪽이 파일을 다룬다. 우리는 텍스트만 받는다 |
| 텍스트 정제(머리글·쪽번호 제거 등) | **우리** | 인용을 대조할 기준 텍스트가 곧 우리가 본 텍스트여야 하기 때문 |
| 문항 생성·검증·draft 표시 | **우리** | |
| draft 저장, 승인 API, 권한, 상태 전이 집행 | 백엔드 | |
| 승인 화면 | 프론트 | 화면 최소 요건은 §7.4 에 우리가 명세한다 |

**막힘 대비**: 백엔드의 PDF 추출이 늦으면 시연이 막힌다.
폴백으로 `assessment/scripts/extract_pdf.py`(pypdf 로 텍스트만 뽑아 파일로 저장)를
같이 만든다. 관리자가 텍스트를 붙여넣는 경로로 시연이 가능해진다. B1 실험 스크립트에
이미 있는 코드라 추가 비용이 거의 없다.

---

## 3. 파일 배치

```
assessment/src/generation/          ← 새 패키지
  __init__.py
  schema.py       생성 API 계약. scoring/schema.py 의 모델을 상속해서 만든다
  preprocess.py   문서 텍스트 정제 + 잘라낸 자리 표시
  prompt.py       프롬프트 전문 + Gemini 응답 형식표 + PROMPT_VERSION
  validate.py     관문 5개와 폐기 사유 판정 (LLM 호출 없음)
  generate.py     오케스트레이션: 요청 → 전처리 → 생성 → 관문 → 응답 조립

assessment/src/llm/client.py        ← 함수 2개 추가만 (기존 서명 불변)
assessment/src/api.py               ← 엔드포인트 2개 추가만
assessment/tests/test_generation.py ← 새 테스트 (가짜 클라이언트, 네트워크 없음)
assessment/scripts/check_generate.py ← 눈으로 값을 확인하는 검증 스크립트
assessment/scripts/extract_pdf.py    ← PDF → 텍스트 (폴백용)
```

**왜 `scoring/` 이 아니라 새 패키지인가.**
`scoring/schema.py` 는 "여기를 바꾸면 백엔드가 깨진다"고 못 박은 채점 계약 파일이다.
생성 계약을 그 안에 섞으면 그 문장의 뜻이 흐려지고, 백엔드가 채점 스키마를 볼 때마다
생성 필드를 함께 읽게 된다. 또 `scoring/` 은 CLAUDE.md 상 "자질을 점수로 바꾸는 층"이고
생성은 점수를 만들지 않는다.

**왜 `llm/` 이 아닌가.**
`llm/` 은 "Gemini 호출과 인용 검증. 채점 로직은 여기 두지 않는다"는 공용 바닥이다.
생성은 그 바닥을 **쓰는** 쪽이지 바닥이 아니다.

**의존 방향 (테스트로 고정한다)**

```
generation  ──▶  llm (client, citation)
     │
     └────────▶  scoring.schema (ItemInfo, ChecklistItem, Mode)
     └────────▶  scoring.validity (prompt_overlap, check_answer_validity)

scoring ──▶ generation   ← 금지. 이 방향 import 가 하나라도 생기면 테스트 실패
```

이 단방향이 "채점 파이프라인 무변경"을 말이 아니라 **검사 가능한 사실**로 만든다.

---

## 4. API 계약

### 4.1 `POST /generate-items` — 문서에서 문항 초안 만들기

무상태다. 문서 텍스트를 요청에 담아 받고, 우리는 아무것도 저장하지 않는다.
채점 API(`/score`)와 같은 원칙이다.

#### 요청

```python
class GenerateOptions(BaseModel):
    item_count: int = Field(default=3, ge=1, le=10,
        description="만들 문항 수. 폐기가 있으면 이보다 적게 나올 수 있다")
    item_types: list[GeneratedItemType] = Field(default_factory=list,
        description="쓸 문항 유형을 좁히고 싶을 때. 비우면 5유형 전부 허용")
    item_id_prefix: str = Field(default="GEN", max_length=8,
        description="문항 id 앞에 붙일 글자. 기본 세트(WRT-)와 구별하려는 것")
    workplace_name: str = Field(default="", max_length=40,
        description="사업장 이름. 지시문에 그대로 쓸 수 있게 넘긴다(예: (주)K-테스트 식품공장)")

class GenerateItemsRequest(BaseModel):
    document_id: str = Field(description="백엔드가 발급한 문서 식별자. 우리는 응답에 되돌려주기만 한다")
    document_text: str = Field(description="문서 전문 텍스트. PDF 추출 결과 그대로 보내면 된다")
    document_title: str = Field(default="", description="문서 제목. 프롬프트에 참고로 넣는다")
    mode: Mode = Field(default=Mode.WRITING, description="지금은 writing 만 받는다")
    options: GenerateOptions = Field(default_factory=GenerateOptions)
```

요청 단계 거부(400) 조건 — 문항을 하나도 만들지 않고 즉시 막는다.

| 조건 | 상수 | 사유 문구 |
|---|---|---|
| `mode != writing` | — | "지금은 쓰기 문항만 만든다. 말하기는 B4 범위다" |
| 정제 후 글자 수 < 500 | `MIN_DOCUMENT_CHARS = 500` | "문서가 너무 짧아 문항을 만들 수 없다" |
| 정제 후 글자 수 > 30,000 | `MAX_DOCUMENT_CHARS = 30_000` | "문서가 너무 길다. 장·절 단위로 나눠 보내라" |

길이 초과를 **조용히 잘라내지 않는다.** 자르면 관리자가 보낸 문서와 문항이 나온
문서가 달라지는데 응답만 보고는 알 수 없다. 명시적 실패가 조용한 절단보다 안전하다.

#### 응답

```python
class Citation(BaseModel):
    """생성물 한 조각의 근거. 채점 쪽 Evidence 와 같은 생각이지만 대조 대상이 문서다."""
    quote: str          # 모델이 적어 낸 인용 (그대로 보관 — 나중에 문제 추적용)
    matched_text: str   # 문서에서 실제로 잘라낸 구간. 화면에 보여줄 것은 이쪽이다
    start: int          # source_text 기준 시작 글자 위치
    end: int            # source_text 기준 끝 글자 위치(파이썬 슬라이스 기준)

class GeneratedChecklistItem(ChecklistItem):     # id, description, weight 를 상속
    citation: Citation

class GeneratedItem(ItemInfo):                   # item_id, prompt, item_type,
                                                 # expected_register, reference_keywords 를 상속
    checklist: list[GeneratedChecklistItem]      # 타입만 좁힌다
    citation: Citation                           # 문항 전체의 근거
    status: Literal["draft"] = "draft"           # 언제나 draft. 다른 값을 넣는 코드가 없다
    document_id: str                             # 어느 문서에서 나왔는지

class GenerationCounts(BaseModel):
    requested: int          # 관리자가 요청한 문항 수
    returned_by_model: int  # 모델이 실제로 내놓은 수
    kept: int               # 관문을 전부 통과해 응답에 실린 수
    dropped: int            # 폐기된 수
    truncated: int = 0      # 요청보다 많이 만들어 잘라낸 수 (폐기가 아니다)
    drop_rate: float        # dropped / returned_by_model, 소수 넷째 자리까지

class DroppedItem(BaseModel):
    """폐기 보고 한 줄. 문항이 아니다 — 문항으로 쓸 수 있는 형태로 담지 않는다."""
    index: int                  # 모델 응답에서 몇 번째였는지
    reason: DropReason          # 코드값. 백엔드·프론트는 문구가 아니라 이 값으로 분기한다
    detail: str                 # 사람이 읽는 한 문장
    rejected_preview: str       # 지시문 앞 40자. 관리자가 "무엇이 걸렸나" 알아보는 용도
    quote_preview: str = ""     # 문제가 된 인용 앞 40자

class GenerationMeta(BaseModel):
    generation_version: str     # 이 모듈 버전 (GENERATION_VERSION)
    prompt_version: str         # 프롬프트를 고치면 올린다 (PROMPT_VERSION)
    llm_model: str
    temperature: float          # 0.0 고정
    document_id: str
    source_text_sha256: str     # 정제 텍스트의 해시. 재검증 때 같은 문서인지 확인한다
    document_chars_raw: int
    document_chars_clean: int
    preprocess_notes: list[str] # 무엇을 지웠는지 사람이 읽는 목록
    elapsed_ms: float
    requires_human_approval: bool = True   # 언제나 True
    wording_reproducible: bool = False     # 언제나 False — 아래 설명

class GenerateItemsResponse(BaseModel):
    document_id: str
    status: Literal["draft"] = "draft"
    mode: Mode
    items: list[GeneratedItem]
    dropped: list[DroppedItem]
    counts: GenerationCounts
    source_text: str            # 정제된 문서 전문. 인용 위치(start/end)의 기준이다
    warnings: list[str]
    meta: GenerationMeta
```

**`wording_reproducible = False` 를 응답에 박아 두는 이유.**
B1 실측에서 같은 문서로 두 번 생성했을 때 주제와 근거는 같았지만 **문구가 달랐다.**
temperature 0 이어도 그렇다. 이 사실을 숨기면 "AI 채점은 재현되는데 생성은 왜 안 되냐"는
질문에 말로 변명하게 된다. 필드로 내보내면 답이 설계가 된다 —
**생성은 1회만 하고, 확정은 사람의 승인이며, 시험에 쓰이는 것은 확정된 문항이다.**
재현되어야 하는 것은 생성이 아니라 채점이고, 채점은 재현성 100%가 실측돼 있다.

**`source_text` 를 응답에 넣는 이유.**
인용의 `start`/`end` 는 정제 텍스트 기준이다. 승인 화면에서 문서를 하이라이트하려면
그 텍스트가 있어야 하는데, 우리는 무상태라 저장하지 않는다. 그래서 돌려준다.
백엔드는 이것을 draft 와 함께 저장해야 한다(최대 30,000자).

**재시도 루프를 만들지 않는다.** 폐기가 생겨 문항이 모자라도 자동으로 다시 부르지 않는다.
자동 재시도는 ① 폐기율 수치를 우리 손으로 지우고 ② 관리자가 실제로 몇 문항을 받았는지
보이지 않게 만든다. 모자라면 관리자가 `item_count` 를 올려 다시 요청한다.

#### 실패 응답

| 상황 | HTTP | 이유 |
|---|---|---|
| 요청 검증 실패 (§4.1 표) | 400 | |
| LLM 키 없음 / 호출 실패 / JSON 깨짐 | 503 | **채점과 달리 대체 경로가 없다.** 규칙만으로 문항을 지어낼 수는 없다. 채점은 LLM 이 죽어도 규칙 자질로 점수를 내지만, 생성은 죽으면 죽는다고 말해야 한다 |
| 모델이 문항을 0개 냈거나 전부 폐기됨 | **200** | 오류가 아니다. `items: []` + `dropped` 전체 + 경고를 돌려준다. 관리자가 문서를 바꿔 다시 시도할 수 있게 |

### 4.2 `POST /verify-items` — 관리자가 고친 문항 재검증 (우선순위 P1)

승인 화면에서 관리자가 체크리스트 문구를 고치면 인용 근거가 깨질 수 있다.
재검증할 자리가 없으면 "승인자가 손대는 순간 근거 보장이 사라진다"는 질문에 답이 없다.
검증 함수는 이미 만들어 놓은 것을 그대로 쓰므로 추가 비용이 작다. **LLM 호출 없음.**

```python
class VerifyItemsRequest(BaseModel):
    source_text: str                 # /generate-items 가 돌려준 정제 텍스트 그대로
    source_text_sha256: str = ""     # 있으면 대조한다. 다르면 경고를 붙인다
    items: list[GeneratedItem]

class ItemVerification(BaseModel):
    item_id: str
    ok: bool
    failures: list[DroppedItem]      # 어느 관문에 왜 걸렸는지 (index 는 목록에서의 순번)

class VerifyItemsResponse(BaseModel):
    all_ok: bool
    results: list[ItemVerification]
    warnings: list[str]
```

백엔드 사용 규칙: `all_ok == false` 인 문항은 `confirmed` 로 바꾸지 않는다.

---

## 5. 생성 프롬프트 (`src/generation/prompt.py`)

`PROMPT_VERSION = "gen_writing_v2"`. 프롬프트를 고치면 이 값을 올리고,
응답 `meta.prompt_version` 으로 나간다. 어떤 프롬프트로 만든 문항인지 추적하기 위해서다.

B1 에서 **실측으로 폐기율 100% → 0%** 를 만든 인용 규칙(규칙 1)이 이 프롬프트의 핵심이며,
문구를 임의로 다듬지 않는다. 나머지는 그 위에 얹은 품질 규칙이다.

### 5.1 시스템 지시문 (전문)

```
당신은 외국인 노동자용 한국어 직무 시험의 문항 설계 도구다.
주어진 안전 문서의 내용으로만 쓰기 문항을 만든다.

반드시 지킬 규칙:

1. [근거] 문서에 없는 내용으로 문항을 만들지 않는다.
   문항마다, 그리고 체크리스트 항목마다 근거가 된 문서 구절을 quote 로 첨부한다.
   quote 규칙:
   - 문서에서 이어진 한 구절만 그대로 복사한다 (띄어쓰기는 달라도 된다)
   - 10~40자의 짧은 구절이면 충분하다
   - 여러 곳의 구절을 합치거나 "...", 생략, 요약을 쓰면 절대 안 된다
   - 〓 기호가 들어간 구절은 쓰지 않는다. 문서에서 잘라낸 자리 표시다
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
```

### 5.2 사용자 프롬프트 (전문)

`{workplace_line}` 은 `workplace_name` 이 있을 때만 넣는다.

````
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
{
  "items": [
    {
      "item_id": "GEN-001",
      "item_type": "work_log | messenger_report | hazard_report | handover_memo | supply_request 중 하나",
      "prompt": "응시자에게 보여줄 지시문 (쉬운 한국어, ①②③ 형식)",
      "expected_register": "formal 또는 polite",
      "checklist": [
        {"id": "c1", "description": "…했는가", "weight": 1.0,
         "quote": "이 항목의 근거가 된 문서 구절 (그대로 복사)"}
      ],
      "reference_keywords": ["핵심어", "3~5개"],
      "source_quote": "이 문항 전체의 근거가 된 문서 구절 (그대로 복사)"
    }
  ]
}
````

- `{workplace_line}` = `이 사업장 이름은 "(주)K-테스트 식품공장" 이다. 지시문에 이 이름을 써도 된다.`
- `{allowed_types}` = `options.item_types` 가 비었으면 5유형 전부, 아니면 지정된 것만.
- 모델이 적어 낸 `item_id` 는 **쓰지 않는다.** 우리가 다시 붙인다(§6.5). 모델이 같은 id 를
  중복 발급하는 일이 있고, 문서가 다른데 id 가 같으면 백엔드에서 충돌한다.

### 5.3 응답 형식표 (Gemini `response_schema`)

B1 에서 통과를 확인한 형식 그대로 쓴다. `required` 를 빠짐없이 적는 것이 중요하다 —
형식표를 안 붙였을 때 모델이 닫는 괄호를 더 붙여 응답 해석이 통째로 실패한 적이 있다
(2026-07-26 채점 쪽 실측).

```python
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
                "required": ["item_id", "item_type", "prompt", "expected_register",
                             "checklist", "reference_keywords", "source_quote"],
            },
        },
    },
    "required": ["items"],
}
```

### 5.4 호출 설정

`src/llm/client.py` 에 **추가만** 한다 (기존 함수 서명은 건드리지 않는다).
모델 선택이 한 파일에 모여 있어야 나중에 모델을 갈아 끼울 때 한 곳만 고친다
(`client_for_errors` 가 이미 그 자리에 있다).

```python
DEFAULT_GENERATION_MODEL = os.getenv("GEMINI_MODEL_GENERATION", "gemini-3-flash-preview")

def client_for_generation(base: GeminiClient | None = None) -> GeminiClient: ...
```

- 모델: `gemini-3-flash-preview` — **B1 에서 실제로 통과를 확인한 모델이다.**
  lite 는 생성에서 검증해 본 적이 없으므로 기본값으로 쓰지 않는다.
- temperature 0.0 (기본값 그대로)
- `max_output_tokens = 4096 + 2048 * item_count` — B1 에서 3문항에 8192 를 썼다.
  **미검증 추정값이므로** 구현 후 실제 응답 길이를 재서 다시 잡는다.
- `timeout_ms = 120_000` — 채점(60초)보다 길다. 문서 전문을 읽고 3~5문항을 쓴다.

---

## 6. 검증 파이프라인

### 6.1 순서도

```
[0] 요청 검증  mode / item_count / (전처리 후) 길이
      └─ 실패 ─▶ 400. 문항을 하나도 만들지 않는다

[1] 전처리  preprocess_document(document_text)
      ─▶ source_text, preprocess_notes, sha256

[2] 생성 1회  client_for_generation().generate_json(...)
      └─ LLMUnavailable ─▶ 503. 대체 경로 없음

[3] 문항별 관문 — 하나라도 걸리면 그 문항만 폐기, 나머지는 계속 간다
      G1 스키마·형식 관문   (문자 세기·정규식. LLM 없음)
      G2 인용 형식 관문     (길이·생략부호·절단 표시)
      G3 인용 대조 관문     verify_citation(source_text, quote)
      G4 채점 가드 예행     prompt_overlap / check_answer_validity  ← 채점 쪽 코드 재사용
      G5 채점 계약 변환     ItemInfo.model_validate(...)

[4] 문항 간 관문  duplicate_item (지시문끼리 겹침 검사)

[5] 조립  item_id 재부여 · status=draft · counts · warnings
```

관문은 **전부 규칙 계산이고 LLM 을 부르지 않는다.** 채점 쪽 유효성 가드와 같은 원칙이다
(`scoring/validity.py` 머리말). 같은 생성 결과를 두 번 검증하면 언제나 같은 판정이 나온다.
**생성은 재현되지 않지만 검증은 재현된다** — 이 구분이 이 모듈의 신뢰 근거다.

### 6.2 [1] 전처리 (`preprocess.py`)

B1 실측: KOSHA PDF 추출 텍스트는 띄어쓰기가 사라지고 쪽마다 머리글이 반복된다.
아래는 전부 결정적인 규칙이며, 무엇을 지웠는지 `preprocess_notes` 로 보고한다.

| 순서 | 하는 일 | 왜 |
|---|---|---|
| 1 | 원문에 있는 `〓`(U+3013) 를 공백으로 바꾼다 | 우리가 쓸 절단 표시와 충돌하지 않게 미리 치운다 |
| 2 | `\r\n` → `\n`, 줄바꿈 없는 공백(NBSP·U+200B) → 보통 공백 | |
| 3 | 같은 줄이 3회 이상 나오고 길이가 40자 이하면 지운다 | 쪽 머리글·바닥글. B1 의 하드코딩 정규식을 일반화한 것 |
| 4 | 쪽번호만 있는 줄(`^\s*-?\s*\d+\s*-?\s*$`)을 지운다 | |
| 5 | 지운 자리에 `\n〓\n` 를 남긴다 | 잘라낸 자리 표시 |
| 6 | 공백 3개 이상 → 1개, 빈 줄 3줄 이상 → 1줄 | |

**절단 표시(`〓`)가 왜 필요한가.** 머리글을 지우면 앞뒤 문장이 붙는다. 모델이 그 이음매를
가로질러 인용을 복사하면, 그 구절은 정제 텍스트에는 있지만 **실제 문서에는 없는 문장**이다.
`〓` 는 `citation.py` 가 무시하는 문자 목록에 없으므로 정규화 후에도 남는다.
그래서 "quote 에 `〓` 가 있으면 폐기"라는 한 줄짜리 규칙으로 이 경우를 정확히 잡을 수 있다.

띄어쓰기 소실은 복원하지 않는다. 인용 대조는 공백을 무시하므로 검증에는 지장이 없고,
붙어 있는 문구가 지시문에 새어 나오는 것은 G1 의 `MAX_UNSPACED_RUN` 검사로 막는다.

### 6.3 [3] 관문 상세

#### G1 스키마·형식 관문

| 검사 | 기준 | 폐기 사유 |
|---|---|---|
| 필수 필드 존재·타입 | `prompt`, `item_type`, `expected_register`, `checklist`, `source_quote` | `schema_invalid` |
| 문항 유형 | 5유형 안에 있고, `options.item_types` 를 지정했으면 그 안 | `unknown_item_type` |
| 말투 | `formal` 또는 `polite` | `schema_invalid` |
| 체크리스트 개수 | 2~5개 | `schema_invalid` |
| 가중치 | 0.5 ≤ weight ≤ 1.5 | `schema_invalid` |
| 지시문 길이 | 30~200자 | `prompt_format_invalid` |
| 지시문에 ①②③ | 세 기호가 모두 있어야 한다 | `prompt_format_invalid` |
| 지시문에 붙어 있는 글자 덩어리 | 공백 없이 이어진 글자가 `MAX_UNSPACED_RUN = 12` 자를 넘으면 안 된다 | `prompt_format_invalid` |
| 쓰기 지시 동사 | `쓰세요 / 작성하세요 / 알리세요 / 보고하세요 / 남기세요 / 요청하세요` 중 하나 이상 | `prompt_not_a_writing_task` |

**가중치가 범위 밖일 때 조용히 깎지 않고 폐기하는 이유.** weight 는 점수에 직접 들어가는
값이다. 우리가 몰래 고치면 관리자가 승인한 문항과 채점에 쓰인 문항이 달라진다.
점수에 들어가는 값은 손대지 않는다.

암기 문제 금지는 금지어 목록으로 잡으려 하면 우회가 너무 쉽다. 그래서 **"쓰기를 시키는
동사가 있는가"라는 통과 조건**으로 뒤집었다. "황화수소의 허용농도는 몇 ppm입니까?" 는
이 조건을 통과하지 못한다. 금지어 목록(`무엇입니까`, `정의를 쓰시오` 등)은 폐기가 아니라
경고로만 쓴다.

#### G2 인용 형식 관문 (LLM 응답만 보고 판단)

| 검사 | 폐기 사유 |
|---|---|
| `source_quote` 또는 체크리스트 `quote` 가 비어 있다 | `citation_missing` |
| 인용에 `...` `…` `(중략)` `~` 이음표가 있다 | `citation_stitched` |
| 인용 길이가 8자 미만 또는 60자 초과 | `citation_stitched` |
| 인용에 `〓` 가 있다 (절단 자리를 가로질렀다) | `citation_crosses_cut` |

**프롬프트 규칙을 코드로 한 번 더 확인하는 이유.** B1 에서 모델이 실제로 한 짓이
"여러 구절을 `...` 으로 이어붙이기"였다. 프롬프트로 막아 폐기율이 0%가 됐지만,
프롬프트는 부탁이고 코드는 강제다. 모델을 바꾸면 부탁은 다시 무시될 수 있다.

#### G3 인용 대조 관문 — 이 모듈의 심장

`verify_citation(source_text, quote)` 를 **문항 인용 1개 + 체크리스트 인용 전부**에 돌린다.
채점에서 쓰던 함수를 그대로 쓴다. 대조 대상만 '응시자 답안' → '안전 문서'로 바뀐 것이다.

- 하나라도 실패하면 **문항 통째로 폐기.** 부분 통과를 인정하지 않는다.
  체크리스트 c3 의 근거가 가짜면 그 문항의 점수 일부가 근거 없이 매겨진다.
- 통과하면 `Citation(quote, matched_text, start, end)` 를 붙인다.
  화면에 보여줄 것은 모델이 적어 낸 `quote` 가 아니라 **문서에서 잘라낸 `matched_text`** 다.
  (채점 쪽과 같은 규칙: 원문에 없는 글자가 근거로 나가면 안 된다)
- 폐기 사유 `citation_not_found`.

#### G4 채점 가드 예행 (LLM 없음)

생성된 문항을 **채점기의 유효성 가드에 미리 태워 본다.** 통과 못 하는 문항은
"응시자가 성실하게 답해도 무효 처리되는 문항"이다.

```python
ratio, _ = prompt_overlap(answer_text=item.prompt, prompt=item.citation.matched_text)
if ratio >= MAX_PROMPT_QUOTE_OVERLAP:   # 0.50
    drop(DropReason.PROMPT_LEAKS_ANSWER)

report = check_answer_validity(answer_text=item.citation.matched_text,
                               item_prompt=item.prompt)
if FLAG_PROMPT_COPY in report.flags:
    drop(DropReason.PROMPT_LEAKS_ANSWER)
```

**왜 이 검사가 필요한가.** 지시문이 문서 문장을 그대로 옮겨 적으면 두 가지가 동시에
망가진다. ① 답이 문제에 들어 있어 시험이 안 된다. ② 그 표현을 따라 쓴 성실한 응시자가
채점 가드의 `prompt_copy` 에 걸려 **무효 0점**을 받는다(가드 C, 겹침 70% 이상).
둘 다 승인 화면에서 사람이 알아채기 어렵다. 숫자로 미리 잰다.

기준값 `MAX_PROMPT_QUOTE_OVERLAP = 0.50` 은 임시값이다. B3 에서 가상 공장 문서로
생성해 보고 오탐(멀쩡한 문항이 걸리는 일) 건수를 세어 다시 잡는다.

#### G5 채점 계약 변환 관문

```python
ItemInfo.model_validate(generated_item.model_dump())   # 실패하면 not_scoreable
```

이 한 줄이 "생성한 문항을 채점기가 받을 수 있다"를 **말이 아니라 코드로** 증명한다.
`GeneratedItem` 은 `ItemInfo` 를 상속하고 pydantic 은 모르는 필드를 무시하므로,
백엔드는 우리 응답의 문항을 그대로 `ScoreRequest.item` 에 넣으면 된다
(`citation`, `status`, `document_id` 는 조용히 버려진다).

### 6.4 [4] 문항 간 관문

- `prompt_overlap(A.prompt, B.prompt) ≥ 0.80` 이면 뒤엣것을 `duplicate_item` 으로 폐기.
- 같은 `item_type` 만 3개 이상이면 **경고**(폐기 아님). 유형 편중은 품질 문제이지
  검증 실패가 아니다.

**폐기와 경고를 가르는 원칙: 폐기는 검증 실패에만 쓴다. 품질 의심은 경고로 보내고
사람이 판단한다.** 이 선을 흐리면 폐기율이라는 수치가 의미를 잃는다.

### 6.5 [5] 조립

- `item_id` 재부여: `{prefix}-{doc6}-{nnn}`
  (`doc6` = `sha256(source_text)[:6].upper()`, `nnn` = 통과 순서 001부터)
  예: `GEN-3F9A2C-001`. 문서가 같으면 앞자리가 같아 추적하기 쉽고, 문서가 다르면 안 겹친다.
- `reference_keywords`: 정제 텍스트에 (공백 무시 비교로) **실제로 있는 낱말만 남긴다.**
  없는 낱말은 빼고 경고에 남긴다. 이 값은 LLM 을 못 쓸 때의 대체 판정에 쓰이는 값이라,
  지어낸 낱말이 들어가면 대체 채점이 엉뚱하게 돈다. 전부 빠져도 문항은 살린다.
- 통과 수가 `item_count` 보다 많으면 앞에서부터 잘라 내고 `counts.truncated` 에 적는다.
  **잘라 낸 것은 폐기가 아니다.** 폐기율 수치에 섞지 않는다.

### 6.6 폐기 사유 코드 (`DropReason`)

문구가 아니라 이 값으로 분기한다(채점 쪽 `validity_flags` 와 같은 원칙).

| 코드 | 뜻 | 관문 |
|---|---|---|
| `schema_invalid` | 필드가 없거나 값의 범위가 틀렸다 | G1 |
| `unknown_item_type` | 5유형에 없는 문항 유형을 만들었다 | G1 |
| `prompt_format_invalid` | 지시문 길이·①②③·붙어 있는 글자 규칙 위반 | G1 |
| `prompt_not_a_writing_task` | 쓰기를 시키지 않는 지시문(암기 문제) | G1 |
| `citation_missing` | 인용을 안 달았다 | G2 |
| `citation_stitched` | 여러 구절을 이어붙였거나 길이 규칙 위반 | G2 |
| `citation_crosses_cut` | 전처리로 잘라낸 자리를 가로지르는 인용 | G2 |
| `citation_not_found` | 문서에서 찾을 수 없는 인용 (지어냄) | G3 |
| `prompt_leaks_answer` | 지시문에 답이 들어 있다 / 채점 가드에 걸리는 문항 | G4 |
| `not_scoreable` | 채점 API 형식으로 바뀌지 않는다 | G5 |
| `duplicate_item` | 앞 문항과 사실상 같은 문항 | 문항 간 |

---

## 7. 승인 상태 모델 (draft → confirmed)

### 7.1 상태값의 뜻 (우리가 정의하고, 백엔드가 집행한다)

| 상태 | 뜻 | 누가 만드나 | 시험 출제 |
|---|---|---|---|
| `draft` | AI 초안. 기계 관문은 통과했지만 **사람이 아직 안 봤다** | 우리 API | 불가 |
| `confirmed` | 관리자가 승인했다 | 백엔드(관리자 행위) | 가능 |
| `rejected` | 관리자가 버렸다 | 백엔드 | 불가 |
| `edited` | 관리자가 고쳤다. 재검증 대기 | 백엔드 | 재검증 통과 뒤 confirmed 로만 |

### 7.2 전이 규칙

```
draft ──승인──▶ confirmed ──시험 편성──▶ 응시
  │                 │
  │                 └──수정──▶ edited ──/verify-items 통과──▶ confirmed(새 item_id)
  ├──거부──▶ rejected                         └──실패──▶ edited 유지
  └──수정──▶ edited ──/verify-items 통과──▶ confirmed
```

**확정된 문항은 불변이다. 고치면 새 `item_id` 를 발급한다.**
같은 `item_id` 의 내용이 바뀌면, 그 문항으로 이미 시험을 본 응시자의 점수는
"무엇을 보고 매긴 점수인지" 설명할 수 없게 된다. 이 프로젝트에서 그것은 결함이다.
백엔드에 요구하는 규칙이며, 우리 쪽에서는 `/verify-items` 가 재검증만 책임진다.

### 7.3 책임 경계

| 항목 | 우리 | 백엔드 |
|---|---|---|
| 문항 생성·검증 | O | |
| `status="draft"` 표시, 근거 인용 부착 | O | |
| 생성 조건 기록(모델·프롬프트 버전·문서 해시) | O | |
| 수정본 재검증(`/verify-items`) | O | |
| draft 저장, `source_text` 보관 | | O |
| 승인·거부 API, 관리자 권한 확인 | | O |
| 승인자·승인 시각 기록 | | O |
| 응시자에게 confirmed 만 노출 | | O |
| `reference_keywords` 응시자 화면 비노출 | | O |
| 문항 불변 규칙 집행(수정 시 새 id) | | O |

**백엔드에 반드시 전달할 한 문장**: 우리 응답을 저장할 때 **필드를 지우지 마라.**
`citation` 을 버리면 승인 화면에서 근거를 보여줄 수 없고, 그 순간 이 기능은
"AI가 만든 문제를 그냥 믿는 서비스"가 된다.

### 7.4 승인 화면 최소 요건 (프론트에 전달)

1. 문항 지시문 (응시자가 볼 그대로)
2. 체크리스트 항목 + 가중치
3. **각 항목 옆에 근거 인용** (`citation.matched_text`), 클릭하면 문서에서
   `start`~`end` 구간 하이라이트
4. 폐기된 문항 수와 사유 (`counts`, `dropped[].reason`) — "AI가 3개 중 1개를 스스로
   버렸다"가 화면에 보여야 이 기능이 설명된다
5. `reference_keywords` 는 관리자에게만
6. 문항별 [승인] / [거부] / [수정]

---

## 8. 테스트해야 할 경계 사례 (`tests/test_generation.py`)

전부 **가짜 클라이언트로, 네트워크 없이** 돈다. 가짜 클라이언트는 미리 적어 둔 JSON 을
돌려주는 객체이며 `type(base) is not GeminiClient` 검사 때문에 실제 호출로 바뀌지 않는다
(`client_for_errors` 주석 참고 — `client_for_generation` 도 같은 방식으로 만든다).

### 폐기가 되어야 하는 것

| # | 상황 | 기대 |
|---|---|---|
| 1 | 문서에 없는 인용을 단 문항 | `citation_not_found`, `items` 에 없음 |
| 2 | `"...으로 이어붙인 인용"` (B1 에서 실제로 나온 형태) | `citation_stitched` |
| 3 | 전처리 절단 표시 `〓` 를 가로지르는 인용 | `citation_crosses_cut` |
| 4 | 인용이 3자뿐 | `citation_stitched` (길이 규칙) |
| 5 | 체크리스트 4개 중 1개만 인용 실패 | 문항 **통째** 폐기 (부분 통과 없음) |
| 6 | `item_type: "essay"` | `unknown_item_type` |
| 7 | `weight: 2.5` | `schema_invalid` (조용한 보정 없음) |
| 8 | 지시문에 ①②③ 이 없음 | `prompt_format_invalid` |
| 9 | 지시문에 공백 없는 20자 덩어리 | `prompt_format_invalid` |
| 10 | "황화수소 허용농도는 몇 ppm입니까?" | `prompt_not_a_writing_task` |
| 11 | 지시문이 문서 문장을 80% 그대로 옮김 | `prompt_leaks_answer` |
| 12 | 지시문이 사실상 같은 문항 2개 | 뒤엣것 `duplicate_item` |

### 통과·동작이 되어야 하는 것

| # | 상황 | 기대 |
|---|---|---|
| 13 | 정상 응답 3문항 | `kept=3`, 모든 `status == "draft"` |
| 14 | 응답의 모든 문항을 `ItemInfo.model_validate` | 예외 없음 |
| 15 | 생성 문항으로 `/score` 를 실제 호출(가짜 LLM) | 채점이 끝까지 돈다 = 채점기 무변경 증명 |
| 16 | 같은 가짜 응답을 두 번 처리 | 결과가 **완전히 같다** (우리 후처리는 결정적) |
| 17 | 모델이 5개를 냄, `item_count=3` | `kept=3`, `truncated=2`, `drop_rate` 오염 없음 |
| 18 | 모델이 0개를 냄 / 전부 폐기 | HTTP 200, `items=[]`, 경고 있음 |
| 19 | `reference_keywords` 에 문서에 없는 낱말 | 그 낱말만 제거 + 경고, 문항은 살아남음 |
| 20 | 문서 원문에 `〓` 가 들어 있음 | 전처리에서 공백으로 치환됨 (표시와 충돌 없음) |
| 21 | 같은 줄이 5번 반복되는 문서(머리글) | 제거되고 `preprocess_notes` 에 기록 |

### 거부되어야 하는 것

| # | 상황 | 기대 |
|---|---|---|
| 22 | `document_text` 200자 | 400 |
| 23 | `document_text` 50,000자 | 400 (절단하지 않는다) |
| 24 | `mode: "speaking"` | 400 |
| 25 | LLM 키 없음 | 503 (채점처럼 대체 경로로 넘어가지 않는다) |
| 26 | 모델 응답 JSON 깨짐 | 503 |

### 구조를 지키는 테스트

| # | 검사 | 기대 |
|---|---|---|
| 27 | `src/scoring/**.py` 안에 `generation` import 가 있는가 | 없어야 한다 |
| 28 | 응답 어디에도 `"confirmed"` 문자열이 생기지 않는가 | 생성 코드에 그 값이 없다 |

---

## 9. 실측한 것과 아직 모르는 것

**실측한 것 (B1, 2026-08-01, KOSHA 화학설비 정비·보수 지침 C-2-2025)**

- 실제 안전문서에서 우리 items 형식의 쓰기 문항 3개 생성 + 인용 검증 통과 (2회 실행)
- 인용 규칙이 없는 프롬프트: **폐기율 100%** — 모델이 여러 구절을 `...` 으로 이어붙였고
  검증기가 전부 걸러냈다
- "이어진 한 덩어리만 / 10~40자 / 생략부호 금지" 규칙 추가 후: **폐기율 0%**
- 같은 문서 2회 생성 시 주제·근거는 같고 **문구는 달랐다** → 생성 1회 + 승인 고정 원칙
- KOSHA PDF 추출 텍스트는 띄어쓰기가 사라지고 머리글이 반복되지만,
  인용 검증은 공백을 무시해 통과했다

**아직 모르는 것 (지어내서 말하지 않는다)**

- 생성 1회에 걸리는 시간과 토큰 비용 — B1 에서 재지 않았다. B2 구현 때 잰다
- 문서 길이 상한 30,000자가 적절한지 — 근거 없는 첫 기준값
- `MAX_PROMPT_QUOTE_OVERLAP = 0.50` 오탐률 — B3 에서 가상 공장 문서로 잰다
- 사람이 보기에 좋은 문항이 몇 %인지 — 폐기율은 '근거가 있는가'이지 '좋은가'가 아니다.
  8/5~6 검수에서 사람 눈으로 세고 그 수치를 따로 보고한다

---

## 10. 이 기능을 심사에서 어떻게 방어하나

**"AI가 문제를 자동 생성하는 건 이미 있지 않나?"** — 맞다. 그 자리에서 밀리면 안 된다.

- **DET(Duolingo English Test)** 은 transformer 기반 자동 문항 생성을 논문으로 공개했고
  (Attali et al., *The interactive reading task: Transformer-based automatic item generation*,
  Frontiers in Artificial Intelligence, 2022), 대규모 파일럿과 human-in-the-loop 검토를
  거친다. 즉 **"AI가 문항을 만든다"는 것 자체는 우리의 차별점이 아니다.**
- **Pearson PTE / Versant** 는 문항은행을 유지하고, 채점되지 않는 문항(unscored items)에
  모인 응답으로 새 문항의 채점 모델을 학습시킨다 — 중앙 문항은행 모델이다.
- **TOPIK** 은 중앙 출제 고정 문항이다(출처를 확인하지 못했으므로 발표에서 단정하지 않는다).

**갈리는 지점 세 가지**

1. **문항의 출처가 시험사의 코퍼스가 아니라 응시 기관이 올린 문서다.**
   위 시험들은 전부 시험사가 가진 자료로 문항을 만든다. "당신 공장 문서로 만든 시험"은
   구조가 다르다. 응시자가 실제로 지켜야 할 규칙으로 평가받는다.
2. **근거 없는 생성물을 사람이 아니라 코드가 먼저 버린다.**
   DET 의 human-in-the-loop 은 사람이 본다. 우리는 사람에게 가기 전에 기계 관문 5개를
   지나며, 원문에서 찾을 수 없는 인용을 단 문항은 **관리자 화면에 뜨지도 않는다.**
   그리고 그 효과를 수치로 갖고 있다 — 규칙 전 폐기율 100%, 규칙 후 0%.
3. **채점기는 손대지 않았다.** 생성 문항도 기존 문항도 같은 파이프라인으로 채점된다
   (재현성 100%, 오류 탐지율 90% 실측). 생성이 채점 신뢰도를 갉아먹지 않는다는 뜻이고,
   이것은 `ItemInfo.model_validate` 관문과 import 방향 테스트로 검사된다.

**하면 안 되는 주장**: "자동 문항 생성 최초", "AI 시험 SOTA". 위 논문 하나로 무너진다.
말할 수 있는 것은 측정 범위와 함께 있는 문장뿐이다 —
"실제 KOSHA 문서에서 인용 근거를 갖춘 쓰기 문항을 만들고, 근거가 없는 것은 자동 폐기한다.
그 폐기가 실제로 작동하는 것을 폐기율 100%→0% 로 확인했다."

---

## 11. 구현 순서와 완료 기준

**P0 (8/2)**
1. `schema.py` — 계약부터 고정한다. 백엔드에 먼저 보낸다
2. `preprocess.py` + 테스트 20·21
3. `prompt.py` — B1 프롬프트 옮기고 §5 규칙 추가
4. `validate.py` — 관문 G1~G5 + 테스트 1~12
5. `generate.py` + `POST /generate-items` + 테스트 13~26

**P1 (8/3)**
6. `POST /verify-items`
7. `scripts/check_generate.py` — 실제 KOSHA 문서로 돌려 눈으로 확인, 시간·토큰 실측
8. `scripts/extract_pdf.py` (시연 폴백)
9. 구조 테스트 27·28

**완료 기준 (PLAN.md B2)**
- pytest 전부 통과 (기존 111개 + 신규)
- 같은 문서 3회 생성 비교표: 문구 일치 여부 / **관문 통과 여부** / 폐기율
  (재현성 주장은 문구가 아니라 검증 결과로 한다)
- `/docs` 에 `POST /generate-items` 노출
- 폐기율·생성 시간 실측값을 HISTORY.md 에 기록
