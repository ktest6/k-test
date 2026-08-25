# -*- coding: utf-8 -*-
"""체크리스트 v2 로 같은 답안 281건을 **두 갈래로 따로** 판정한다.

■ 두 갈래

    B2  이진 패스  — 항목마다 충족(1)/미충족(0) + 근거 인용. v1 의 B 와 **같은 규약**이다.
    S2  점수 패스  — 항목마다 **0~100 점** + 근거 인용. 논문의 flexible scoring 이다.

두 패스는 **각각 독립된 호출**로 돈다. 한 번 불러서 0/1 과 0~100 을 같이 받게 하면
둘이 서로를 보고 맞춰 버려서(예: 0/1 을 먼저 정하고 거기에 점수를 끼워 맞춤)
"이진과 점수 중 무엇이 나은가"라는 질문 자체가 성립하지 않는다.

■ 논문과 다른 점 — 반드시 함께 읽어야 하는 각주

논문(RLCF, arXiv 2507.18624v2)의 flexible scoring 은 항목마다 **25회 샘플링해 평균**을
낸다. 우리는 **온도 0 · 1회 호출**이다. 따라서
  · 우리 0~100 값은 논문의 기댓값이 아니라 한 번 뽑은 값이다
  · 논문이 25회 평균으로 얻는 '부드러운 점수'의 이점이 우리 조건에서는 줄어든다
이 차이는 결과 JSON 의 `differences_from_paper` 에도 적는다.

■ 공정 규칙 (앞 실험과 똑같이 유지한다)

  · 같은 답안 281건 · 같은 화자 단위 5겹 · 같은 사람 점수(evals.content)
  · 같은 모델 gemini-3.1-flash-lite · 온도 0 · JSON 강제
  · 입력은 음성이 아니라 사람이 직접 적은 전사(ref)
  · 인용 검증 규약도 v1 과 같다 — **원문에 없는 인용으로 받은 충족·득점은 폐기한다**

■ 기존 실험 도구는 건드리지 않는다

`run_experiment.py` 는 8/9 실험의 재현 도구라 한 줄도 고치지 않았다. 결과도 다른
파일(`judgments_v2.jsonl`)에 쌓아서 v1 결과를 덮을 수 없게 했다.

■ 쓰는 법

    python run_experiment_v2.py --pilot                  # 문항 2종 × 답안 10건 파일럿
    python run_experiment_v2.py                          # 본실행 (대상 전체 × B2·S2)
    python run_experiment_v2.py --pass-tag rep1 --repro  # 재현성용 60건 1회차
    python run_experiment_v2.py --methods S2             # 갈래를 골라서
"""

from __future__ import annotations

import argparse
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
from gen_checklists_v2 import load_checklists_v2  # noqa: E402
from run_experiment import met_ratio_to_score  # noqa: E402  (v1 의 반올림 규칙을 그대로 쓴다)

#: v2 판정 결과를 한 줄씩 쌓는 파일. v1 결과와 **다른 파일**이다.
DEFAULT_OUT_V2 = OUT_DIR / "judgments_v2.jsonl"

#: 이 스크립트가 돌리는 갈래.
ALL_METHODS_V2 = ("B2", "S2")

#: 한 번에 몇 개까지 동시에 부를지.
DEFAULT_WORKERS = 3


# ─────────────────────────────────────────────────────────────────────────────
# S2 — 항목마다 0~100 점 (논문의 flexible scoring)
# ─────────────────────────────────────────────────────────────────────────────
# 이진 패스(B2)가 쓰는 지시문은 `src/features/checklist.py` 의 것을 그대로 빌려 쓴다.
# 아래 점수 패스 지시문은 그것과 **같은 뼈대**로 짰다. 두 패스의 차이가 오직
# "0/1 이냐 0~100 이냐"여야 비교가 성립하기 때문이다.
SCORE_SYSTEM_INSTRUCTION = """\
당신은 한국어 시험 답안이 문항의 요구 사항을 충족했는지 확인하는 판정 도구다.
전체 점수를 매기지 않는다. 각 항목에 대해 **얼마나 충족했는지를 0~100 으로만** 답한다.

점수의 뜻:
  0   전혀 충족하지 않았다
  50  절반쯤 충족했다(말은 했으나 얕거나 일부만 다뤘다)
  100 완전히 충족했다

반드시 지킬 규칙:
1. 1점 이상을 주면 quote 필드에 답안 원문의 해당 부분을 그대로 복사해 넣는다.
   한 글자도 바꾸지 않는다. 원문에 없는 문장을 지어내면 그 판정은 폐기되어 0점 처리된다.
2. 답안에 근거가 없으면 주저 없이 0으로 판정한다. 너그럽게 봐주지 않는다.
3. 문법이 틀렸어도 내용을 전달했으면 점수를 준다. 문법은 다른 곳에서 따로 채점한다.
4. 항목마다 따로 판단한다. 다른 항목의 점수에 맞추려 하지 않는다.
5. 반드시 지정된 JSON 형식으로만 답한다.
"""

