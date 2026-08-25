# -*- coding: utf-8 -*-
"""'내용 및 과제 수행'을 채점하는 세 가지 방식을 **같은 답안에** 돌려 결과를 쌓는다.

■ 무엇을 비교하나

    A0  LLM 이 0~5 점을 바로 매긴다 (제로샷)
    A1  A0 과 똑같되, 같은 문항의 **학습 겹에서 뽑은 앵커 예시**를 프롬프트에 붙인다
    B   문항별 체크리스트 항목을 하나씩 0/1 로 판정하고, 충족율 × 5 를 점수로 삼는다

C(체크리스트 + 문항별 가중치 학습)는 **B 의 0/1 판정 결과를 그대로 다시 쓴다.**
LLM 을 새로 부르지 않으므로 B 와 C 의 차이는 오직 '0/1 을 점수로 바꾸는 방식'이다.
그래서 C 는 여기서 돌리지 않고 `analyze.py` 가 계산한다.

■ 공정 비교를 위해 못 박은 것

  · 세 방식 모두 **같은 모델(gemini-3.1-flash-lite) · 같은 온도 0 · 같은 JSON 강제**
  · 입력은 음성이 아니라 **사람이 직접 적은 전사**(받아쓰기 오차를 실험에서 걷어낸다)
  · A1 의 앵커는 **학습 겹에서만** 뽑는다. 시험 볼 답안이 프롬프트에 들어가면
    그건 답을 보고 시험 치는 것이다(누출)
  · A0·A1 의 채점 기준 설명(0~5 의 뜻)은 **글자 하나까지 같다**. 둘의 차이는
    앵커가 붙었느냐뿐이어야 한다

■ 중간에 끊겨도 이어서 한다

판정 한 건이 끝날 때마다 결과 파일에 바로 적고, 다시 실행하면 **성공한 줄만**
건너뛴다. 실패로 적힌 줄은 다시 해 보고, 성공하면 그 결과가 이긴다(나중 줄이 이긴다).
무료 등급 한도(429)에 막히면 정중히 멈추고, 된 데까지는 파일에 남는다.

■ 쓰는 법

    python run_experiment.py --pilot                 # 문항 2종 × 답안 10건 파일럿
    python run_experiment.py                         # 본실행 (대상 전체 × A0·A1·B)
    python run_experiment.py --pass-tag rep1 --repro # 재현성용 60건 1회차
    python run_experiment.py --methods A0            # 방식을 골라서
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import (  # noqa: E402
    ASSESSMENT_DIR,
    DEFAULT_RPM,
    JUDGE_MODEL,
    N_FOLDS,
    OUT_DIR,
    CallThrottle,
    append_record,
    assign_folds,
    call_with_retry,
    enable_utf8_output,
    group_by_prompt,
    human_score,
    load_done,
    load_rows,
    make_judge_client,
    print_table,
    prompt_key,
    select_repro_subset,
    use_free_backup_key,
)
from gen_checklists import load_checklists  # noqa: E402

#: 판정 결과를 한 줄씩 쌓는 파일. (답안, 방식, 몇 번째 실행) 하나가 한 줄이다.
DEFAULT_OUT = OUT_DIR / "judgments.jsonl"

#: 이 스크립트가 돌리는 방식들. C 는 B 결과를 다시 쓰므로 여기 없다.
ALL_METHODS = ("A0", "A1", "B")

#: 한 번에 몇 개까지 동시에 부를지. 무료 등급이라 크게 잡지 않는다.
DEFAULT_WORKERS = 3

#: A1 이 프롬프트에 붙일 앵커 예시의 최소·최대 개수.
MIN_ANCHORS, MAX_ANCHORS = 4, 6


# ─────────────────────────────────────────────────────────────────────────────
# A0 · A1 — LLM 이 직접 0~5 를 매기는 방식
# ─────────────────────────────────────────────────────────────────────────────
# 채점 기준 설명. **A0 와 A1 이 이것을 글자 하나까지 똑같이 쓴다.**
# 두 방식의 차이가 '앵커 예시가 붙었느냐'뿐이어야 비교가 성립하기 때문이다.
#
# ※ AI Hub 가 실제로 쓴 채점 기준표는 우리에게 공개돼 있지 않다. 그래서 이 설명은
#   우리가 쓴 것이다. 이 실험이 재는 것은 '기준 문구를 얼마나 잘 맞췄나'가 아니라
#   '같은 기준을 놓고 채점 방식을 바꾸면 어떻게 되나'이므로, 세 방식이 같은 조건이면 된다.
RUBRIC = """\
0점: 과제를 수행하지 않았거나 문항과 관계없는 말을 했다.
1점: 문항과 관련은 있으나 요구된 것을 거의 수행하지 못했다.
2점: 요구된 것 가운데 일부만 수행했고 내용이 매우 빈약하다.
3점: 요구된 것의 핵심은 말했으나 일부가 빠졌거나 설명이 얕다.
4점: 요구된 것을 모두 수행했으나 구체성이나 분량이 다소 아쉽다.
5점: 요구된 것을 빠짐없이 수행했고 내용이 구체적이며 충분히 전개됐다."""

JUDGE_SYSTEM = """\
당신은 한국어 말하기 시험의 '내용 및 과제 수행' 영역 채점자다.
문항이 요구한 내용을 응시자가 말했는지, 과제를 수행했는지만 본다.
발음·억양·속도, 문법·어휘의 정확성은 다른 영역에서 따로 채점하므로 여기서는 보지 않는다.

