# -*- coding: utf-8 -*-
"""자질 개편 실험 — "더하는 방식"이 아니라 "재는 자" 자체를 바꿔 본다.

■ 왜 이 실험을 하나

어제(2026-08-06) 실험에서 결론이 하나 나왔다.
사람이 직접 받아쓴 완벽한 전사 107건에서도, 지금 쓰는 자질 12개는
전문 평가자 점수와 거의 같이 움직이지 않았다(전부 상관 |0.25| 미만).
게다가 두 개는 **방향이 거꾸로**였다(어휘 다양도 -0.215, 고급 어휘 비율 -0.238).
결합층을 XGBoost 로 갈아끼워도 0.308 → 0.322 로, 우연과 구별되지 않았다.

즉 병목은 '더하는 방식'이 아니라 **자질 자체**다.
이 스크립트는 그래서 자질 후보를 새로 만들고, 정직한 절차로 걸러 본다.

■ 새 자질은 LLM 을 부르지 않는다

후보는 전부 Kiwi(한국어 형태소 분석기)와 순수 파이썬으로만 센다.
이미 저장돼 있는 사람 전사에서 다시 계산하는 것이라, 같은 명령을 몇 번 돌려도
같은 숫자가 나온다. `scoring-design` 스킬의 경계("셀 수 있는 것은 규칙으로")를 지킨 것이고,
동시에 실험을 몇 초 만에 되풀이할 수 있게 하려는 목적도 있다.

■ 낚시(과적합)를 막으려고 지킨 것

107건에서 상관이 높은 자질을 골라 놓고 "이 자질이 좋다"고 말하는 것은
답을 보고 문제를 고르는 것과 같다. 그래서 최종 검증에서는
**자질 고르기를 배우는 겹 안에서만** 한다. 시험 볼 21건은 어떤 자질을 쓸지
정하는 데 한 번도 참여하지 않는다. (`select_features` 와 `run_cv_selected` 참고)

■ 쓰는 법

    C:\\해커톤\\.venv\\Scripts\\python.exe assessment/scripts/speech_lab/feature_lab.py

    # 계산 함수가 제대로 도는지 예시 입력으로 확인만 하고 끝내기
    ... --selftest

    # 어휘 오용 과검출 점검에서 LLM 을 다시 불러 인용까지 받아 오기(선택)
    ... --wordchoice-llm 20

이 스크립트는 `assessment/src/` 를 **읽기만** 한다. 한 줄도 고치지 않는다.
`train_score_model.py` 의 검증 절차(화자 5겹·씨앗 42·부트스트랩 1000회)는
그대로 가져다 쓴다. 절차가 달라지면 어제 숫자와 오늘 숫자를 나란히 놓을 수 없다.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import stats
from sklearn.model_selection import GroupKFold

# ── 같은 폴더의 train_score_model.py 를 그대로 가져다 쓴다 ───────────────────
# 검증 절차를 베껴 적으면 어느 순간 두 파일이 갈라져서 비교가 무의미해진다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
# assessment 폴더를 열어 둬야 `src.features...` 를 읽을 수 있다(읽기 전용).
ASSESSMENT_DIR = Path(__file__).resolve().parents[2]
if str(ASSESSMENT_DIR) not in sys.path:
    sys.path.insert(0, str(ASSESSMENT_DIR))

import xgboost as xgb  # noqa: E402
from kiwipiepy import Kiwi  # noqa: E402

from train_score_model import (  # noqa: E402
    FEATURE_IDS as LEGACY_FEATURE_IDS,
    XGB_PARAMS,
    baseline_metrics,
    bootstrap_diff,
    choose_n_trees,
    score_metrics,
    fit_linear_map,
    run_cv,
)


# ═══════════════════════════════════════════════════════════════════════════
# 0) 품사 표시 묶음 — src/features/lexical.py 와 같은 기준을 쓴다
# ═══════════════════════════════════════════════════════════════════════════

#: 문장부호. 자질 계산에서 뺀다.
PUNCT_TAGS = {"SF", "SP", "SS", "SE", "SO", "SW", "SB", "SSO", "SSC"}

#: 뜻을 가진 말(내용어). 어휘 크기를 잴 때 분자로 쓴다.
CONTENT_TAGS = {
    "NNG", "NNP", "NR", "VV", "VA", "MAG", "MM", "XR",
    "VV-I", "VV-R", "VA-I", "VA-R",
}

#: 군말로 셀 감탄사 모양. '네/아니요' 같은 대답은 군말이 아니므로 목록에서 뺐다.
#: (Kiwi 는 이런 말을 IC = 감탄사 로 표시한다)
FILLER_FORMS = {"어", "음", "아", "그", "저", "뭐", "에", "저기", "그니까", "그러니까", "인제", "이제"}

#: '사전에 없는 듯한 낱말'로 볼 확신도 기준선.
#: Kiwi 는 말조각마다 "이 분석이 얼마나 그럴듯한가"를 점수로 준다(0에 가까울수록 확실).
#: 실측(2026-08-07): 정상 낱말 '회사' -7.9 / '베트남' -8.5 인데
#: 망가진 낱말 '디브' -18.8, '조현' -15.9, '고항' -16.4, '개후' -21.7 로 뚜렷하게 갈렸다.
#: 그래서 -15 를 경계로 잡았다. 손으로 정한 값이라 절대 기준이 아니다.
ODDWORD_SCORE_THRESHOLD = -15.0


# ═══════════════════════════════════════════════════════════════════════════
# 1) 후보 자질 계산 (규칙만, LLM 호출 없음)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Ev:
    """자질 하나를 계산할 때 실제로 쓴 원문 자리.

    이 프로젝트에서 근거 없는 점수는 결함이다. 실험 스크립트라고 예외를 두면
    나중에 이 자질을 서버로 옮길 때 근거를 새로 만들어야 하므로 여기서부터 남긴다.
    """

    feature_id: str
    quote: str
    start: int
    end: int
    comment: str


@dataclass
class Candidates:
    """후보 자질 계산 결과 한 묶음."""

    values: dict[str, float] = field(default_factory=dict)
    evidence: list[Ev] = field(default_factory=list)


#: 후보 자질 설명표. {자질 id: 사람이 읽는 이름}
#: 순서를 고정해 두어야 표와 학습 행렬의 칸이 어긋나지 않는다.
CANDIDATE_NAMES: dict[str, str] = {
    # ── 발화 양: '얼마나 말했나' ─────────────────────────────────────────
    "amt_eojeol": "어절 수",
    "amt_morpheme": "형태소 수",
    "amt_sentence": "문장 수",
    "amt_char": "글자 수(공백 제외)",
    "amt_content_types": "서로 다른 내용어 종류 수",
    # ── 문장 완성도: '문장을 끝까지 맺었나' ──────────────────────────────
    "sent_final_ending_ratio": "종결어미로 끝난 문장 비율",
    "sent_mean_len": "평균 문장 길이(어절)",
    "sent_len_sd": "문장 길이 들쭉날쭉함(표준편차)",
    # ── 오류 밀도: 절대 건수로 되돌린 값 ─────────────────────────────────
    "err_total_per100": "오류 4종 합계(100어절당)",
    "err_total_count": "오류 4종 합계(절대 건수)",
    "err_word_choice_count": "어휘 오용(절대 건수)",
    # ── 유창성 흔적 ──────────────────────────────────────────────────────
    "flu_filler_ratio": "군말(어·음·그) 비율",
    "flu_repeat_eojeol_ratio": "바로 옆 어절 반복 비율",
    "flu_content_ttr": "내용어 TTR(길이에 민감·대조용)",
    "flu_oddword_per100": "사전에 없는 듯한 낱말 100어절당",
    # ── 구조: '문장을 어떻게 엮나' ───────────────────────────────────────
    "str_connective_per_sent": "문장당 연결어미 수",
    "str_adnominal_per_sent": "문장당 관형절 어미 수",
    "str_nominal_per_sent": "문장당 명사형 어미 수",
    "str_josa_types": "서로 다른 조사 종류 수",
    "str_ending_types": "서로 다른 종결어미 종류 수",
    "str_prefinal_per100": "선어말어미(시제·높임) 100어절당",
    "str_adverb_ratio": "부사 비율",
    "str_mean_eojeol_char": "어절당 평균 글자 수",
}

CANDIDATE_IDS = list(CANDIDATE_NAMES)


def _eojeols(text: str) -> list[str]:
    """어절(띄어쓰기로 나뉜 덩어리) 목록. 여러 비율의 분모로 쓴다."""
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _kiwi() -> Kiwi:
    """Kiwi 분석기를 한 번만 만들어 계속 쓴다(만드는 데 몇 초 걸린다)."""
    if not hasattr(_kiwi, "_inst"):
        _kiwi._inst = Kiwi()
    return _kiwi._inst


def _sentences(kiwi: Kiwi, text: str):
    """문장 경계를 구한다. 분리에 실패하면 전체를 한 문장으로 본다.

    문장 수가 0이 되면 '문장당 ○○' 자질이 통째로 죽으므로 최소 한 문장은 보장한다.
    """
    try:
        sents = list(kiwi.split_into_sents(text))
    except Exception:
        sents = []
    return sents


def odd_words(text: str, threshold: float = ODDWORD_SCORE_THRESHOLD) -> list[dict]:
    """Kiwi 가 "이런 낱말은 잘 모르겠다"고 표시한 낱말을 골라낸다.

    ※ 임시(TEMP) ※ 이것은 사전 대조가 아니라 **확신도 점수를 이용한 근사**다.
    Gemini 하루 호출 한도가 걸려(429) 어휘 오용 판정을 다시 받아 올 수 없어서,
    "LLM 이 어휘 오용이라고 한 자리"를 눈으로 볼 대체 재료로 만든 것이다.
    정식 판정이 아니므로 채점에 그대로 쓰면 안 된다.

    뜻을 가진 말(내용어)만 본다. 조사·어미는 Kiwi 가 늘 잘 알아보기 때문이다.
    """
    hits = []
    for t in _kiwi().tokenize(text):
        # 내용어이면서 확신도가 기준선보다 낮으면 '사전에 없는 듯한 낱말'로 본다
        if t.tag in CONTENT_TAGS and t.score < threshold:
            hits.append({
                "form": t.form, "tag": t.tag, "score": float(t.score),
                "start": t.start, "end": t.start + t.len,
                # 낱말만 보여 주면 맥락을 알 수 없으므로 주변까지 조금 넓게 잘라 둔다
                "quote": text[max(0, t.start - 8): t.start + t.len + 8],
            })
    return hits


def extract_candidates(text: str, error_counts: dict[str, float] | None = None) -> Candidates:
    """전사 한 건에서 후보 자질을 전부 계산한다.

    `error_counts` 는 이미 저장돼 있는 LLM 오류 자질 값(100어절당 건수)이다.
    여기서 LLM 을 새로 부르지 않고, 어제 받아 둔 값을 '밀도'와 '절대 건수' 두 모양으로
    다시 빚기만 한다. 지금 자질이 길이에 어떻게 휘둘리는지 보려는 것이다.
    """
    kiwi = _kiwi()
    out = Candidates()
    ev = out.evidence
    v = out.values

    tokens = list(kiwi.tokenize(text))
    # 문장부호는 어휘도 문법도 아니므로 세는 대상에서 뺀다
    real = [t for t in tokens if t.tag not in PUNCT_TAGS]
    words = _eojeols(text)
    n_eojeol = max(1, len(words))          # 0으로 나누는 것을 막는 최소값
    sents = _sentences(kiwi, text)
    n_sent = max(1, len(sents))

    # ── 발화 양 ──────────────────────────────────────────────────────────
    # 말을 충분히 했는지 자체가 채점의 출발점이다. 지금 12개 자질에는
    # '얼마나 말했나'가 하나도 들어 있지 않아서(전부 비율값) 여기부터 넣었다.
    v["amt_eojeol"] = float(len(words))
    v["amt_morpheme"] = float(len(real))
    v["amt_sentence"] = float(len(sents))
    v["amt_char"] = float(len(re.sub(r"\s+", "", text)))
    content = [t for t in real if t.tag in CONTENT_TAGS]
    # 같은 글자라도 품사가 다르면 다른 낱말로 본다('밝다'의 밝 / '밝히다'의 밝)
    v["amt_content_types"] = float(len({(t.form, t.tag) for t in content}))
    ev.append(Ev("amt_eojeol", text[:40], 0, min(len(text), 40),
                 f"전체 {len(words)}어절 / {len(sents)}문장 (앞부분 표시)"))

    # ── 문장 완성도 ──────────────────────────────────────────────────────
    # 초급 학습자는 문장을 맺지 못하고 중간에 끊는 일이 많다.
    # 종결어미(EF)로 끝났는지를 문장마다 확인해서 그 비율을 잰다.
    finished = 0
    for s in sents:
        stoks = [t for t in tokens if s.start <= t.start < s.end and t.tag not in PUNCT_TAGS]
        if stoks and (stoks[-1].tag == "EF" or (stoks[-1].tag.startswith("J") and stoks[-1].form == "요")):
            finished += 1
        elif stoks:
            # 맺지 못한 문장은 근거로 남긴다 — 이 값이 낮은 이유를 짚어 주려는 것
            if len([e for e in ev if e.feature_id == "sent_final_ending_ratio"]) < 3:
                ev.append(Ev("sent_final_ending_ratio", s.text, s.start, s.end,
                             f"종결어미 없이 끊긴 문장(끝 조각 '{stoks[-1].form}'/{stoks[-1].tag})"))
    v["sent_final_ending_ratio"] = finished / n_sent

    sent_lens = [len(_eojeols(s.text)) for s in sents] or [len(words)]
    v["sent_mean_len"] = float(sum(sent_lens) / len(sent_lens))
    # 문장 길이가 다 똑같으면(예: 전부 3어절) 단조로운 발화라는 신호로 볼 수 있다
    v["sent_len_sd"] = float(statistics.pstdev(sent_lens)) if len(sent_lens) > 1 else 0.0

    # ── 오류 밀도 ────────────────────────────────────────────────────────
    # 확인해 보니 지금 저장된 error_* 값은 이미 '100어절당 건수'다(절대 개수가 아니다).
    # 그래서 여기서는 반대로 **절대 건수**를 되살려서, 밀도와 절대 건수 중
    # 어느 쪽이 사람 점수와 더 붙는지를 견줘 본다.
    ec = error_counts or {}
    per100_sum = sum(float(ec.get(k, 0.0) or 0.0) for k in
                     ("error_josa", "error_conjugation", "error_word_choice", "error_honorific"))
    v["err_total_per100"] = per100_sum
    v["err_total_count"] = per100_sum / 100.0 * len(words)
    v["err_word_choice_count"] = float(ec.get("error_word_choice", 0.0) or 0.0) / 100.0 * len(words)

    # ── 유창성 흔적 ──────────────────────────────────────────────────────
    # 군말은 Kiwi 가 감탄사(IC)로 표시한다. 그중 '네/아니요' 같은 대답은 빼고 센다.
    fillers = [t for t in real if t.tag == "IC" and t.form in FILLER_FORMS]
    v["flu_filler_ratio"] = len(fillers) / max(1, len(real))
    for t in fillers[:3]:
        ev.append(Ev("flu_filler_ratio", text[max(0, t.start - 6):t.start + t.len + 6],
                     max(0, t.start - 6), min(len(text), t.start + t.len + 6),
                     f"군말 '{t.form}'"))

    # 말이 막히면 같은 어절을 곧바로 되풀이한다('저는 저는 회사에').
    # 문장부호를 뗀 뒤 바로 옆 어절이 같은 자리를 센다.
    stripped = [re.sub(r"[^\w가-힣]", "", w) for w in words]
    repeats = [i for i in range(1, len(stripped)) if stripped[i] and stripped[i] == stripped[i - 1]]
    v["flu_repeat_eojeol_ratio"] = len(repeats) / n_eojeol
    for i in repeats[:3]:
        # 되풀이된 자리를 원문에서 찾아 근거로 남긴다(찾지 못하면 건너뛴다)
        pos = text.find(words[i - 1] + " " + words[i])
        if pos >= 0:
            ev.append(Ev("flu_repeat_eojeol_ratio", words[i - 1] + " " + words[i], pos,
                         pos + len(words[i - 1]) + 1 + len(words[i]),
                         f"어절 '{words[i]}' 곧바로 되풀이"))

    # 내용어 TTR = 서로 다른 내용어 ÷ 전체 내용어. 길이가 길수록 자동으로 낮아진다.
    # 일부러 넣은 '길이에 휘둘리는 자질'의 본보기로, MATTR 방향 역전 진단에 쓴다.
    v["flu_content_ttr"] = (v["amt_content_types"] / len(content)) if content else float("nan")

    # 사전에 없는 듯한 낱말('디브', '개후' 같은 것)이 얼마나 섞였는지.
    # 지금 LLM 이 '어휘 오용'이라 부르는 것과 같은 자리를 규칙으로 짚어 보려는 자질이다
    odd = odd_words(text)
    v["flu_oddword_per100"] = len(odd) / n_eojeol * 100
    for o in odd[:3]:
        ev.append(Ev("flu_oddword_per100", o["quote"], o["start"], o["end"],
                     f"사전에 없는 듯한 낱말 '{o['form']}'({o['tag']}, 확신도 {o['score']:.1f})"))

    # ── 구조 ─────────────────────────────────────────────────────────────
    # 문장을 몇 겹으로 엮는지를 어미 종류별로 나눠서 센다.
    # 지금 자질의 '절 밀도'는 이 셋을 뭉뚱그린 값이라, 어느 쪽이 실력을 가르는지 알 수 없었다.
    ec_tok = [t for t in real if t.tag == "EC"]     # 연결어미: '-고', '-지만'
    etm_tok = [t for t in real if t.tag == "ETM"]   # 관형절 어미: '먹는 밥'의 '-는'
    etn_tok = [t for t in real if t.tag == "ETN"]   # 명사형 어미: '먹기', '먹음'
    v["str_connective_per_sent"] = len(ec_tok) / n_sent
    v["str_adnominal_per_sent"] = len(etm_tok) / n_sent
    v["str_nominal_per_sent"] = len(etn_tok) / n_sent
    for t in etm_tok[:2]:
        ev.append(Ev("str_adnominal_per_sent", text[max(0, t.start - 8):t.start + t.len + 8],
                     max(0, t.start - 8), min(len(text), t.start + t.len + 8),
                     f"관형절 어미 '{t.form}'"))

    # 조사를 몇 종류나 부리는지 = 문법 그릇의 크기. 비율이 아니라 '종류 수'로 센다
    v["str_josa_types"] = float(len({t.form for t in real if t.tag.startswith("J")}))
    v["str_ending_types"] = float(len({t.form for t in real if t.tag == "EF"}))
    # 선어말어미(EP) = '-었-'(과거), '-시-'(높임), '-겠-'(추측). 시제를 부리는지 본다
    v["str_prefinal_per100"] = len([t for t in real if t.tag.startswith("EP")]) / n_eojeol * 100
    v["str_adverb_ratio"] = len([t for t in real if t.tag in ("MAG", "MAJ")]) / max(1, len(real))
    v["str_mean_eojeol_char"] = v["amt_char"] / n_eojeol

    return out


# ═══════════════════════════════════════════════════════════════════════════
# 2) 데이터 읽기
# ═══════════════════════════════════════════════════════════════════════════


def load_rows(path: Path) -> list[dict]:
    """하류 평가 결과에서 '사람 전사 + 정상 처리' 줄만 꺼낸다.

    받아쓰기 오류가 섞이면 '자질이 문제인가'라는 이번 질문에 답할 수 없다.
    그래서 받아쓰기가 완벽한 조건(arm=="ref")만 남긴다 — 어제 실험과 같은 표본이다.
    """
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("arm") == "ref" and r.get("status") == "ok":
                rows.append(r)
    if not rows:
        raise SystemExit(f"쓸 수 있는 줄이 하나도 없다: {path}")
    return rows


def build_matrices(rows: list[dict]):
    """읽은 줄들을 학습에 넣을 수 있는 표 모양으로 바꾼다.

    돌려주는 것:
        X_old   기존 자질 12개 표
        X_new   새 후보 자질 표
        y       사람 점수 0~5
        groups  화자 번호(겹을 가를 때 이 번호로 묶는다)
        base    지금 채점기의 손 가중치 점수 0~100
        meta    항목 식별 정보
        sample_ev  첫 항목의 근거 목록(눈으로 확인용)
    """
    n = len(rows)
    X_old = np.full((n, len(LEGACY_FEATURE_IDS)), np.nan)
    X_new = np.full((n, len(CANDIDATE_IDS)), np.nan)
    y = np.zeros(n)
    groups, base, meta = [], [], []
    sample_ev: list[Ev] = []

    for i, r in enumerate(rows):
        # 기존 자질 값은 contributions 안에 자질별로 들어 있다
        raw = {}
        for c in r.get("contributions", []):
            fid = c.get("feature_id")
            raw[fid] = float(c.get("raw_value"))
            if fid in LEGACY_FEATURE_IDS:
                X_old[i, LEGACY_FEATURE_IDS.index(fid)] = float(c.get("raw_value"))

        # 새 자질은 저장된 전사에서 지금 다시 계산한다(LLM 호출 없음)
        cand = extract_candidates(r["transcript"], raw)
        for j, fid in enumerate(CANDIDATE_IDS):
            X_new[i, j] = cand.values.get(fid, np.nan)
        if i == 0:
            sample_ev = cand.evidence

        y[i] = float(r["human_score"])
        base.append(float(r["language_score"]))
        # 항목 번호 앞자리가 화자 번호다 ("00131-F-99-..." → 화자 00131)
        groups.append(r["id"].split("-")[0])
        meta.append({"id": r["id"], "speaker_id": r["id"].split("-")[0],
                     "nationality": r.get("nationality"), "topik_level": r.get("topik_level")})

    return X_old, X_new, y, np.array(groups), np.array(base), meta, sample_ev


# ═══════════════════════════════════════════════════════════════════════════
# 3) 상관 재기 — '이 자질이 사람 점수와 같이 움직이나'
# ═══════════════════════════════════════════════════════════════════════════


def safe_pearson(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """값이 빠진 칸을 빼고 상관과 p값을 낸다.

    한쪽 값이 전부 같으면(예: 늘 0인 자질) 상관을 정의할 수 없으므로 NaN 을 돌려준다.
    '거의 상수'인 자질을 골라내는 데도 이 판정을 쓴다.
    """
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 3 or np.std(a[m]) < 1e-12 or np.std(b[m]) < 1e-12:
        return float("nan"), float("nan")
    r, p = stats.pearsonr(a[m], b[m])
    return float(r), float(p)


def correlation_table(X_new, X_old, y, length):
    """자질마다 사람 점수와의 상관을 재서 한 줄씩 표로 만든다.

    같이 싣는 것:
      - 스피어만: 순위만 보는 상관. 값이 튀는 자질에서 피어슨과 크게 갈리면 표시가 된다
      - 길이상관: 그 자질이 '길게 말했는지'와 얼마나 붙어 있는지.
        방향이 거꾸로인 자질(어휘 다양도 등)이 사실은 길이의 그림자인지 가려내려는 것이다
      - 상수여부: 값이 거의 변하지 않는 자질은 배울 것이 없으므로 표시해 둔다
    """
    rows = []
    for label, ids, X in (("신규", CANDIDATE_IDS, X_new), ("기존", LEGACY_FEATURE_IDS, X_old)):
        for j, fid in enumerate(ids):
            col = X[:, j]
            r, p = safe_pearson(col, y)
            m = ~(np.isnan(col) | np.isnan(y))
            sp = float(stats.spearmanr(col[m], y[m])[0]) if m.sum() >= 3 and np.std(col[m]) > 1e-12 else float("nan")
            r_len, _ = safe_pearson(col, length)
            # 서로 다른 값이 5가지도 안 되면 사실상 상수로 본다(어제 '4종은 거의 상수' 판정과 같은 기준)
            uniq = len(np.unique(col[~np.isnan(col)]))
            rows.append({
                "kind": label, "feature_id": fid,
                "name": CANDIDATE_NAMES.get(fid, fid),
                "r": r, "p": p, "spearman": sp, "r_len": r_len,
                "n_uniq": uniq, "constantish": uniq < 5,
            })
    # 상관이 센 것부터 위로 (부호는 무시하고 크기만 본다)
    rows.sort(key=lambda d: (-abs(d["r"]) if not np.isnan(d["r"]) else 1e9))
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# 4) 자질 고르기 — 반드시 배우는 겹 안에서만
# ═══════════════════════════════════════════════════════════════════════════


def select_features(X_tr: np.ndarray, y_tr: np.ndarray, top_k: int) -> list[int]:
    """배우는 겹의 자료만 보고, 사람 점수와 잘 붙는 자질 상위 k개를 고른다.

    **이 함수에는 시험 겹의 자료가 절대 들어오지 않는다.** 그래야 "107건에서
    좋아 보이는 자질을 고른 뒤 그 107건에서 성적을 쟀다"는 낚시를 피할 수 있다.
    값이 거의 변하지 않는 자질은 애초에 후보에서 뺀다(배울 것이 없다).
    """
    scores = []
    for j in range(X_tr.shape[1]):
        col = X_tr[:, j]
        r, _ = safe_pearson(col, y_tr)
        # 상관을 낼 수 없는 자질(전부 같은 값 등)은 맨 뒤로 보낸다
        scores.append((-abs(r) if not np.isnan(r) else 1e9, j))
    scores.sort()
    return sorted(j for _, j in scores[:top_k])


def run_cv_selected(X, y, groups, folds: int, seed: int, top_k: int):
    """화자를 통째로 갈라 가며, 겹마다 자질을 새로 골라 학습하고 시험 본다.

    한 겹의 순서:
      ① 배우는 겹만 보고 자질 상위 k개를 고른다 (시험 겹은 안 본다)
      ② 그 자질만으로 나무 개수를 정한다 (역시 배우는 겹 안에서)
      ③ 학습하고, 한 번도 안 본 시험 겹을 채점한다
      ④ 어느 자질이 몇 점을 밀고 당겼는지(SHAP)를 함께 받아 둔다 — 근거표
    """
    gkf = GroupKFold(n_splits=folds)
    n = len(y)
    oof = np.full(n, np.nan)
    fold_idx = np.full(n, -1, dtype=int)
    picked_per_fold: list[list[int]] = []
    # 자질별 밀고당김 크기를 겹마다 더해 두었다가 마지막에 평균 낸다
    shap_abs_sum = np.zeros(X.shape[1])
    shap_n = 0
    fold_rows = []

    for k, (tr, te) in enumerate(gkf.split(X, y, groups), start=1):
        # ① 자질 고르기 — 배우는 겹 안에서만
        cols = select_features(X[tr], y[tr], top_k)
        picked_per_fold.append(cols)

        # ② 나무 개수 고르기 — 이것도 배우는 겹 안에서만
        n_trees = choose_n_trees(X[tr][:, cols], y[tr], groups[tr], seed)

        # ③ 학습 후 한 번도 안 본 항목 채점
        model = xgb.XGBRegressor(n_estimators=n_trees, random_state=seed, **XGB_PARAMS)
        model.fit(X[tr][:, cols], y[tr], verbose=False)
        oof[te] = model.predict(X[te][:, cols])

        # ④ 예측마다 자질별 기여도를 계산해 둔다(마지막 칸은 출발점이라 뗀다)
        contribs = model.get_booster().predict(xgb.DMatrix(X[te][:, cols]), pred_contribs=True)
        for pos, j in enumerate(cols):
            shap_abs_sum[j] += np.abs(contribs[:, pos]).sum()
        shap_n += len(te)

        fold_idx[te] = k
        fold_rows.append({"fold": k, "n_test": len(te), "n_speakers": len(set(groups[te])),
                          "n_trees": n_trees, "cols": cols,
                          "metrics": score_metrics(oof[te], y[te])})

    mean_abs = shap_abs_sum / max(1, shap_n)
    return oof, fold_idx, fold_rows, picked_per_fold, mean_abs


# ═══════════════════════════════════════════════════════════════════════════
# 5) 어휘 오용 과검출 점검 (분석만, 고치지 않는다)
# ═══════════════════════════════════════════════════════════════════════════


def scan_stored_wordchoice(rows: list[dict]) -> dict:
    """저장된 근거 안에 '어휘 오용' 지적이 실제로 몇 개나 남아 있는지 센다.

    주의: eval_downstream.py 는 근거를 앞에서 6개만 잘라 저장했고(`evidence[:6]`),
    자질 순서상 앞자리를 Kiwi 규칙 자질이 차지한다. 그래서 LLM 오류 근거가
    통째로 잘려 나갔을 가능성이 있다. 그 사실을 숫자로 확인하는 함수다.
    """
    total_ev = 0
    llm_ev = 0
    wc_ev = 0
    for r in rows:
        for e in r.get("evidence", []):
            total_ev += 1
            c = e.get("comment", "")
            # errors.py 는 근거 설명을 "어휘 오용: ..." 처럼 자질 이름으로 시작시킨다
            if any(c.startswith(k) for k in ("조사 오류", "어미 활용 오류", "어휘 오용", "높임법 오류")):
                llm_ev += 1
            if c.startswith("어휘 오용"):
                wc_ev += 1
    return {"total": total_ev, "llm": llm_ev, "word_choice": wc_ev}


def wordchoice_samples(rows: list[dict], n: int) -> list[dict]:
    """어휘 오용이 많이 잡힌 순서로 사례를 골라 눈으로 볼 재료를 만든다."""
    picked = []
    for r in rows:
        raw = {c["feature_id"]: c["raw_value"] for c in r.get("contributions", [])}
        per100 = float(raw.get("error_word_choice", 0.0) or 0.0)
        eoj = len(_eojeols(r["transcript"]))
        picked.append({
            "id": r["id"],
            "human_score": r["human_score"],
            "nationality": r.get("nationality"),
            "eojeol": eoj,
            "per100": per100,
            # 100어절당 값을 절대 건수로 되돌린다(반올림 오차가 있어 근사값이다)
            "count": round(per100 / 100 * eoj),
            "prompt": r.get("prompt", ""),
            "transcript": r["transcript"],
            # LLM 인용을 받아 올 수 없을 때 쓸 대체 재료(임시 근사)
            "odd": odd_words(r["transcript"]),
        })
    picked.sort(key=lambda d: -d["count"])
    return picked[:n]


def rerun_wordchoice_llm(samples: list[dict]) -> list[dict]:
    """고른 사례를 LLM 오류 추출기에 다시 넣어 '어떤 낱말을 왜 오용이라 했는지' 받아 온다.

    저장 파일에 인용이 남아 있지 않아서, 과검출인지 눈으로 판단하려면 이 길밖에 없다.
    `assessment/src` 의 추출기를 그대로 부르므로(고치지 않는다) 지금 서버가 내리는
    판정과 같은 판정을 본다. 인용 검증(원문에 없는 인용 폐기)도 그대로 걸린다.
    """
    from src.features.errors import extract_error_features  # 읽기만 한다
    from src.llm.client import client_for_errors
    from src.scoring.schema import Mode

    # 문법 판정 전용 모델(.env 의 GEMINI_MODEL_ERRORS)로 부른다 — 서버와 같은 조건
    client = client_for_errors()
    out = []
    for s in samples:
        rec = dict(s)
        rec["llm"] = []
        rec["llm_note"] = ""
        try:
            res = extract_error_features(s["transcript"], mode=Mode.SPEAKING,
                                         client=client, item_prompt=s["prompt"])
        except Exception as exc:  # 호출이 막혀도 실험 전체를 멈추지 않는다
            rec["llm_note"] = f"호출 실패: {exc}"
            out.append(rec)
            continue
        # 어휘 오용 자질 하나만 꺼내서 근거(인용·고친 형태·설명)를 모은다
        for fv in res.features:
            if fv.id == "error_word_choice":
                rec["llm_value"] = fv.value
                rec["llm"] = [{"quote": e.quote, "comment": e.comment} for e in fv.evidence]
        if res.warnings:
            rec["llm_note"] = " / ".join(res.warnings)
        out.append(rec)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 6) 출력
# ═══════════════════════════════════════════════════════════════════════════

LINE = "=" * 96


def print_corr_table(rows):
    """자질별 상관표를 찍는다. 신규·기존을 한 표에 섞어 크기순으로 놓는다."""
    print(f"\n{LINE}\n  ① 자질별 상관표 — 사람 점수(0~5)와 같이 움직이나 (107건)\n{LINE}")
    print("  r = 피어슨 상관(-1~1, 0이면 무관) / 길이r = 그 자질이 '어절 수'와 붙어 있는 정도")
    print("  ※ 이 표는 107건 전부를 보고 잰 값이라 '고르는 근거'로 쓰면 낚시가 된다. 진단용이다.")
    print(f"  {'구분':<5}{'자질':<30}{'r':>8}{'p':>9}{'스피어만':>10}{'길이r':>9}{'값종류':>7}  비고")
    print(f"  {'-' * 92}")
    for d in rows:
        flag = "거의 상수" if d["constantish"] else ("방향 역전 의심" if (not np.isnan(d["r"]) and d["r"] < -0.15) else "")
        rr = "  nan" if np.isnan(d["r"]) else f"{d['r']:+.3f}"
        pp = "  nan" if np.isnan(d["p"]) else f"{d['p']:.3f}"
        sp = "  nan" if np.isnan(d["spearman"]) else f"{d['spearman']:+.3f}"
        rl = "  nan" if np.isnan(d["r_len"]) else f"{d['r_len']:+.3f}"
        print(f"  {d['kind']:<5}{d['feature_id']:<30}{rr:>8}{pp:>9}{sp:>10}{rl:>9}{d['n_uniq']:>7}  {flag}")


def print_reversal_diag(X_old, X_new, y, length):
    """방향이 거꾸로인 자질이 사실은 '길이의 그림자'인지 따져 본다."""
    print(f"\n{LINE}\n  ② 방향 역전 진단 — 어휘 다양도·고급 어휘는 왜 거꾸로인가\n{LINE}")
    print("  가설: 짧게 답하면 같은 낱말을 되풀이할 틈이 없어 다양도가 높게 나온다.")
    print("        그런데 짧은 답은 사람 점수가 낮다. 그래서 '다양도 높음 = 점수 낮음'이 된다.")
    print(f"  {'자질':<30}{'점수와 r':>10}{'길이와 r':>10}{'길이 통제 후 r':>16}")
    print(f"  {'-' * 68}")
    for fid in ("lexical_diversity_mattr", "advanced_vocab_ratio", "lexical_density", "clause_density"):
        j = LEGACY_FEATURE_IDS.index(fid)
        col = X_old[:, j]
        r_y, _ = safe_pearson(col, y)
        r_l, _ = safe_pearson(col, length)
        # 길이를 뺀 뒤에도 점수와 붙어 있는지 본다(편상관).
        # 길이 통제 후 상관이 0 근처로 무너지면, 그 자질은 길이를 거꾸로 잰 것에 가깝다
        pr = partial_corr(col, y, length)
        print(f"  {fid:<30}{r_y:>+10.3f}{r_l:>+10.3f}{pr:>+16.3f}")
    # 새로 만든 '내용어 TTR'은 일부러 길이에 약한 자질이라 대조군으로 같이 본다
    j = CANDIDATE_IDS.index("flu_content_ttr")
    print(f"  {'flu_content_ttr(대조군)':<30}"
          f"{safe_pearson(X_new[:, j], y)[0]:>+10.3f}"
          f"{safe_pearson(X_new[:, j], length)[0]:>+10.3f}"
          f"{partial_corr(X_new[:, j], y, length):>+16.3f}")


def partial_corr(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """c(=길이)의 영향을 뺀 뒤 a와 b가 얼마나 붙어 있는지 잰다(편상관).

    방법은 간단하다. a에서 'c로 설명되는 부분'을 빼고, b에서도 같은 것을 뺀 뒤
    남은 찌꺼기끼리 상관을 잰다. 남은 상관이 0에 가까우면 원래 상관은 c 덕분이었다는 뜻이다.
    """
    m = ~(np.isnan(a) | np.isnan(b) | np.isnan(c))
    if m.sum() < 4:
        return float("nan")
    aa, bb, cc = a[m], b[m], c[m]
    if np.std(cc) < 1e-12:
        return safe_pearson(aa, bb)[0]
    ra = aa - np.polyval(np.polyfit(cc, aa, 1), cc)
    rb = bb - np.polyval(np.polyfit(cc, bb, 1), cc)
    return safe_pearson(ra, rb)[0]


def print_compare(m_hand, m_old, m_new, boot_new_old, boot_new_hand, folds, seed, n_boot):
    """세 방식의 성적을 나란히 놓고, 차이가 우연인지까지 찍는다."""
    print(f"\n{LINE}\n  ③ 3자 비교 — 모두 '한 번도 안 본 항목'에서만 채점 ({folds}겹 화자단위, 씨앗 {seed})\n{LINE}")
    print(f"  {'방식':<40}{'피어슨':>10}{'스피어만':>12}{'QWK':>10}")
    print(f"  {'-' * 72}")
    for name, m in (("손 가중치 (지금 채점기)", m_hand),
                    ("기존 12종 XGB (어제 실험)", m_old),
                    ("개편 자질 XGB (오늘)", m_new)):
        print(f"  {name:<36}{m['pearson']:>10.3f}{m['spearman']:>12.3f}{m['qwk']:>10.3f}")

    print(f"\n  차이가 우연인가 (화자 다시뽑기 {n_boot}회, 95% 구간)")
    for label, boot in (("개편 − 기존12종", boot_new_old), ("개편 − 손 가중치", boot_new_hand)):
        (mp, lp, hp), (ms, ls, hs) = boot
        v1 = "유의하게 올랐다" if lp > 0 else ("유의하게 떨어졌다" if hp < 0 else "0을 걸친다 → 올랐다고 말할 수 없다")
        v2 = "유의하게 올랐다" if ls > 0 else ("유의하게 떨어졌다" if hs < 0 else "0을 걸친다 → 올랐다고 말할 수 없다")
        print(f"    {label} 피어슨  {mp:>+.3f}  [{lp:>+.3f}, {hp:>+.3f}]  → {v1}")
        print(f"    {label} 스피어만 {ms:>+.3f}  [{ls:>+.3f}, {hs:>+.3f}]  → {v2}")


def print_selection(fold_rows, picked_per_fold, all_ids, mean_abs):
    """겹마다 어떤 자질이 뽑혔는지 보여 준다 — 뽑힘이 들쭉날쭉하면 그것도 결과다."""
    print(f"\n{LINE}\n  ④ 겹마다 고른 자질 (고르기는 배우는 겹 안에서만 했다)\n{LINE}")
    for r, cols in zip(fold_rows, picked_per_fold):
        names = ", ".join(all_ids[j] for j in cols)
        print(f"  겹{r['fold']} (시험 {r['n_test']}건/화자 {r['n_speakers']}명, 나무 {r['n_trees']}그루, "
              f"피어슨 {r['metrics']['pearson']:+.3f})")
        print(f"      {names}")
    # 다섯 겹 모두에서 뽑힌 자질 = 표본을 바꿔도 살아남은 자질
    stable = set(picked_per_fold[0])
    for cols in picked_per_fold[1:]:
        stable &= set(cols)
    print(f"\n  다섯 겹 전부에서 뽑힌 자질 {len(stable)}개: " +
          (", ".join(all_ids[j] for j in sorted(stable)) or "없음"))

    print(f"\n  배운 모델이 실제로 본 곳 (밀고당김 크기 평균, 큰 순 10개)")
    order = np.argsort(-mean_abs)[:10]
    for j in order:
        if mean_abs[j] <= 0:
            continue
        print(f"    {all_ids[j]:<32}{mean_abs[j]:>8.4f}")


def print_wordchoice(scan, samples, llm_rows, r_proxy):
    """어휘 오용 과검출 점검 재료를 찍는다."""
    print(f"\n{LINE}\n  ⑤ 어휘 오용(error_word_choice) 과검출 점검 — 분석만, 코드는 고치지 않는다\n{LINE}")
    print(f"  저장된 근거 {scan['total']}개 중 LLM 오류 근거 {scan['llm']}개, 그중 어휘 오용 {scan['word_choice']}개")
    if scan["llm"] == 0:
        print("  → eval_downstream.py 가 근거를 앞에서 6개만 저장했고(evidence[:6]) 그 자리를")
        print("     Kiwi 규칙 자질이 모두 차지했다. 즉 **저장 파일에 LLM 인용이 한 개도 없다.**")
        print("     인용 없이는 과검출 여부를 눈으로 볼 수 없어서, 아래 두 가지로 대신한다.")
    print("\n  ※ 임시 대체 경로 ※ Gemini 하루 호출 한도(429)에 걸려 판정을 다시 받아 올 수 없다.")
    print("     그래서 Kiwi 확신도로 '사전에 없는 듯한 낱말'을 골라 나란히 놓았다. 근사이지 판정이 아니다.")
    print(f"     LLM 어휘오용(100어절당) ↔ 사전에 없는 듯한 낱말(100어절당) 상관 r = {r_proxy:+.3f}")
    print("     (이 값이 높으면, LLM 이 지목한 자리가 실제로 망가진 낱말일 가능성이 크다는 뜻)")

    print(f"\n  어휘 오용이 많이 잡힌 사례 {len(samples)}건 (건수 = 100어절당 값 × 어절 수 ÷ 100)")
    for i, s in enumerate(samples, 1):
        print(f"\n  [{i}] {s['id']}  사람점수 {s['human_score']}  {s['nationality']}  "
              f"{s['eojeol']}어절  어휘오용 {s['count']}건({s['per100']:.1f}/100어절)")
        print(f"      문항: {s['prompt'][:60]}")
        print(f"      답안: {s['transcript'][:200]}")
        # 대체 재료: Kiwi 가 모르겠다고 한 낱말을 원문 위치와 함께 보여 준다
        if s["odd"]:
            words = ", ".join(f"'{o['form']}'({o['score']:.0f})" for o in s["odd"][:8])
            print(f"      사전에 없는 듯한 낱말 {len(s['odd'])}개: {words}")
        else:
            print("      사전에 없는 듯한 낱말: 없음  ← 그런데도 어휘 오용이 잡혔다면 과검출 의심 자리")
        row = next((r for r in llm_rows if r["id"] == s["id"]), None)
        if row is not None:
            if row.get("llm_note"):
                print(f"      LLM 재호출: {row['llm_note']}")
            for e in row.get("llm", []):
                print(f"      · 인용 '{e['quote']}' → {e['comment']}")


# ═══════════════════════════════════════════════════════════════════════════
# 7) 계산 함수가 제대로 도는지 예시로 확인
# ═══════════════════════════════════════════════════════════════════════════


def selftest() -> int:
    """새 자질 계산기를 값이 뻔한 예시 문장에 넣어 보고 눈으로 확인한다.

    자질 추출기는 훑어봐서 맞는지 알 수 없다. 여기서 확인하는 것:
      - 어절·문장·군말·반복을 사람이 손으로 센 값과 같게 세는가
      - 문장을 맺지 못한 답안에서 '종결어미 비율'이 실제로 내려가는가
      - 자질 고르기가 시험 겹 자료를 절대 보지 않는가 (새는 데 확인)
    """
    ok = True
    print("── 계산 함수 확인 ────────────────────────────────────────────────")

    # (1) 손으로 셀 수 있는 문장
    t1 = "어 음 저는 회사에 갔어요. 그리고 밥을 먹었어요."
    c1 = extract_candidates(t1, {"error_word_choice": 0.0})
    print(f"  예시1 «{t1}»")
    print(f"    어절 수 {c1.values['amt_eojeol']:.0f} (기대 8) / 문장 수 {c1.values['amt_sentence']:.0f} (기대 2)")
    print(f"    종결어미로 끝난 문장 비율 {c1.values['sent_final_ending_ratio']:.2f} (기대 1.00)")
    print(f"    군말 비율 {c1.values['flu_filler_ratio']:.3f}  (군말 '어','음' 2개)")
    ok &= c1.values["amt_eojeol"] == 8 and c1.values["amt_sentence"] == 2
    ok &= abs(c1.values["sent_final_ending_ratio"] - 1.0) < 1e-9
    ok &= c1.values["flu_filler_ratio"] > 0

    # (2) 문장을 맺지 못하고 끊긴 답안 → 종결어미 비율이 0 이어야 한다
    t2 = "저는 회사에서 일을"
    c2 = extract_candidates(t2, {})
    print(f"  예시2 «{t2}» → 종결어미 비율 {c2.values['sent_final_ending_ratio']:.2f} (기대 0.00)")
    ok &= c2.values["sent_final_ending_ratio"] == 0.0

    # (3) 같은 어절을 곧바로 되풀이한 답안
    t3 = "저는 저는 밥을 먹었어요."
    c3 = extract_candidates(t3, {})
    print(f"  예시3 «{t3}» → 옆 어절 반복 비율 {c3.values['flu_repeat_eojeol_ratio']:.3f} (기대 0.250 = 1/4)")
    ok &= abs(c3.values["flu_repeat_eojeol_ratio"] - 0.25) < 1e-9

    # (4) 오류 밀도 되돌리기: 100어절당 10건 × 20어절 = 2건
    c4 = extract_candidates("가 " * 20, {"error_word_choice": 10.0})
    print(f"  예시4 20어절·어휘오용 10.0/100어절 → 절대 건수 {c4.values['err_word_choice_count']:.1f} (기대 2.0)")
    ok &= abs(c4.values["err_word_choice_count"] - 2.0) < 1e-6

    # (5) 사전에 없는 듯한 낱말 골라내기 — 정상 문장은 0개, 망가진 문장은 잡혀야 한다
    t5a = "저는 회사에 가서 일을 했어요."
    t5b = "제 고항은 개후가 덥고 디브 구수할 때"
    o5a, o5b = odd_words(t5a), odd_words(t5b)
    print(f"  예시5 정상 문장 «{t5a}» → 사전에 없는 듯한 낱말 {len(o5a)}개 (기대 0)")
    print(f"        망가진 문장 «{t5b}» → {len(o5b)}개: "
          + ", ".join(f"'{o['form']}'({o['score']:.0f})" for o in o5b))
    ok &= len(o5a) == 0 and len(o5b) >= 3

    # (6) 자질 고르기가 시험 겹을 보지 않는가 — 시험 겹 정답을 뒤섞어도 선택이 그대로여야 한다
    rng = np.random.default_rng(0)
    Xs = rng.normal(size=(60, 8))
    ys = Xs[:, 3] * 2 + rng.normal(scale=0.3, size=60)
    tr, te = np.arange(0, 40), np.arange(40, 60)
    pick1 = select_features(Xs[tr], ys[tr], 3)
    ys2 = ys.copy()
    rng.shuffle(ys2[te])          # 시험 겹 정답만 엉망으로 만든다
    pick2 = select_features(Xs[tr], ys2[tr], 3)
    print(f"  자질 고르기 새는지 확인 → 시험 겹 정답을 뒤섞기 전 {pick1}, 뒤섞은 후 {pick2} (같아야 정상)")
    ok &= pick1 == pick2
    # 정말로 '정답을 만든 자질'(3번)을 골라내는지도 본다
    print(f"    (정답을 만든 자질은 3번 — 뽑힌 목록에 들어 있어야 한다: {3 in pick1})")
    ok &= 3 in pick1

    # (7) 편상관: 길이만으로 만들어 낸 가짜 상관은 길이를 빼면 0 근처로 무너져야 한다
    L = rng.normal(size=200)
    A = L + rng.normal(scale=0.1, size=200)
    B = L + rng.normal(scale=0.1, size=200)
    print(f"  편상관 확인 → 원래 r {safe_pearson(A, B)[0]:+.3f}, 길이 통제 후 "
          f"{partial_corr(A, B, L):+.3f} (기대: 크게 무너짐)")
    ok &= abs(partial_corr(A, B, L)) < 0.3

    print("── 결과: " + ("전부 통과" if ok else "실패한 항목 있음") + " ──")
    return 0 if ok else 1


# ═══════════════════════════════════════════════════════════════════════════
# 8) 실행
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")   # 윈도우 명령창에서 한글이 깨지지 않게
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="자질 후보를 새로 만들고 정직한 절차로 걸러낸다")
    ap.add_argument("--data", default=r"D:\해커톤데이터\downstream_results.jsonl")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--top-k", type=int, default=10, help="겹마다 고를 자질 개수 (기본 10)")
    ap.add_argument("--wordchoice-n", type=int, default=20, help="어휘 오용 사례 개수 (기본 20)")
    ap.add_argument("--wordchoice-llm", type=int, default=0,
                    help="어휘 오용 사례 중 앞 N건을 LLM에 다시 물어 인용을 받아 온다 (기본 0=안 함)")
    ap.add_argument("--out-pred", default=r"D:\해커톤데이터\feature_lab_predictions.jsonl")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    # ── 재료 준비 ────────────────────────────────────────────────────────
    rows = load_rows(Path(args.data))
    X_old, X_new, y, groups, base, meta, sample_ev = build_matrices(rows)
    length = X_new[:, CANDIDATE_IDS.index("amt_eojeol")]
    print(f"읽은 항목 {len(y)}건 (사람 전사·정상 처리) / 화자 {len(set(groups))}명")
    print(f"기존 자질 {X_old.shape[1]}개 + 새 후보 {X_new.shape[1]}개 = 합계 {X_old.shape[1] + X_new.shape[1]}개")

    # 자질 값이 어디서 나왔는지 눈으로 볼 수 있게 첫 항목의 근거를 보여 준다
    print(f"\n  [근거 예시] {meta[0]['id']}")
    print(f"  답안: {rows[0]['transcript'][:80]}")
    for e in sample_ev[:5]:
        print(f"    · {e.feature_id}: '{e.quote}' ({e.start}~{e.end}) — {e.comment}")

    # ── ① 상관표 ─────────────────────────────────────────────────────────
    corr_rows = correlation_table(X_new, X_old, y, length)
    print_corr_table(corr_rows)

    # ── ② 방향 역전 진단 ─────────────────────────────────────────────────
    print_reversal_diag(X_old, X_new, y, length)

    # ── ③ 세 방식 비교 ───────────────────────────────────────────────────
    # 손 가중치 + 기존 12종 XGB 는 어제 스크립트를 그대로 불러서 잰다(절차가 갈리지 않게)
    oof_old, oof_base, _, _, _, _, _ = run_cv(X_old, y, groups, base, args.folds, args.seed)
    m_hand = baseline_metrics(base, oof_base, y)
    m_old = score_metrics(oof_old, y)

    # 개편 자질 = 기존 12개 + 새 후보를 한 표로 합친 뒤, 겹마다 상위 k개만 고른다
    X_all = np.hstack([X_old, X_new])
    all_ids = list(LEGACY_FEATURE_IDS) + list(CANDIDATE_IDS)
    oof_new, fold_idx, fold_rows, picked, mean_abs = run_cv_selected(
        X_all, y, groups, args.folds, args.seed, args.top_k)
    m_new = score_metrics(oof_new, y)

    # 상관 차이의 다시뽑기: 손 가중치는 눈금을 옮겨도 상관이 같으므로 원점수를 쓴다
    boot_new_old = bootstrap_diff(oof_new, oof_old, y, groups, args.bootstrap, args.seed)
    boot_new_hand = bootstrap_diff(oof_new, base, y, groups, args.bootstrap, args.seed)
    print_compare(m_hand, m_old, m_new, boot_new_old, boot_new_hand,
                  args.folds, args.seed, args.bootstrap)

    # ── ④ 겹마다 고른 자질 ───────────────────────────────────────────────
    print_selection(fold_rows, picked, all_ids, mean_abs)

    # ── ⑤ 어휘 오용 과검출 점검 ──────────────────────────────────────────
    scan = scan_stored_wordchoice(rows)
    samples = wordchoice_samples(rows, args.wordchoice_n)
    llm_rows = []
    if args.wordchoice_llm > 0:
        print(f"\n  LLM 재호출 중 ... ({args.wordchoice_llm}건)")
        llm_rows = rerun_wordchoice_llm(samples[:args.wordchoice_llm])
    # LLM 어휘오용 값과 규칙 근사값이 얼마나 붙어 있는지 — 과검출 판단의 핵심 숫자
    r_proxy, _ = safe_pearson(X_old[:, LEGACY_FEATURE_IDS.index("error_word_choice")],
                              X_new[:, CANDIDATE_IDS.index("flu_oddword_per100")])
    print_wordchoice(scan, samples, llm_rows, r_proxy)

    # ── 항목별 예측 저장 (점수만 남기지 않는다) ──────────────────────────
    out = Path(args.out_pred)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for i, mi in enumerate(meta):
            f.write(json.dumps({
                **mi,
                "fold": int(fold_idx[i]),
                "human_score": float(y[i]),
                "hand_score_100": float(base[i]),
                "xgb_old_0_5": round(float(oof_old[i]), 4),
                "xgb_new_0_5": round(float(oof_new[i]), 4),
                # 이 예측을 만드는 데 실제로 쓴 자질과 그 값 — 근거 없는 점수를 남기지 않는다
                "features_used": [all_ids[j] for j in picked[int(fold_idx[i]) - 1]],
                "feature_values": {all_ids[j]: (None if np.isnan(X_all[i, j]) else round(float(X_all[i, j]), 4))
                                   for j in picked[int(fold_idx[i]) - 1]},
            }, ensure_ascii=False) + "\n")
    print(f"\n항목별 예측·자질값 저장: {out}  ({len(meta)}줄)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
