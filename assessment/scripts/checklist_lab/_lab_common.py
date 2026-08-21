# -*- coding: utf-8 -*-
"""체크리스트 실험실이 함께 쓰는 도구 상자.

이 폴더(`scripts/checklist_lab/`)는 **실험 코드만** 둔다.
실제 채점에 쓰이는 코드는 `assessment/src/` 에 있고, 여기서는 그것을 **읽기만** 한다
(한 줄도 고치지 않는다). 실험하려고 진짜 채점 코드를 손대면
여기서 나온 숫자가 서비스의 숫자가 아니게 되기 때문이다.

여기 모아 둔 것 네 가지:
  ① 데이터 고르기 — AI Hub 목록에서 실험 대상 답안을 걸러 낸다
  ② 겹 나누기   — 같은 사람이 배우는 쪽과 시험 보는 쪽에 동시에 들어가지 않게 가른다
  ③ 재는 자     — QWK(등급 일치도)·상관·부트스트랩 신뢰구간
  ④ 이어서 하기 — 중간에 끊겨도 다음 실행이 남은 것부터 하도록 한 줄씩 저장

'재는 자'를 한 곳에만 두는 이유: 스크립트마다 조금씩 다른 계산을 쓰면
어제 잰 숫자와 오늘 잰 숫자를 나란히 놓을 수 없게 된다.
"""

from __future__ import annotations

import glob
import json
import math
import os
import random
import sys
import threading
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

# ── 폴더 위치 ────────────────────────────────────────────────────────────────
#: 이 파일 = assessment/scripts/checklist_lab/_lab_common.py 이므로 두 칸 위가 assessment
ASSESSMENT_DIR = Path(__file__).resolve().parents[2]
#: 저장소 최상위 (C:\해커톤)
REPO_ROOT = ASSESSMENT_DIR.parent
#: AI Hub 목록 파일들이 사는 곳
MANIFEST_DIR = REPO_ROOT / "data" / "manifests"
#: 이 실험이 만들어 내는 것들을 모아 두는 곳
OUT_DIR = ASSESSMENT_DIR / "outputs" / "checklist_lab"

# ── 실험 조건: 고정값 ────────────────────────────────────────────────────────
#: 자유 발화 과제만 쓴다. 낭독(LAR)은 읽을 문장이 정해져 있어서
#: '무슨 내용을 말했는가'를 잴 수 없다(읽으라는 대로 읽으면 내용은 언제나 같다).
TASK = "ATQ"

#: 사람 점수를 어느 칸에서 읽을지. AI Hub 전문 평가자가 매긴 '내용 및 과제 수행' 0~5 점이다.
HUMAN_SCORE_KEY = "content"

#: 점수가 가질 수 있는 값. 6단계다.
SCORE_LABELS = (0, 1, 2, 3, 4, 5)

#: 스키마가 달라 섞을 수 없는 목록 파일(전사·평가 칸의 뜻이 다르다).
EXCLUDED_MANIFESTS = ("gold_team399",)

#: 한 문항에 답안이 이만큼은 있어야 실험 대상으로 삼는다.
#: 문항마다 가중치를 배우는 방식(C)이 있어서, 너무 적으면 배울 것이 없다.
MIN_ROWS_PER_PROMPT = 25

#: 겹(fold) 수. 화자 단위로 가른다.
N_FOLDS = 5

#: 부트스트랩(다시뽑기) 횟수와 씨앗값.
N_BOOTSTRAP = 1000
SEED = 20260809

#: 판정에 쓰는 모델. **세 방식이 모두 같은 모델·같은 온도 0 을 쓴다.**
#: 이것이 공정 비교의 전제라서 방식마다 모델을 바꾸는 실험은 하지 않는다.
JUDGE_MODEL = "gemini-3.1-flash-lite"

#: 한 번 부를 때 기다려 주는 시간(밀리초)과 답변 길이 예산.
#: 판정 모델(lite)은 생각을 길게 하지 않아 서버 기본값보다 작게 잡아도 잘린 적이 없다.
JUDGE_TIMEOUT_MS = 180_000
JUDGE_MAX_OUTPUT_TOKENS = 8_192

#: LLM 판정이 실패했을 때 다시 해 보는 횟수(첫 시도 포함)와 쉬는 시간(초).
LLM_MAX_ATTEMPTS = 4
LLM_RETRY_SLEEP_SEC = (5, 15, 40)

#: 429(사용량 초과)가 이만큼 연달아 나오면 한도가 바닥난 것으로 보고 정중히 멈춘다.
#: 다만 아래 설명대로 **분당 한도에 걸린 429 는 여기 세지 않는다.**
QUOTA_STOP_AFTER = 6

#: 1분에 몇 번까지 부를지. **무료 등급의 진짜 벽은 '분당 15회'다**(8/9 실측).
#:
#: 처음에는 429 를 '하루치 소진'으로 보고 멈추게 해 두었는데, 실제로 서버가 보낸 사유는
#:   quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier, quotaValue: 15
#:   "Please retry in 22.9s"
#: 였다. 즉 **잠깐 기다리면 풀리는 벽**이지 오늘치가 끝난 것이 아니었다.
#: 그래서 멈추는 대신 **처음부터 그 속도에 맞춰 천천히 부른다.**
#: 15가 아니라 13으로 잡은 이유는 서버가 세는 1분 구간과 우리가 세는 구간이
#: 조금씩 어긋나기 때문이다. 딱 15로 맞추면 경계에서 계속 부딪힌다.
DEFAULT_RPM = 13

