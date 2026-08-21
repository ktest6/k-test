# -*- coding: utf-8 -*-
"""문항마다 '내용 및 과제 수행' 이진 체크리스트를 **한 번 만들어 파일로 고정**한다.

■ 왜 한 번만 만들어 고정하는가

이 프로젝트의 양보 불가 원칙 중 하나가 **응시자별 실시간 생성 금지**다
(`PLAN.md` 트랙 B 원칙 ①). 응시자마다 체크리스트를 새로 만들면 사람마다 다른 잣대로
채점하는 셈이 되어 표준화 시험이 성립하지 않는다. 그래서 체크리스트는
**시험 전에 문항당 한 벌만** 만들어 `checklists.json` 에 박아 두고,
채점할 때는 그 파일을 읽기만 한다.

이 실험에서도 같다. B(충족율)와 C(가중치 학습)는 **똑같은 이 한 벌**을 쓴다.
그래야 두 방식의 차이가 오직 '결합 방식'에서만 나온다.

■ 생성 프롬프트는 팀원이 쓴 원문을 한 글자도 바꾸지 않았다

아래 `TEAM_PROMPT` 가 그것이다. 다만 **받는 형식만** 손댔다 — 원문은 "JSON 배열만
출력"을 요구하는데, 채점 서버의 LLM 래퍼(`src/llm/client.py`)는 최상위가 JSON 객체가
아니면 응답을 폐기하도록 만들어져 있다. src 를 고치지 않기로 했으므로,
응답 형식표(response_schema)로 배열을 `{"checklist": [...]}` 안에 담게 했다.
**항목의 내용(question·category·required)은 원문이 지정한 그대로다.**

■ 쓰는 법

    python gen_checklists.py                # 대상 문항 전부 생성(이미 있으면 건너뜀)
    python gen_checklists.py --force        # 이미 있어도 다시 생성
    python gen_checklists.py --repro 3      # 문항 3종 × 3회 생성해 재현성만 확인
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
    prompt_key,
    use_free_backup_key,
)

#: 체크리스트를 고정해 두는 파일. 뒤의 모든 실험이 이 파일만 읽는다.
CHECKLIST_PATH = OUT_DIR / "checklists.json"
#: 생성 자체의 재현성을 확인한 기록.
REPRO_PATH = OUT_DIR / "checklist_gen_repro.json"

# ─────────────────────────────────────────────────────────────────────────────
# 팀원이 쓴 생성 프롬프트 원문. **한 글자도 바꾸지 않는다.**
# 문항 지시문이 들어갈 자리만 {prompt_text} 로 남아 있고, 그 자리를 치환해서 보낸다.
# ─────────────────────────────────────────────────────────────────────────────
TEAM_PROMPT = """당신은 한국어 말하기 시험의 문항 검토 전문가입니다.
아래 문항에 대해, 응시자 응답의 "내용 및 과제 수행"만을 평가하는
이진 체크리스트를 작성하세요.

문항 지시문
{prompt_text}

작성 규칙
각 항목은 '예/아니오'로만 답할 수 있어야 하며, '예'가 항상 더 좋은 응답을 뜻해야 합니다.
한 항목은 한 가지만 물어야 합니다.(예: "위치와 이유를 말했는가"는 두 항목으로 분리)
응답 전사 텍스트만 보고 판정할 수 있어야 합니다.
발음·억양·속도에 대한 항목, 문법·어휘의 정확성에 대한 항목은 만들지 마십시오.
그 영역은 별도의 자질이 담당하므로 중복 평가가 됩니다.
개수를 채우지 마십시오. 최대 5개이되, 과제 완수에 꼭 필요한 것만 만드십시오.
2개로 충분한 문항이면 2개만 출력하십시오.
억지로 만든 유사 항목이나 자명한 항목은 없는 것만 못합니다.
난이도를 섞으십시오. 최소한을 말한 응답도 통과할 수 있는 항목과,
과제를 충실히 수행한 응답만 통과하는 항목이 함께 있어야 합니다.
각 항목에 다음을 표기하십시오.
category: "정보전달"(요구된 정보를 말했는가) |"행위수행"(요구된 말하기 행위를 수행했는가) |"상황판단"(상황·상대에 맞게 판단했는가) 중 하나
required: true(이 항목이 충족되지 않으면 과제 실패) | false