SCORE_USER_TEMPLATE = """\
[문항 지시문]
{item_prompt}

[답안 원문]
```
{answer_text}
```

[확인할 항목]
{checklist_text}

다음 JSON 형식으로만 답하라. 항목은 하나도 빠뜨리지 마라.
{{
  "results": [
    {{
      "id": "항목 id",
      "score": 0에서 100 사이의 정수,
      "quote": "1점 이상이면 답안 원문에서 그대로 복사한 근거 부분, 0점이면 빈 문자열",
      "reason": "그렇게 판정한 이유 한 문장"
    }}
  ]
}}
"""

SCORE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    # 0~100 정수만 받는다. 모델이 "80점" 같은 문자열로 답하는 것을 막는다
                    "score": {"type": "integer"},
                    "quote": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "score", "quote", "reason"],
            },
        },
    },
    "required": ["results"],
}


def build_score_prompt(answer_text: str, prompt_text: str, items: list[dict]) -> str:
    """점수 패스에 보낼 지시문을 만든다.

    항목마다 id 를 붙여서 보낸다. 그래야 돌아온 판정을 어느 항목의 것인지 짝지을 수 있다
    (이진 패스가 쓰는 `src/features/checklist.py` 의 방식과 같다).
    """
    checklist_text = "\n".join(f"- id={it['id']}: {it['question']}" for it in items)
    return SCORE_USER_TEMPLATE.format(
        item_prompt=prompt_text or "(지시문 없음)",
        answer_text=answer_text,
        checklist_text=checklist_text or "(항목 없음)",
    )


def score_results_from_payload(answer_text: str, items: list[dict], payload: dict):
    """점수 패스의 응답을 검증해서 최종 항목별 점수로 바꾼다.

    **핵심 규약은 이진 패스와 같다** — 근거 인용이 원문에 없으면 그 득점을 폐기한다.
    이진에서는 충족(1)을 0으로 내렸으니, 여기서는 **1점 이상을 0점으로 내린다.**
    "근거는 못 대지만 70점" 을 남겨 두면 v1 에서 막아 둔 구멍을 v2 에서 다시 여는 셈이다.

    폐기 전 점수(raw)도 함께 남긴다. 나중에 "이 규약이 점수를 얼마나 깎았나"를
    따로 따질 수 있어야 하기 때문이다.

    돌려주는 값은 (항목별 결과, 경고, 폐기 건수)다.
    """
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))
    from src.llm.citation import verify_citation  # 채점 서버의 검증기를 그대로 빌려 쓴다

    warnings: list[str] = []
    dropped = 0

    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raw_results = []
        warnings.append("LLM 응답에 results 목록이 없어 전 항목을 0점으로 처리했다.")

    # LLM 이 항목 순서를 바꿔 보낼 수 있으므로 id 로 찾아 쓸 수 있게 정리해 둔다
    by_id = {str(r.get("id")): r for r in raw_results if isinstance(r, dict)}

    final: list[dict] = []
    for it in items:
        cid = str(it["id"])
        raw = by_id.get(cid)

        # 판정하지 않은 항목은 '모르니까 만점'이 아니라 0점으로 본다(이진 패스와 같은 처리)
        if raw is None:
            warnings.append(f"항목 '{cid}' 에 대한 LLM 판정이 없어 0점으로 처리했다.")
            final.append({"cid": cid, "question": it["question"], "score": 0,
                          "raw_score": None, "quote": "", "start": None, "end": None,
                          "citation_ok": False, "reason": "", "note": "LLM 응답 누락"})
            continue

        try:
            value = int(round(float(raw.get("score"))))
        except (TypeError, ValueError):
            warnings.append(f"항목 '{cid}': 점수를 숫자로 읽지 못해 0점으로 뒀다 "
                            f"({raw.get('score')!r})")
            value = 0
        # 범위 밖으로 답하는 경우가 있어 0~100 으로 눌러 둔다
        clipped = max(0, min(100, value))
        quote = str(raw.get("quote", "")).strip()
        reason = str(raw.get("reason", "")).strip()

        # 0점은 인용이 필요 없다. 없는 것을 인용할 수는 없기 때문이다
        if clipped == 0:
            final.append({"cid": cid, "question": it["question"], "score": 0,
                          "raw_score": value, "quote": "", "start": None, "end": None,
                          "citation_ok": False, "reason": reason, "note": ""})
            continue

        check = verify_citation(answer_text, quote)
        if not check.ok:
            dropped += 1
            warnings.append(f"항목 '{cid}': {clipped}점의 근거 인용이 원문에 없어 폐기하고 "
                            f"0점으로 내렸다 — {check.reason}")
            final.append({"cid": cid, "question": it["question"], "score": 0,
                          "raw_score": clipped, "quote": "", "start": None, "end": None,
                          "citation_ok": False, "reason": reason,
                          "note": "근거 인용 폐기로 0점 처리", "discarded_quote": quote})
            continue

        # 검증을 통과한 득점. 근거에는 LLM 이 적어 준 문자열이 아니라
        # 원문에서 실제로 잘라낸 구간과 그 위치를 담는다
        final.append({"cid": cid, "question": it["question"], "score": clipped,
                      "raw_score": value, "quote": check.matched_text,
                      "start": check.start, "end": check.end,
                      "citation_ok": True, "reason": reason, "note": ""})

    return final, warnings, dropped