#: 분당 한도에 걸렸을 때, 재시도 횟수와 별도로 몇 번까지 기다려 줄지.
#: 기다려서 풀리는 실패를 '판정 실패'로 세면 표본이 애먼 이유로 줄어든다.
MAX_RATE_WAITS = 10


def enable_utf8_output() -> None:
    """윈도우 명령창에서 한글이 깨지지 않게 출력 형식을 UTF-8 로 맞춘다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            # 출력이 파일로 넘어가 있는 등 바꿀 수 없는 경우는 그냥 넘어간다
            pass


# ── ① 데이터 고르기 ──────────────────────────────────────────────────────────
def load_rows(
    manifest_dir: Path = MANIFEST_DIR,
    min_per_prompt: int = MIN_ROWS_PER_PROMPT,
) -> tuple[list[dict], dict[str, int]]:
    """실험에 쓸 답안을 조건 네 개로 걸러 낸다.

    조건은 순서대로 이렇다.
      1) 여러 목록 파일에 같은 답안이 중복으로 들어 있으므로 id 로 하나만 남긴다
      2) 자유 발화(ATQ) 과제인가
      3) 사람이 매긴 '내용 및 과제 수행' 점수가 있는가
      4) 그 문항에 답안이 충분히 모였는가(기본 25건 이상)

    ※ **입력은 음성이 아니라 사람이 직접 적은 전사(`ref`)를 쓴다.**
      받아쓰기 기계를 끼우면 '채점 방식의 차이'와 '받아쓰기 오차'가 뒤섞여서,
      세 방식 중 무엇이 나은지가 아니라 그날 받아쓰기가 잘됐는지를 재게 된다.
      이번 실험의 질문은 오직 "같은 글을 놓고 채점 방식만 바꾸면 어떻게 되는가"다.

    돌려주는 값은 (걸러 낸 목록, 단계별로 몇 건이 남았는지)다.
    숫자를 함께 내는 이유는 예상과 다른 건수가 나왔을 때 어느 단계에서
    어긋났는지 바로 알 수 있게 하려는 것이다.
    """
    # 1) 여러 파일에 흩어져 있는 줄을 id 로 하나만 남기며 모은다.
    #    파일 이름 순서를 고정해야 같은 id 가 중복될 때 늘 같은 줄이 남는다
    seen: dict[str, dict] = {}
    files = sorted(glob.glob(str(Path(manifest_dir) / "*.jsonl")))
    for path in files:
        if any(bad in Path(path).name for bad in EXCLUDED_MANIFESTS):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = row.get("id")
                if rid and rid not in seen:
                    seen[rid] = row

    counts = {"목록 파일 수": len(files), "중복 제거 후 전체": len(seen)}

    # 2) 자유 발화만
    rows = [r for r in seen.values() if r.get("task") == TASK]
    counts[f"{TASK}만"] = len(rows)

    # 3) 사람 점수가 있는 것만. 견줄 대상이 없으면 실험에 쓸 수 없다
    rows = [r for r in rows if (r.get("evals") or {}).get(HUMAN_SCORE_KEY) is not None]
    counts["사람 점수(content) 있음"] = len(rows)

    # 4) 답안이 충분히 모인 문항만 남긴다
    per_prompt = Counter(r.get("prompt") or "" for r in rows)
    rows = [r for r in rows if per_prompt[r.get("prompt") or ""] >= min_per_prompt]
    counts[f"문항당 {min_per_prompt}건 이상"] = len(rows)
    counts["대상 문항 수"] = len({r.get("prompt") for r in rows})

    # 목록 파일의 줄 순서에 결과가 좌우되지 않도록 id 로 줄을 세운다.
    # 몇 번을 돌려도 늘 같은 순서로 처리된다
    rows.sort(key=lambda r: str(r.get("id")))
    return rows, counts


def prompt_key(prompt_text: str) -> str:
    """문항 지시문을 짧은 이름표로 바꾼다(파일과 표에 쓰기 위해서다).

    지시문 자체를 열쇠로 쓰면 표가 지시문 전문으로 뒤덮이므로,
    글자에서 만든 고정 번호를 붙인다. 같은 지시문이면 늘 같은 이름표가 나온다.
    """
    import hashlib

    digest = hashlib.sha1((prompt_text or "").encode("utf-8")).hexdigest()[:8]
    return f"P{digest}"


def group_by_prompt(rows: list[dict]) -> dict[str, list[dict]]:
    """답안을 문항별로 묶는다. 문항 이름표 순서와 각 묶음의 id 순서를 고정한다."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[prompt_key(r.get("prompt") or "")].append(r)
    for key in buckets:
        buckets[key].sort(key=lambda r: str(r.get("id")))
    return dict(sorted(buckets.items()))


