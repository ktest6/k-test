# -*- coding: utf-8 -*-
"""체크리스트 v4 판정 — **O/X 대신 확률로 받는다.**

■ 팀원 요청과, 그것을 어떻게 실현했는가

요청은 "판정을 O/X 가 아니라 정규화 확률 p(예)/(p(예)+p(아니오)) 로 받아서
가중치 학습을 다시 해 보자"였다.

3차(v3)에서 **Gemini 로는 불가능하다**는 것이 실측으로 확인됐다. 구글이 3.x 계열에서
logprobs 를 의도적으로 뺐고("WAI"), AI Studio 키로는 텍스트 모델 24개가 전부 400 이다.
그래서 **판정 창구만 OpenRouter 로 바꿨다.**

    모델    qwen/qwen3-30b-a3b-instruct-2507
    설정    temperature 0 · max_tokens 4 · logprobs · top_logprobs 8

■ 확률을 어떻게 만드는가 — "아니오"는 첫 토큰이 '아' 로 잘려 나온다

응답의 **첫 토큰**에 대해 후보 8개와 각각의 확률이 함께 온다. 실측하면 이렇다.

    충족한 답안 :  [('예', 0.999), ('네', 0.001), (' 예', 0.000), ...]
    미충족 답안 :  [('아', 1.000), ('예', 0.000), (' 아니', 0.000), ...]

"아니오"라는 낱말이 통째로 오지 않고 **'아' 한 글자로 잘려 온다.** 그래서 토큰을
그대로 견주면 안 되고, **첫 토큰 후보들을 '예 쪽'과 '아니오 쪽'으로 접어서** 센다.

    p = Σp(예 쪽) / (Σp(예 쪽) + Σp(아니오 쪽))

양쪽 어디에도 안 걸리는 답이 오면 **1회 다시 해 보고, 그래도 안 되면 실패로 적는다.**
확률을 0.5 로 채워 넣지 않는다 — 모르는 것을 '반반'이라고 적으면 그것이 데이터가 된다.

■ 항목 하나당 호출 하나다

한 번에 여러 항목을 물으면 답이 길어져 첫 토큰의 확률이 "첫 항목의 확률"이 아니라
"문장을 어떻게 시작할지"의 확률이 되어 버린다. 그래서 항목마다 따로 부른다.
그리고 **같은 호출에서 확률과 O/X(p>0.5)를 함께 얻는다** — 두 방식을 완전히 같은
조건에서 견주기 위해서다. 판정이 달라서 생긴 차이가 아니라 **읽는 법**만 다르다.

■ 이 판정에는 인용 근거가 없다 (반드시 알고 읽어야 할 한계)

v1~v3 의 이진 판정은 충족(1)마다 답안 원문 인용을 요구하고 원문에 없으면 폐기했다.
한 낱말짜리 답에는 인용을 붙일 자리가 없다. 그래서 v4 는 인용 검증을 **못 한다.**
대신 판정 한 줄마다 **첫 토큰 후보와 확률 원본을 그대로 저장**해서, 그 판정이 어떤
분포에서 나왔는지 나중에 따질 수 있게 했다. 이것은 실험용 타협이고,
**운영 채점에 그대로 쓸 수 있는 규약이 아니다.** 결과 JSON 에도 같은 말을 적어 둔다.

■ 공정 규칙 (앞 실험과 똑같이 유지한다)

  · 같은 답안 281건 · 같은 화자 단위 5겹(같은 함수·같은 배정) · 같은 사람 점수
  · 답안 하나를 **다섯 겹 체크리스트 전부로** 판정한다 — 가중치 학습에 학습 겹
    판정이 필요하기 때문이다. 성적은 언제나 자기 겹 판정으로만 낸다(누출 없음)
  · 입력은 음성이 아니라 사람이 직접 적은 전사(ref)
  · **판정 모델이 Qwen 으로 바뀌었으므로 v1~v3 와 직접 비교하지 않는다**

■ 비용 감시

응답에 실제 청구액(`usage.cost`)이 실려 온다. 그것을 더해 가며 로그에 찍고,
**누적 $4 를 넘으면 정중히 멈춘다**(크레딧 $10). 멈춰도 된 데까지는 파일에 남고,
같은 명령을 다시 실행하면 이어서 한다.

■ 앞 실험 도구·결과는 건드리지 않는다

`run_experiment.py`·`_v2`·`_v3` 와 그 결과 파일은 한 줄도 고치지 않았다.
v4 결과는 `judgments_v4.jsonl` 에 따로 쌓는다.

■ 쓰는 법

    python run_experiment_v4.py --pilot                 # 문항 2종 × 답안 3건 파일럿
    python run_experiment_v4.py                         # 본 판정 (281건 × 5겹 × 항목)
    python run_experiment_v4.py --pass-tag rep1 --repro # 재현성 60건 1회차(자기 겹만)
    python run_experiment_v4.py --self-test             # 계산기만 예시 입력으로 점검
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import (  # noqa: E402
    ASSESSMENT_DIR,
    N_FOLDS,
    OUT_DIR,
    append_record,
    assign_folds,
    enable_utf8_output,
    group_by_prompt,
    human_score,
    load_rows,
    print_table,
    prompt_key,
    select_repro_subset,
)
from gen_checklists_v4 import items_for_v4, load_checklists_v4  # noqa: E402

#: v4 판정 결과를 한 줄씩 쌓는 파일. v1·v2·v3 결과와 **다른 파일**이다.
DEFAULT_OUT_V4 = OUT_DIR / "judgments_v4.jsonl"

# ── 판정 창구: OpenRouter ────────────────────────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

#: 판정 모델. 한국어 판정이 정확하고 logprobs 가 정상으로 오며 값이 싸다(실측으로 고름).
JUDGE_MODEL_V4 = "qwen/qwen3-30b-a3b-instruct-2507"

#: 이 모델을 서비스하는 곳 중 **logprobs 를 실제로 돌려주는 곳만** 골라 쓴다.
#:
#: 왜 굳이 지정하나 (8/9 실측): OpenRouter 는 같은 모델이라도 여러 회사에 나눠 보낸다.
#: 그런데 Nebius·SiliconFlow 로 가면 `logprobs` 를 넣어도 **조용히 빼고 답만 준다**
#: (200 인데 logprobs 가 null). 그러면 확률을 못 만든다.
#: `require_parameters` 는 "내가 넣은 설정을 지원하는 곳으로만 보내라"는 뜻이고,
#: `only` 로 한 번 더 좁혀 값이 싼 곳부터 쓰게 한다. 어디로 갔는지는 줄마다 기록한다.
LOGPROB_PROVIDERS = ["StreamLake", "CoreWeave", "Alibaba"]
PROVIDER_PREFERENCE = {"only": LOGPROB_PROVIDERS, "require_parameters": True}

#: 한 번 부를 때의 설정. **확률을 깨끗하게 얻으려는 값들이라 바꾸면 안 된다.**
JUDGE_TEMPERATURE_V4 = 0.0
JUDGE_MAX_TOKENS_V4 = 4
JUDGE_TOP_LOGPROBS = 8
HTTP_TIMEOUT_SEC = 120

#: 실패했을 때 다시 해 보는 횟수(첫 시도 포함)와 쉬는 시간(초).
MAX_ATTEMPTS_V4 = 4
RETRY_SLEEP_SEC = (3, 10, 30)

#: ★ 비용 상한(달러). 누적 청구액이 이만큼을 넘으면 정중히 멈춘다.
#: 크레딧이 $10 이라 절반 아래에서 멈추게 잡아 두었다.
COST_STOP_USD = 4.0

#: 동시에 보낼 호출 수(기본). 429 가 없으면 --workers 로 16까지 올려도 된다.
DEFAULT_WORKERS_V4 = 8

# ── 첫 토큰을 '예 쪽/아니오 쪽'으로 접는 규칙 ────────────────────────────────
#: 앞뒤 공백을 떼고 소문자로 바꾼 뒤, 이 글자들로 **시작하면** 그 쪽으로 센다.
#: "아니오"가 '아' 한 글자로 잘려 오는 것이 이 규칙이 필요한 이유다.
YES_PREFIXES = ("예", "네", "응", "맞", "yes", "y")
NO_PREFIXES = ("아", "노", "틀", "no", "n")


def fold_token(token: str) -> str:
    """첫 토큰 후보 하나가 '예 쪽'인지 '아니오 쪽'인지 가른다.

    돌려주는 값은 "yes" · "no" · "" (어느 쪽도 아님) 셋 중 하나다.

    공백과 대소문자를 무시하는 이유: 같은 답이 '예'·' 예'·'Yes' 처럼 여러 모양으로
    오는데, 그것을 다른 답으로 세면 확률이 여러 조각으로 흩어져 값이 낮아진다.
    """
    text = str(token).strip().lower()
    if not text:
        return ""
    # '아니'가 '아'로도 잘려 오므로 아니오 쪽을 먼저 본다(둘 다 같은 쪽이라 순서는
    # 결과를 바꾸지 않지만, 읽는 사람이 헷갈리지 않게 순서를 못 박아 둔다)
    if text.startswith(NO_PREFIXES):
        return "no"
    if text.startswith(YES_PREFIXES):
        return "yes"
    return ""


def normalized_yes_prob(top_logprobs: list[dict]) -> tuple[float | None, dict]:
    """첫 토큰 후보들을 접어서 **정규화 확률 p(예)** 를 만든다.

    계산은 이렇다.
      ① 후보마다 logprob(로그 확률)을 확률로 되돌린다  → exp(logprob)
      ② '예 쪽'끼리, '아니오 쪽'끼리 각각 더한다
      ③ p = 예쪽 합 / (예쪽 합 + 아니오쪽 합)

    왜 그냥 p(예)를 안 쓰고 나누는가: 모델이 확률의 일부를 엉뚱한 토큰(줄바꿈,
    다른 언어 등)에 흘리기 때문에, 그대로 쓰면 '예'와 '아니오'가 둘 다 낮게 나온다.
    **둘 중 어느 쪽인가**만 알면 되므로 둘의 몫으로 다시 나눈다.

    양쪽 다 후보에 없으면 (None, 내역)을 돌려준다. 부르는 쪽이 한 번 더 시도한 뒤
    실패로 적는다. **임의로 0.5 를 채우지 않는다.**
    """
    detail = {"yes_mass": 0.0, "no_mass": 0.0, "other_mass": 0.0,
              "yes_tokens": [], "no_tokens": []}
    for cand in top_logprobs or []:
        token = cand.get("token", "")
        try:
            prob = math.exp(float(cand.get("logprob")))
        except (TypeError, ValueError):
            continue
        side = fold_token(token)
        if side == "yes":
            detail["yes_mass"] += prob
            detail["yes_tokens"].append(token)
        elif side == "no":
            detail["no_mass"] += prob
            detail["no_tokens"].append(token)
        else:
            detail["other_mass"] += prob

    total = detail["yes_mass"] + detail["no_mass"]
    if total <= 0:
        return None, detail
    return detail["yes_mass"] / total, detail


# ─────────────────────────────────────────────────────────────────────────────
# 판정 지시문 — 항목 하나만 묻고 한 낱말로 답하게 한다
# ─────────────────────────────────────────────────────────────────────────────
JUDGE_SYSTEM_V4 = """\
당신은 한국어 시험 답안이 항목 하나를 충족했는지 확인하는 판정 도구다.
점수를 매기지 않는다. 설명하지 않는다. 오직 '예' 또는 '아니오' 한 낱말로만 답한다.