def weighted_mean_0to100(results: list[dict], items: list[dict]) -> float:
    """항목별 0~100 점을 **중요도로 가중 평균**한다(논문 방식). 0~1 로 돌려준다.

    중요도 합이 0이면 나눌 수 없으므로 그때만 단순 평균으로 물러난다
    (생성 단계에서 이미 막아 두었지만, 옛 파일을 읽을 때를 대비한 안전장치다).
    """
    weights = {str(it["id"]): float(it.get("importance", 50)) for it in items}
    total = sum(weights.get(r["cid"], 0.0) for r in results)
    if total <= 0:
        return (sum(r["score"] for r in results) / len(results) / 100.0) if results else 0.0
    return sum(weights.get(r["cid"], 0.0) * r["score"] for r in results) / total / 100.0


def ratio_to_score(ratio: float) -> int:
    """0~1 비율을 0~5 점으로 바꾼다. 비율 × 5 를 반올림한다(0.5 는 위로).

    계산을 여기서 새로 적지 않고 **v1 의 함수를 그대로 부른다.** 규칙이 조금이라도
    달라지면 v1·v2 비교가 '결합 규칙 차이'로 오염되기 때문이다.
    """
    return met_ratio_to_score(ratio)


# ─────────────────────────────────────────────────────────────────────────────
# B2 — 항목별 0/1 (v1 의 B 와 같은 규약)
# ─────────────────────────────────────────────────────────────────────────────
def _to_item_info(row: dict, entry: dict):
    """고정해 둔 v2 체크리스트를 채점 서버가 쓰는 문항 정보 모양으로 옮긴다.

    weight 에 중요도를 넣지 않고 1.0 으로 둔다. 프롬프트에는 weight 가 나가지 않지만,
    **판정 단계에서는 항목의 경중을 모르는 편이 옳다** — 중요도는 점수를 만들 때 쓰는
    것이지, "이 항목을 충족했는가"라는 사실 판정을 좌우해서는 안 되기 때문이다.
    """
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))
    from src.scoring.schema import ChecklistItem, ItemInfo

    return ItemInfo(
        item_id=str(row["id"]),
        prompt=row.get("prompt") or "",
        item_type="free_response",
        checklist=[
            ChecklistItem(id=str(it["id"]), description=it["question"], weight=1.0)
            for it in entry.get("items", [])
        ],
    )


