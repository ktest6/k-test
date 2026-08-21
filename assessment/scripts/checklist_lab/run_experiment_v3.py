# -*- coding: utf-8 -*-
"""체크리스트 v3 로 판정한다 — 이진 패스, 확률 판정 예비조사(probe), 소프트 패스.

■ 세 갈래

    B3  이진 패스   — 항목마다 충족(1)/미충족(0) + 근거 인용. **v1·v2 와 같은 규약**이다.
                     v3 는 체크리스트가 겹마다 다르므로, 답안 하나를 **다섯 벌 모두로**
                     판정한다(281건 × 5겹 = 1,405 판정). 왜 다섯 번인지는 아래 설명.
    PROBE 예비조사  — "확률로 판정받기"가 우리 조건에서 가능한지 먼저 재는 단계.
    S3  소프트 패스 — 예비조사가 '가능'으로 나왔을 때만 돈다. 씨앗을 바꿔 여러 번
                     판정해 항목마다 p(예) 를 만든다.

■ 왜 답안 하나를 다섯 벌로 판정하나

겹 k 의 체크리스트는 학습 겹 답안만 보고 만들었다. 그래서
  · 겹 k 답안의 판정  → **평가용**(이 점수로 성적을 잰다)
  · 나머지 겹 답안의 판정 → **학습용**(문항별 가중치를 배우는 재료)
가 된다. 가중치를 배우려면 같은 체크리스트로 채점된 학습 답안이 있어야 하므로,
겹 k 의 체크리스트로 그 문항 답안을 전부 판정해 두어야 한다.
(성적은 언제나 '자기 겹의 체크리스트'로 받은 판정만 쓴다 — 누출 없음)

■ logprobs 는 이 API 로 불가능하다 — 그래서 대체재를 잰다

팀원 요청은 O/X 대신 **정규화 확률 p(예)/(p(예)+p(아니오))** 로 받는 것이었다.
Gemini 개발자 API 로는 **불가능하다**(실측). `response_logprobs=True, logprobs=5` 를
넣으면 쓸 수 있는 모델 전부가 400 INVALID_ARGUMENT "Logprobs is not enabled for
this model" 을 돌려준다. 자세한 시도 목록은 `LOGPROBS_STATUS` 에 적어 두었다.

그래서 대체재를 쓴다 — **씨앗(seed)을 바꿔 여러 번 판정하고 '예'가 나온 비율**을
확률로 삼는 것이다. 다만 이것이 쓸 만한지부터 재야 한다. 온도를 올려도 모델이
늘 같은 답을 내놓는다면 비율은 언제나 0 또는 1 이고, 그건 O/X 와 똑같아서
아무것도 새로 얻는 것이 없다. 그 사실을 숫자로 확인하는 것이 예비조사다.

  판정 규칙(미리 못 박는다): 12표가 갈린 항목 칸이 **15% 이상**이면 확률에 신호가
  있다고 보고 소프트 패스를 돌린다. 그 미만이면 **대체재는 쓸 수 없다**고 결론 내고
  소프트 패스를 생략한다. 결과가 나온 뒤에 기준을 정하면 원하는 답을 고를 수 있다.

■ 공정 규칙 (앞 실험과 똑같이 유지한다)

  · 같은 답안 281건 · 같은 화자 단위 5겹(같은 함수·같은 배정) · 같은 사람 점수
  · 같은 모델 gemini-3.1-flash-lite · **본 판정은 온도 0** · JSON 강제
  · 입력은 음성이 아니라 사람이 직접 적은 전사(ref)
  · 인용 검증 규약도 v1·v2 와 같다 — 원문에 없는 인용으로 받은 충족은 폐기한다

■ 앞 실험 도구·결과는 건드리지 않는다

`run_experiment.py`·`run_experiment_v2.py` 와 그 결과 파일은 한 줄도 고치지 않았다.
v3 결과는 `judgments_v3.jsonl` 에 따로 쌓는다.

■ 쓰는 법

    python run_experiment_v3.py --pilot                 # 문항 2종 × 답안 5건 파일럿
    python run_experiment_v3.py --probe                 # 2단계: 확률 판정 예비조사
    python run_experiment_v3.py                         # 3단계: 이진 본 판정 1,405건
    python run_experiment_v3.py --pass-tag rep1 --repro # 재현성 60건 1회차
    python run_experiment_v3.py --soft                  # 소프트 패스(예비조사 통과 시에만)
    python run_experiment_v3.py --self-test             # 계산기만 예시 입력으로 점검
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import (  # noqa: E402
    ASSESSMENT_DIR,
    DEFAULT_RPM,
    JUDGE_MAX_OUTPUT_TOKENS,
    JUDGE_MODEL,
    JUDGE_TIMEOUT_MS,
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
from gen_checklists_v3 import items_for, load_checklists_v3  # noqa: E402
from run_experiment import met_ratio_to_score  # noqa: E402  (v1 의 반올림 규칙을 그대로 쓴다)

#: v3 판정 결과를 한 줄씩 쌓는 파일. v1·v2 결과와 **다른 파일**이다.
DEFAULT_OUT_V3 = OUT_DIR / "judgments_v3.jsonl"
#: 확률 판정 예비조사 결과.
PROBE_PATH = OUT_DIR / "softprob_probe.json"

#: 한 번에 몇 개까지 동시에 부를지.
DEFAULT_WORKERS = 8

# ─────────────────────────────────────────────────────────────────────────────
# 2단계 예비조사 설정 — 결과를 보기 **전에** 정해 둔 값들
# ─────────────────────────────────────────────────────────────────────────────
#: 예비조사에 쓸 답안 수. 사람 점수가 중간대(1~4점)인 것만 쓴다 —
#: 0점·5점 답안은 누가 봐도 답이 정해져 있어서 판정이 갈릴 여지가 애초에 없다.
PROBE_N_ANSWERS = 20
PROBE_SCORE_RANGE = (1, 4)

#: 답안 하나를 몇 번 판정할지, 어떤 온도로 두 벌을 돌릴지.
PROBE_N_SEEDS = 12
PROBE_TEMPERATURES = (1.0, 1.3)

#: 씨앗의 기준값. seed = PROBE_SEED_BASE + i 로 준다(i = 0..11).
#: 고정해 두는 이유: 같은 씨앗 목록이면 같은 값이 나와야 재현성을 확인할 수 있다.
PROBE_SEED_BASE = 20260809

#: ★ 판정 기준 — 갈린 칸이 이 비율 이상이면 소프트 패스를 돌린다.
#: 결과를 보기 전에 정한 값이다. 이 아래면 "확률 대체재는 쓸 수 없다"가 결론이다.
PROBE_SPLIT_THRESHOLD = 0.15

#: 소프트 패스에서 쓸 씨앗 개수(예비조사 통과 시에만 돈다).
SOFT_N_SEEDS = 8
SOFT_TEMPERATURE = 1.0

#: logprobs 를 실제로 시도해 본 기록. 결과 JSON 에 그대로 싣는다.
#: "안 된다"만 적으면 다음 사람이 또 시도하므로, 무엇을 어떻게 해 봤는지 남긴다.
LOGPROBS_STATUS = {
    "requested": "판정을 O/X 대신 정규화 확률 p(예)/(p(예)+p(아니오)) 로 받기",
    "available": False,
    "api": "Gemini 개발자 API (google-genai 2.14.0)",
    "attempted_parameters": "GenerateContentConfig(response_logprobs=True, logprobs=5)",
    "models_tried_400": [
        "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.5-flash-lite",
        "gemini-3.6-flash", "gemini-flash-latest", "gemini-flash-lite-latest",
        "gemini-2.5-flash",
    ],
    "error_400": "INVALID_ARGUMENT — \"Logprobs is not enabled for this model\"",
    "models_tried_404": ["gemini-2.0 계열", "gemini-2.5-pro", "gemini-3-pro"],
    "keys_tried": "주 키(유료)·무료 백업 키 둘 다 같은 응답",
    "local_model_option": (
        "로컬 모델로 진짜 logprobs 를 뽑는 길은 택하지 않았다. 이 PC 는 torch 2.13.0+cpu · "
        "CUDA 없음 · C: 여유 8GB 라서, 판정자가 바뀌면 앞 실험(v1·v2)과의 비교가 통째로 "
        "깨지고 속도도 나오지 않는다."
    ),
    "substitute": (
        "씨앗(seed)을 바꿔 여러 번 판정하고 '예'가 나온 비율을 확률로 쓰는 방법. "
        "쓸 만한지를 예비조사(probe)로 먼저 쟀다 — 아래 probe 결과 참고."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# ※ 실험 전용 ※ 온도·씨앗을 지정해 부르는 클라이언트
# ─────────────────────────────────────────────────────────────────────────────
class SeededJudgeClient:
    """온도와 씨앗을 지정해서 부를 수 있는 **실험 전용** 클라이언트.

    왜 따로 만드나:
    채점 서버의 래퍼(`src/llm/client.py`)는 **온도 0 고정**이 설계다. 재현성을 지키는
    장치라서 바꾸면 안 되고, 이 실험 때문에 서버 코드를 고칠 수도 없다.
    그런데 예비조사는 일부러 온도를 올려 "그래도 판정이 갈리는가"를 봐야 한다.
    그래서 여기서만 쓰는 클라이언트를 따로 두고, **본 판정(B3)은 서버 래퍼를 그대로 쓴다.**

    서버 래퍼가 지키는 것들은 여기서도 똑같이 지킨다 — JSON 강제, 응답 형식표,
    답이 잘렸는지 확인, 실패 사유를 같은 문구로 만들기. 그래야 위쪽의 재시도·
    사용량 조절이 v1·v2 와 똑같이 동작한다.
    """

    def __init__(self, model: str = JUDGE_MODEL,
                 max_output_tokens: int = JUDGE_MAX_OUTPUT_TOKENS,
                 timeout_ms: int = JUDGE_TIMEOUT_MS):
        if str(ASSESSMENT_DIR) not in sys.path:
            sys.path.insert(0, str(ASSESSMENT_DIR))
        import os

        self.model_name = model
        self._max_output_tokens = max_output_tokens
        self._timeout_ms = timeout_ms
        self._api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _ensure(self):
        """접속 객체를 준비한다(한 번만 만들어 두고 계속 쓴다)."""
        from src.llm.client import LLMUnavailable

        if not self._api_key:
            raise LLMUnavailable("GEMINI_API_KEY 가 없다.")
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_json(self, prompt: str, system_instruction: str = "",
                      response_schema=None, temperature: float = 0.0,
                      seed: int | None = None) -> dict:
        """온도와 씨앗을 지정해서 한 번 부르고 JSON(dict)으로 받는다."""
        # 서버 래퍼의 판별기·해석기를 그대로 빌려 쓴다(같은 실패 문구, 같은 JSON 처리)
        from google.genai import types

        from src.llm.client import (
            LLMUnavailable,
            _is_truncated,
            _parse_json_object,
            classify_failure,
        )

        client = self._ensure()
        config = types.GenerateContentConfig(
            temperature=temperature,
            seed=seed,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json",
            system_instruction=system_instruction or None,
            response_schema=response_schema,
            http_options=types.HttpOptions(timeout=self._timeout_ms),
        )
        try:
            response = client.models.generate_content(
                model=self.model_name, contents=prompt, config=config)
        except Exception as exc:
            raise LLMUnavailable(classify_failure(exc), detail=str(exc)) from exc

        # 답이 잘렸으면 반쪽 결과를 만들지 않고 실패로 둔다(서버 래퍼와 같은 원칙)
        if _is_truncated(response):
            raise LLMUnavailable("LLM 답이 길이 제한에 걸려 잘렸다.",
                                 detail=f"max_output_tokens={self._max_output_tokens}")
        text = (response.text or "").strip()
        if not text:
            raise LLMUnavailable("LLM이 빈 응답을 보냈다.")
        return _parse_json_object(text)


# ─────────────────────────────────────────────────────────────────────────────
# 판정 한 건
# ─────────────────────────────────────────────────────────────────────────────
def _to_item_info(row: dict, items: list[dict]):
    """고정해 둔 v3 항목을 채점 서버가 쓰는 문항 정보 모양으로 옮긴다.

    weight 는 전부 1.0 으로 둔다. **판정 단계에서는 항목의 경중을 모르는 편이 옳다** —
    중요도는 점수를 만들 때 쓰는 것이지 "충족했는가"라는 사실 판정을 흔들면 안 된다.
    """
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))
    from src.scoring.schema import ChecklistItem, ItemInfo

    return ItemInfo(
        item_id=str(row["id"]),
        prompt=row.get("prompt") or "",
        item_type="free_response",
        checklist=[ChecklistItem(id=str(it["id"]), description=it["question"], weight=1.0)
                   for it in items],
    )


def judge_binary(client, row: dict, items: list[dict], throttle,
                 temperature: float | None = None, seed: int | None = None) -> dict:
    """이진 판정 한 건. **판정 규약은 채점 서버의 것을 그대로 쓴다.**

    v1 의 B·v2 의 B2 와 글자 하나까지 같은 지시문·같은 폐기 규약이므로,
    세 실험의 차이는 오직 **체크리스트 내용**에서만 나온다. 그것이 이 실험의 질문이다.

    `temperature`/`seed` 를 주면 실험 전용 클라이언트로 부른다(예비조사·소프트 패스용).
    안 주면 서버 래퍼 그대로, 즉 **온도 0** 이다(본 판정).
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
    if not items:
        return {"status": "no_checklist", "reason": "이 (문항, 겹)에 고정된 v3 체크리스트가 없다"}

    item = _to_item_info(row, items)
    prompt = build_prompt(answer_text, item)

    if temperature is None:
        call = lambda: client.generate_json(  # noqa: E731
            prompt, system_instruction=SYSTEM_INSTRUCTION, response_schema=RESPONSE_SCHEMA)
    else:
        call = lambda: client.generate_json(  # noqa: E731
            prompt, system_instruction=SYSTEM_INSTRUCTION, response_schema=RESPONSE_SCHEMA,
            temperature=temperature, seed=seed)

    result = call_with_retry(call, throttle=throttle, label=str(row["id"])[-16:])
    if result["status"] != "ok":
        return {"status": result["status"], "reason": result.get("reason", ""),
                "attempts": result.get("attempts")}

    judged, warnings, dropped = results_from_llm_payload(
        answer_text, item.checklist, result["value"])

    # 항목마다 판정과 **근거 위치**를 함께 남긴다. 점수만 남기면 나중에 따질 수가 없다
    out_items = []
    for r in judged:
        ev = r.evidence[0] if r.evidence else None
        out_items.append({
            "cid": r.id,
            "question": r.description,
            "met": int(r.met),
            "quote": getattr(ev, "quote", "") if ev else "",
            "start": getattr(ev, "start", None) if ev else None,
            "end": getattr(ev, "end", None) if ev else None,
            "comment": getattr(ev, "comment", "") if ev else "",
            "note": r.note,
        })

    ratio = sum(i["met"] for i in out_items) / len(out_items) if out_items else 0.0
    return {
        "status": "ok",
        # 실행 중에 눈으로 보려는 값이다. 최종 점수(I·J·K)는 analyze_v3.py 가 낸다
        "pred": met_ratio_to_score(ratio),
        "met_ratio": round(ratio, 4),
        "items": out_items,
        "n_items": len(out_items),
        "n_met": sum(i["met"] for i in out_items),
        "dropped_citations": dropped,
        "warnings": warnings[:5],
        "elapsed_sec": result["elapsed_sec"],
        "attempts": result["attempts"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2단계 — 확률 판정 예비조사
# ─────────────────────────────────────────────────────────────────────────────
def select_probe_rows(rows: list[dict], n: int = PROBE_N_ANSWERS) -> list[dict]:
    """예비조사에 쓸 답안을 고른다. **중간 점수대에서, 문항이 고루 섞이게.**

    왜 중간 점수대인가: 0점(아무것도 못 함)과 5점(다 함)은 판정이 갈릴 여지가 거의 없다.
    거기서 "안 갈린다"는 결과가 나오면 그건 모델이 결정적이어서가 아니라 문제가 쉬워서다.
    갈릴 만한 자리에서 재야 대체재가 쓸 만한지 알 수 있다.

    무작위를 쓰지 않는다 — 문항을 한 바퀴씩 돌며 하나씩 가져오므로 늘 같은 20건이 나온다.
    """
    lo, hi = PROBE_SCORE_RANGE
    buckets = group_by_prompt([r for r in rows if lo <= human_score(r) <= hi])
    queues = {pkey: sorted(items, key=lambda r: (human_score(r), str(r["id"])))
              for pkey, items in buckets.items()}
    picked: list[dict] = []
    turn = 0
    while len(picked) < n and any(len(q) > turn for q in queues.values()):
        for pkey in sorted(queues):
            if turn < len(queues[pkey]):
                picked.append(queues[pkey][turn])
                if len(picked) >= n:
                    break
        turn += 1
    picked.sort(key=lambda r: str(r["id"]))
    return picked


def summarize_probe(records: list[dict]) -> dict:
    """예비조사 판정들을 모아 **갈린 칸의 비율**을 낸다.

    한 '칸'은 (답안 하나, 항목 하나, 온도 하나)다. 그 칸에서 12번의 판정이
    모두 같은 답이면 만장일치, 하나라도 다르면 '갈린 칸'이다.

    갈린 칸에서는 확률값 p(예) = 예라고 한 횟수 / 전체 횟수 도 함께 모은다.
    갈린 칸이 있어도 그 값이 11/12 나 1/12 로만 몰려 있다면 사실상 O/X 와 다를 바 없다.
    그래서 비율과 값 분포를 둘 다 낸다.
    """
    # (온도, 답안, 항목) 마다 '예' 판정을 모은다
    votes: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    n_calls_ok = 0
    for rec in records:
        if rec.get("status") != "ok":
            continue
        n_calls_ok += 1
        key_head = (str(rec.get("temperature")), str(rec.get("id")))
        for item in rec.get("items", []):
            votes[(*key_head, str(item["cid"]))].append(int(item["met"]))

    by_temp: dict[str, dict] = {}
    for (temp, _rid, _cid), _ in votes.items():
        by_temp.setdefault(temp, {"n_cells": 0, "n_split": 0, "probs": [], "split_probs": []})

    for (temp, _rid, _cid), values in votes.items():
        # 12번을 다 못 채운 칸(호출 실패가 있었던 칸)은 세지 않는다 —
        # 표본 수가 다른 칸을 섞으면 '갈린 비율'이 표본 수 차이로 흔들린다
        if len(values) < PROBE_N_SEEDS:
            continue
        bucket = by_temp[temp]
        bucket["n_cells"] += 1
        p_yes = sum(values) / len(values)
        bucket["probs"].append(p_yes)
        if len(set(values)) > 1:
            bucket["n_split"] += 1
            bucket["split_probs"].append(p_yes)

    out: dict = {"by_temperature": {}}
    all_cells, all_split = 0, 0
    for temp, bucket in sorted(by_temp.items()):
        cells, split = bucket["n_cells"], bucket["n_split"]
        all_cells += cells
        all_split += split
        sp = sorted(bucket["split_probs"])
        out["by_temperature"][temp] = {
            "n_cells": cells,
            "n_split_cells": split,
            "split_rate": (split / cells) if cells else float("nan"),
            "split_prob_mean": (sum(sp) / len(sp)) if sp else None,
            "split_prob_min": sp[0] if sp else None,
            "split_prob_max": sp[-1] if sp else None,
            "split_prob_values": sp,
            # 확률이 0/1 이 아닌 중간값을 얼마나 갖는지 — 0.25~0.75 를 '진짜 중간'으로 본다
            "n_middle_cells": sum(1 for p in bucket["probs"] if 0.25 <= p <= 0.75),
        }
    out["n_cells_total"] = all_cells
    out["n_split_cells_total"] = all_split
    out["split_rate_overall"] = (all_split / all_cells) if all_cells else float("nan")
    out["n_calls_ok"] = n_calls_ok
    out["threshold"] = PROBE_SPLIT_THRESHOLD
    # ★ 결과를 보기 전에 정한 기준으로 가부를 판정한다
    out["soft_pass_enabled"] = bool(all_cells) and out["split_rate_overall"] >= PROBE_SPLIT_THRESHOLD
    out["verdict"] = (
        f"갈린 칸 {out['split_rate_overall']:.1%} ≥ 기준 {PROBE_SPLIT_THRESHOLD:.0%} → "
        "확률에 신호가 있다. 소프트 패스를 돌린다."
        if out["soft_pass_enabled"] else
        f"갈린 칸 {out['split_rate_overall']:.1%} < 기준 {PROBE_SPLIT_THRESHOLD:.0%} → "
        "씨앗을 바꿔도 판정이 거의 안 갈린다. 확률 대체재는 쓸 수 없다고 보고 "
        "소프트 패스를 생략한다."
    ) if all_cells else "잰 칸이 없다(예비조사 미실행)."
    return out


def check_seed_determinism(client, rows, checklists, fold_of, throttle,
                           n_answers: int = 2, n_repeats: int = 3) -> dict:
    """**같은 씨앗을 여러 번 주면 같은 판정이 나오는가**를 확인한다.

    왜 이걸 재야 하나: 예비조사의 '갈린 칸 비율'을 어떻게 읽을지가 여기서 갈린다.
      · 씨앗이 지켜진다면 → 갈린 칸은 **씨앗을 바꿔서 얻은 흔들림의 전부**다.
        즉 "확률을 더 뽑아도 이 이상은 안 갈린다"고 말할 수 있다.
      · 씨앗이 무시된다면 → 그냥 매번 다른 주사위를 굴린 것이라 위 해석이 성립하지 않는다.

    소프트 패스를 돌렸을 때 "같은 씨앗 목록이면 같은 값이 나온다"를 확인하는 것과
    같은 검사이기도 하다(소프트 패스를 안 돌려도 이 사실은 남겨야 한다).
    """
    result = {"n_answers": n_answers, "n_repeats": n_repeats, "cases": [], "all_same": True}
    for row in select_probe_rows(rows, PROBE_N_ANSWERS)[:n_answers]:
        rid = str(row["id"])
        items = items_for(checklists, prompt_key(row.get("prompt") or ""), fold_of[rid])
        for temp in PROBE_TEMPERATURES:
            seen = []
            for _ in range(n_repeats):
                out = judge_binary(client, row, items, throttle,
                                   temperature=temp, seed=PROBE_SEED_BASE)
                if out["status"] != "ok":
                    seen.append(None)
                    continue
                seen.append("".join(str(i["met"]) for i in out["items"]))
            same = len(set(seen)) == 1 and seen[0] is not None
            result["all_same"] &= same
            result["cases"].append({"id": rid, "temperature": temp,
                                    "judgments": seen, "same": same})
    result["설명"] = (
        "같은 씨앗·같은 온도로 되풀이해서 판정이 같은지 본다. 같다면 예비조사의 "
        "'갈린 칸'은 씨앗을 바꿔서 생긴 흔들림의 전부라고 읽을 수 있다."
    )
    return result


def run_probe(rows, checklists, fold_of, out_path: Path, workers: int, rpm: int) -> dict:
    """예비조사를 돌린다. 답안 20건 × 씨앗 12개 × 온도 2벌 = 480회 호출."""
    probe_rows = select_probe_rows(rows)
    print(f"\n=== 2단계 예비조사: 답안 {len(probe_rows)}건 × 씨앗 {PROBE_N_SEEDS}개 × "
          f"온도 {len(PROBE_TEMPERATURES)}벌 = "
          f"{len(probe_rows) * PROBE_N_SEEDS * len(PROBE_TEMPERATURES)}회 호출 ===")
    print(f"  표본: 사람 점수 {PROBE_SCORE_RANGE[0]}~{PROBE_SCORE_RANGE[1]}점 · "
          f"문항 {len({prompt_key(r.get('prompt') or '') for r in probe_rows})}종")
    print(f"  판정 기준(미리 정함): 갈린 칸 {PROBE_SPLIT_THRESHOLD:.0%} 이상이면 소프트 패스를 돈다")

    client = SeededJudgeClient()
    if not client.available:
        print("[중단] GEMINI_API_KEY 가 없다.")
        return {}
    throttle = CallThrottle(workers, rpm=rpm)
    done = load_done(out_path)

    tasks = []
    for row in probe_rows:
        rid = str(row["id"])
        fold = fold_of[rid]
        items = items_for(checklists, prompt_key(row.get("prompt") or ""), fold)
        for temp in PROBE_TEMPERATURES:
            method = f"PROBE_t{temp}"
            for i in range(PROBE_N_SEEDS):
                pass_tag = f"s{i}"
                if (done.get((rid, method, pass_tag)) or {}).get("status") == "ok":
                    continue
                tasks.append({"row": row, "items": items, "fold": fold,
                              "temperature": temp, "seed": PROBE_SEED_BASE + i,
                              "method": method, "pass_tag": pass_tag})

    print(f"  할 일 {len(tasks)}건 (이미 끝난 것 제외)")
    counters = {"ok": 0, "failed": 0}
    started = time.perf_counter()

    def one(index: int, task: dict) -> None:
        row = task["row"]
        outcome = judge_binary(client, row, task["items"], throttle,
                               temperature=task["temperature"], seed=task["seed"])
        if outcome["status"] == "quota_stopped":
            return
        append_record(out_path, {
            "id": str(row["id"]), "method": task["method"], "pass": task["pass_tag"],
            "prompt_key": prompt_key(row.get("prompt") or ""),
            "speaker_id": str(row.get("speaker_id") or str(row["id"]).split("-")[0]),
            "fold": task["fold"], "checklist_fold": task["fold"],
            "human_score": human_score(row), "answer_chars": len(row.get("ref") or ""),
            "model": JUDGE_MODEL, "checklist_version": "v3",
            "temperature": task["temperature"], "seed": task["seed"],
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **outcome})
        if outcome["status"] == "ok":
            counters["ok"] += 1
            if index % 40 == 0:
                print(f"   [{index:4d}/{len(tasks)}] 진행 중 (성공 {counters['ok']})")
        else:
            counters["failed"] += 1
            print(f"   [{index:4d}/{len(tasks)}] 실패({outcome['status']}): "
                  f"{str(outcome.get('reason'))[:70]}")

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-cl3probe") as pool:
        futures = [pool.submit(one, i, t) for i, t in enumerate(tasks, 1)]
        for fut in futures:
            try:
                fut.result()
            except Exception as exc:
                print(f"   일꾼에서 예외: {type(exc).__name__}: {str(exc)[:150]}")

    elapsed = time.perf_counter() - started
    print(f"   예비조사 {len(tasks)}건 시도 · 성공 {counters['ok']} · "
          f"실패 {counters['failed']} · {elapsed:.0f}초")

    # 씨앗이 실제로 지켜지는지 확인한다(예비조사 숫자를 어떻게 읽을지가 여기서 갈린다)
    print("\n   씨앗이 지켜지는지 확인 중...")
    seed_check = check_seed_determinism(client, rows, checklists, fold_of, throttle)
    print(f"   같은 씨앗 되풀이 판정: "
          f"{'전부 같음' if seed_check['all_same'] else '달라진 경우가 있음'} "
          f"({len(seed_check['cases'])}가지 조건 × {seed_check['n_repeats']}회)")

    # 파일에 쌓인 것 전체를 다시 읽어 요약한다(이어서 한 실행도 함께 세기 위해서다)
    all_records = [rec for (rid, m, p), rec in load_done(out_path).items()
                   if m.startswith("PROBE_")]
    summary = summarize_probe(all_records)
    summary["n_answers"] = len(probe_rows)
    summary["answer_ids"] = [str(r["id"]) for r in probe_rows]
    summary["n_seeds"] = PROBE_N_SEEDS
    summary["temperatures"] = list(PROBE_TEMPERATURES)
    summary["seed_base"] = PROBE_SEED_BASE
    summary["logprobs_status"] = LOGPROBS_STATUS
    summary["seed_determinism"] = seed_check
    summary["elapsed_sec"] = round(elapsed, 1)
    summary["failed_calls"] = counters["failed"]
    Path(PROBE_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(PROBE_PATH).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                encoding="utf-8")

    print(f"\n=== 예비조사 결과 ===")
    print_table(["온도", "잰 칸", "갈린 칸", "갈린 비율", "갈린 칸 확률 평균", "중간값(0.25~0.75) 칸"],
                [[t, v["n_cells"], v["n_split_cells"], f"{v['split_rate']:.1%}",
                  f"{v['split_prob_mean']:.3f}" if v["split_prob_mean"] is not None else "-",
                  v["n_middle_cells"]]
                 for t, v in summary["by_temperature"].items()])
    print(f"  전체: {summary['n_split_cells_total']}/{summary['n_cells_total']}칸 "
          f"({summary['split_rate_overall']:.1%})")
    print(f"  → {summary['verdict']}")
    print(f"저장: {PROBE_PATH}")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# 3단계 — 본 판정
# ─────────────────────────────────────────────────────────────────────────────
def build_binary_tasks(rows, fold_of, checklists, pass_tag, done, own_fold_only: bool):
    """이진 판정 할 일 목록을 만든다. **이미 성공한 것은 뺀다.**

    `own_fold_only=True` 면 답안마다 **자기 겹의 체크리스트 한 벌**로만 판정한다
    (재현성 실행이 그렇다 — 실제 채점에 쓰이는 배치만 반복해서 재면 된다).
    """
    tasks = []
    for row in rows:
        rid = str(row["id"])
        pkey = prompt_key(row.get("prompt") or "")
        folds = [fold_of[rid]] if own_fold_only else list(range(N_FOLDS))
        for fold in folds:
            method = f"B3f{fold}"
            if (done.get((rid, method, pass_tag)) or {}).get("status") == "ok":
                continue
            tasks.append({"row": row, "method": method, "checklist_fold": fold,
                          "fold": fold_of[rid], "pass_tag": pass_tag,
                          "items": items_for(checklists, pkey, fold)})
    return tasks


def build_soft_tasks(rows, fold_of, checklists, done):
    """소프트 패스 할 일 목록. 자기 겹의 체크리스트로 씨앗만 바꿔 여러 번 판정한다."""
    tasks = []
    for row in rows:
        rid = str(row["id"])
        fold = fold_of[rid]
        items = items_for(checklists, prompt_key(row.get("prompt") or ""), fold)
        for i in range(SOFT_N_SEEDS):
            method, pass_tag = "S3own", f"s{i}"
            if (done.get((rid, method, pass_tag)) or {}).get("status") == "ok":
                continue
            tasks.append({"row": row, "method": method, "checklist_fold": fold,
                          "fold": fold, "pass_tag": pass_tag, "items": items,
                          "temperature": SOFT_TEMPERATURE, "seed": PROBE_SEED_BASE + i})
    return tasks


def run_tasks(tasks, out_path: Path, workers: int, rpm: int, label: str) -> dict:
    """할 일을 겹쳐서 돌리고 한 건씩 파일에 적는다.

    **동시에 여러 개를 보내도 결과는 달라지지 않는다** — 판정은 답안 하나만 보고
    그 답안의 결과를 낸다. 옆 항목의 결과를 참고하지도, 처리 순서를 보지도 않는다.
    """
    total = len(tasks)
    print(f"\n=== [{label}] 할 일 {total}건 (이미 끝난 것 제외) ===")
    if not total:
        return {"total": 0, "ok": 0, "failed": 0, "stopped": False, "elapsed": 0.0}

    # 온도를 지정하는 일(소프트 패스)이 하나라도 있으면 실험 전용 클라이언트를 쓴다.
    # 본 판정은 서버 래퍼 그대로(온도 0)라 이 갈래를 타지 않는다
    needs_seed = any("temperature" in t for t in tasks)
    client = SeededJudgeClient() if needs_seed else make_judge_client()
    throttle = CallThrottle(workers, rpm=rpm)
    counters = {"ok": 0, "failed": 0, "skipped_quota": 0}
    started = time.perf_counter()

    def one(index: int, task: dict) -> None:
        row = task["row"]
        rid = str(row["id"])
        outcome = judge_binary(client, row, task["items"], throttle,
                               temperature=task.get("temperature"), seed=task.get("seed"))
        # 한도가 바닥나 물러난 경우에는 **아무것도 적지 않는다.**
        # 실패로 적어 두면 그것도 결과처럼 보이는데, 사실은 시도조차 못 한 것이다
        if outcome["status"] == "quota_stopped":
            counters["skipped_quota"] += 1
            return
        append_record(out_path, {
            "id": rid, "method": task["method"], "pass": task["pass_tag"],
            "prompt_key": prompt_key(row.get("prompt") or ""),
            "speaker_id": str(row.get("speaker_id") or rid.split("-")[0]),
            "nationality": row.get("nationality"), "topik_level": row.get("topik_level"),
            "fold": task["fold"], "checklist_fold": task["checklist_fold"],
            "is_own_fold": task["fold"] == task["checklist_fold"],
            "human_score": human_score(row), "answer_chars": len(row.get("ref") or ""),
            "model": JUDGE_MODEL, "checklist_version": "v3",
            "temperature": task.get("temperature", 0.0), "seed": task.get("seed"),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **outcome})
        if outcome["status"] == "ok":
            counters["ok"] += 1
            if index % 100 == 0 or total <= 50:
                print(f"   [{index:4d}/{total}] {task['method']} {rid[-16:]} "
                      f"예측 {outcome['pred']} · 사람 {human_score(row)} · "
                      f"충족 {outcome['n_met']}/{outcome['n_items']}")
        else:
            counters["failed"] += 1
            print(f"   [{index:4d}/{total}] {task['method']} {rid[-16:]} "
                  f"실패({outcome['status']}): {str(outcome.get('reason'))[:70]}")

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-cl3") as pool:
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
    print(f"\n   [{label}] {total}건 시도 · 성공 {counters['ok']} · 실패 {counters['failed']}"
          f" · 한도로 보류 {counters['skipped_quota']}"
          f" · {elapsed:.0f}초 (건당 평균 {elapsed / max(1, total):.1f}초)"
          f" · 분당 한도 대기 {throttle.rate_waits}회")
    if throttle.stopped:
        print(f"\n   ※ {throttle.stop_reason}\n"
              "     여기까지 된 것은 파일에 적혀 있다. 같은 명령을 다시 실행하면 이어서 한다.")
    return {"total": total, "elapsed": round(elapsed, 1),
            "stopped": throttle.stopped, "stop_reason": throttle.stop_reason, **counters}


# ─────────────────────────────────────────────────────────────────────────────
# 자체 점검
# ─────────────────────────────────────────────────────────────────────────────
def self_test() -> int:
    """계산기들이 맞게 도는지 답을 아는 예시로 확인한다(네트워크·파일 안 건드림)."""
    ok = True
    rows_out = []

    def check(label, got, want):
        nonlocal ok
        passed = got == want
        ok &= passed
        rows_out.append([label, str(got), str(want), "통과" if passed else "실패"])

    print("=== 계산기 자체 점검 (run_experiment_v3) ===")

    # ① 예비조사 표본 — 중간 점수대만, 문항이 섞이게
    sample = []
    for p in ("문항A", "문항B", "문항C"):
        for i in range(12):
            sample.append({"id": f"{p}-{i:02d}", "prompt": p, "speaker_id": f"S{i}",
                           "ref": "가나다", "evals": {"content": i % 6}})
    probe = select_probe_rows(sample, 9)
    check("예비조사 표본 개수", len(probe), 9)
    check("중간 점수대만 뽑힘",
          all(1 <= human_score(r) <= 4 for r in probe), True)
    check("문항이 고루 섞임", len({r["prompt"] for r in probe}), 3)
    check("두 번 뽑으면 같은 표본",
          [r["id"] for r in select_probe_rows(sample, 9)], [r["id"] for r in probe])

    # ② 예비조사 요약 — 만장일치 칸과 갈린 칸을 정확히 세는가
    def fake(rid, temp, seed_i, met_a, met_b):
        return {"id": rid, "method": f"PROBE_t{temp}", "pass": f"s{seed_i}",
                "status": "ok", "temperature": temp,
                "items": [{"cid": "1", "met": met_a}, {"cid": "2", "met": met_b}]}

    records = []
    for i in range(PROBE_N_SEEDS):
        # 항목 1 은 늘 1(만장일치), 항목 2 는 절반씩 갈린다
        records.append(fake("R1", 1.0, i, 1, i % 2))
    summary = summarize_probe(records)
    check("잰 칸 수(항목 2개)", summary["n_cells_total"], 2)
    check("갈린 칸 수", summary["n_split_cells_total"], 1)
    check("갈린 비율", round(summary["split_rate_overall"], 3), 0.5)
    check("갈린 칸 확률", round(summary["by_temperature"]["1.0"]["split_prob_mean"], 3), 0.5)
    check("기준 넘으면 소프트 패스 켬", summary["soft_pass_enabled"], True)

    # 전부 만장일치면 소프트 패스를 끈다 — 이번 실험에서 가장 중요한 갈림길이다
    unanimous = [fake("R2", 1.0, i, 1, 0) for i in range(PROBE_N_SEEDS)]
    s2 = summarize_probe(unanimous)
    check("만장일치면 갈린 비율 0", s2["split_rate_overall"], 0.0)
    check("만장일치면 소프트 패스 끔", s2["soft_pass_enabled"], False)

    # 12번을 다 못 채운 칸은 세지 않는다(표본 수가 다른 칸을 섞지 않는다)
    partial = [fake("R3", 1.0, i, 1, i % 2) for i in range(PROBE_N_SEEDS - 1)]
    check("판정이 모자란 칸은 안 센다", summarize_probe(partial)["n_cells_total"], 0)

    # ③ 할 일 목록 — 답안 하나가 다섯 겹 체크리스트로 판정되는가
    fake_rows = [{"id": "A-1", "prompt": "문항A", "ref": "가", "speaker_id": "S1",
                  "evals": {"content": 3}}]
    fold_of = {"A-1": 2}
    checklists = {prompt_key("문항A"): {"folds": {
        str(k): {"status": "ok", "items": [{"id": "1", "question": "가?"}]}
        for k in range(N_FOLDS)}}}
    all_tasks = build_binary_tasks(fake_rows, fold_of, checklists, "main", {}, False)
    own_tasks = build_binary_tasks(fake_rows, fold_of, checklists, "rep1", {}, True)
    check("답안 하나 → 다섯 벌 판정", len(all_tasks), N_FOLDS)
    check("재현성은 자기 겹 한 벌만", len(own_tasks), 1)
    check("자기 겹 체크리스트 번호", own_tasks[0]["checklist_fold"], 2)
    check("이미 끝난 것은 뺀다",
          len(build_binary_tasks(fake_rows, fold_of, checklists, "main",
                                 {("A-1", "B3f0", "main"): {"status": "ok"}}, False)),
          N_FOLDS - 1)

    print_table(["항목", "나온 값", "기대", "판정"], rows_out)
    print("\n" + ("모두 통과" if ok else "실패한 항목이 있다"))
    return 0 if ok else 1


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(
        description="체크리스트 v3 로 이진 판정·확률 예비조사·소프트 패스를 돌린다")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_V3)
    ap.add_argument("--pass-tag", default="main",
                    help="이번 실행의 이름표. 재현성 실행은 rep1·rep2·rep3 로 준다")
    ap.add_argument("--probe", action="store_true", help="2단계: 확률 판정 예비조사만 돌린다")
    ap.add_argument("--soft", action="store_true",
                    help="소프트 패스를 돌린다(예비조사가 '가능'일 때만 허용)")
    ap.add_argument("--force-soft", action="store_true",
                    help="예비조사 결과와 무관하게 소프트 패스를 돌린다(권장하지 않음)")
    ap.add_argument("--repro", action="store_true",
                    help="재현성용 고정 부분표본(60건)만, 자기 겹 체크리스트로 돌린다")
    ap.add_argument("--repro-n", type=int, default=60)
    ap.add_argument("--pilot", action="store_true",
                    help="파일럿: 문항 2종 × 답안 5건만 돌려 형식·시간을 확인한다")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--rpm", type=int, default=DEFAULT_RPM)
    ap.add_argument("--self-test", action="store_true",
                    help="계산기만 예시 입력으로 점검하고 끝낸다")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    print(use_free_backup_key())
    print(f"판정 모델: {JUDGE_MODEL} · 본 판정은 온도 0 · "
          f"분당 {args.rpm}회 · 동시 {args.workers}개")

    # ── 표본과 겹 ────────────────────────────────────────────────────────────
    rows, counts = load_rows()
    print("\n=== 표본 고르기 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])
    fold_of, diag = assign_folds(rows, N_FOLDS)
    print(f"\n겹 나누기: 화자 단위 {N_FOLDS}겹 · 겹을 넘나든 화자 {diag['speaker_leak_count']}명"
          f" (앞 실험과 같은 함수·같은 배정)")

    # ── 체크리스트 확인 ──────────────────────────────────────────────────────
    checklists = load_checklists_v3()
    need = {prompt_key(r.get("prompt") or "") for r in rows}
    missing = [f"{p}/겹{k}" for p in sorted(need) for k in range(N_FOLDS)
               if not items_for(checklists, p, k)]
    if missing:
        print(f"\n[중단] v3 체크리스트가 없는 (문항,겹) {len(missing)}개: "
              f"{', '.join(missing[:8])}\n  먼저 gen_checklists_v3.py 를 돌려라.")
        return 1
    n_items = sum(len(items_for(checklists, p, k)) for p in need for k in range(N_FOLDS))
    print(f"체크리스트 v3: 문항 {len(need)}종 × 겹 {N_FOLDS}개 = {len(need) * N_FOLDS}벌 · "
          f"항목 {n_items}개 (벌당 평균 {n_items / (len(need) * N_FOLDS):.1f}개, 읽기만 한다)")

    # ── 2단계: 예비조사 ──────────────────────────────────────────────────────
    if args.probe:
        summary = run_probe(rows, checklists, fold_of, args.out, args.workers, args.rpm)
        return 0 if summary else 1

    # ── 표본 좁히기 ──────────────────────────────────────────────────────────
    if args.repro:
        rows = select_repro_subset(rows, args.repro_n)
        print(f"재현성용 고정 부분표본: {len(rows)}건 (v1·v2 와 같은 60건 — 같은 함수로 고른다)")
    elif args.pilot:
        buckets = group_by_prompt(rows)
        picked = []
        for pkey in list(buckets)[:2]:
            picked.extend(buckets[pkey][:5])
        rows = sorted(picked, key=lambda r: str(r["id"]))
        print(f"파일럿 표본: {len(rows)}건 (문항 2종 × 5건)")

    done = load_done(args.out)

    # ── 소프트 패스 ──────────────────────────────────────────────────────────
    if args.soft:
        probe = json.loads(Path(PROBE_PATH).read_text(encoding="utf-8")) \
            if Path(PROBE_PATH).exists() else {}
        if not probe.get("soft_pass_enabled") and not args.force_soft:
            print("\n[생략] 예비조사가 '확률 대체재를 쓸 수 없다'로 나왔다 —",
                  probe.get("verdict", "예비조사 결과 파일이 없다"))
            print("  소프트 패스를 돌리지 않는다. 정말 돌리려면 --force-soft 를 준다.")
            return 0
        tasks = build_soft_tasks(rows, fold_of, checklists, done)
        summary = run_tasks(tasks, args.out, args.workers, args.rpm, "소프트 패스")
        print(f"\n결과 파일: {args.out}")
        return 2 if summary.get("stopped") else 0

    # ── 이진 본 판정 ─────────────────────────────────────────────────────────
    tasks = build_binary_tasks(rows, fold_of, checklists, args.pass_tag, done,
                               own_fold_only=bool(args.repro))
    summary = run_tasks(tasks, args.out, args.workers, args.rpm,
                        f"이진 패스/{args.pass_tag}")
    print(f"\n결과 파일: {args.out}")
    return 2 if summary.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
