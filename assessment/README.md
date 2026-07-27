# assessment — 문항 + AI 채점

- **담당자**: 전재완

외국인 노동자의 한국어 답안(말하기·쓰기)을 자동 채점해 **점수 + 영역별 서브스코어 + 근거**를 돌려주는 모듈입니다.
백엔드와는 **REST로만** 연결합니다. 채점 모델을 바꿔도 백엔드가 수정되지 않도록 인터페이스를 고정했습니다.

---

## 백엔드 연동 (이것만 보시면 됩니다)

엔드포인트는 2개입니다. **문항이 끝날 때마다 `/score`, 시험이 끝나면 `/finalize`.**

### `POST /score` — 문항 하나 채점

```json
{
  "submission_id": "sub-0001",
  "mode": "writing",
  "answer_text": "오늘 삼번 라인에서 포장 작업을 하였습니다...",
  "item": {
    "item_id": "WRT-001",
    "prompt": "작업일지를 작성하세요.",
    "checklist": [
      { "id": "c1", "description": "작업 내용을 기록했는가", "weight": 1.0 },
      { "id": "c2", "description": "발생한 문제를 기록했는가", "weight": 1.5 }
    ]
  }
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `submission_id` | O | 답안 식별자 |
| `mode` | O | `writing` / `speaking` |
| `answer_text` | O | 답안 텍스트 |
| `item.item_id` | O | 문항 식별자 |
| `item.prompt` | O | 응시자에게 제시된 지시문 |
| `item.checklist[]` | | 내용 채점 항목. **없으면 내용 점수가 나오지 않습니다** |
| `item.expected_register` | | `formal`(기본) / `polite` / `any` |
| `options.use_llm` | | 기본 `true`. `false`면 규칙 자질만으로 채점 |

**응답 주요 필드**

| 필드 | 설명 |
|---|---|
| `overall_score` | 0~100 종합 점수 |
| `overall_grade` | A / B / C / D / E |
| `subscores[]` | 영역별 점수 (`content_task`, `language_use`, `delivery`) |
| `subscores[].contributions[]` | 어떤 자질이 몇 점 보탰는지 내역 |
| `subscores[].evidence[]` | 근거. `quote`, `start`, `end`(원문 글자 위치) |
| `checklist_results[]` | 항목별 `met`(0/1) + 근거 인용 |
| `warnings[]` | 사람이 읽는 경고 문구 |
| `meta.reliability` | `full` / `partial` / `fallback` |
| `meta.safe_to_show_candidate` | **점수 표시 전 반드시 확인** |

> ### 프론트에 꼭 전달해 주세요
>
> **`meta.safe_to_show_candidate` 가 `false` 면 점수를 화면에 띄우면 안 됩니다.**
>
> LLM 장애 시에도 채점은 멈추지 않고 대체 경로로 점수를 냅니다. 그때도 **점수는 멀쩡한 숫자로 나옵니다.**
> 실측 예: 같은 답안이 정상일 때 70.58점, 대체 경로에서 79.66점.
> 숫자만으로는 구별할 수 없으므로 이 값 하나로 판단하세요. `warnings` 를 읽어서 판단하지 마세요.

### `POST /finalize` — 시험 전체 최종 등급

```json
{
  "session_id": "sess-0042",
  "candidate_id": "cand-0042",
  "items": [],
  "expected_items": [ { "item_id": "WRT-001", "mode": "writing" } ]
}
```

`items` 에는 **`/score` 응답을 가공 없이 그대로** 담으면 됩니다. 필드명을 맞춰 두었고 모르는 필드는 무시합니다.

**응답**: `overall_score`, `overall_grade`, `percentile`, `subscores[]`, `mode_results[]`(말하기/쓰기 각각), `cross_mode_check`(말하기·쓰기 등급 차이 — 부정행위 교차검증 신호)

### 구현 상태

| | 상태 |
|---|---|
| 쓰기 채점 (`mode: writing`) | 연동 가능 |
| 최종 등급 (`/finalize`) | 연동 가능 |
| 말하기 채점 (`mode: speaking`) | 텍스트(STT 전사본)를 넣으면 동작. **음성 파일 입력은 미구현** |
| 발화 전달력 (`delivery`) | 미채점. Azure Pronunciation Assessment 도입 전이라 비중 0 |

말하기 음성 입력(`audio.url`)은 Azure 계정 발급 후 추가합니다. 그때 필드가 늘어나지만 **기존 필드는 바뀌지 않습니다.**

---

## 채점 흐름

```
답안 도착
  |
  1. STT 전사 보정     말하기만. 기계가 잘못 받아쓴 곳을 고침
  |                    -> 내용은 보정본, 문법은 원본으로 채점
  2. 규칙 자질 추출    Kiwi 형태소 분석. LLM 없이 항상 같은 값
  3. LLM 판정          문법 오류 찾기 + 체크리스트 0/1 (동시 호출)
  4. 인용 검증         원문에 없는 근거는 폐기하고 0점 처리
  5. 점수 결합         자질 -> 영역 점수 -> 종합 점수
  6. 최종 등급         문항별 결과를 모아 등급·백분위 (/finalize)