def run_binary(client, row: dict, entry: dict, throttle) -> dict:
    """B2 판정 한 건. **판정 규약은 채점 서버(`src/features/checklist.py`)의 것을 그대로 쓴다.**

    v1 의 B 와 글자 하나까지 같은 지시문·같은 폐기 규약을 쓰므로, v1 의 B 와 v2 의 D 의
    차이는 오직 **체크리스트 내용**에서만 나온다. 그것이 이번 실험의 질문이다.
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
    item = _to_item_info(row, entry)
    if not item.checklist:
        return {"status": "no_checklist", "reason": "이 문항에 고정된 v2 체크리스트가 없다"}

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
        # 실행 중에 눈으로 보려는 값이다. 최종 점수(D·E·F)는 analyze_v2.py 가 낸다
        "pred": ratio_to_score(ratio),
        "met_ratio": round(ratio, 4),
        "items": items,
        "n_items": len(items),
        "n_met": sum(i["met"] for i in items),
        "dropped_citations": dropped,
        "warnings": warnings[:5],
        "elapsed_sec": result["elapsed_sec"],
        "attempts": result["attempts"],
    }


def run_score(client, row: dict, entry: dict, throttle) -> dict:
    """S2 판정 한 건. 항목마다 0~100 점 + 근거 인용."""
    answer_text = (row.get("ref") or "").strip()
    items_def = entry.get("items", [])
    if not items_def:
        return {"status": "no_checklist", "reason": "이 문항에 고정된 v2 체크리스트가 없다"}

    prompt = build_score_prompt(answer_text, row.get("prompt") or "", items_def)
    result = call_with_retry(
        lambda: client.generate_json(
            prompt, system_instruction=SCORE_SYSTEM_INSTRUCTION,
            response_schema=SCORE_RESPONSE_SCHEMA,
        ),
        throttle=throttle,
        label=str(row["id"])[-16:],
    )
    if result["status"] != "ok":
        return {"status": result["status"], "reason": result.get("reason", ""),
                "attempts": result.get("attempts")}

    judged, warnings, dropped = score_results_from_payload(
        answer_text, items_def, result["value"])
    weighted = weighted_mean_0to100(judged, items_def)

    return {
        "status": "ok",
        # 실행 중에 눈으로 보려는 값(=방식 G). 나머지 점수는 analyze_v2.py 가 낸다
        "pred": ratio_to_score(weighted),
        "weighted_ratio": round(weighted, 4),
        "mean_score": round(sum(r["score"] for r in judged) / len(judged), 2) if judged else 0.0,
        "items": judged,
        "n_items": len(judged),
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
    """
    client = make_judge_client()
    throttle = CallThrottle(workers, rpm=rpm)
    done = load_done(out_path)
    tasks = build_tasks(rows, fold_of, methods, pass_tag, done)

    total = len(tasks)
    print(f"\n=== [{pass_tag}] 할 일 {total}건 "
          f"(답안 {len(rows)}건 × 갈래 {len(methods)}종, 이미 끝난 것 제외) ===")
    if not total:
        return {"total": 0, "ok": 0, "failed": 0, "stopped": False, "elapsed": 0.0}

    counters = {"ok": 0, "failed": 0, "skipped_quota": 0}
    started = time.perf_counter()

    def one(index: int, task: dict) -> None:
        row, method = task["row"], task["method"]
        rid = str(row["id"])
        pkey = prompt_key(row.get("prompt") or "")
        base = {
            "id": rid,
            "method": method,
            "pass": task["pass_tag"],
            "prompt_key": pkey,
            "speaker_id": str(row.get("speaker_id") or rid.split("-")[0]),
            "nationality": row.get("nationality"),
            "topik_level": row.get("topik_level"),
            "fold": task["fold"],
            "human_score": human_score(row),
            "answer_chars": len(row.get("ref") or ""),
            "model": JUDGE_MODEL,
            "checklist_version": "v2",
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        entry = checklists.get(pkey, {})
        if method == "B2":
            outcome = run_binary(client, row, entry, throttle)
        else:
            outcome = run_score(client, row, entry, throttle)

        # 한도가 바닥나 물러난 경우에는 **아무것도 적지 않는다.**
        # 실패로 적어 두면 그것도 결과처럼 보이는데, 사실은 시도조차 못 한 것이다
        if outcome["status"] == "quota_stopped":
            counters["skipped_quota"] += 1
            return

        append_record(out_path, {**base, **outcome})
        if outcome["status"] == "ok":
            counters["ok"] += 1
            extra = (f"충족 {outcome['n_met']}/{outcome['n_items']}" if method == "B2"
                     else f"가중평균 {outcome['weighted_ratio']:.2f}")
            print(f"   [{index:4d}/{total}] {method} {rid[-16:]} "
                  f"예측 {outcome['pred']} · 사람 {base['human_score']} · {extra}")
        else:
            counters["failed"] += 1
            print(f"   [{index:4d}/{total}] {method} {rid[-16:]} "
                  f"실패({outcome['status']}): {str(outcome.get('reason'))[:70]}")

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-cl2") as pool:
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
    ap = argparse.ArgumentParser(
        description="체크리스트 v2 로 이진 패스·점수 패스를 각각 독립 호출로 돌린다")
    ap.add_argument("--methods", default=",".join(ALL_METHODS_V2),
                    help=f"쉼표로 구분한 갈래 이름. 기본 {','.join(ALL_METHODS_V2)}")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_V2)
    ap.add_argument("--pass-tag", default="main",
                    help="이번 실행의 이름표. 재현성 실행은 rep1·rep2·rep3 로 준다")
    ap.add_argument("--repro", action="store_true",
                    help="재현성용 고정 부분표본(60건)만 돌린다. v1 과 같은 60건이다")
    ap.add_argument("--repro-n", type=int, default=60)
    ap.add_argument("--pilot", action="store_true",
                    help="파일럿: 문항 2종 × 답안 10건만 돌려 형식·시간을 확인한다")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--rpm", type=int, default=DEFAULT_RPM,
                    help=f"1분에 몇 번까지 부를지. 기본 {DEFAULT_RPM}")
    args = ap.parse_args()

    print(use_free_backup_key())
    print(f"판정 모델: {JUDGE_MODEL} (두 갈래 모두 같은 모델·온도 0) · "
          f"분당 {args.rpm}회 · 동시 {args.workers}개")

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    unknown = [m for m in methods if m not in ALL_METHODS_V2]
    if unknown:
        print(f"모르는 갈래: {', '.join(unknown)} (쓸 수 있는 것: {', '.join(ALL_METHODS_V2)})")
        return 1

    # ── 표본과 겹 ────────────────────────────────────────────────────────────
    rows, counts = load_rows()
    print("\n=== 표본 고르기 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])

    # 겹은 **언제나 전체 표본에서** 정한다. v1 과 같은 함수·같은 규칙이므로 같은 배정이 나온다
    fold_of, diag = assign_folds(rows, N_FOLDS)
    print(f"\n겹 나누기: 화자 단위 {N_FOLDS}겹 · 겹을 넘나든 화자 {diag['speaker_leak_count']}명"
          f" · 빈 칸 {len(diag['prompts_with_empty_fold'])}개")

    if args.repro:
        rows = select_repro_subset(rows, args.repro_n)
        print(f"재현성용 고정 부분표본: {len(rows)}건 (v1 과 같은 60건 — 같은 함수로 고른다)")
    elif args.pilot:
        buckets = group_by_prompt(rows)
        picked = []
        for pkey in list(buckets)[:2]:
            picked.extend(buckets[pkey][:10])
        rows = sorted(picked, key=lambda r: str(r["id"]))
        print(f"파일럿 표본: {len(rows)}건 (문항 2종 × 10건)")

    # ── 체크리스트 확인 ──────────────────────────────────────────────────────
    checklists = load_checklists_v2()
    need = {prompt_key(r.get("prompt") or "") for r in rows}
    missing = [p for p in sorted(need) if checklists.get(p, {}).get("status") != "ok"]
    if missing:
        print(f"\n[중단] v2 체크리스트가 없는 문항 {len(missing)}종: {', '.join(missing)}\n"
              "  먼저 gen_checklists_v2.py 를 돌려 체크리스트를 고정하라.")
        return 1
    n_items = sum(len(checklists[p]["items"]) for p in need)
    print(f"체크리스트 v2: 문항 {len(need)}종 · 항목 {n_items}개 "
          f"(문항당 평균 {n_items / len(need):.1f}개, 고정본을 읽기만 한다)")

    summary = run_all(rows, fold_of, checklists, methods, args.pass_tag,
                      args.out, args.workers, args.rpm)
    print(f"\n결과 파일: {args.out}")
    if summary.get("stopped"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