판정 원칙:
1. 답안 원문에 근거가 있으면 '예', 없으면 '아니오' 다.
2. 근거가 없으면 주저 없이 '아니오' 라고 답한다. 너그럽게 봐주지 않는다.
3. 문법이나 어휘가 틀렸어도 내용을 전달했으면 충족으로 본다.
   문법은 다른 곳에서 따로 채점한다.
4. '예' 또는 '아니오' 외의 어떤 글자도 쓰지 않는다."""

JUDGE_PROMPT_V4 = """\
[문항 지시문]
{prompt_text}

[답안 원문]
```
{answer_text}
```

[확인할 항목]
{question}

위 항목을 이 답안이 충족했는가? '예' 또는 '아니오' 로만 답하라."""


def build_judge_prompt_v4(prompt_text: str, answer_text: str, question: str) -> str:
    """판정 지시문 하나를 만든다(항목 하나만 묻는다)."""
    return (JUDGE_PROMPT_V4
            .replace("{prompt_text}", prompt_text or "(지시문 없음)")
            .replace("{answer_text}", answer_text)
            .replace("{question}", question))


# ─────────────────────────────────────────────────────────────────────────────
# 비용 감시기
# ─────────────────────────────────────────────────────────────────────────────
class CostGuard:
    """실제 청구액을 더해 가며 상한을 넘으면 멈추게 하는 감시기.

    OpenRouter 는 응답의 `usage.cost` 에 **그 호출의 실제 청구액(달러)** 을 실어 준다.
    토큰 수로 우리가 어림하지 않고 그 값을 그대로 더한다 — 어림이 틀리면
    "안 넘었다고 생각했는데 넘은" 상황이 생기기 때문이다.

    멈춰도 결과를 버리지 않는다. 지금까지 된 것은 이미 파일에 한 줄씩 적혀 있고,
    안 된 것은 아무것도 안 적혀 있어서 다음 실행이 그대로 이어서 한다.
    """

    def __init__(self, limit_usd: float = COST_STOP_USD):
        self._lock = threading.Lock()
        self.limit = float(limit_usd)
        self.spent = 0.0
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.stop_reason = ""

    def add(self, usage: dict) -> None:
        """호출 하나가 끝날 때마다 청구액과 토큰 수를 더한다."""
        with self._lock:
            self.calls += 1
            self.spent += float((usage or {}).get("cost") or 0.0)
            self.prompt_tokens += int((usage or {}).get("prompt_tokens") or 0)
            self.completion_tokens += int((usage or {}).get("completion_tokens") or 0)
            if self.spent >= self.limit and not self.stop_reason:
                self.stop_reason = (
                    f"누적 비용 ${self.spent:.4f} 가 상한 ${self.limit:.2f} 에 닿았다. "
                    "여기서 정중히 멈춘다(된 것은 파일에 남아 있고 재실행이 이어서 한다)."
                )

    @property
    def stopped(self) -> bool:
        with self._lock:
            return bool(self.stop_reason)

    def snapshot(self) -> dict:
        with self._lock:
            return {"n_calls": self.calls, "cost_usd": round(self.spent, 6),
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "limit_usd": self.limit, "stop_reason": self.stop_reason}


# ─────────────────────────────────────────────────────────────────────────────
# OpenRouter 판정 클라이언트
# ─────────────────────────────────────────────────────────────────────────────
class OpenRouterProbJudge:
    """항목 하나를 물어 **확률과 O/X 를 한 번에** 받아 오는 판정기.

    채점 서버의 Gemini 래퍼(`src/llm/client.py`)를 쓰지 않는 이유는 단 하나 —
    그쪽은 Gemini 전용이고 logprobs 를 받을 길이 없기 때문이다.
    래퍼가 지키던 것들(온도 0 고정, 실패를 조용히 넘기지 않기, 사유를 남기기)은
    여기서도 똑같이 지킨다. **`assessment/src/` 는 한 줄도 고치지 않았다.**
    """

    def __init__(self, api_key: str = "", model: str = JUDGE_MODEL_V4):
        self.model = model
        self._api_key = api_key or self._key_from_env()
        self._session = None
        self._session_lock = threading.Lock()

    @staticmethod
    def _key_from_env() -> str:
        """`.env` 에서 OpenRouter 키를 읽는다. **`.env` 파일은 고치지 않는다.**"""
        from dotenv import dotenv_values

        values = dotenv_values(ASSESSMENT_DIR / ".env")
        return (os.getenv("OPENROUTER_API_KEY")
                or values.get("OPENROUTER_API_KEY") or "").strip()

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _get_session(self):
        """접속 통로를 하나 만들어 계속 쓴다(매번 새로 열면 느리다)."""
        import requests

        with self._session_lock:
            if self._session is None:
                self._session = requests.Session()
            return self._session

    def judge_once(self, prompt_text: str, answer_text: str, question: str) -> dict:
        """항목 하나를 한 번 물어 확률·O/X·원본 분포를 돌려준다.

        돌려주는 값의 status:
          "ok"       — 확률을 만들었다
          "no_label" — 첫 토큰 후보에 '예/아니오' 쪽이 하나도 없었다(확률 없음)
          "failed"   — 부르는 데 실패했다(사유 포함)
        """
        started = time.perf_counter()
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_V4},
                {"role": "user",
                 "content": build_judge_prompt_v4(prompt_text, answer_text, question)},
            ],
            "temperature": JUDGE_TEMPERATURE_V4,
            "max_tokens": JUDGE_MAX_TOKENS_V4,
            "logprobs": True,
            "top_logprobs": JUDGE_TOP_LOGPROBS,
            "provider": PROVIDER_PREFERENCE,
        }
        response = self._get_session().post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
            json=body, timeout=HTTP_TIMEOUT_SEC)
        elapsed = round(time.perf_counter() - started, 3)

        if response.status_code != 200:
            return {"status": "failed", "http_status": response.status_code,
                    "reason": f"HTTP {response.status_code}: {response.text[:200]}",
                    "elapsed_sec": elapsed,
                    "retryable": response.status_code in (408, 409, 429, 500, 502, 503, 504)}

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        content = ((choice.get("message") or {}).get("content") or "").strip()

        # 첫 토큰의 후보 목록을 꺼낸다. 이것이 없으면 확률을 만들 수 없다
        logprobs = choice.get("logprobs") or {}
        tokens = logprobs.get("content") or []
        top = (tokens[0].get("top_logprobs") if tokens else None) or []

        p_yes, detail = normalized_yes_prob(top)
        # 원본 분포를 그대로 남긴다. 이 판정이 어떤 분포에서 나왔는지가 유일한 근거다
        raw = [{"token": c.get("token"), "logprob": c.get("logprob"),
                "p": round(math.exp(float(c.get("logprob"))), 6)}
               for c in top if c.get("logprob") is not None]

        common = {
            "content": content,
            "top_logprobs": raw,
            "mass": {k: round(v, 6) for k, v in detail.items()
                     if k.endswith("_mass")},
            "provider": data.get("provider"),
            "usage": usage,
            "cost_usd": float(usage.get("cost") or 0.0),
            "elapsed_sec": elapsed,
        }
        if not top:
            return {"status": "no_label", "reason": "응답에 logprobs 가 없다(공급자 문제)",
                    "retryable": True, **common}
        if p_yes is None:
            return {"status": "no_label",
                    "reason": f"첫 토큰 후보에 예/아니오 쪽이 없다: {[c['token'] for c in raw]}",
                    "retryable": True, **common}

        return {"status": "ok", "p_yes": round(p_yes, 8),
                # ★ 같은 호출에서 확률과 O/X 를 함께 얻는다. 판정이 아니라 읽는 법만 다르다
                "met": int(p_yes > 0.5), **common}


def judge_with_retry(judge: OpenRouterProbJudge, prompt_text: str, answer_text: str,
                     question: str, guard: CostGuard, label: str = "") -> dict:
    """판정 한 건을 실패해도 몇 번 다시 해 본다.

    · 확률을 못 만든 경우(`no_label`)도 **한 번은 다시** 해 본다. 공급자가 바뀌면
      logprobs 가 오기도 하기 때문이다. 그래도 안 되면 실패로 적는다.
    · 비용 상한에 닿으면 더 부르지 않고 물러난다(`cost_stopped`). 이때는
      **아무것도 기록하지 않는다** — 시도조차 못 한 것을 실패로 적으면 그것도
      결과처럼 보이기 때문이다.
    """
    last = {}
    for attempt in range(1, MAX_ATTEMPTS_V4 + 1):
        if guard.stopped:
            return {"status": "cost_stopped", "reason": guard.stop_reason,
                    "attempts": attempt - 1}
        try:
            out = judge.judge_once(prompt_text, answer_text, question)
        except Exception as exc:
            out = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}",
                   "retryable": True, "elapsed_sec": 0.0}

        # 부르기는 했으므로 비용은 성공·실패와 무관하게 센다
        if out.get("usage"):
            guard.add(out["usage"])

        if out["status"] == "ok":
            out["attempts"] = attempt
            return out

        last = out
        if not out.get("retryable") or attempt >= MAX_ATTEMPTS_V4:
            break
        wait = RETRY_SLEEP_SEC[min(attempt - 1, len(RETRY_SLEEP_SEC) - 1)]
        print(f"      판정 실패({attempt}/{MAX_ATTEMPTS_V4}) {label} — "
              f"{str(out.get('reason'))[:80]} / {wait}초 쉬고 다시")
        time.sleep(wait)

    last["attempts"] = MAX_ATTEMPTS_V4
    return last


# ─────────────────────────────────────────────────────────────────────────────
# 이어서 하기 — 항목 한 칸이 결과 한 줄이다
# ─────────────────────────────────────────────────────────────────────────────
def record_key_v4(rec: dict) -> tuple[str, str, str, str]:
    """결과 한 줄을 가리키는 열쇠. (답안 id, 체크리스트 겹, 항목 id, 몇 번째 실행)."""
    return (str(rec.get("id")), str(rec.get("checklist_fold")),
            str(rec.get("item_id")), str(rec.get("pass")))


def load_done_v4(path: Path) -> dict[tuple[str, str, str, str], dict]:
    """이미 끝낸 판정을 읽어 온다. 다시 실행할 때 건너뛰기 위한 것이다.

    같은 열쇠가 여러 번 적혀 있으면 **나중 것이 이긴다**(앞서 실패로 적힌 줄을
    나중에 성공으로 덮어쓸 수 있어야 재실행이 뜻을 가진다).
    항목 하나가 한 줄이라 파일이 크지만, 한 칸씩 이어서 할 수 있는 것이 그 값이다.
    """
    done: dict[tuple[str, str, str, str], dict] = {}
    if not Path(path).exists():
        return done
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # 실행 중에 끊겨 마지막 줄이 잘렸을 수 있다. 그 줄만 버리고 나머지는 쓴다
                continue
            done[record_key_v4(rec)] = rec
    return done


def build_tasks_v4(rows, fold_of, checklists, pass_tag, done, own_fold_only: bool):
    """판정 할 일 목록을 만든다(항목 하나가 할 일 하나). **이미 성공한 것은 뺀다.**

    `own_fold_only=True` 면 답안마다 **자기 겹의 체크리스트**로만 판정한다
    (재현성 실행이 그렇다 — 실제 채점에 쓰이는 배치만 되풀이해서 재면 된다).
    """
    tasks = []
    for row in rows:
        rid = str(row["id"])
        pkey = prompt_key(row.get("prompt") or "")
        folds = [fold_of[rid]] if own_fold_only else list(range(N_FOLDS))
        for fold in folds:
            for item in items_for_v4(checklists, pkey, fold):
                key = (rid, str(fold), str(item["id"]), pass_tag)
                if (done.get(key) or {}).get("status") == "ok":
                    continue
                tasks.append({"row": row, "pkey": pkey, "checklist_fold": fold,
                              "fold": fold_of[rid], "pass_tag": pass_tag, "item": item})
    return tasks


def run_tasks_v4(tasks, out_path: Path, workers: int, label: str,
                 cost_limit: float) -> dict:
    """할 일을 겹쳐서 돌리고 한 건씩 파일에 적는다.

    **동시에 여러 개를 보내도 결과는 달라지지 않는다** — 판정은 답안 하나와 항목
    하나만 보고 그 결과를 낸다. 옆 항목의 결과를 참고하지도, 처리 순서를 보지도 않는다.
    """
    total = len(tasks)
    print(f"\n=== [{label}] 할 일 {total}건 (항목 한 칸이 한 건 · 이미 끝난 것 제외) ===")
    if not total:
        return {"total": 0, "ok": 0, "failed": 0, "stopped": False, "elapsed": 0.0,
                "cost": {}}

    judge = OpenRouterProbJudge()
    if not judge.available:
        print("[중단] OPENROUTER_API_KEY 가 없다. assessment/.env 를 확인하라.")
        return {"total": total, "ok": 0, "failed": 0, "stopped": True,
                "stop_reason": "키 없음", "elapsed": 0.0, "cost": {}}

    guard = CostGuard(cost_limit)
    counters = {"ok": 0, "failed": 0, "no_label": 0, "skipped_cost": 0}
    providers: dict[str, int] = {}
    started = time.perf_counter()
    lock = threading.Lock()

    def one(index: int, task: dict) -> None:
        row, item = task["row"], task["item"]
        rid = str(row["id"])
        outcome = judge_with_retry(
            judge, row.get("prompt") or "", (row.get("ref") or "").strip(),
            item["question"], guard, label=f"{rid[-12:]}/항목{item['id']}")

        # 비용 상한에 닿아 물러난 경우에는 아무것도 적지 않는다
        if outcome["status"] == "cost_stopped":
            with lock:
                counters["skipped_cost"] += 1
            return

        append_record(out_path, {
            "id": rid, "method": f"P4f{task['checklist_fold']}", "pass": task["pass_tag"],
            "prompt_key": task["pkey"],
            "speaker_id": str(row.get("speaker_id") or rid.split("-")[0]),
            "fold": task["fold"], "checklist_fold": task["checklist_fold"],
            "is_own_fold": task["fold"] == task["checklist_fold"],
            "human_score": human_score(row), "answer_chars": len(row.get("ref") or ""),
            "item_id": str(item["id"]), "question": item["question"],
            "difficulty": item.get("difficulty"), "importance": item.get("importance"),
            "category": item.get("category"),
            "model": JUDGE_MODEL_V4, "checklist_version": "v4",
            "temperature": JUDGE_TEMPERATURE_V4,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **outcome})

        with lock:
            if outcome["status"] == "ok":
                counters["ok"] += 1
                providers[str(outcome.get("provider"))] = \
                    providers.get(str(outcome.get("provider")), 0) + 1
            elif outcome["status"] == "no_label":
                counters["no_label"] += 1
            else:
                counters["failed"] += 1
            done_now = counters["ok"] + counters["failed"] + counters["no_label"]

        if outcome["status"] != "ok":
            print(f"   [{index:5d}/{total}] {outcome['status']}: "
                  f"{str(outcome.get('reason'))[:80]}")
        elif done_now % 500 == 0:
            snap = guard.snapshot()
            rate = done_now / max(1e-9, time.perf_counter() - started)
            print(f"   [{done_now:5d}/{total}] 진행 · 누적 ${snap['cost_usd']:.4f}"
                  f"/${snap['limit_usd']:.2f} · {rate:.1f}건/초 · "
                  f"남은 시간 약 {(total - done_now) / max(rate, 1e-9) / 60:.1f}분")

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ktest-cl4") as pool:
        futures = []
        for i, task in enumerate(tasks, 1):
            if guard.stopped:
                print(f"   [{i:5d}/{total}] 이후 {total - i + 1}건은 손대지 않고 남긴다")
                counters["skipped_cost"] += total - i + 1
                break
            futures.append(pool.submit(one, i, task))
        for fut in futures:
            try:
                fut.result()
            except Exception as exc:
                print(f"   일꾼에서 예외: {type(exc).__name__}: {str(exc)[:150]}")

    elapsed = time.perf_counter() - started
    snap = guard.snapshot()
    print(f"\n   [{label}] {total}건 시도 · 성공 {counters['ok']} · "
          f"확률없음 {counters['no_label']} · 실패 {counters['failed']} · "
          f"비용으로 보류 {counters['skipped_cost']}")
    print(f"   {elapsed:.0f}초 ({elapsed / 60:.1f}분) · 건당 {elapsed / max(1, total):.2f}초 · "
          f"실제 비용 ${snap['cost_usd']:.4f} · 토큰 입력 {snap['prompt_tokens']:,}")
    if providers:
        print(f"   판정한 곳: {providers}")
    if guard.stopped:
        print(f"\n   ※ {snap['stop_reason']}")
    return {"total": total, "elapsed": round(elapsed, 1), "stopped": guard.stopped,
            "cost": snap, "providers": providers, **counters}


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

    def close(label, got, want, tol=1e-6):
        nonlocal ok
        passed = got is not None and abs(got - want) < tol
        ok &= passed
        rows_out.append([label, f"{got}", f"{want}", "통과" if passed else "실패"])

    print("=== 계산기 자체 점검 (run_experiment_v4) ===")

    # ① 토큰 접기 — '아니오'가 '아'로 잘려 와도 아니오 쪽으로 세는가
    check("'예' → 예 쪽", fold_token("예"), "yes")
    check("' 예'(앞 공백) → 예 쪽", fold_token(" 예"), "yes")
    check("'네' → 예 쪽", fold_token("네"), "yes")
    check("'Yes' → 예 쪽", fold_token("Yes"), "yes")
    check("'아' → 아니오 쪽 (핵심)", fold_token("아"), "no")
    check("'아니오' → 아니오 쪽", fold_token("아니오"), "no")
    check("' 아니' → 아니오 쪽", fold_token(" 아니"), "no")
    check("'No' → 아니오 쪽", fold_token("No"), "no")
    check("'은' → 어느 쪽도 아님", fold_token("은"), "")
    check("빈 토큰 → 어느 쪽도 아님", fold_token("  "), "")

    # ② 정규화 확률 — 딱 떨어지는 값으로 확인한다
    def cand(token, prob):
        return {"token": token, "logprob": math.log(prob)}

    p, detail = normalized_yes_prob([cand("예", 0.6), cand("아", 0.2), cand("은", 0.2)])
    close("예0.6·아0.2 → p=0.75", p, 0.75)
    close("남은 확률은 other 로 센다", detail["other_mass"], 0.2)

    # 흩어진 '예' 표기를 하나로 접는가 (접지 않으면 0.5 가 나온다)
    p2, _ = normalized_yes_prob([cand("예", 0.3), cand(" 예", 0.2), cand("네", 0.1),
                                 cand("아", 0.4)])
    close("예 쪽 세 조각을 합친다 → 0.6", p2, 0.6)

    # 실측 응답과 같은 모양
    p3, _ = normalized_yes_prob([cand("예", 0.999), cand("네", 0.001)])
    rows_out.append(["충족 답안 실측 모양", f"{p3:.4f}", "1에 가깝다",
                     "통과" if p3 > 0.99 else "실패"])
    ok &= p3 > 0.99
    p4, _ = normalized_yes_prob([cand("아", 0.9999), cand("예", 0.0001)])
    rows_out.append(["미충족 답안 실측 모양", f"{p4:.4f}", "0에 가깝다",
                     "통과" if p4 < 0.01 else "실패"])
    ok &= p4 < 0.01

    # 양쪽 다 없으면 None — **임의로 0.5 를 채우지 않는다**
    p5, _ = normalized_yes_prob([cand("은", 0.5), cand("그", 0.5)])
    check("예/아니오 쪽이 없으면 None", p5, None)
    check("후보가 아예 없어도 None", normalized_yes_prob([])[0], None)

    # ③ O/X 는 확률에서 바로 나온다(같은 호출·같은 판정, 읽는 법만 다르다)
    check("p=0.75 → 충족", int(0.75 > 0.5), 1)
    check("p=0.40 → 미충족", int(0.40 > 0.5), 0)

    # ④ 비용 감시 — 상한에 닿으면 멈춤 표시가 선다
    guard = CostGuard(0.01)
    guard.add({"cost": 0.004, "prompt_tokens": 100, "completion_tokens": 1})
    check("상한 전에는 안 멈춘다", guard.stopped, False)
    guard.add({"cost": 0.007, "prompt_tokens": 100, "completion_tokens": 1})
    check("상한에 닿으면 멈춘다", guard.stopped, True)
    check("실제 청구액을 더한다", round(guard.snapshot()["cost_usd"], 4), 0.011)
    check("토큰도 센다", guard.snapshot()["prompt_tokens"], 200)

    # ⑤ 할 일 목록 — 답안 하나가 다섯 겹 × 항목 수만큼 생기는가
    fake_rows = [{"id": "A-1", "prompt": "문항A", "ref": "가", "speaker_id": "S1",
                  "evals": {"content": 3}}]
    fold_of = {"A-1": 2}
    checklists = {prompt_key("문항A"): {"folds": {
        str(k): {"status": "ok", "items": [{"id": "1", "question": "가?"},
                                           {"id": "2", "question": "나?"}]}
        for k in range(N_FOLDS)}}}
    all_tasks = build_tasks_v4(fake_rows, fold_of, checklists, "main", {}, False)
    own_tasks = build_tasks_v4(fake_rows, fold_of, checklists, "rep1", {}, True)
    check("답안 하나 → 5겹 × 항목 2개", len(all_tasks), N_FOLDS * 2)
    check("재현성은 자기 겹만 → 항목 2개", len(own_tasks), 2)
    check("자기 겹 번호", own_tasks[0]["checklist_fold"], 2)
    check("이미 끝난 한 칸은 뺀다",
          len(build_tasks_v4(fake_rows, fold_of, checklists, "main",
                             {("A-1", "0", "1", "main"): {"status": "ok"}}, False)),
          N_FOLDS * 2 - 1)
    check("실패로 적힌 칸은 다시 한다",
          len(build_tasks_v4(fake_rows, fold_of, checklists, "main",
                             {("A-1", "0", "1", "main"): {"status": "failed"}}, False)),
          N_FOLDS * 2)

    # ⑥ 결과 줄 열쇠 — 항목까지 갈라야 한 칸씩 이어서 할 수 있다
    check("열쇠에 항목 id 가 들어간다",
          record_key_v4({"id": "A-1", "checklist_fold": 3, "item_id": "2", "pass": "main"}),
          ("A-1", "3", "2", "main"))

    # ⑦ 지시문에 답안과 항목이 실제로 들어가는가
    prompt = build_judge_prompt_v4("문항 지시문", "저는 시장에 갔습니다", "장소를 말했는가?")
    check("지시문에 답안이 들어간다", "저는 시장에 갔습니다" in prompt, True)
    check("지시문에 항목이 들어간다", "장소를 말했는가?" in prompt, True)
    check("항목은 하나만 묻는다", prompt.count("[확인할 항목]"), 1)

    print_table(["항목", "나온 값", "기대", "판정"], rows_out)
    print("\n" + ("모두 통과" if ok else "실패한 항목이 있다"))
    return 0 if ok else 1


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(
        description="체크리스트 v4 를 OpenRouter logprobs 확률로 판정한다(항목당 호출 1회)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_V4)
    ap.add_argument("--pass-tag", default="main",
                    help="이번 실행의 이름표. 재현성 실행은 rep1·rep2·rep3 로 준다")
    ap.add_argument("--repro", action="store_true",
                    help="재현성용 고정 부분표본(60건)만, 자기 겹 체크리스트로 돌린다")
    ap.add_argument("--repro-n", type=int, default=60)
    ap.add_argument("--pilot", action="store_true",
                    help="파일럿: 문항 2종 × 답안 3건만 돌려 형식·시간·비용을 확인한다")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS_V4)
    ap.add_argument("--cost-limit", type=float, default=COST_STOP_USD,
                    help="누적 청구액 상한(달러). 넘으면 정중히 멈춘다")
    ap.add_argument("--self-test", action="store_true",
                    help="계산기만 예시 입력으로 점검하고 끝낸다")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    print(f"판정 모델: {JUDGE_MODEL_V4} (OpenRouter) · 온도 {JUDGE_TEMPERATURE_V4} · "
          f"logprobs top {JUDGE_TOP_LOGPROBS} · 동시 {args.workers}개")
    print(f"공급자: {LOGPROB_PROVIDERS} 중에서만 (logprobs 를 실제로 주는 곳)")
    print(f"비용 상한: ${args.cost_limit:.2f}")
    print("※ 판정 모델이 v1~v3(Gemini)와 다르다. 앞 실험과 직접 비교하지 않는다.")

    # ── 표본과 겹 ────────────────────────────────────────────────────────────
    rows, counts = load_rows()
    print("\n=== 표본 고르기 ===")
    print_table(["단계", "건수"], [[k, v] for k, v in counts.items()])
    fold_of, diag = assign_folds(rows, N_FOLDS)
    print(f"\n겹 나누기: 화자 단위 {N_FOLDS}겹 · 겹을 넘나든 화자 {diag['speaker_leak_count']}명"
          f" (앞 실험과 같은 함수·같은 배정)")

    # ── 체크리스트 확인 ──────────────────────────────────────────────────────
    checklists = load_checklists_v4()
    need = {prompt_key(r.get("prompt") or "") for r in rows}
    missing = [f"{p}/겹{k}" for p in sorted(need) for k in range(N_FOLDS)
               if not items_for_v4(checklists, p, k)]
    if missing:
        print(f"\n[중단] v4 체크리스트가 없는 (문항,겹) {len(missing)}개: "
              f"{', '.join(missing[:8])}\n  먼저 gen_checklists_v4.py 를 돌려라.")
        return 1
    n_items = sum(len(items_for_v4(checklists, p, k)) for p in need for k in range(N_FOLDS))
    print(f"체크리스트 v4: 문항 {len(need)}종 × 겹 {N_FOLDS}개 = {len(need) * N_FOLDS}벌 · "
          f"항목 {n_items}개 (벌당 평균 {n_items / (len(need) * N_FOLDS):.2f}개, 읽기만 한다)")

    # ── 표본 좁히기 ──────────────────────────────────────────────────────────
    if args.repro:
        rows = select_repro_subset(rows, args.repro_n)
        print(f"재현성용 고정 부분표본: {len(rows)}건 (v1~v3 와 같은 60건 — 같은 함수로 고른다)")
    elif args.pilot:
        buckets = group_by_prompt(rows)
        picked = []
        for pkey in list(buckets)[:2]:
            picked.extend(buckets[pkey][:3])
        rows = sorted(picked, key=lambda r: str(r["id"]))
        print(f"파일럿 표본: {len(rows)}건 (문항 2종 × 3건)")

    done = load_done_v4(args.out)
    print(f"이미 적힌 판정: {len(done)}칸")

    tasks = build_tasks_v4(rows, fold_of, checklists, args.pass_tag, done,
                           own_fold_only=bool(args.repro))
    summary = run_tasks_v4(tasks, args.out, args.workers,
                           f"확률 판정/{args.pass_tag}", args.cost_limit)
    print(f"\n결과 파일: {args.out}")
    return 2 if summary.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