반드시 지킬 규칙:
1. 점수는 0~5의 정수 하나로만 낸다.
2. quote 필드에는 그렇게 판단한 근거가 되는 부분을 답안 원문에서 그대로 복사해 넣는다.
   한 글자도 바꾸지 않는다. 원문에 없는 문장을 지어내면 안 된다.
3. 반드시 지정된 JSON 형식으로만 답한다."""

JUDGE_USER_TEMPLATE = """\
[채점 기준 — 내용 및 과제 수행]
{rubric}

[문항 지시문]
{prompt_text}
{anchors}
[채점할 답안 전사]
```
{answer_text}
```

다음 JSON 형식으로만 답하라.
{{
  "score": 0에서 5 사이의 정수,
  "quote": "그 점수를 준 근거가 되는 답안 원문의 일부(그대로 복사)",
  "reason": "그렇게 판단한 이유 한 문장"
}}
"""

JUDGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        # 0~5 정수만 받는다. 모델이 "3점" 같은 문자열로 답하는 것을 막는다
        "score": {"type": "integer"},
        "quote": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["score", "quote", "reason"],
}


def pick_anchors(train_rows: list[dict], min_n: int = MIN_ANCHORS,
                 max_n: int = MAX_ANCHORS) -> list[dict]:
    """A1 이 프롬프트에 붙일 앵커 예시를 학습 겹에서 고른다.

    고르는 규칙 (무작위 없이 늘 같은 것이 뽑힌다):
      ① 점수대가 고루 퍼지도록 **점수 값마다 한 건씩** 먼저 가져온다.
         한 점수대만 잔뜩 보여 주면 모델이 그 점수만 따라 찍게 된다.
      ② 그렇게 모아도 4건이 안 되면(그 문항의 학습 겹에 점수 종류가 적을 때)
         점수가 낮은 쪽부터 한 건씩 더 채운다.
      ③ 6건을 넘기지 않는다. 예시가 길어지면 정작 채점할 답안이 묻힌다.

    같은 점수대에서 어느 것을 고를지는 **id 가 가장 앞선 것**으로 정한다.
    '가장 잘 쓴 예'를 고르면 우리가 모델을 유리하게 도와준 것이 되므로 그러지 않는다.
    """
    by_score: dict[int, list[dict]] = {}
    for row in sorted(train_rows, key=lambda r: str(r["id"])):
        by_score.setdefault(human_score(row), []).append(row)

    # ① 점수 값마다 한 건씩
    picked: list[dict] = []
    for score in sorted(by_score):
        picked.append(by_score[score][0])
        if len(picked) >= max_n:
            break

    # ② 모자라면 낮은 점수대부터 두 번째, 세 번째를 더 가져온다
    depth = 1
    while len(picked) < min_n:
        added = False
        for score in sorted(by_score):
            if depth < len(by_score[score]):
                picked.append(by_score[score][depth])
                added = True
                if len(picked) >= max_n:
                    break
        depth += 1
        # 더 가져올 것이 없으면 있는 만큼만 쓴다(문항 표본이 아주 작을 때)
        if not added:
            break

    picked.sort(key=lambda r: (human_score(r), str(r["id"])))
    return picked[:max_n]


def format_anchors(anchors: list[dict]) -> str:
    """앵커 예시를 프롬프트에 넣을 글로 만든다. 앵커가 없으면 빈 글(=A0)."""
    if not anchors:
        return "\n"
    lines = ["\n[같은 문항에 대한 채점 예시 — 전문 평가자가 매긴 점수다]"]
    for i, row in enumerate(anchors, 1):
        lines.append(f"예시 {i} (점수 {human_score(row)}점)")
        lines.append("```")
        lines.append((row.get("ref") or "").strip())
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def build_judge_prompt(answer_text: str, prompt_text: str, anchors: list[dict]) -> str:
    """A0·A1 이 보낼 지시문을 만든다. 앵커 목록이 비면 그것이 곧 A0 이다."""
    return JUDGE_USER_TEMPLATE.format(
        rubric=RUBRIC,
        prompt_text=prompt_text,
        anchors=format_anchors(anchors),
        answer_text=answer_text,
    )


def parse_direct_score(payload: dict, answer_text: str) -> dict:
    """LLM 이 매긴 점수를 받아 정리하고, 근거 인용이 진짜인지 확인한다.

    **점수는 LLM 이 정한 그대로 둔다**(이 방식의 정의가 그렇다). 다만 근거 인용이
    답안 원문에 실제로 있는지는 채점 서버와 같은 검증기로 확인해 기록한다.
    "근거는 못 대지만 점수는 4점" 이 얼마나 자주 나오는지가 이 방식의 약점을 보여 주는
    숫자이므로, 폐기하지 않고 **세어서 남긴다.**
    """
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))
    from src.llm.citation import verify_citation  # 채점 서버의 검증기를 그대로 빌려 쓴다

    raw = payload.get("score")
    try:
        score = int(round(float(raw)))
    except (TypeError, ValueError):
        return {"status": "bad_score", "reason": f"점수를 숫자로 읽지 못했다: {raw!r}"}
    # 범위 밖으로 답하는 경우가 있어 0~5 로 눌러 둔다(눌렀다는 사실은 기록한다)
    clipped = max(0, min(5, score))

    quote = str(payload.get("quote", "")).strip()
    check = verify_citation(answer_text, quote)
    return {
        "status": "ok",
        "pred": clipped,
        "raw_score": score,
        "clipped": clipped != score,
        "quote": quote,
        "citation_ok": bool(check.ok),
        "citation_reason": "" if check.ok else check.reason,
        "citation_start": check.start,
        "citation_end": check.end,
        "rationale": str(payload.get("reason", "")).strip(),
    }


def run_direct(client, row: dict, anchors: list[dict], throttle) -> dict:
    """A0 또는 A1 판정 한 건을 실행한다(앵커가 있으면 A1)."""
    answer_text = (row.get("ref") or "").strip()
    prompt = build_judge_prompt(answer_text, row.get("prompt") or "", anchors)

    result = call_with_retry(
        lambda: client.generate_json(
            prompt, system_instruction=JUDGE_SYSTEM, response_schema=JUDGE_RESPONSE_SCHEMA
        ),
        throttle=throttle,
        label=str(row["id"])[-16:],
    )
    if result["status"] != "ok":
        return {"status": result["status"], "reason": result.get("reason", ""),
                "attempts": result.get("attempts")}

    parsed = parse_direct_score(result["value"], answer_text)
    parsed["elapsed_sec"] = result["elapsed_sec"]
    parsed["attempts"] = result["attempts"]
    parsed["anchor_ids"] = [str(a["id"]) for a in anchors]
    parsed["anchor_scores"] = [human_score(a) for a in anchors]
    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# B — 체크리스트 항목별 0/1 판정
# ─────────────────────────────────────────────────────────────────────────────
def _to_item_info(row: dict, checklist_entry: dict):
    """고정해 둔 체크리스트를 채점 서버가 쓰는 문항 정보 모양으로 옮긴다."""
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))
    from src.scoring.schema import ChecklistItem, ItemInfo

    return ItemInfo(
        item_id=str(row["id"]),
        prompt=row.get("prompt") or "",
        item_type="free_response",
        checklist=[
            ChecklistItem(id=str(it["id"]), description=it["question"], weight=1.0)
            for it in checklist_entry.get("items", [])
        ],
    )


def met_ratio_to_score(met_ratio: float) -> int:
    """충족율(0~1)을 0~5 점으로 바꾼다. 충족율 × 5 를 반올림한다.

    반올림은 **0.5 를 위로** 올린다(2.5 -> 3). 파이썬 기본 `round` 는 2.5 를 2로
    내리는 규칙이라 사람이 기대하는 것과 다르고, 항목이 2개인 문항에서 절반 충족이
    자주 2.5 로 떨어지기 때문에 여기서 규칙을 못 박아 둔다.
    """
    return max(0, min(5, math.floor(met_ratio * 5 + 0.5)))


def run_checklist(client, row: dict, checklist_entry: dict, throttle) -> dict:
    """B 판정 한 건을 실행한다. **인용 검증 규약은 채점 서버의 것을 그대로 빌려 쓴다.**

    `src/features/checklist.py` 에서 세 가지를 읽어다 쓴다(한 줄도 고치지 않는다).
      · SYSTEM_INSTRUCTION / build_prompt — 판정을 시키는 말
      · RESPONSE_SCHEMA                   — 받아야 할 JSON 모양
      · results_from_llm_payload          — **핵심 규약**: 충족(1)이라고 했는데
        근거 인용이 답안 원문에 없으면 그 판정을 폐기하고 미충족(0)으로 내린다

    감싸는 함수(`judge_checklist`)를 쓰지 않고 이 세 조각을 직접 부르는 이유:
    그 함수는 LLM 호출이 실패하면 멈추지 않고 '핵심어 일치'라는 임시 대체 판정으로
    넘어가면서 **실패 원인을 삼켜 버린다.** 그러면 이 실험에서 두 가지가 곤란해진다.
      ① 내용 판정이 아닌 대체값이 성공으로 섞여 들어가 방식 비교가 망가진다
      ② 429 가 '기다리면 풀리는 분당 한도'인지 '오늘 끝'인지 가릴 수 없어
        재시도 판단을 못 한다(8/9 실측: 무료 등급의 벽은 분당 15회였다)
    그래서 호출은 여기서 직접 하고, **판정 규약만** 저쪽 것을 쓴다.
    """
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))
    from src.features.checklist import (
        RESPONSE_SCHEMA,
        SYSTEM_INSTRUCTION,
        build_prompt,
        results_from_llm_payload,
    )

    answer_text = (row.get("ref") or "").strip()
    item = _to_item_info(row, checklist_entry)
    if not item.checklist:
        return {"status": "no_checklist", "reason": "이 문항에 고정된 체크리스트가 없다"}

    prompt = build_prompt(answer_text, item)
    result = call_with_retry(
        lambda: client.generate_json(
            prompt, system_instruction=SYSTEM_INSTRUCTION, response_schema=RESPONSE_SCHEMA
        ),
        throttle=throttle,
        label=str(row["id"])[-16:],
    )
    if result["status"] != "ok":
        return {"status": result["status"], "reason": result.get("reason", ""),
                "attempts": result.get("attempts")}

    # 받은 답을 그대로 믿지 않고 인용 검증을 거쳐 최종 판정으로 바꾼다
    judged, warnings, _notices, dropped = results_from_llm_payload(
        answer_text, item.checklist, result["value"])

    # 항목마다 판정과 **근거 위치**를 함께 남긴다. 점수만 남기면 나중에 따질 수가 없다
    items = []
    for r in judged:
        ev = r.evidence[0] if r.evidence else None
        items.append({
            "cid": r.id,
            "question": r.description,
            "met": int(r.met),
            "quote": getattr(ev, "quote", "") if ev else "",
            "start": getattr(ev, "start", None) if ev else None,
            "end": getattr(ev, "end", None) if ev else None,
            "comment": getattr(ev, "comment", "") if ev else "",
            "note": r.note,
        })

    ratio = sum(i["met"] for i in items) / len(items) if items else 0.0
    return {
        "status": "ok",
        "pred": met_ratio_to_score(ratio),
        "met_ratio": round(ratio, 4),
        "items": items,
        "n_items": len(items),
        "n_met": sum(i["met"] for i in items),
        # 충족이라고 했다가 근거 인용이 가짜라서 미충족으로 내려간 항목 수
        "dropped_citations": dropped,
        "warnings": warnings[:5],
        "elapsed_sec": result["elapsed_sec"],
        "attempts": result["attempts"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────────────────────
def build_tasks(rows, fold_of, methods, pass_tag, done) -> list[dict]:
    """할 일 목록을 만든다. **이미 성공한 것은 뺀다.**

    실패로 적힌 줄은 남겨 둔다 — 그때 운이 나빴을 뿐인 실패를 영영 실패로 굳히면
    한 번의 장애 때문에 표본이 계속 줄어든 채로 남는다.
    """
    tasks = []
    for row in rows:
        rid = str(row["id"])
        for method in methods:
            if (done.get((rid, method, pass_tag)) or {}).get("status") == "ok":
                continue
            tasks.append({"row": row, "method": method,
                          "fold": fold_of[rid], "pass_tag": pass_tag})
    return tasks


def run_all(rows, fold_of, checklists, methods, pass_tag, out_path,
            workers: int, rpm: int = DEFAULT_RPM) -> dict:
    """할 일을 겹쳐서 돌리고 한 건씩 파일에 적는다.

    **동시에 여러 개를 보내도 결과는 달라지지 않는다** — 판정은 답안 하나만 보고
    그 답안의 결과를 낸다. 옆 항목의 결과를 참고하지도, 처리 순서를 보지도 않는다.
    대부분이 '남의 서버가 답할 때까지 기다리는' 시간이라 겹쳐 두면 그만큼 빨라진다.
    """
    client = make_judge_client()
    # 무료 등급의 벽은 '분당 몇 번'이다. 부딪히고 물러서지 않고 처음부터 그 속도로 간다
    throttle = CallThrottle(workers, rpm=rpm)
    done = load_done(out_path)
    tasks = build_tasks(rows, fold_of, methods, pass_tag, done)

    # A1 은 문항·겹마다 앵커가 정해진다. 같은 (문항, 겹) 은 늘 같은 앵커를 쓴다
    by_prompt = group_by_prompt(rows)
    anchor_cache: dict[tuple[str, int], list[dict]] = {}

    def anchors_for(row: dict) -> list[dict]:
        pkey = prompt_key(row.get("prompt") or "")
        fold = fold_of[str(row["id"])]
        key = (pkey, fold)
        if key not in anchor_cache:
            # **학습 겹에서만** 뽑는다. 시험 볼 답안이 프롬프트에 들어가면 누출이다
            train = [r for r in by_prompt[pkey] if fold_of[str(r["id"])] != fold]
            anchor_cache[key] = pick_anchors(train)
        return anchor_cache[key]

    total = len(tasks)
    print(f"\n=== [{pass_tag}] 할 일 {total}건 "
          f"(답안 {len(rows)}건 × 방식 {len(methods)}종, 이미 끝난 것 제외) ===")
    if not total:
        return {"total": 0, "ok": 0, "failed": 0, "stopped": False, "elapsed": 0.0}

    counters = {"ok": 0, "failed": 0, "skipped_quota": 0}
    started = time.perf_counter()

    def one(index: int, task: dict) -> None:
        row, method = task["row"], task["method"]
        rid = str(row["id"])
        base = {
            "id": rid,
            "method": method,
            "pass": task["pass_tag"],
            "prompt_key": prompt_key(row.get("prompt") or ""),
            "speaker_id": str(row.get("speaker_id") or rid.split("-")[0]),
            "nationality": row.get("nationality"),
            "topik_level": row.get("topik_level"),
            "fold": task["fold"],
            "human_score": human_score(row),
            "answer_chars": len(row.get("ref") or ""),
            "model": JUDGE_MODEL,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        if method in ("A0", "A1"):
            anchors = anchors_for(row) if method == "A1" else []
            outcome = run_direct(client, row, anchors, throttle)
        else:
            entry = checklists.get(base["prompt_key"], {})
            outcome = run_checklist(client, row, entry, throttle)

        # 한도가 바닥나 물러난 경우에는 **아무것도 적지 않는다.**
        # 실패로 적어 두면 그것도 결과처럼 보이는데, 사실은 시도조차 못 한 것이다
        if outcome["status"] == "quota_stopped":
            counters["skipped_quota"] += 1
            return

        record = {**base, **outcome}
        append_record(out_path, record)
        if outcome["status"] == "ok":
            counters["ok"] += 1
            extra = (f"충족 {outcome['n_met']}/{outcome['n_items']}"
                     if method == "B" else
                     ("근거O" if outcome.get("citation_ok") else "근거X"))
            print(f"   [{index:4d}/{total}] {method} {rid[-16:]} "
                  f"예측 {outcome['pred']} · 사람 {base['human_score']} · {extra}")
        else:
            counters["failed"] += 1
            print(f"   [{index:4d}/{total}] {method} {rid[-16:]} "
                  f"실패({outcome['status']}): {str(outcome.get('reason'))[:70]}")

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-cl") as pool:
        futures = []
        for i, task in enumerate(tasks, 1):
            if throttle.stopped:
                print(f"   [{i:4d}/{total}] 이후 {total - i + 1}건은 손대지 않고 남긴다")
                counters["skipped_quota"] += total - i + 1
                break
            futures.append(pool.submit(one, i, task))
        for fut in futures:
            try:
                fut.result()
            except Exception as exc:
                print(f"   일꾼에서 예외: {type(exc).__name__}: {str(exc)[:150]}")

    elapsed = time.perf_counter() - started
    print(f"\n   [{pass_tag}] {total}건 시도 · 성공 {counters['ok']} · 실패 {counters['failed']}"
          f" · 한도로 보류 {counters['skipped_quota']}"
          f" · {elapsed:.0f}초 (건당 평균 {elapsed / max(1, total):.1f}초)"
          f" · 분당 한도 대기 {throttle.rate_waits}회")
    if throttle.stopped:
        print(f"\n   ※ {throttle.stop_reason}\n"
              "     여기까지 된 것은 파일에 적혀 있다. 같은 명령을 다시 실행하면 이어서 한다.")

    return {"total": total, "elapsed": round(elapsed, 1),
            "stopped": throttle.stopped, "stop_reason": throttle.stop_reason, **counters}


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="내용·과제 수행 채점 방식 3종을 실제 데이터에 돌린다")
    ap.add_argument("--methods", default=",".join(ALL_METHODS),
                    help=f"쉼표로 구분한 방식 이름. 기본 {','.join(ALL_METHODS)}")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--pass-tag", default="main",
                    help="이번 실행의 이름표. 재현성 실행은 rep1·rep2·rep3 로 준다")
    ap.add_argument("--repro", action="store_true",
                    help="재현성용 고정 부분표본(60건)만 돌린다")
    ap.add_argument("--repro-n", type=int, default=60)
    ap.add_argument("--pilot", action="store_true",
                    help="파일럿: 문항 2종 × 답안 10건만 돌려 형식·시간을 확인한다")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help=f"동시에 보낼 호출 수. 기본 {DEFAULT_WORKERS}(무료 등급이라 작게)")
    ap.add_argument("--rpm", type=int, default=DEFAULT_RPM,
                    help=f"1분에 몇 번까지 부를지. 기본 {DEFAULT_RPM} "
                         "(무료 등급의 실제 벽은 분당 15회다)")
    args = ap.parse_args()

    print(use_free_backup_key())
    print(f"판정 모델: {JUDGE_MODEL} (세 방식 모두 같은 모델·온도 0) · "
          f"분당 {args.rpm}회 · 동시 {args.workers}개")

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = [m for m in methods if m not in ALL_METHODS]
    if unknown:
        print(f"모르는 방식: {', '.join(unknown)} (쓸 수 있는 것: {', '.join(ALL_METHODS)})")
        return 1

    # ── 표본과 겹 ────────────────────────────────────────────────────────────
    rows, counts = load_rows()
    print("\n=== 표본 고르기 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])

    # 겹은 **언제나 전체 표본에서** 정한다. 파일럿이나 재현성 실행이라고 해서
    # 겹이 달라지면 그 결과를 본실행과 나란히 놓을 수 없다
    fold_of, diag = assign_folds(rows, N_FOLDS)
    print(f"\n겹 나누기: 화자 단위 {N_FOLDS}겹 · 겹을 넘나든 화자 {diag['speaker_leak_count']}명"
          f" · 빈 칸 {len(diag['prompts_with_empty_fold'])}개"
          f" · 어느 문항·겹에서든 학습 표본 최소 {diag['min_train_rows_in_any_prompt_fold']}건")
    if not diag["usable"]:
        print("  ※ 겹 나누기가 문항 안에서 성립하지 않는다. analyze.py 가 LOO 로 바꿔 계산한다.")

    if args.repro:
        rows = select_repro_subset(rows, args.repro_n)
        print(f"재현성용 고정 부분표본: {len(rows)}건 "
              f"(문항 {len({prompt_key(r['prompt']) for r in rows})}종)")
    elif args.pilot:
        buckets = group_by_prompt(rows)
        picked = []
        for pkey in list(buckets)[:2]:
            picked.extend(buckets[pkey][:10])
        rows = sorted(picked, key=lambda r: str(r["id"]))
        print(f"파일럿 표본: {len(rows)}건 (문항 2종 × 10건)")

    # ── 체크리스트 확인 ──────────────────────────────────────────────────────
    checklists = load_checklists()
    if "B" in methods:
        need = {prompt_key(r.get("prompt") or "") for r in rows}
        missing = [p for p in sorted(need)
                   if checklists.get(p, {}).get("status") != "ok"]
        if missing:
            print(f"\n[중단] 체크리스트가 없는 문항 {len(missing)}종: {', '.join(missing)}\n"
                  "  먼저 gen_checklists.py 를 돌려 체크리스트를 고정하라.")
            return 1
        print(f"체크리스트: 문항 {len(need)}종 · 항목 "
              f"{sum(len(checklists[p]['items']) for p in need)}개 (고정본을 읽기만 한다)")

    summary = run_all(rows, fold_of, checklists, methods, args.pass_tag,
                      args.out, args.workers, args.rpm)
    print(f"\n결과 파일: {args.out}")
    if summary.get("stopped"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