def human_score(row: dict) -> int:
    """이 답안에 사람이 매긴 '내용 및 과제 수행' 점수(0~5)."""
    return int((row.get("evals") or {})[HUMAN_SCORE_KEY])


def select_repro_subset(rows: list[dict], n: int = 60) -> list[dict]:
    """재현성 시험에 쓸 고정 부분표본을 고른다. **문항이 고루 섞이게** 뽑는다.

    한 문항에서만 60건을 뽑으면 그 문항이 유난히 쉬웠거나 어려웠을 때
    '흔들림'이 아니라 '그 문항의 성질'을 재게 된다.
    그래서 문항을 한 바퀴씩 돌며 하나씩 가져온다(라운드 로빈).
    각 문항 안에서는 점수 순으로 줄을 세워 가져오므로 점수대도 함께 퍼진다.

    무작위를 쓰지 않으므로 몇 번을 돌려도 **같은 60건**이 나온다.
    재현성을 재는 실험에서 표본이 실행마다 바뀌면 아무것도 재지 못한다.
    """
    buckets = group_by_prompt(rows)
    queues = {
        pkey: sorted(items, key=lambda r: (human_score(r), str(r["id"])))
        for pkey, items in buckets.items()
    }
    picked: list[dict] = []
    turn = 0
    # 문항을 한 바퀴씩 돌며 하나씩 가져온다. 다 떨어진 문항은 그냥 지나간다
    while len(picked) < n and any(queues.values()):
        for pkey in sorted(queues):
            queue = queues[pkey]
            if turn < len(queue):
                picked.append(queue[turn])
                if len(picked) >= n:
                    break
        turn += 1
    picked.sort(key=lambda r: str(r["id"]))
    return picked


# ── ② 겹 나누기 ──────────────────────────────────────────────────────────────
def assign_folds(
    rows: list[dict], n_folds: int = N_FOLDS
) -> tuple[dict[str, int], dict]:
    """답안마다 몇 번째 겹에서 시험을 볼지 정한다. **화자 단위**로 가른다.

    왜 화자 단위인가:
    같은 사람의 답안이 배우는 쪽과 시험 보는 쪽에 나뉘어 들어가면, 모델이
    '내용을 잘 말했는지'가 아니라 '그 사람의 말버릇'을 외워서 점수가 부풀려진다.

    어떻게 고루 퍼뜨리나:
    문항 안에서 답안을 **점수 순으로 줄 세운 뒤 차례로 돌려 가며** 겹을 준다.
    그러면 한 겹에 낮은 점수만 몰리는 일이 없다. 문항당 27~40건뿐이라
    한 겹에 5~8건씩만 들어가므로, 여기서 치우치면 숫자가 통째로 흔들린다.

    한 사람이 여러 문항에 답한 경우(실측 270명 중 11명)는 **먼저 정해진 겹을
    그대로 따른다.** 그래야 그 사람이 어느 문항에서도 배우는 쪽과 시험 보는 쪽에
    동시에 들어가지 않는다.

    무작위를 쓰지 않는다. 줄 세우는 규칙만으로 정해지므로 몇 번을 돌려도 같은 배정이 나온다.

    돌려주는 값은 (답안 id -> 겹 번호, 점검 결과)다.
    """
    buckets = group_by_prompt(rows)
    speaker_fold: dict[str, int] = {}
    fold_of: dict[str, int] = {}

    for prompt_index, (pkey, items) in enumerate(buckets.items()):
        # 점수 순으로 줄을 세운다(같은 점수면 id 순). 그 줄을 차례로 겹에 나눠 준다
        ordered = sorted(items, key=lambda r: (human_score(r), str(r["id"])))
        # 문항마다 시작 겹을 한 칸씩 옮긴다. 모든 문항이 0번 겹부터 시작하면
        # 각 문항의 '가장 낮은 점수'가 전부 0번 겹에 몰린다
        cursor = prompt_index % n_folds
        for row in ordered:
            speaker = str(row.get("speaker_id") or row["id"].split("-")[0])
            fold = speaker_fold.get(speaker)
            if fold is None:
                fold = cursor % n_folds
                cursor += 1
                speaker_fold[speaker] = fold
            fold_of[str(row["id"])] = fold

    diagnostics = check_folds(rows, fold_of, n_folds)
    return fold_of, diagnostics


