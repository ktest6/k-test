"""백엔드에 넘길 '문구 코드표'를 카탈로그에서 그대로 뽑아 만든다.

**왜 손으로 안 쓰고 뽑는가.**
코드는 `src/scoring/messages.py` 에 있고 문서는 `outputs/api_message_codes.md` 에 있다.
둘을 따로 관리하면 코드를 하나 고쳤을 때 문서만 옛날 그대로 남는다. 백엔드는 문서를
보고 영어 문장을 만드는데, 문서가 옛날 것이면 화면에 엉뚱한 문구가 뜬다.
그래서 문서는 **언제나 코드에서 뽑아 만든다.** 코드를 고치고 이것을 다시 돌리면 끝이다.

    python scripts/export_message_codes.py

돌리면 `assessment/outputs/api_message_codes.md` 를 새로 쓴다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 이 스크립트를 어디서 돌려도 assessment 폴더를 찾을 수 있게 경로를 잡아 둔다
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))

from assessment.src.scoring.messages import MESSAGE_CATALOG, MessageSpec  # noqa: E402

OUT_PATH = ROOT / "outputs" / "api_message_codes.md"


# 표를 엔드포인트별로 나눠 싣는다. (제목, 어느 endpoint 값을 여기 넣을지 판별하는 함수)
SECTIONS: list[tuple[str, str]] = [
    ("공통(모든 POST) — 인증", "공통(모든 POST)"),
    ("POST /score", "/score"),
    ("POST /score · POST /generate-items 공용 — LLM 실패 사유", "/score, /generate-items"),
    ("POST /finalize", "/finalize"),
    ("POST /score · POST /finalize 공용", "/score, /finalize"),
    ("POST /generate-items", "/generate-items"),
    ("POST /generate-items · POST /verify-items 공용", "/generate-items, /verify-items"),
    ("POST /verify-items", "/verify-items"),
]


def _escape(text: str) -> str:
    """표 한 칸에 넣어도 표가 깨지지 않게 다듬는다.

    마크다운 표는 `|` 로 칸을 나누므로 문구 안의 `|` 를 그대로 두면 칸이 어긋난다.
    줄바꿈도 표 안에서는 칸을 깨뜨리므로 공백 하나로 바꾼다.
    """
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _params_cell(spec: MessageSpec) -> str:
    """params 칸에 넣을 글. 키 · 타입 · 예시값을 한 줄씩 적는다."""
    if not spec.params:
        return "(없음)"
    lines = []
    for key, kind in spec.params.items():
        sample = spec.examples.get(key)
        # 중첩 Notice 는 통째로 적으면 표가 길어지므로 안쪽 코드만 보여 준다
        if isinstance(sample, dict) and "code" in sample:
            shown = f"→ {sample['code']}"
        elif isinstance(sample, list):
            shown = f"[{len(sample)}개]"
        else:
            shown = json.dumps(sample, ensure_ascii=False)
        lines.append(f"`{key}` ({kind}) 예: {shown}")
    return "<br>".join(_escape(line) for line in lines)


def _row(code: str, spec: MessageSpec) -> str:
    """표 한 줄을 만든다."""
    내부표시 = " ※내부용" if spec.internal else ""
    return (
        f"| `{code}`{내부표시} "
        f"| {_params_cell(spec)} "
        f"| {_escape(spec.template)} "
        f"| {_escape(spec.english)} "
        f"| {_escape(spec.where)} |"
    )


HEADER = """\
# K-TEST 채점 API — 오류·상태 문구 코드표 (백엔드 전달용)

> **이 문서는 손으로 쓰지 않는다.** `assessment/src/scoring/messages.py` 의 카탈로그에서
> `python scripts/export_message_codes.py` 로 뽑아 만든다. 코드를 고치면 다시 돌려 주세요.

## 한눈에 — 무엇이 바뀌었나

우리 채점 API가 내보내던 문구는 전부 한국어였다. 응시자는 외국인 노동자라서 화면에는
영어가 떠야 하는데, 우리가 영어 문장까지 만들어 보내면 문구 하나 고칠 때마다 채점 서버를
다시 배포해야 한다. 그래서 **문장 대신 '코드'와 '값'을 보낸다.**