출력 형식 (JSON 배열만 출력. 설명 문장 금지)
[
  {"id": 1, "question": "...", "category": "정보전달", "required": true},
  {"id": 2, "question": "...", "category": "행위수행", "required": false}
]"""

# 위 원문이 요구하는 배열을 객체 한 겹으로 감싸 받기 위한 형식표.
# (이유는 이 파일 맨 위 설명 참고 — src 를 고치지 않기 위한 실험실 쪽 조치다)
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "checklist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "question": {"type": "string"},
                    "category": {"type": "string"},
                    "required": {"type": "boolean"},
                },
                "required": ["id", "question", "category", "required"],
            },
        },
    },
    "required": ["checklist"],
}

#: 원문이 정한 세 갈래. 이 밖의 값이 오면 그대로 적어 두되 표시를 남긴다.
VALID_CATEGORIES = ("정보전달", "행위수행", "상황판단")

#: 원문이 정한 상한. 넘겨 보내면 앞에서부터 잘라 쓴다.
MAX_ITEMS = 5


def build_generation_prompt(prompt_text: str) -> str:
    """문항 지시문을 원문 프롬프트의 제자리에 끼워 넣는다.

    `.format()` 을 쓰지 않고 문자열 치환을 쓰는 이유: 원문 마지막의 출력 예시에
    중괄호가 그대로 들어 있어서 `.format()` 을 쓰면 그 부분이 깨진다.
    """
    return TEAM_PROMPT.replace("{prompt_text}", prompt_text)


def normalize_items(payload: dict) -> tuple[list[dict], list[str]]:
    """LLM이 준 체크리스트를 쓸 수 있는 모양으로 다듬고, 이상한 점을 적어 둔다.

    다듬는 것 네 가지.
      ① 항목 번호(id)를 문자열로 통일한다 — 뒤의 판정 결과와 짝지을 열쇠가 된다
      ② 질문이 비어 있는 항목은 버린다(판정할 수 없다)
      ③ 원문이 정한 세 갈래 밖의 category 는 그대로 두되 경고로 남긴다
      ④ 5개를 넘으면 앞에서부터 5개만 쓴다(원문이 정한 상한)

    돌려주는 값은 (항목 목록, 경고 목록)이다. 경고는 버리지 않고 파일에 함께 적는다 —
    나중에 "이 체크리스트가 어떻게 만들어졌나"를 따질 수 있어야 하기 때문이다.
    """
    warnings: list[str] = []
    raw = payload.get("checklist")
    if not isinstance(raw, list):
        return [], ["응답에 checklist 배열이 없다"]

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
        required_raw = entry.get("required", False)
        required = str(required_raw).strip().lower() in ("true", "1", "yes")
        items.append({
            "id": str(entry.get("id", len(items) + 1)),
            "question": question,
            "category": category,
            "required": required,
        })

    if len(items) > MAX_ITEMS:
        warnings.append(f"항목이 {len(items)}개로 상한({MAX_ITEMS})을 넘어 앞에서 잘라 썼다")
        items = items[:MAX_ITEMS]
    if not items:
        warnings.append("쓸 수 있는 항목이 하나도 남지 않았다")
    return items, warnings


def generate_one(client, prompt_text: str) -> dict:
    """문항 하나에 대한 체크리스트를 한 번 생성한다.

    돌려주는 값에는 항목뿐 아니라 **어떤 조건에서 만들었는지**(모델·걸린 시간·경고)를
    함께 담는다. 나중에 이 체크리스트로 매긴 점수를 따질 때 필요한 정보다.
    """
    prompt = build_generation_prompt(prompt_text)
    result = call_with_retry(
        lambda: client.generate_json(prompt, response_schema=RESPONSE_SCHEMA),
        label="체크리스트 생성",
    )
    if result["status"] != "ok":
        return {"status": result["status"], "reason": result.get("reason", ""), "items": []}

    items, warnings = normalize_items(result["value"])
    return {
        "status": "ok" if items else "empty",
        "items": items,
        "warnings": warnings,
        "model": client.model_name,
        "elapsed_sec": result["elapsed_sec"],
        "attempts": result["attempts"],
    }


def load_checklists(path: Path = CHECKLIST_PATH) -> dict:
    """고정해 둔 체크리스트 파일을 읽는다. 없으면 빈 것을 돌려준다."""
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_checklists(data: dict, path: Path = CHECKLIST_PATH) -> None:
    """체크리스트를 파일에 고정한다. 사람이 눈으로 검수할 수 있게 들여쓰기해 둔다."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_generate(force: bool) -> int:
    """대상 문항 전부에 대해 체크리스트를 만들어 파일에 고정한다."""
    rows, counts = load_rows()
    buckets = group_by_prompt(rows)
    print("=== 대상 고르기 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])

    client = make_judge_client()
    if not client.available:
        print("\n[중단] GEMINI_API_KEY 가 없다. assessment/.env 를 확인하라.")
        return 1

    existing = load_checklists()
    made, skipped, failed = 0, 0, 0

    for pkey, items in buckets.items():
        prompt_text = items[0].get("prompt") or ""
        # 이미 만들어 둔 것이 있으면 건드리지 않는다.
        # 체크리스트가 실행마다 바뀌면 앞서 매긴 점수와 견줄 수 없게 된다
        if not force and existing.get(pkey, {}).get("status") == "ok":
            skipped += 1
            continue

        print(f"\n── [{pkey}] {prompt_text[:44]} (답안 {len(items)}건)")
        result = generate_one(client, prompt_text)
        if result["status"] != "ok":
            failed += 1
            print(f"   실패({result['status']}): {str(result.get('reason'))[:80]}")
            existing[pkey] = {"prompt_key": pkey, "prompt": prompt_text, **result}
            continue

        made += 1
        existing[pkey] = {
            "prompt_key": pkey,
            "prompt": prompt_text,
            "n_answers": len(items),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            **result,
        }
        for it in result["items"]:
            mark = "필수" if it["required"] else "선택"
            print(f"   {it['id']}. [{it['category']}/{mark}] {it['question']}")
        if result["warnings"]:
            print(f"   경고: {'; '.join(result['warnings'])}")
        # 한 문항이 끝날 때마다 저장한다 — 중간에 끊겨도 앞의 것이 살아남는다
        save_checklists(existing)

    save_checklists(existing)
    print(f"\n=== 생성 {made}문항 · 건너뜀 {skipped}문항 · 실패 {failed}문항 ===")
    print(f"저장: {CHECKLIST_PATH}")

    ok_items = [len(v.get("items", [])) for v in existing.values() if v.get("status") == "ok"]
    if ok_items:
        print(f"항목 수: 총 {sum(ok_items)}개 / 문항당 평균 "
              f"{sum(ok_items) / len(ok_items):.1f}개 (최소 {min(ok_items)} · 최대 {max(ok_items)})")
    return 0 if failed == 0 else 1


def run_repro(n_prompts: int, n_runs: int = 3) -> int:
    """체크리스트 **생성 자체**가 얼마나 흔들리는지 몇 문항만 여러 번 만들어 본다.

    주의해서 읽어야 할 구분이 있다. 본 실험은 **고정된 체크리스트 한 벌**만 쓰므로
    여기서 나온 흔들림은 **점수에 전혀 영향을 주지 않는다.**
    이 숫자가 말해 주는 것은 "지금 이 체크리스트를 다시 만들면 같은 것이 나오는가",
    즉 문항을 새로 준비할 때 관리자 검수가 얼마나 필요한가다.
    """
    rows, _ = load_rows()
    buckets = group_by_prompt(rows)
    targets = list(buckets.items())[:n_prompts]

    client = make_judge_client()
    if not client.available:
        print("[중단] GEMINI_API_KEY 가 없다.")
        return 1

    report = {"model": client.model_name, "n_runs": n_runs, "prompts": {}}
    table_rows = []

    for pkey, items in targets:
        prompt_text = items[0].get("prompt") or ""
        print(f"\n── [{pkey}] {prompt_text[:44]}")
        runs = []
        for r in range(1, n_runs + 1):
            result = generate_one(client, prompt_text)
            questions = [it["question"] for it in result.get("items", [])]
            runs.append({"run": r, "status": result["status"], "questions": questions,
                         "n_items": len(questions)})
            print(f"   {r}회차: 항목 {len(questions)}개 — "
                  f"{' / '.join(q[:24] for q in questions)}")

        counts_ = {r["n_items"] for r in runs}
        # 문구가 완전히 같은지: 항목 문구를 정렬해 붙인 것이 세 번 다 같은가
        signatures = {tuple(sorted(r["questions"])) for r in runs}
        report["prompts"][pkey] = {
            "prompt": prompt_text,
            "runs": runs,
            "item_count_same": len(counts_) == 1,
            "wording_identical": len(signatures) == 1,
        }
        table_rows.append([
            pkey,
            prompt_text[:24],
            ",".join(str(r["n_items"]) for r in runs),
            "같음" if len(counts_) == 1 else "다름",
            "같음" if len(signatures) == 1 else "다름",
        ])

    print("\n=== 체크리스트 '생성'의 재현성 (본 실험 점수와는 무관 — 고정본 1벌을 쓰므로) ===")
    print_table(["문항", "지시문", "회차별 항목 수", "항목 수", "문구"], table_rows)

    Path(REPRO_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(REPRO_PATH).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {REPRO_PATH}")
    return 0


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="문항별 체크리스트를 만들어 파일로 고정한다")
    ap.add_argument("--force", action="store_true",
                    help="이미 만들어 둔 문항도 다시 생성한다(점수 비교가 깨지므로 평소엔 쓰지 않는다)")
    ap.add_argument("--repro", type=int, default=0, metavar="문항수",
                    help="이 개수만큼의 문항을 3회씩 생성해 생성 재현성만 확인하고 끝낸다")
    args = ap.parse_args()

    print(use_free_backup_key())
    print(f"판정·생성 모델: {JUDGE_MODEL}\n")

    if args.repro:
        return run_repro(args.repro)
    return run_generate(args.force)


if __name__ == "__main__":
    raise SystemExit(main())