def check_folds(rows: list[dict], fold_of: dict[str, int], n_folds: int) -> dict:
    """겹 나누기가 실제로 쓸 만한지 확인한다.

    두 가지를 본다.
      ① 같은 사람이 배우는 쪽과 시험 보는 쪽에 동시에 들어가지 않는가(0명이어야 한다)
      ② 문항마다 모든 겹에 시험 볼 답안이 들어 있고, 배울 답안도 충분한가

    ②가 깨지면 문항별 학습(C)과 앵커 뽑기(A1)가 성립하지 않으므로,
    그때는 부르는 쪽에서 LOO(하나 빼기)로 바꾸고 그 사실을 결과에 적어야 한다.
    """
    buckets = group_by_prompt(rows)

    # ① 화자가 겹을 넘나드는지
    speaker_folds: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        speaker = str(r.get("speaker_id") or r["id"].split("-")[0])
        speaker_folds[speaker].add(fold_of[str(r["id"])])
    leaked = sorted(s for s, fs in speaker_folds.items() if len(fs) > 1)

    # ② 문항 안에서 겹이 성립하는지
    per_prompt = {}
    empty_cells = []
    min_train = None
    for pkey, items in buckets.items():
        sizes = Counter(fold_of[str(r["id"])] for r in items)
        row = {
            "n": len(items),
            "test_per_fold": [sizes.get(k, 0) for k in range(n_folds)],
            "train_per_fold": [len(items) - sizes.get(k, 0) for k in range(n_folds)],
        }
        per_prompt[pkey] = row
        for k in range(n_folds):
            if sizes.get(k, 0) == 0:
                empty_cells.append((pkey, k))
        smallest = min(row["train_per_fold"])
        min_train = smallest if min_train is None else min(min_train, smallest)

    return {
        "n_folds": n_folds,
        "speaker_leak_count": len(leaked),
        "speaker_leak_examples": leaked[:5],
        "prompts_with_empty_fold": [f"{p}:겹{k}" for p, k in empty_cells],
        "min_train_rows_in_any_prompt_fold": min_train,
        "usable": len(leaked) == 0 and not empty_cells,
        "per_prompt": per_prompt,
    }


# ── ③ 재는 자 ────────────────────────────────────────────────────────────────
def qwk(pred: list[int], truth: list[int], labels: tuple[int, ...] = SCORE_LABELS) -> float:
    """QWK(이차 가중 카파) — 두 채점자가 **등급을 얼마나 같게 매기는가**.

    쉬운 말로: 1.0 이면 완전히 같게 매긴 것, 0 이면 아무렇게나 찍은 것과 다를 바 없는 것,
    음수면 오히려 반대로 매긴 것이다. 시험 채점 일치율을 말할 때 쓰는 표준 지표다.

    '이차 가중'이란 **많이 빗나갈수록 더 크게 깎는다**는 뜻이다.
    3점짜리를 4점으로 본 것과 3점짜리를 0점으로 본 것을 똑같이 세면 안 되기 때문이다
    (빗나간 칸 수의 제곱으로 벌점을 준다).

    계산은 이렇다.
      1) 실제로 어떻게 엇갈렸는지 표(O)를 만든다
      2) 두 채점자가 각자 버릇대로 아무 관련 없이 매겼다면 나왔을 표(E)를 만든다
      3) 1 - (실제 벌점 합) / (우연 벌점 합)
    """
    if len(pred) != len(truth):
        raise ValueError("예측과 정답의 개수가 다르다")
    n = len(truth)
    if n == 0:
        return float("nan")

    k = len(labels)
    index = {v: i for i, v in enumerate(labels)}

    # 1) 실제 엇갈림 표. 세로가 예측, 가로가 사람 점수다
    observed = [[0.0] * k for _ in range(k)]
    for p, t in zip(pred, truth):
        observed[index[int(p)]][index[int(t)]] += 1.0

    # 2) 우연히 그렇게 될 표. 각자 매긴 비율만 곱해서 만든다
    pred_marginal = [sum(observed[i]) for i in range(k)]
    truth_marginal = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    expected = [[pred_marginal[i] * truth_marginal[j] / n for j in range(k)] for i in range(k)]

    # 3) 빗나간 칸 수의 제곱을 벌점으로 삼아 둘을 견준다
    denom_scale = (k - 1) ** 2
    num = sum(
        ((i - j) ** 2 / denom_scale) * observed[i][j] for i in range(k) for j in range(k)
    )
    den = sum(
        ((i - j) ** 2 / denom_scale) * expected[i][j] for i in range(k) for j in range(k)
    )
    # 두 채점자 중 한쪽이 모든 답안에 같은 점수만 줬다면 우연 벌점이 0이 되어 나눌 수 없다.
    # 그럴 때는 '완전히 같으면 1, 아니면 0'으로 본다(표준 처리)
    if den == 0:
        return 1.0 if num == 0 else 0.0
    return 1.0 - num / den