```json
{"code": "AUDIO_FILE_TOO_LARGE", "params": {"actualMb": 25.3, "maxMb": 20}}
```

백엔드는 이 `code` 로 자기 쪽 영어 문장을 고르고, `params` 값을 그 문장에 끼워 넣는다.
문구를 바꾸고 싶으면 백엔드만 고치면 되고, 나중에 베트남어·네팔어가 늘어도 우리 코드는
그대로다.

### 바뀐 것 세 가지

| 자리 | 어떻게 바뀌었나 |
|---|---|
| HTTP 오류의 `detail` | 글자 하나가 아니라 `{code, params, message}` **묶음**으로 나간다. 401·400·503 전부 같은 모양이다. **모양이 바뀌는 자리는 여기 하나뿐이다.** |
| 응답 본문 | `warnings` 옆에 `notices` 가 **새로 생겼다**. 같은 내용을 코드로 담은 목록이고, 두 목록의 길이와 차례는 언제나 같다. |
| 근거·상태 문구 | `subscores[].note` 옆에 `notice`, `evidence[].comment` 옆에 `notice`, `checklist_results[].note` 옆에 `notice`, `dropped[].detail` 옆에 `notice` 가 생겼다. |

**지금 쓰고 있는 필드는 하나도 모양이 바뀌지 않았다.** 필드를 지우거나 이름을 바꾼 것도
없다. 위 `detail` 하나만 빼면 전부 '더하기'다.

### ★ 새 연동은 `notices` 만 쓰세요 ★

`warnings` · `note` · `comment` · `detail` 에 담긴 **한국어 문장은 호환용으로 남겨 둔 것**이다.
백엔드가 지금 그것을 쓰고 있어서 갑자기 없애면 화면이 깨지기 때문에, 갈아탈 때까지만
같이 내보낸다. 백엔드가 `notices` / `notice` 로 다 옮기고 나면 **이 한국어 문장들은 없앨
예정**이다. 그러니 **새로 붙이는 화면은 처음부터 `notices` 만 보고 만들어 주세요.**
한국어 문장을 화면에 그대로 쓰는 코드를 새로 만들면, 나중에 그 화면부터 깨진다.

### 백엔드가 알아야 할 규칙 네 가지

**1. `message` 는 우리가 만든 한국어 문장이다.**
백엔드가 아직 영어 문장을 안 만든 코드를 만나면 이 값을 대신 띄우면 된다. 아무것도 안
뜨는 것보다는 한국어라도 뜨는 편이 낫다.

**2. 안쪽에 또 코드가 들어 있는 경우가 있다(중첩).**
`[채점 무효] {reason}` 처럼 겉 문구가 안쪽 사유를 감싸는 자리가 있다. 이럴 때 params 에
`reasonNotice` 같은 이름으로 **안쪽 Notice 가 통째로** 들어간다. 겉과 속을 각각 영어로
바꾼 뒤 이어 붙이면 된다.

```json
{"code": "VALIDITY_INVALID_WRAP",
 "params": {"reason": "답안의 한글 비율이 12%로 …",
            "reasonNotice": {"code": "VALIDITY_HANGUL_RATIO",
                             "params": {"ratio": "12%", "threshold": "50%"},
                             "message": "답안의 한글 비율이 12%로 …"}}}
```

params 이름이 `...Notice` 로 끝나면 전부 이 중첩이다.

**3. 한국어를 그대로 두어야 하는 값이 있다.**
`STT_TOO_QUIET` 의 `preview`, `CITATION_DISCARDED_WRAP` 의 `quote`,
`CHECKLIST_EVIDENCE_WRAP` 의 `description` 처럼 **응시자가 실제로 쓴 글이나 문항 원문**이
들어오는 자리는 번역하지 말고 그대로 끼워 넣어야 한다. 응시자의 말을 영어로 바꿔
보여 주면 "나는 그렇게 말하지 않았다"는 이의를 확인할 길이 사라진다.
표의 params 칸에 `str(한국어 그대로)` 라고 적힌 것이 그 자리다.