```

### 설계 원칙

1. **근거 없는 점수는 만들지 않는다.** 모든 점수에 원문 인용과 위치가 붙습니다.
2. **LLM은 사실 확인만, 점수 계산은 코드가 한다.** "몇 점?"은 매번 다르지만 "이 말을 했나?"는 안정적입니다.
3. **LLM이 죽어도 채점은 멈추지 않는다.** 대신 무엇이 빠졌는지 `warnings` 와 `meta.reliability` 에 남깁니다.
4. **백엔드가 보는 형식은 고정, 내부는 자유.** 계약은 `src/scoring/schema.py` 한 곳에 있습니다.
5. **임시값은 임시값이라고 크게 써 둔다.** 가중치·등급 커트라인·백분위가 모두 학습 전 임시값이며, 그 경고가 응답에 실려 나갑니다.

> **주의**: 현재 가중치와 등급 커트라인은 손으로 정한 임시값입니다.
> 답안 사이 비교에는 쓸 수 있으나 **확정 등급 통보에는 쓸 수 없습니다.**

---

## 폴더 구조

```
assessment/
├── src/
│   ├── features/        자질 추출 (자질 하나가 늘면 여기에 함수가 하나 는다)
│   │   ├── lexical.py     Kiwi 규칙 자질 9종 + 띄어쓰기 대조
│   │   ├── errors.py      LLM 오류 자질 (조사·어미활용·어휘오용·높임법·맞춤법)
│   │   └── checklist.py   내용·과제 수행 0/1 판정
│   ├── llm/             Gemini 호출과 인용 검증 (채점 로직은 두지 않는다)
│   │   ├── client.py      temperature 0 · JSON 강제 래퍼
│   │   ├── citation.py    원문에 없는 인용을 폐기하는 검증
│   │   └── transcript.py  STT 전사 보정 + 보정 위치 기록
│   ├── scoring/
│   │   ├── schema.py      백엔드와의 REST 계약 (여기를 바꾸면 백엔드가 깨진다)
│   │   ├── combine.py     자질 -> 영역 점수 -> 종합 점수
│   │   ├── pipeline.py    전체 조립 + 신뢰도 판정
│   │   └── finalize.py    시험 전체 최종 등급·백분위
│   ├── resources/       어휘 등급 목록 등 데이터 파일
│   └── api.py           FastAPI 엔드포인트
├── scripts/             실행해서 눈으로 값을 확인하는 검증 스크립트
└── tests/               pytest 회귀 방지 (86개)
```

자질을 추가할 때 **규칙 계산이면 `features/lexical.py`, 판단이 필요하면 `features/errors.py`** 입니다.
이 경계가 재현성을 만들므로 섞지 않습니다.

---

## 실행 방법

### 준비

```bash
cd assessment
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
```

`.env` 에 `GEMINI_API_KEY` 를 넣습니다. **`.env` 는 절대 커밋하지 않습니다**(루트 `.gitignore` 에서 제외됨).

### 서버 실행

```bash
python -m uvicorn src.api:app --port 8000
```

- API 문서: http://localhost:8000/docs — **필드를 직접 보고 브라우저에서 테스트 요청을 보낼 수 있습니다**
- 상태 확인: http://localhost:8000/health

### 답안 하나 빠르게 채점해 보기

```bash
python scripts/score_writing.py "오늘 삼번 라인에서 포장 작업을 하였습니다."
python scripts/score_writing.py --file answer.txt
python scripts/score_writing.py "..." --no-llm
```

### 전체 파이프라인 확인

```bash
python scripts/check_pipeline_demo.py
```

3문항(말하기 2 + 쓰기 1) 채점부터 최종 등급까지 전부 출력합니다.

### 테스트

```bash
python -m pytest tests -q
```

---

## 사용 모델과 비용

| 항목 | 값 |
|---|---|
| 모델 | `gemini-3.1-flash-lite` (`.env` 의 `GEMINI_MODEL` 로 교체 가능) |
| 단가 | 입력 $0.25 / 출력 $1.50 (per 1M 토큰) |
| 실측 토큰 | 말하기 1문항 = 입력 1,755 / 출력 716 |
| 문항당 | 말하기 2.1원 / 쓰기 1.3원 |
| 응시자 1명 (10문항) | 약 18원 |

> Gemini 무료 등급은 **하루 호출 한도가 모델마다 따로** 걸립니다. 상위 모델일수록 한도가 작아 개발 중 금방 막힙니다.
> 무료 등급에서는 주고받은 내용이 제품 개선에 사용될 수 있으므로, **응시자 답안을 다루는 이상 결제 등급 전환이 필요합니다.**