def pearson(xs, ys) -> float:
    """두 값이 **직선으로** 같이 움직이는 정도. -1 ~ 1, 1이면 완전히 같은 방향."""
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    # 한쪽 값이 전부 똑같으면(퍼짐이 0) 같이 움직이는지 따질 수가 없다
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def _ranks(values) -> list[float]:
    """값들을 작은 것부터 순위로 바꾼다. 같은 값끼리는 순위를 나눠 갖는다(평균 순위).

    점수가 0~5의 여섯 칸뿐이라 같은 값이 잔뜩 나온다.
    같은 값에 임의로 다른 순위를 주면 상관이 우연에 흔들리므로 반드시 평균을 쓴다.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0 + 1.0
        for m in range(i, j + 1):
            ranks[order[m]] = average
        i = j + 1
    return ranks


def spearman(xs, ys) -> float:
    """**순서**가 같이 움직이는 정도. 값 자체가 아니라 등수만 본다."""
    if len(xs) < 3:
        return float("nan")
    return pearson(_ranks(xs), _ranks(ys))


def all_metrics(pred: list[int], truth: list[int]) -> dict:
    """한 방식의 성적을 다섯 가지 자로 한꺼번에 잰다.

    - qwk        : 주 지표. 등급 일치도
    - pearson    : 값이 나란히 커지고 작아지는 정도
    - spearman   : 등수가 얼마나 같은지
    - exact      : 사람 점수와 **정확히** 같게 매긴 비율
    - within1    : 1점 차 이내로 맞힌 비율(시험 채점에서 흔히 함께 보는 참고 지표)
    """
    n = len(truth)
    if n == 0:
        return {"n": 0, "qwk": float("nan"), "pearson": float("nan"),
                "spearman": float("nan"), "exact": float("nan"), "within1": float("nan")}
    return {
        "n": n,
        "qwk": qwk(pred, truth),
        "pearson": pearson([float(v) for v in pred], [float(v) for v in truth]),
        "spearman": spearman([float(v) for v in pred], [float(v) for v in truth]),
        "exact": sum(1 for p, t in zip(pred, truth) if p == t) / n,
        "within1": sum(1 for p, t in zip(pred, truth) if abs(p - t) <= 1) / n,
    }


def bootstrap_qwk_ci(
    preds_by_method: dict[str, list[int]],
    truth: list[int],
    speakers: list[str],
    n_boot: int = N_BOOTSTRAP,
    seed: int = SEED,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """QWK 가 얼마나 믿을 만한 숫자인지, 그리고 방식 간 차이가 우연인지 잰다.

    **화자를 통째로 다시 뽑는다**(클러스터 부트스트랩). 답안 하나하나를 따로 뽑으면
    같은 사람의 답안끼리 닮아 있다는 사실이 무시되어, 표본이 실제보다 많은 척하게 된다.
    그러면 신뢰구간이 실제보다 좁아져 "개선했다"고 말하기 쉬워진다.

    돌려주는 값은 (방식별 구간, 방식 쌍별 차이 구간)이다.
    **차이 구간이 0을 걸치면 '개선'이라고 쓰지 않는다.** 이 프로젝트의 정직 규칙이다.
    """
    rng = random.Random(seed)
    unique_speakers = sorted(set(speakers))
    # 화자별로 어느 줄들이 그 사람 것인지 미리 묶어 둔다
    by_speaker: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(speakers):
        by_speaker[s].append(i)

    methods = list(preds_by_method.keys())
    samples: dict[str, list[float]] = {m: [] for m in methods}
    diff_samples: dict[str, list[float]] = {
        f"{a}-{b}": [] for i, a in enumerate(methods) for b in methods[i + 1:]
    }

    for _ in range(n_boot):
        picked = [unique_speakers[rng.randrange(len(unique_speakers))]
                  for _ in range(len(unique_speakers))]
        idx = [i for s in picked for i in by_speaker[s]]
        t = [truth[i] for i in idx]
        values = {}
        for m in methods:
            v = qwk([preds_by_method[m][i] for i in idx], t)
            values[m] = v
            if not math.isnan(v):
                samples[m].append(v)
        for name in diff_samples:
            a, b = name.split("-")
            if not math.isnan(values[a]) and not math.isnan(values[b]):
                diff_samples[name].append(values[a] - values[b])

    def interval(vals: list[float]) -> dict:
        if not vals:
            return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n_boot": 0}
        ordered = sorted(vals)
        lo = ordered[int(0.025 * (len(ordered) - 1))]
        hi = ordered[int(math.ceil(0.975 * (len(ordered) - 1)))]
        return {"mean": sum(vals) / len(vals), "lo": lo, "hi": hi, "n_boot": len(vals)}

    return (
        {m: interval(v) for m, v in samples.items()},
        {name: interval(v) for name, v in diff_samples.items()},
    )


def verdict(diff_ci: dict) -> str:
    """차이 구간을 사람이 읽을 한 마디로 바꾼다. 0을 걸치면 개선이라고 쓰지 않는다."""
    if math.isnan(diff_ci.get("lo", float("nan"))):
        return "측정불가"
    if diff_ci["lo"] > 0:
        return "앞쪽이 유의하게 높다"
    if diff_ci["hi"] < 0:
        return "뒤쪽이 유의하게 높다"
    return "0을 걸친다 → 차이를 주장할 수 없다"


# ── ④ 이어서 하기 (중간에 끊겨도) ────────────────────────────────────────────
def record_key(rec: dict) -> tuple[str, str, str]:
    """결과 한 줄을 가리키는 열쇠. (답안 id, 방식, 몇 번째 실행인지)."""
    return (str(rec.get("id")), str(rec.get("method")), str(rec.get("pass")))


def load_done(path: Path) -> dict[tuple[str, str, str], dict]:
    """이미 끝낸 판정을 읽어 온다. 다시 실행할 때 건너뛰기 위한 것이다.

    같은 열쇠가 여러 번 적혀 있으면 **나중 것이 이긴다.**
    앞서 실패로 적힌 줄을 나중에 성공으로 덮어쓸 수 있어야 재실행이 뜻을 가진다.
    """
    done: dict[tuple[str, str, str], dict] = {}
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
            done[record_key(rec)] = rec
    return done


#: 결과 파일에 글을 쓰는 순번표. 여러 판정이 동시에 끝나도 한 번에 한 줄씩만 적는다.
#: 이것이 없으면 두 줄이 뒤엉켜 다시 읽을 수 없는 줄이 생긴다.
_WRITE_LOCK = threading.Lock()


def append_record(path: Path, record: dict) -> None:
    """판정 한 줄을 파일에 바로 적고 디스크까지 밀어 넣는다.

    한 건 끝날 때마다 적는 이유: 수백 건 × 세 방식은 한참 걸리고
    무료 등급 하루 사용량에 막혀 중간에 끊기는 일이 실제로 있다.
    끝까지 모아 뒀다가 한꺼번에 적으면 그때 전부 날아간다.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        with Path(path).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