**4. LLM 이 그때그때 쓴 문장에는 고정 코드가 없다.**
체크리스트 판정 이유처럼 모델이 직접 쓰는 문장은 문구가 정해져 있지 않다. 그런 자리는
`LLM_FREE_TEXT` 코드에 `text` 값으로 원문이 들어온다. 미리 만들어 둔 영어 문장이 없으니
그대로 보여 주거나 그쪽에서 번역해야 한다.

### 내부용 표시

코드 뒤에 `※내부용` 이 붙은 것은 응시자가 아니라 **운영자에게 주는 안내**다
(예: "이 점수는 임시값이니 확정 등급으로 통보하지 말 것"). 응시자 화면에 띄우지 않는다면
영어 문장을 만들 필요가 없다. 그래도 코드는 붙여 두었는데, 그래야 `warnings` 와
`notices` 의 길이가 어긋나지 않기 때문이다.

### 표 읽는 법

- **code** — 백엔드가 영어 문장을 고를 때 쓰는 열쇠
- **params** — 그 문장에 끼워 넣을 값. `키 (타입) 예: 예시값` 꼴로 적었다
- **한국어 원문** — 지금 `message` 로 나가는 문장. `{키}` 자리에 params 값이 들어간다
- **영어 초안** — 우리가 적어 둔 제안. 백엔드가 고쳐 써도 된다
- **어디서 나오는지** — 응답의 어느 자리에 실리는지
"""


def build_markdown() -> str:
    """카탈로그 전체를 마크다운 문서 한 장으로 만든다."""
    parts = [HEADER]

    # 표에 한 번씩만 실리도록, 이미 실은 코드를 기억해 둔다
    실은코드: set[str] = set()
    합계 = len(MESSAGE_CATALOG)
    내부용 = sum(1 for spec in MESSAGE_CATALOG.values() if spec.internal)
    parts.append(
        f"\n**전체 {합계}개** (그중 내부용 {내부용}개는 영어화 대상이 아님)\n"
    )

    for 제목, endpoint in SECTIONS:
        골라낸 = [
            (code, spec)
            for code, spec in MESSAGE_CATALOG.items()
            if spec.endpoint == endpoint and code not in 실은코드
        ]
        if not 골라낸:
            continue
        실은코드.update(code for code, _ in 골라낸)

        parts.append(f"\n---\n\n## {제목} ({len(골라낸)}개)\n")
        parts.append("| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |")
        parts.append("|---|---|---|---|---|")
        parts.extend(_row(code, spec) for code, spec in 골라낸)

    # 어느 칸에도 안 들어간 코드가 있으면 마지막에 몰아 싣는다.
    # 조용히 빠뜨리면 백엔드가 그 코드를 영영 못 보게 된다
    남은것 = [(c, s) for c, s in MESSAGE_CATALOG.items() if c not in 실은코드]
    if 남은것:
        parts.append(f"\n---\n\n## 그 밖 ({len(남은것)}개)\n")
        parts.append("| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |")
        parts.append("|---|---|---|---|---|")
        parts.extend(_row(code, spec) for code, spec in 남은것)

    parts.append("")
    return "\n".join(parts)


def main() -> None:
    """문서를 만들어 파일로 쓰고, 무엇을 썼는지 눈으로 확인할 수 있게 알려 준다."""
    markdown = build_markdown()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(markdown, encoding="utf-8")

    print(f"코드 {len(MESSAGE_CATALOG)}개를 문서로 뽑았다 -> {OUT_PATH}")
    print(f"  줄 수: {markdown.count(chr(10)) + 1}")
    # 엔드포인트별로 몇 개씩 들어갔는지 세어 준다(빠진 칸이 없는지 눈으로 보려는 것)
    세기: dict[str, int] = {}
    for spec in MESSAGE_CATALOG.values():
        세기[spec.endpoint] = 세기.get(spec.endpoint, 0) + 1
    for endpoint, count in sorted(세기.items(), key=lambda kv: -kv[1]):
        print(f"  {endpoint}: {count}개")


if __name__ == "__main__":
    main()