# ── 동시 호출 조절기 ─────────────────────────────────────────────────────────
def is_quota_error(reason: str) -> bool:
    """실패 사유가 '사용량을 다 썼다(429)'인지 가려낸다.

    사유 문구는 채점 쪽(`src/llm/client.py`)이 만들어 준 것을 그대로 읽는다.
    같은 판별을 여기서 새로 만들면 저쪽 문구가 바뀔 때 조용히 어긋난다.
    """
    text = str(reason)
    return "429" in text or "한도를 다 썼다" in text or "RESOURCE_EXHAUSTED" in text


def classify_429(reason: str, detail: str) -> tuple[str, float]:
    """같은 429 라도 **기다리면 풀리는 것**과 **오늘은 끝난 것**을 갈라 본다.

    왜 갈라야 하나 (8/9 실측):
    무료 등급은 '분당 15회' 벽에 먼저 부딪힌다. 서버가 "22.9초 뒤에 다시 해 보라"고
    친절히 알려 주는데, 이것을 '한도 소진'으로 오해해서 멈추면 멀쩡히 더 돌릴 수 있는
    실험을 스스로 접는 것이 된다. 반대로 유료 키의 429 는
    "prepayment credits are depleted"(선불 잔액 소진)라 기다려도 풀리지 않는다.

    돌려주는 값은 (갈래, 기다릴 초)다.
      "rate" — 분당 한도. 알려 준 만큼 자고 다시 하면 된다
      "hard" — 잔액·하루치 소진. 더 두드리지 않는다
      ""     — 429 가 아니다
    """
    import re

    text = f"{reason} {detail}"
    if not is_quota_error(text):
        return "", 0.0

    # 서버가 알려 준 대기 시간을 그대로 따른다(우리가 임의로 정하지 않는다)
    wait = 0.0
    for pattern in (r"retryDelay'?:\s*'?(\d+(?:\.\d+)?)s", r"retry in (\d+(?:\.\d+)?)s"):
        found = re.search(pattern, text)
        if found:
            wait = float(found.group(1))
            break

    per_minute = ("PerMinute" in text or "per minute" in text
                  or "retryDelay" in text or "retry in" in text)
    if per_minute:
        # 알려 준 시간이 없으면 1분 구간이 지나가도록 넉넉히 기다린다
        return "rate", wait or 25.0
    return "hard", 0.0


class CallThrottle:
    """LLM 호출을 몇 개까지 동시에 보낼지 조절하고, 한도가 바닥나면 멈추게 한다.

    하는 일 두 가지.
      ① 호출이 나가는 속도를 붙든다. 여기에는 조절이 둘 들어 있다.
         · 동시에 나가는 호출 수 (한 번에 몇 개를 겹칠지)
         · **1분에 몇 번까지 부를지** — 무료 등급의 진짜 벽이 여기다.
           벽에 부딪히고 나서 물러서는 것보다 처음부터 그 속도로 가는 편이 훨씬 빠르다
           (한 번 부딪히면 25초를 통째로 버린다).
      ② 기다려도 풀리지 않는 429(잔액·하루치 소진)가 이어지면 더 두드리지 않고
         멈춤 표시를 세운다.

    멈출 때 결과를 버리지 않는다. 지금까지 된 것은 이미 파일에 적혀 있고,
    안 된 것은 아무것도 안 적혀 있어서 다음 실행이 그대로 이어서 한다.
    """

    def __init__(self, workers: int, rpm: int = DEFAULT_RPM,
                 stop_after: int = QUOTA_STOP_AFTER):
        # 자리 수를 도중에 바꿀 수 있어야 해서 세마포어 대신 조건 변수로 직접 센다
        self._cv = threading.Condition()
        self._limit = max(1, workers)
        self._in_use = 0
        self._rpm = max(1, rpm)
        # 최근 1분 안에 나간 호출의 시각. 이 개수가 분당 한도를 넘지 않게 붙든다
        self._recent: list[float] = []
        self._consecutive_quota = 0
        self._stop_after = stop_after
        self.stop_reason = ""
        self.rate_waits = 0

    def _wait_for_rate_budget(self) -> None:
        """1분에 정해진 횟수만 나가도록 붙든다.

        최근 60초 안에 나간 호출을 세어, 한도가 찼으면 가장 오래된 호출이
        60초를 넘길 때까지 기다린다. 기다리는 동안에는 자물쇠를 놓아 준다
        (안 그러면 다른 일꾼까지 함께 멈춰 버린다).
        """
        while True:
            with self._cv:
                now = time.monotonic()
                self._recent = [t for t in self._recent if now - t < 60.0]
                if len(self._recent) < self._rpm:
                    self._recent.append(now)
                    return
                sleep_for = 60.0 - (now - min(self._recent)) + 0.1
            time.sleep(min(max(sleep_for, 0.1), 5.0))

    @contextmanager
    def slot(self):
        """분당 예산과 동시 호출 자리를 둘 다 잡고 나서 호출한다."""
        self._wait_for_rate_budget()
        with self._cv:
            while self._in_use >= self._limit:
                self._cv.wait()
            self._in_use += 1
        try:
            yield
        finally:
            # 어떤 일이 있어도 자리는 돌려놔야 한다. 안 그러면 뒤가 영영 멈춘다
            with self._cv:
                self._in_use -= 1
                self._cv.notify()

    def note_rate_limited(self, wait_sec: float) -> None:
        """분당 한도에 부딪혔다. 속도를 한 칸 낮추고, 얼마나 기다릴지 알려 준다.

        이것은 실패가 아니다. 기다리면 풀리므로 '한도 소진' 세기에 넣지 않는다.
        """
        with self._cv:
            self.rate_waits += 1
            if self._rpm > 3:
                self._rpm -= 1
                print(f"      [속도 조절] 분당 한도에 걸려 분당 {self._rpm}회로 낮춘다"
                      f" ({wait_sec:.0f}초 대기)")

    def note(self, quota_hit: bool) -> None:
        """호출 하나가 끝날 때마다 '기다려도 안 풀리는 429' 였는지 알려 준다.

        아니었다면 연속 세기를 0으로 되돌린다. '연속'이 뜻을 가지려면
        중간에 성공이 끼는 순간 끊겨야 하기 때문이다.
        """
        with self._cv:
            if not quota_hit:
                self._consecutive_quota = 0
                return
            self._consecutive_quota += 1
            if self._consecutive_quota >= self._stop_after:
                self.stop_reason = (
                    f"기다려도 풀리지 않는 사용량 초과(429)가 "
                    f"{self._consecutive_quota}번 연달아 났다. 한도를 다 쓴 것으로 본다."
                )
                self._cv.notify_all()
                return
            # 아직 한도가 남았을 수도 있으니 우선 속도를 절반으로 줄여 본다
            if self._limit > 1:
                self._limit = max(1, self._limit // 2)
                print(f"      [속도 조절] 429 를 만나 동시 호출을 {self._limit}개로 줄인다")

    @property
    def stopped(self) -> bool:
        return bool(self.stop_reason)

    @property
    def limit(self) -> int:
        with self._cv:
            return self._limit


# ── LLM 클라이언트 만들기 ────────────────────────────────────────────────────
def use_free_backup_key() -> str:
    """무료 예비 키를 이번 실행의 기본 키로 올린다.

    유료 키가 429 로 막혀 있어서(8/9 실측) `.env` 의 `GEMINI_API_KEY_FREE_BACKUP` 을
    `GEMINI_API_KEY` 자리에 올려 쓴다. **`.env` 파일은 고치지 않는다.**
    이 실행 안에서만 바꿔 끼우는 것이라 채점 서버 설정에는 영향이 없다.

    ※ 임시 조치다. 유료 키가 풀리면 이 함수를 부르지 않는 것만으로 되돌아간다.

    ■ 키를 골라 쓰는 법 (8/9 추가)

    무료 등급의 하루 한도는 **키(프로젝트)마다 · 모델마다 따로** 걸린다. 실측으로
    flash-lite 는 한 키에 하루 500회였고, 이번 실험은 그보다 많이 필요하다.
    그래서 환경변수 `KTEST_LAB_KEY` 로 이번 실행이 쓸 키를 고를 수 있게 했다.

        KTEST_LAB_KEY=backup  (기본) → GEMINI_API_KEY_FREE_BACKUP
        KTEST_LAB_KEY=primary        → GEMINI_API_KEY (.env 의 주 키)

    **어느 키를 쓰든 모델·온도·프롬프트는 그대로다.** 키는 요금 창구일 뿐이라
    판정 결과에 영향을 주지 않는다(공정 비교 조건은 모델과 설정이지 키가 아니다).
    다만 결과 줄에 어느 키로 돌렸는지 남기지는 않으므로, 실행 로그로 확인한다.
    """
    from dotenv import dotenv_values

    values = dotenv_values(ASSESSMENT_DIR / ".env")
    which = (os.getenv("KTEST_LAB_KEY") or "backup").strip().lower()
    if which == "primary":
        primary = (values.get("GEMINI_API_KEY") or "").strip()
        if not primary:
            return "주 키를 찾지 못해 기존 GEMINI_API_KEY 를 그대로 쓴다"
        os.environ["GEMINI_API_KEY"] = primary
        return "주 키(GEMINI_API_KEY)로 돌린다 — KTEST_LAB_KEY=primary"
    backup = (values.get("GEMINI_API_KEY_FREE_BACKUP") or "").strip()
    if not backup:
        return "예비 키를 찾지 못해 기존 GEMINI_API_KEY 를 그대로 쓴다"
    os.environ["GEMINI_API_KEY"] = backup
    return "※ 임시 ※ 무료 예비 키(GEMINI_API_KEY_FREE_BACKUP)로 돌린다 — 유료 키가 429"


def make_judge_client(model: str = JUDGE_MODEL):
    """판정에 쓸 LLM 클라이언트를 만든다.

    설정은 채점 서버가 쓰는 래퍼를 그대로 빌려 쓴다(temperature 0 · JSON 강제).
    여기서 정하는 것은 모델 이름과 기다리는 시간·글자 예산뿐이다.
    """
    if str(ASSESSMENT_DIR) not in sys.path:
        sys.path.insert(0, str(ASSESSMENT_DIR))
    from src.llm.client import GeminiClient, GeminiConfig

    return GeminiClient(
        config=GeminiConfig(
            model=model,
            temperature=0.0,
            max_output_tokens=JUDGE_MAX_OUTPUT_TOKENS,
            timeout_ms=JUDGE_TIMEOUT_MS,
        )
    )


def call_with_retry(fn, throttle: CallThrottle | None = None, label: str = "") -> dict:
    """LLM 호출 하나를 실패해도 몇 번 다시 해 본다.

    실패를 세 갈래로 다르게 다룬다.
      · **분당 한도(429·기다리면 풀림)** — 실패로 세지 않는다. 서버가 알려 준 만큼
        자고 그대로 다시 한다. 이것을 실패로 세면 기다리면 될 일 때문에 표본이 준다.
      · **잔액·하루치 소진(429·기다려도 안 풀림)** — 조절기에 알리고, 정해진 횟수를
        넘기면 조용히 물러난다(`quota_stopped`). 이 경우 **아무것도 기록하지 않는다** —
        시도조차 못 한 것을 실패로 적어 두면 그것도 결과처럼 보이기 때문이다.
      · 그 밖의 실패 — 갈수록 오래 쉬며 정해진 횟수만큼 다시 해 본다.

    돌려주는 값은 {"status": "ok"/"failed"/"quota_stopped", ...} 이다.
    """
    last_reason = ""
    attempt = 0
    rate_waits = 0
    while attempt < LLM_MAX_ATTEMPTS:
        if throttle is not None and throttle.stopped:
            return {"status": "quota_stopped", "reason": throttle.stop_reason,
                    "attempts": attempt}
        attempt += 1
        started = time.perf_counter()
        try:
            with (throttle.slot() if throttle is not None else _null_slot()):
                value = fn()
            if throttle is not None:
                throttle.note(quota_hit=False)
            return {"status": "ok", "value": value, "attempts": attempt,
                    "elapsed_sec": round(time.perf_counter() - started, 2)}
        except Exception as exc:
            # 친절한 사유(사람이 읽을 한 줄)와 서버 원문을 함께 본다.
            # 429 의 갈래는 원문에만 적혀 있어서, 친절한 문구만 보면 구분할 수 없다
            detail = str(getattr(exc, "detail", "") or "")
            last_reason = f"{type(exc).__name__}: {exc}"
            kind, wait_sec = classify_429(last_reason, detail)

            if kind == "rate" and rate_waits < MAX_RATE_WAITS:
                # 기다리면 풀리는 벽이다. 이 시도는 없었던 것으로 치고 다시 센다
                rate_waits += 1
                attempt -= 1
                if throttle is not None:
                    throttle.note_rate_limited(wait_sec)
                time.sleep(wait_sec + 1.0)
                continue

            if throttle is not None:
                throttle.note(quota_hit=(kind == "hard"))
            if attempt < LLM_MAX_ATTEMPTS:
                wait = LLM_RETRY_SLEEP_SEC[min(attempt - 1, len(LLM_RETRY_SLEEP_SEC) - 1)]
                print(f"      LLM 실패({attempt}/{LLM_MAX_ATTEMPTS}) {label} — "
                      f"{last_reason[:70]} / {wait}초 쉬고 다시")
                time.sleep(wait)
    return {"status": "failed", "reason": last_reason, "attempts": LLM_MAX_ATTEMPTS,
            "rate_waits": rate_waits}


@contextmanager
def _null_slot():
    """조절기를 안 쓸 때 자리 잡기를 건너뛰기 위한 빈 껍데기."""
    yield


# ── 표 그리기 ────────────────────────────────────────────────────────────────
def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """터미널에 표를 그린다. 한글은 두 칸을 차지하므로 그만큼 넓혀 맞춘다."""
    import unicodedata

    def width(text: str) -> int:
        return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(text))

    all_rows = [headers] + [[str(c) for c in r] for r in rows]
    widths = [max(width(r[i]) for r in all_rows) for i in range(len(headers))]

    def line(cells) -> str:
        return " | ".join(str(c) + " " * (widths[i] - width(c)) for i, c in enumerate(cells))

    print(line(headers))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


def fmt(value: float, digits: int = 3) -> str:
    """숫자를 표에 넣을 글자로 바꾼다. 계산할 수 없었던 값은 '측정불가'로 적는다."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "측정불가"
    return f"{value:.{digits}f}"
