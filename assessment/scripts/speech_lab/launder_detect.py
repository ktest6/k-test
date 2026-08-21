# -*- coding: utf-8 -*-
"""⑦-2 세탁 탐지기 — 사람 라벨이 학습자의 실수를 몰래 고쳐 놓았는지 가려낸다 (판정 단계).

**"세탁"이 무엇인가**
외국인 학습자가 "과심사"라고 잘못 말했는데 사람 라벨러가 표준형 "관심사"로 적어
버린 것. 이런 줄로 받아쓰기 모델을 가르치면 모델이 **오류를 지우는 버릇**을 배운다.
그러면 채점기가 볼 오류가 사라지고, 틀린 응시자의 점수가 안 깎인다.

**이 도구는 보통의 품질 필터와 방향이 반대다.**
보통은 "표준 한국어답지 않은 줄"을 버린다. 우리는 정반대로 **오류가 그대로 적힌
줄은 반드시 남기고**, 오류가 지워진(=세탁된) 줄만 걸러낸다. 이 원칙이 이 도구의
존재 이유이므로, 확신이 없는 자리는 전부 '보류(남김)'로 둔다.

**판정 방식 — 증인 다수결**
같은 녹음을 증인 4명(오디션으로 뽑은 받아쓰기 모델)에게 들려주고 사람 라벨과
견준다. 한 자리에서 증인 2명 이상이 **같은 다른 형태**를 적었고 라벨 지지보다
표가 많으면 그 자리를 후보로 본다(2:2 동점이면 보류).

**방향 판정 (여기가 급소)**
후보라고 다 세탁이 아니다. 반대 경우가 있기 때문이다.

    라벨 "채위"(학습자가 실제로 낸 오류)  vs  증인들 "책이"(증인들이 고쳐 적음)

이건 라벨이 **잘한** 것이고, 세탁한 쪽은 증인이다. 이걸 걸러내면 좋은 라벨을
버리게 된다. 그래서 "어느 쪽이 표준형인가"를 따로 판정하고, 라벨이 표준형일
때만 세탁으로 표시한다. 판정 근거는 세 가지를 이 순서로 본다.

    ① 제시문(낭독 과제) — 읽으라고 준 문장이 곧 표준형이다. 가장 확실하다
    ② 군말(어·음·그)  — 라벨에 없고 증인들에게만 있으면 라벨이 지운 것이다
    ③ Kiwi 형태소 분석 — 어느 쪽이 한국어로 더 그럴듯하게 분석되는가

셋 다 갈리지 않으면 '불명' → 보류(남김)다.

쓰는 법:
    # (a) 판정 — 학습쌍 전체를 훑어 세탁 의심을 찾는다
    python launder_detect.py --labels D:/해커톤데이터/v1_selection.json \\
        --witness D:/해커톤데이터/launder/qwen3-asr-1.7b.jsonl --witness ... \\
        --out D:/해커톤데이터/launder_verdicts.jsonl

    # (b) gold 검증 — 정답을 아는 499건으로 탐지기 성적을 낸다
    python launder_detect.py --mode gold --gold ../../../data/manifests/gold_100.jsonl \\
        --gold-orig ../../../data/manifests/71479_all.jsonl \\
        --witness D:/해커톤데이터/audition_transcripts.jsonl

    # (c) 정제 — 세탁 의심만 뺀 새 선별 목록을 만든다
    python launder_detect.py --labels D:/해커톤데이터/v1_selection.json \\
        --witness ... --emit-selection D:/해커톤데이터/v2_selection.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    DATA_ROOT,
    enable_utf8_output,
    norm_text,
    print_table,
    read_manifest,
)

# ── 증인단 ───────────────────────────────────────────────────────────────────
#: 8/7 오디션에서 채용된 증인 4명. 이름은 audition.py 가 전사 파일에 적는 이름
#: 그대로다(그래야 오디션 때 받아쓴 것을 그대로 다시 쓸 수 있다).
#: 문맥형 2 + 직청형 2 로 성격을 섞었다 — 같은 성격끼리만 모으면 같이 틀려서
#: 다수결이 '다수의 착각'이 된다.
DEFAULT_WITNESSES = (
    "qwen3-asr-1.7b",     # 문맥형
    "fw(small)",          # 문맥형
    "owsm-ctc-v4",        # 직청형
    "sensevoice-small",   # 직청형
)

#: 군말(말을 고르며 내는 소리)로 볼 글자. 이 글자들로만 이루어진 토막을 군말로 본다.
#: 좁게 잡았다 — '네'·'에' 같은 것은 진짜 낱말일 때가 많아 일부러 뺐다.
FILLER_CHARS = set("어음그아으엄")

#: 증인 하나가 라벨보다 이만큼 넘게 길게 쏟아 내면 '폭주'로 보고 그 건에서 뺀다.
#: 왜 필요한가: 폭주한 증인은 라벨 전체와 어긋나서 **불일치 자리 하나를 통째로
#: 삼켜 버린다**. 그러면 다른 증인들이 잡아낸 진짜 자리까지 한 덩이로 뭉개져
#: 판정이 안 된다. (8/7 오디션 실측: fw(small) 이 100건 중 4건에서 같은 말을
#: 끝없이 되풀이했다)
RUNAWAY_RATIO = 3.0
RUNAWAY_SLACK = 10


# ── 글자 다듬기 ──────────────────────────────────────────────────────────────
def tokenize(text: str) -> list[str]:
    """글을 **비교용 어절 목록**으로 바꾼다.

    띄어 놓은 자리로 자른 뒤 어절마다 공백·문장부호를 떼어 낸다. 받아쓰기 모델마다
    쉼표 찍는 버릇과 띄어쓰기가 다른데, 그대로 두면 '말을 잘못했다'가 아니라
    '쉼표를 안 찍었다'가 불일치로 잡히기 때문이다.
    """
    out = []
    for word in (text or "").split():
        w = norm_text(word)
        if w:
            out.append(w)
    return out


def is_filler(form: str) -> bool:
    """이 토막이 군말('어', '음', '어어' 같은 것)인지 본다."""
    return bool(form) and all(ch in FILLER_CHARS for ch in form)


# ── 불일치 자리 찾기 ─────────────────────────────────────────────────────────
@dataclass
class Record:
    """증인 한 명이 라벨과 어긋난 자리 하나.

    i1·i2 는 **라벨 어절 목록에서의 위치**다. 라벨을 기준자로 삼는 이유는
    증인 4명을 서로 견주려면 공통의 눈금이 필요하기 때문이다.
    (i1 == i2 이면 '라벨에는 없는데 증인이 끼워 넣은 자리' — 군말이 주로 여기다)
    """

    witness: str
    i1: int
    i2: int
    label_form: str      # 라벨이 그 자리에 적어 놓은 것
    witness_form: str    # 증인이 그 자리에 적은 것


def witness_records(label_tokens: list[str], hyp_tokens: list[str],
                    witness: str) -> list[Record]:
    """증인 한 명의 받아쓰기를 라벨과 나란히 맞춰 어긋난 자리를 모두 뽑는다.

    difflib 이 두 어절 목록을 맞춰 주고, 그중 '같음'이 아닌 구간만 가져온다.
    이미 어절마다 문장부호를 떼어 둔 상태라, 여기서 걸리는 것은 띄어쓰기·문장부호가
    아닌 **진짜 다른 말**이다. 그래도 붙여쓰기 차이("관련 있는" vs "관련있는")는
    어절 수가 달라 걸리므로, 양쪽을 붙여 보고 같으면 버린다.
    """
    records: list[Record] = []
    matcher = difflib.SequenceMatcher(None, label_tokens, hyp_tokens)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        label_form = "".join(label_tokens[i1:i2])
        hyp_form = "".join(hyp_tokens[j1:j2])
        # 붙여 놓고 보면 같다 = 띄어쓰기만 다른 것이다. 불일치로 세지 않는다
        if label_form == hyp_form:
            continue
        records.append(Record(witness, i1, i2, label_form, hyp_form))
    return records


def merge_sites(records: list[Record]) -> list[tuple[int, int, list[Record]]]:
    """증인마다 따로 찾은 불일치들을 **겹치는 것끼리 한 자리로** 묶는다.

    증인 A는 3번 어절만, 증인 B는 3~4번 어절을 통째로 다르게 적었을 수 있다.
    같은 곳을 가리키는 것이므로 한 자리로 봐야 표를 셀 수 있다.
    닿기만 해도(끝과 시작이 같아도) 묶는다 — 나누는 쪽으로 틀리면 같은 자리를
    두 번 세게 되는데, 묶는 쪽으로 틀리면 판정이 어려워질 뿐이라 안전하다.

    돌려주는 것은 (시작 어절, 끝 어절, 그 자리에 걸린 증인 기록들) 목록이다.
    """
    if not records:
        return []

    # 자리 순서대로 세워 놓고 앞에서부터 이어 붙인다(같은 자리면 증인 이름순 — 재현성)
    order = sorted(records, key=lambda r: (r.i1, r.i2, r.witness))
    groups: list[tuple[int, int, list[Record]]] = []
    start, end, bag = order[0].i1, order[0].i2, [order[0]]

    for rec in order[1:]:
        if rec.i1 <= end:            # 앞 묶음에 닿거나 겹친다 → 같은 자리로 본다
            bag.append(rec)
            end = max(end, rec.i2)
        else:
            groups.append((start, end, bag))
            start, end, bag = rec.i1, rec.i2, [rec]
    groups.append((start, end, bag))
    return groups


def form_over(recs: list[Record], label_tokens: list[str], start: int, end: int) -> str:
    """증인 한 명이 **이 자리 전체를** 뭐라고 적었는지 하나의 글로 만든다.

    자리가 3~5번 어절인데 그 증인은 3번만 다르게 적었다면, 4·5번은 라벨과 같다는
    뜻이므로 라벨 것을 그대로 붙여 준다. 그래야 자리 전체를 다르게 적은 다른
    증인과 같은 눈금에서 견줄 수 있다.
    """
    pieces: list[str] = []
    cursor = start
    for rec in sorted(recs, key=lambda r: (r.i1, r.i2)):
        # 이 증인이 손대지 않은 앞부분은 라벨 것을 그대로 쓴다
        pieces.extend(label_tokens[cursor:rec.i1])
        pieces.append(rec.witness_form)
        cursor = max(cursor, rec.i2)
    pieces.extend(label_tokens[cursor:end])
    return "".join(pieces)


# ── 표 세기 ──────────────────────────────────────────────────────────────────
@dataclass
class Vote:
    """한 자리의 표 계산 결과."""

    label_form: str
    alt_form: str
    label_voters: list[str]      # 라벨과 같게 적은 증인들
    alt_voters: list[str]        # 가장 표가 많은 '다른 형태'를 적은 증인들
    all_forms: dict[str, list[str]]   # 형태 → 그렇게 적은 증인들 (근거로 남긴다)


def count_votes(label_form: str, forms: dict[str, str]) -> Vote | None:
    """한 자리에서 라벨 편과 대안 편의 표를 센다.

    forms 는 {증인 이름: 그 증인이 이 자리에 적은 글}이다. 라벨과 똑같이 적은
    증인은 라벨 편, 다르게 적은 증인은 자기가 적은 형태 편이다. 대안이 여럿이면
    표가 가장 많은 하나를 대표로 세운다(표가 같으면 글자 순 — 실행할 때마다
    답이 달라지지 않게 하려는 것이다).

    아무도 다르게 적지 않았으면 볼 것이 없으므로 None 을 돌려준다.
    """
    tally: dict[str, list[str]] = {}
    for witness in sorted(forms):
        tally.setdefault(forms[witness], []).append(witness)

    label_voters = tally.get(label_form, [])
    alts = [(form, voters) for form, voters in tally.items() if form != label_form]
    if not alts:
        return None

    alts.sort(key=lambda item: (-len(item[1]), item[0]))
    alt_form, alt_voters = alts[0]
    return Vote(label_form, alt_form, label_voters, alt_voters, tally)


# ── 방향 판정: 어느 쪽이 표준형인가 ──────────────────────────────────────────
class KiwiStandardness:
    """Kiwi 형태소 분석기에게 "이 문장이 한국어로 얼마나 그럴듯한가"를 물어보는 자.

    Kiwi 는 문장을 형태소로 쪼개면서 그 쪼갬이 얼마나 그럴듯한지 점수를 함께 준다
    (0에 가까울수록 그럴듯하다). 표준형 "관심사와"는 [관심사+와]로 깔끔하게
    쪼개지지만, 오류형 "과심사와"는 [과+심사+와]로 억지스럽게 쪼개져 점수가 낮다.

    **한계를 분명히 해 둔다**: 이 점수는 "표준형인가"가 아니라 "흔한 한국어인가"를
    잰다. 그래서 둘 다 멀쩡한 한국어일 때(예: "요리만" vs "요리를")는 뜻이 없다.
    그런 자리는 점수 차가 작게 나오므로 문턱값을 두어 '불명'으로 흘려보낸다.
    """

    def __init__(self):
        from kiwipiepy import Kiwi

        self._kiwi = Kiwi()
        # 같은 문장을 자리마다 되풀이해 묻게 되므로 한 번 물은 것은 적어 둔다
        self._cache: dict[str, float | None] = {}

    def score(self, sentence: str) -> float | None:
        """문장 하나의 그럴듯함 점수. 분석에 실패하면 None."""
        if sentence in self._cache:
            return self._cache[sentence]
        try:
            result = self._kiwi.analyze(sentence)
            value = result[0][1] if result else None
        except Exception:
            # 분석기가 넘어지더라도 판정 전체를 멈추지 않는다. 그 자리는 '불명'이 된다
            value = None
        self._cache[sentence] = value
        return value


def judge_direction(label_tokens: list[str], start: int, end: int,
                    label_form: str, alt_form: str,
                    prompt_norm: str | None, scorer, margin: float) -> tuple[str, str]:
    """이 자리에서 **라벨이 표준형인지 오류형인지**를 판정한다. 탐지기의 급소다.

    돌려주는 값은 (방향, 사유)이고 방향은 셋 중 하나다.

      세탁방향 — 라벨이 표준형, 증인들이 오류형. 라벨이 고쳐 적은 것이다 → 의심
      역방향   — 라벨이 오류형, 증인들이 표준형. **라벨이 잘한 것이다** → 남긴다
      불명     — 가릴 수 없다 → 보류(남긴다)

    확신이 없으면 무조건 '불명'이다. 좋은 라벨을 잘못 버리는 쪽이,
    나쁜 라벨을 몇 개 놓치는 쪽보다 나쁘기 때문이다.
    """
    # ① 군말 — 라벨에는 없는데 증인들만 '어/음/그'를 적었다면 라벨이 지운 것이다.
    #    (8/4 사람 귀 감사에서 실제로 나왔다: 한 줄에서 '어'·'음' 10개가 통째로 빠져 있었다)
    if not label_form and is_filler(alt_form):
        return "세탁방향", f"라벨이 군말 '{alt_form}' 을 지웠다"
    # 반대로 라벨에만 군말이 있으면 라벨이 들리는 대로 살린 것이다 — 잘한 라벨
    if not alt_form and is_filler(label_form):
        return "역방향", f"라벨이 군말 '{label_form}' 을 살렸다"

    # ② 제시문 — 낭독 과제는 읽으라고 준 문장이 있다. 다만 **라벨을 지키는 쪽으로만**
    #    쓴다. 처음에는 "라벨이 제시문과 같으면 라벨이 표준형이니 세탁"으로 만들었는데,
    #    8/8 gold 100건 실측에서 그렇게 잡은 낭독 4건이 **전부 헛detection** 이었다.
    #    까닭을 따져 보면 당연하다 — 낭독은 대부분 제대로 읽으므로, "라벨=제시문인데
    #    증인들이 다르게 적었다"의 흔한 원인은 세탁이 아니라 **증인들이 잘못 들은 것**이다.
    #    그래서 제시문이 라벨 편일 때는 곧바로 세탁이라 하지 않고 Kiwi 의 확인을 받는다.
    prompt_backs_launder = False
    if prompt_norm:
        label_in = bool(label_form) and label_form in prompt_norm
        alt_in = bool(alt_form) and alt_form in prompt_norm

        # 라벨을 지키는 두 갈래는 그 자리에서 판정을 끝낸다(거부권)
        if alt_in and not label_in:
            return "역방향", f"증인 '{alt_form}' 이 제시문에 있고 라벨 형태는 없다"
        # 둘 다 제시문에 없다 = **라벨이 이미 제시문과 다르게 적혀 있다**는 뜻이다.
        # 세탁이란 라벨이 표준형(제시문)을 적어 놓은 것인데, 여기서는 라벨 자신이
        # 표준형이 아니다. 즉 라벨은 이 자리에서 오류를 이미 살려 놓았고, 증인들은
        # 그 오류를 다르게 알아들었을 뿐이다.
        # (실측 예: 제시문 "너무 비싸다"를 응시자가 "비쌌다"로 읽었고 라벨도 "비쌌다"로
        #  옳게 적었는데, 증인 3명이 "비싼다"로 잘못 들어 세탁으로 몰리던 자리다)
        if bool(label_form) and not label_in and not alt_in:
            return "역방향", f"라벨 '{label_form}' 이 제시문과 이미 다르다 — 오류를 살린 자리"

        prompt_backs_launder = label_in and not alt_in

    # ③ Kiwi — 문장을 통째로 두 벌 만들어(라벨판/증인판) 어느 쪽이 더 그럴듯한지 본다.
    #    낱말만 떼어 재지 않고 문장째 재는 이유: 앞뒤 말을 봐야 판이 갈린다.
    if scorer is not None:
        label_sentence = " ".join(
            label_tokens[:start] + ([label_form] if label_form else []) + label_tokens[end:]
        )
        alt_sentence = " ".join(
            label_tokens[:start] + ([alt_form] if alt_form else []) + label_tokens[end:]
        )
        s_label, s_alt = scorer.score(label_sentence), scorer.score(alt_sentence)
        if s_label is not None and s_alt is not None:
            # 글자 수로 나눈다. 긴 자리는 점수 차가 그냥 크게 나오기 때문이다
            span = max(len(label_form), len(alt_form), 1)
            gap = (s_label - s_alt) / span
            backing = "제시문도 라벨 편이고 " if prompt_backs_launder else ""
            if gap >= margin:
                return "세탁방향", (f"{backing}Kiwi: 라벨 쪽이 표준 한국어로 더 깔끔하다 "
                                    f"(글자당 {gap:+.1f})")
            if gap <= -margin:
                return "역방향", (f"Kiwi: 증인 쪽이 표준 한국어로 더 깔끔하다 "
                                  f"(글자당 {gap:+.1f})")
            return "불명", f"Kiwi 점수 차가 작다 (글자당 {gap:+.1f}) — 보류"

    # 제시문이 라벨 편이더라도 그것만으로는 버리지 않는다(위 ②의 실측 근거)
    if prompt_backs_launder:
        return "불명", f"제시문은 라벨 편이지만 Kiwi 확인을 못 받았다 — 보류"

    return "불명", "표준형을 가릴 근거가 없다 — 보류"


# ── 쌍 하나 판정 ─────────────────────────────────────────────────────────────
@dataclass
class PairVerdict:
    """학습쌍 하나에 대한 판정 결과. 점수만이 아니라 **근거를 반드시 함께** 담는다."""

    id: str
    verdict: str                 # suspect(세탁 의심) / hold(보류) / keep(남김)
    reason: str
    sites: list[dict] = field(default_factory=list)
    skipped: dict = field(default_factory=dict)   # 표에서 뺀 증인과 그 까닭

    def to_dict(self) -> dict:
        return {"id": self.id, "판정": self.verdict, "사유": self.reason,
                "자리": self.sites, "제외증인": self.skipped}


def judge_pair(pair_id: str, label: str, transcripts: dict[str, str],
               prompt: str | None = None, scorer=None,
               min_votes: int = 2, margin: float = 1.0) -> PairVerdict:
    """학습쌍 하나(라벨 + 증인 4명의 받아쓰기)를 판정한다.

    순서는 이렇다.
      1) 증언할 수 없는 증인을 뺀다 (아무 말도 못 적었거나 폭주한 증인)
      2) 증인마다 라벨과 어긋난 자리를 뽑고, 겹치는 것끼리 한 자리로 묶는다
      3) 자리마다 표를 세고, 표가 갈리면 어느 쪽이 표준형인지 판정한다
      4) 자리 판정을 모아 쌍 전체의 판정을 낸다
    """
    label_tokens = tokenize(label)
    prompt_norm = norm_text(prompt) if prompt else None

    # 1) 증언할 수 없는 증인 골라내기 ────────────────────────────────────────
    active: dict[str, list[str]] = {}
    skipped: dict[str, str] = {}
    for witness in sorted(transcripts):
        hyp_tokens = tokenize(transcripts[witness])
        if not hyp_tokens:
            # 빈 전사 = 아무 증언도 안 한 것. 라벨 편으로도 대안 편으로도 세면 안 된다
            skipped[witness] = "빈 전사"
            continue
        if len(hyp_tokens) > len(label_tokens) * RUNAWAY_RATIO + RUNAWAY_SLACK:
            skipped[witness] = f"폭주(어절 {len(hyp_tokens)} vs 라벨 {len(label_tokens)})"
            continue
        active[witness] = hyp_tokens

    if len(active) < min_votes:
        return PairVerdict(pair_id, "hold",
                           f"증언할 수 있는 증인이 {len(active)}명뿐이라 표를 셀 수 없다",
                           skipped=skipped)

    # 2) 어긋난 자리 모으기 ──────────────────────────────────────────────────
    records: list[Record] = []
    for witness, hyp_tokens in active.items():
        records.extend(witness_records(label_tokens, hyp_tokens, witness))

    if not records:
        return PairVerdict(pair_id, "keep", "증인 전원이 라벨과 같게 적었다",
                           skipped=skipped)

    # 3) 자리마다 표를 세고 방향을 본다 ──────────────────────────────────────
    sites: list[dict] = []
    for start, end, bag in merge_sites(records):
        label_form = "".join(label_tokens[start:end])

        # 이 자리에서 증인들이 각각 뭐라고 적었는지 모은다.
        # 이 자리에 기록이 없는 증인은 라벨과 같게 적은 것이다
        by_witness: dict[str, list[Record]] = {}
        for rec in bag:
            by_witness.setdefault(rec.witness, []).append(rec)
        forms = {
            witness: (form_over(by_witness[witness], label_tokens, start, end)
                      if witness in by_witness else label_form)
            for witness in active
        }

        vote = count_votes(label_form, forms)
        if vote is None:
            continue

        n_alt, n_label = len(vote.alt_voters), len(vote.label_voters)
        site = {
            "어절위치": [start, end],
            "라벨형태": label_form,
            "증인형태": vote.alt_form,
            "증인표": n_alt,
            "라벨표": n_label,
            "증인들": vote.alt_voters,
            "라벨지지": vote.label_voters,
            "모든형태": {f: ws for f, ws in sorted(vote.all_forms.items())},
        }

        # ③-1 표 규칙: 대안이 2표 이상 + 라벨 지지보다 많아야 후보다
        if n_alt < min_votes:
            site["자리판정"] = "약함"
            site["사유"] = f"대안 {n_alt}표뿐 (필요 {min_votes}표)"
        elif n_alt <= n_label:
            # 2:2 동점이 여기 걸린다. 절반이 라벨 편인데 라벨을 버릴 수는 없다
            site["자리판정"] = "보류"
            site["사유"] = f"{n_alt}:{n_label} 로 갈려 판정 보류"
        else:
            # ③-2 방향 규칙: 라벨이 표준형일 때만 세탁이다
            direction, why = judge_direction(label_tokens, start, end, label_form,
                                             vote.alt_form, prompt_norm, scorer, margin)
            site["방향"] = direction
            site["사유"] = why
            site["자리판정"] = {"세탁방향": "세탁", "역방향": "역방향",
                                "불명": "보류"}[direction]
        sites.append(site)

    # 4) 쌍 전체 판정 ────────────────────────────────────────────────────────
    laundered = [s for s in sites if s["자리판정"] == "세탁"]
    held = [s for s in sites if s["자리판정"] == "보류"]
    reversed_ = [s for s in sites if s["자리판정"] == "역방향"]

    if laundered:
        head = laundered[0]
        verdict, reason = "suspect", (
            f"세탁 의심 {len(laundered)}자리 — 예: 라벨 '{head['라벨형태'] or '(없음)'}' "
            f"vs 증인 {head['증인표']}명 '{head['증인형태'] or '(없음)'}' · {head['사유']}"
        )
    elif held:
        verdict, reason = "hold", f"판정 보류 {len(held)}자리 — 남긴다"
    elif reversed_:
        verdict, reason = "keep", (
            f"라벨이 오류를 살린 자리 {len(reversed_)}곳 — 좋은 라벨이다"
        )
    else:
        verdict, reason = "keep", "세탁으로 볼 자리가 없다"

    return PairVerdict(pair_id, verdict, reason, sites, skipped)


# ── 파일 읽기 ────────────────────────────────────────────────────────────────
def load_witness_transcripts(paths: list[str], keep: set[str] | None
                             ) -> dict[str, dict[str, str]]:
    """증인들의 받아쓰기 파일을 읽어 {파일 id: {증인 이름: 받아쓴 글}} 로 모은다.

    두 가지 파일 모양을 다 받는다.
      · launder_transcribe.py 가 낸 것  {"id":…, "model":…, "text":…}
      · audition.py 가 낸 것            {"id":…, "model":…, "hyp":…}
    같은 (증인, 파일)이 두 번 나오면 나중 것으로 덮는다(이어 돌린 결과가 최신이다).
    """
    by_id: dict[str, dict[str, str]] = {}
    for path in paths:
        with Path(path).open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                model = row.get("model")
                # 채용된 증인만 남긴다(오디션 파일에는 탈락자 전사도 함께 들어 있다)
                if keep is not None and model not in keep:
                    continue
                text = row.get("text", row.get("hyp", ""))
                by_id.setdefault(row["id"], {})[model] = text
    return by_id


def load_labels(path: str) -> list[dict]:
    """판정할 학습쌍 목록을 읽는다. 두 가지 모양을 받는다.

      · v1_selection.json  {"LAR": [[id, 라벨], …], "ATQ": […]}
      · manifest jsonl     한 줄에 {"id":…, "ref":…, "task":…}
    """
    p = Path(path)
    if p.suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        return [{"id": pair_id, "label": label, "task": task}
                for task, pairs in data.items() for pair_id, label in pairs]

    rows = read_manifest(p)
    return [{"id": r["id"], "label": r.get("ref", ""), "task": r.get("task", "")}
            for r in rows]


def load_prompt_table(paths: list[str]) -> dict[str, str]:
    """낭독 과제의 **제시문 표**를 만든다 (문항 코드 → 읽어야 했던 문장).

    v1_selection.json 에는 (id, 라벨)만 있고 제시문이 없다. 그런데 파일 이름에
    문항 코드가 박혀 있고(`…-LAR004-…`), 같은 코드는 같은 문장을 읽는 것이라
    다른 목록 파일에서 제시문을 한 번 긁어 오면 전부 이어 붙일 수 있다.
    (실측: 코드 30종으로 v1 낭독 6,500건 전부가 제시문을 얻는다)
    """
    table: dict[str, str] = {}
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        for row in read_manifest(p):
            if row.get("task") != "LAR" or not row.get("prompt"):
                continue
            code = item_code(row["id"])
            if code:
                table.setdefault(code, row["prompt"])
    return table


def item_code(pair_id: str) -> str:
    """파일 이름에서 문항 코드를 꺼낸다. `00067-F-91-VI-A-LAR010-0004411` → `LAR010`."""
    for part in str(pair_id).split("-"):
        if part.startswith(("LAR", "ATQ")):
            return part
    return ""


def default_prompt_sources() -> list[str]:
    """제시문을 긁어 올 기본 목록 파일들 (`data/manifests/*.jsonl`)."""
    manifest_dir = DATA_ROOT / "manifests"
    if not manifest_dir.exists():
        return []
    return [str(p) for p in sorted(manifest_dir.glob("*.jsonl"))]


# ── (a) 판정 모드 ────────────────────────────────────────────────────────────
def run_detect(pairs: list[dict], transcripts: dict[str, dict[str, str]],
               prompts: dict[str, str], scorer, args) -> list[PairVerdict]:
    """학습쌍 전체를 훑어 판정한다. 진행 상황을 중간중간 알려 준다."""
    verdicts: list[PairVerdict] = []
    missing = 0

    for i, pair in enumerate(pairs, 1):
        heard = transcripts.get(pair["id"])
        if not heard:
            # 받아쓰기가 없는 쌍은 판정할 수 없다. 버리지 않고 '보류'로 남긴다
            missing += 1
            verdicts.append(PairVerdict(pair["id"], "hold", "증인 받아쓰기가 없다"))
            continue

        prompt = prompts.get(item_code(pair["id"])) if pair.get("task") != "ATQ" else None
        verdicts.append(judge_pair(pair["id"], pair["label"], heard, prompt=prompt,
                                   scorer=scorer, min_votes=args.min_votes,
                                   margin=args.kiwi_margin))
        if i % 500 == 0:
            print(f"  {i}/{len(pairs)} 판정", flush=True)

    if missing:
        print(f"  경고: 증인 받아쓰기가 없는 쌍 {missing}건 — 전부 보류로 남겼다")
    return verdicts


def summarize(verdicts: list[PairVerdict]) -> dict:
    """판정 결과를 숫자로 요약한다."""
    counts = {"suspect": 0, "hold": 0, "keep": 0}
    site_kinds = {"세탁": 0, "역방향": 0, "보류": 0, "약함": 0}
    for v in verdicts:
        counts[v.verdict] += 1
        for s in v.sites:
            site_kinds[s["자리판정"]] += 1

    total = len(verdicts) or 1
    return {
        "총쌍수": len(verdicts),
        "판정": counts,
        "비율": {k: round(v / total, 4) for k, v in counts.items()},
        "자리판정": site_kinds,
    }


# ── (b) gold 검증 모드 ───────────────────────────────────────────────────────
def load_gold(gold_path: str, orig_path: str | None) -> list[dict]:
    """정답을 아는 검증 세트를 읽는다. 돌려주는 줄마다 원본 라벨과 교정본이 함께 있다.

    두 가지 모양을 받는다.
      · gold_team399.jsonl — {"file":…, "label_orig": 원본 라벨, "gold": 사람 교정본}
        한 줄에 둘 다 있어 그대로 쓴다.
      · gold_100.jsonl     — `ref` 가 **이미 교정본**이라 원본 라벨이 없다.
        그래서 `--gold-orig` 로 원본이 든 목록(71479_all.jsonl)을 함께 받아 짝지운다.
    """
    rows = read_manifest(Path(gold_path))
    out: list[dict] = []

    if rows and "label_orig" in rows[0]:
        for r in rows:
            pair_id = r["file"][:-4] if str(r["file"]).endswith(".wav") else r["file"]
            out.append({"id": pair_id, "label_orig": r["label_orig"], "gold": r["gold"]})
        return out

    if not orig_path:
        raise SystemExit("이 gold 파일에는 원본 라벨이 없다. --gold-orig 로 원본 목록을 줘라.")

    origin = {r["id"]: r.get("ref", "") for r in read_manifest(Path(orig_path))}
    for r in rows:
        if r["id"] not in origin:
            continue
        out.append({"id": r["id"], "label_orig": origin[r["id"]], "gold": r.get("ref", "")})
    return out


#: gold 검증에서 '세탁 양성'을 무엇으로 볼지에 대한 정의. 출력에 그대로 찍는다.
GOLD_POSITIVE_DEF = (
    "세탁 양성 = 공백·문장부호를 뗀 뒤 원본 라벨(label_orig) 과 사람 교정본(gold) 이 "
    "다른 줄. 사람이 귀로 듣고 고쳐야 했다는 것은 원본 라벨이 실제 발화와 달랐다는 "
    "뜻이다. 다만 이 정의에는 '표준형으로 고쳐 적은 것(진짜 세탁)' 말고 "
    "'받아쓰다 빠뜨린 것'도 섞여 있다 — 탐지기는 앞쪽만 잡도록 만들어져 있으므로 "
    "재현율은 이 정의 기준에서 원리적으로 100% 가 될 수 없다."
)


def run_gold(gold_rows: list[dict], transcripts: dict[str, dict[str, str]],
             prompts: dict[str, str], scorer, args) -> dict:
    """gold 세트로 탐지기 성적(정밀도·재현율)을 낸다.

    탐지기가 실제로 하는 일은 "suspect 인 쌍을 학습에서 뺀다"이므로,
    **suspect 만 양성으로 세고 hold·keep 은 음성으로 센다.** 보류를 양성에 넣으면
    실제로 하지도 않는 일로 성적을 부풀리게 된다.
    """
    rows_with_audio = [r for r in gold_rows if r["id"] in transcripts]
    print(f"gold {len(gold_rows)}건 중 증인 받아쓰기가 있는 것 {len(rows_with_audio)}건")
    if len(rows_with_audio) < len(gold_rows):
        print(f"  (받아쓰기가 없는 {len(gold_rows) - len(rows_with_audio)}건은 성적에서 뺀다 "
              f"— launder_transcribe.py 로 받아쓰면 채워진다)")

    tp = fp = fn = tn = 0
    # 보조: '보류까지 함께 뺐다면' 어떤 성적이 되는지도 같이 잰다.
    # 지금은 보류를 남기기로 정했지만, 나중에 "보류도 빼자"는 선택지를 놓고
    # 이야기하려면 그때의 숫자가 있어야 하기 때문이다
    tp2 = fp2 = fn2 = tn2 = 0
    wrong: list[dict] = []
    per_row: list[dict] = []

    for r in rows_with_audio:
        # 정답: 사람이 고쳐야 했는가
        truth = norm_text(r["label_orig"]) != norm_text(r["gold"])
        prompt = prompts.get(item_code(r["id"]))
        # 탐지기는 **원본 라벨**을 보고 판정한다(교정본은 정답지라 보여 주면 안 된다)
        v = judge_pair(r["id"], r["label_orig"], transcripts[r["id"]], prompt=prompt,
                       scorer=scorer, min_votes=args.min_votes, margin=args.kiwi_margin)
        guess = v.verdict == "suspect"

        if guess and truth:
            tp += 1
        elif guess and not truth:
            fp += 1
        elif not guess and truth:
            fn += 1
        else:
            tn += 1

        wide = v.verdict in ("suspect", "hold")
        if wide and truth:
            tp2 += 1
        elif wide and not truth:
            fp2 += 1
        elif not wide and truth:
            fn2 += 1
        else:
            tn2 += 1

        per_row.append({"id": r["id"], "과제": item_code(r["id"])[:3],
                        "정답": "세탁" if truth else "정상",
                        "판정": v.verdict, "사유": v.reason})
        if guess != truth and len(wrong) < 10:
            wrong.append({
                "id": r["id"], "정답": "세탁" if truth else "정상", "판정": v.verdict,
                "원본라벨": r["label_orig"][:70], "사람교정": r["gold"][:70],
                "사유": v.reason[:90],
            })

    precision, recall, f1 = _prf(tp, fp, fn)
    p2, r2, f2 = _prf(tp2, fp2, fn2)

    return {"정의": GOLD_POSITIVE_DEF, "평가건수": len(rows_with_audio),
            "혼동행렬": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
            "정밀도": precision, "재현율": recall, "F1": f1,
            "보류까지뺐다면": {"혼동행렬": {"TP": tp2, "FP": fp2, "FN": fn2, "TN": tn2},
                               "정밀도": p2, "재현율": r2, "F1": f2},
            "과제별": by_task(per_row),
            "설정": {"min_votes": args.min_votes, "kiwi_margin": args.kiwi_margin,
                     "kiwi": scorer is not None},
            "틀린사례": wrong, "줄별": per_row}


def by_task(per_row: list[dict]) -> dict:
    """낭독(LAR)과 자유발화(ATQ)의 성적을 갈라 낸다.

    두 과제는 판정 근거가 다르다 — 낭독에는 제시문이 있고 자유발화에는 없다.
    합쳐 놓은 숫자 하나만 보면 한쪽이 통째로 안 되는 것을 못 본다
    (8/8 실측에서 실제로 낭독 쪽이 한 건도 못 맞히고 있었다).
    """
    out: dict[str, dict] = {}
    for row in per_row:
        task = row["과제"] or "기타"
        cell = out.setdefault(task, {"TP": 0, "FP": 0, "FN": 0, "TN": 0})
        truth, guess = row["정답"] == "세탁", row["판정"] == "suspect"
        cell["TP" if (guess and truth) else "FP" if guess
             else "FN" if truth else "TN"] += 1

    for task, cell in out.items():
        p, r, f = _prf(cell["TP"], cell["FP"], cell["FN"])
        cell.update({"정밀도": p, "재현율": r, "F1": f,
                     "건수": sum(cell[k] for k in ("TP", "FP", "FN", "TN"))})
    return out


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """맞힌 수를 정밀도·재현율·F1 로 바꾼다. 셀 것이 없으면 '측정불가'(NaN)."""
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    if precision != precision or recall != recall or not (precision + recall):
        return precision, recall, float("nan")
    return precision, recall, 2 * precision * recall / (precision + recall)


# ── (c) 정제 모드 ────────────────────────────────────────────────────────────
def emit_selection(source: str, verdicts: list[PairVerdict], out_path: str) -> dict:
    """세탁 의심(suspect)만 뺀 새 선별 목록을 만든다. 보류(hold)는 남긴다.

    형식은 v1_selection.json 과 똑같다. 학습 코드가 그대로 읽을 수 있어야 하기
    때문이다(파일만 바꿔 끼우면 되도록).
    """
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    drop = {v.id for v in verdicts if v.verdict == "suspect"}

    kept = {task: [[i, t] for i, t in pairs if i not in drop] for task, pairs in data.items()}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")

    before = {task: len(pairs) for task, pairs in data.items()}
    after = {task: len(pairs) for task, pairs in kept.items()}
    return {"원본": before, "정제후": after,
            "제외": {t: before[t] - after[t] for t in before},
            "제외비율": {t: round((before[t] - after[t]) / before[t], 4) if before[t] else 0
                         for t in before},
            "파일": str(out_path)}


# ── 실행 ─────────────────────────────────────────────────────────────────────
def build_scorer(args):
    """Kiwi 판정기를 준비한다. 없으면 없는 대로 알리고 계속 간다(그 자리는 보류가 된다)."""
    if args.no_kiwi:
        print("Kiwi 방향 판정을 끄고 돌린다 — 제시문·군말로만 판정한다")
        return None
    try:
        scorer = KiwiStandardness()
        print("방향 판정: 제시문 → 군말 → Kiwi 순")
        return scorer
    except Exception as exc:
        print(f"경고: Kiwi 를 못 불러왔다 ({type(exc).__name__}) — 제시문·군말로만 판정한다")
        return None


def main() -> int:
    enable_utf8_output()

    ap = argparse.ArgumentParser(description="세탁 탐지기 — 판정·검증·정제")
    ap.add_argument("--mode", choices=["detect", "gold"], default="detect")
    ap.add_argument("--witness", action="append", required=True,
                    help="증인 받아쓰기 jsonl (여러 번 지정 가능)")
    ap.add_argument("--witness-models", default=",".join(DEFAULT_WITNESSES),
                    help="표를 셀 증인 이름 (쉼표 구분). 'all' 이면 파일에 있는 전부")
    ap.add_argument("--labels", help="판정할 학습쌍 (v1_selection.json 또는 manifest jsonl)")
    ap.add_argument("--gold", help="gold 검증용 파일")
    ap.add_argument("--gold-orig", help="gold 파일에 원본 라벨이 없을 때 원본이 든 목록")
    ap.add_argument("--prompts", action="append", default=None,
                    help="낭독 제시문을 긁어 올 목록 파일 (기본: data/manifests/*.jsonl)")
    ap.add_argument("--out", help="판정 결과 jsonl 저장 위치")
    ap.add_argument("--summary", help="요약 json 저장 위치")
    ap.add_argument("--emit-selection", help="세탁 의심을 뺀 새 선별 목록 저장 위치")
    ap.add_argument("--min-votes", type=int, default=2, help="세탁으로 보려면 필요한 대안 표 수")
    ap.add_argument("--kiwi-margin", type=float, default=1.0,
                    help="Kiwi 점수 차 문턱(글자당). 작을수록 과감, 클수록 보수적")
    ap.add_argument("--no-kiwi", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 몇 건만 판정(확인용)")
    args = ap.parse_args()

    # 증인 받아쓰기 읽기 ─────────────────────────────────────────────────────
    keep = None if args.witness_models == "all" else set(
        w.strip() for w in args.witness_models.split(",") if w.strip()
    )
    transcripts = load_witness_transcripts(args.witness, keep)
    seen = sorted({m for v in transcripts.values() for m in v})
    print(f"증인 받아쓰기 {len(transcripts)}건 · 증인 {len(seen)}명: {', '.join(seen)}")
    if keep:
        absent = sorted(keep - set(seen))
        if absent:
            print(f"  경고: 채용된 증인 중 받아쓰기가 없는 사람 — {', '.join(absent)}")

    prompts = load_prompt_table(args.prompts or default_prompt_sources())
    print(f"낭독 제시문 표: 문항 {len(prompts)}종")

    scorer = build_scorer(args)

    # gold 검증 모드 ─────────────────────────────────────────────────────────
    if args.mode == "gold":
        if not args.gold:
            print("--mode gold 에는 --gold 가 필요하다")
            return 1
        gold_rows = load_gold(args.gold, args.gold_orig)
        if args.limit:
            gold_rows = gold_rows[: args.limit]
        report = run_gold(gold_rows, transcripts, prompts, scorer, args)
        print_gold_report(report)
        if args.summary:
            Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
            Path(args.summary).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
            print(f"\n저장: {args.summary}")
        return 0

    # 판정 모드 ──────────────────────────────────────────────────────────────
    if not args.labels:
        print("--mode detect 에는 --labels 가 필요하다")
        return 1

    pairs = load_labels(args.labels)
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"판정할 학습쌍 {len(pairs)}건\n")

    verdicts = run_detect(pairs, transcripts, prompts, scorer, args)
    stats = summarize(verdicts)
    print_detect_report(stats, verdicts)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with Path(args.out).open("w", encoding="utf-8") as f:
            for v in verdicts:
                f.write(json.dumps(v.to_dict(), ensure_ascii=False) + "\n")
        print(f"\n저장: {args.out}")

    if args.emit_selection:
        if Path(args.labels).suffix != ".json":
            print("--emit-selection 은 v1_selection.json 형식의 --labels 에만 쓸 수 있다")
            return 1
        info = emit_selection(args.labels, verdicts, args.emit_selection)
        print("\n=== 정제 결과 ===")
        print_table(
            ["과제", "원본", "정제후", "제외", "제외비율"],
            [[t, str(info["원본"][t]), str(info["정제후"][t]), str(info["제외"][t]),
              f"{info['제외비율'][t]:.2%}"] for t in info["원본"]],
        )
        print(f"저장: {info['파일']}")
        stats["정제"] = info

    if args.summary:
        Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary).write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        print(f"저장: {args.summary}")
    return 0


def print_detect_report(stats: dict, verdicts: list[PairVerdict]) -> None:
    """판정 요약과 실제 사례를 함께 찍는다. 숫자만 내면 맞는지 따질 수 없다."""
    print("\n=== 판정 요약 ===")
    print_table(
        ["판정", "뜻", "건수", "비율"],
        [[k, {"suspect": "세탁 의심 — 학습에서 뺀다",
              "hold": "보류 — 남긴다",
              "keep": "이상 없음 — 남긴다"}[k],
          str(stats["판정"][k]), f"{stats['비율'][k]:.2%}"]
         for k in ("suspect", "hold", "keep")],
    )
    print(f"  자리 판정: 세탁 {stats['자리판정']['세탁']} · "
          f"역방향(라벨이 오류를 살림) {stats['자리판정']['역방향']} · "
          f"보류 {stats['자리판정']['보류']} · 약함 {stats['자리판정']['약함']}")

    samples = [v for v in verdicts if v.verdict == "suspect"][:8]
    if samples:
        print("\n[세탁 의심 사례]")
        print_table(
            ["파일", "라벨 형태", "증인 형태", "표", "사유"],
            [[v.id[-20:], s["라벨형태"] or "(없음)", s["증인형태"] or "(없음)",
              f"{s['증인표']}:{s['라벨표']}", s["사유"][:40]]
             for v in samples for s in v.sites if s["자리판정"] == "세탁"][:8],
        )

    good = [v for v in verdicts
            if any(s["자리판정"] == "역방향" for s in v.sites)][:5]
    if good:
        print("\n[라벨이 오류를 살린 사례 — 이런 줄은 반드시 남긴다]")
        print_table(
            ["파일", "라벨 형태", "증인 형태", "표", "사유"],
            [[v.id[-20:], s["라벨형태"] or "(없음)", s["증인형태"] or "(없음)",
              f"{s['증인표']}:{s['라벨표']}", s["사유"][:40]]
             for v in good for s in v.sites if s["자리판정"] == "역방향"][:5],
        )


def print_gold_report(report: dict) -> None:
    """gold 검증 성적표를 찍는다. 정의와 틀린 사례를 반드시 함께 낸다."""
    m = report["혼동행렬"]
    print("\n=== gold 검증 성적 ===")
    print(f"양성 정의: {report['정의']}\n")
    print_table(
        ["", "탐지기: 세탁 의심", "탐지기: 남김"],
        [["정답: 세탁", str(m["TP"]), str(m["FN"])],
         ["정답: 정상", str(m["FP"]), str(m["TN"])]],
    )

    def pct(v):
        return "측정불가" if v != v else f"{v:.1%}"

    print(f"\n  정밀도 {pct(report['정밀도'])} "
          f"(세탁이라 한 것 중 실제로 세탁인 비율 — 좋은 라벨을 안 버리는가)")
    print(f"  재현율 {pct(report['재현율'])} "
          f"(실제 세탁 중 잡아낸 비율)")
    print(f"  F1     {pct(report['F1'])}  ·  평가 {report['평가건수']}건"
          f"  ·  설정 {report['설정']}")
    wide = report["보류까지뺐다면"]
    print(f"  (참고) 보류까지 함께 뺐다면 — 정밀도 {pct(wide['정밀도'])} · "
          f"재현율 {pct(wide['재현율'])}. 지금은 보류를 **남기는** 쪽을 쓴다")

    print("\n[과제별] 낭독은 제시문이 있고 자유발화는 없다 — 근거가 달라 따로 본다")
    print_table(
        ["과제", "건수", "TP", "FP", "FN", "TN", "정밀도", "재현율"],
        [[task, str(c["건수"]), str(c["TP"]), str(c["FP"]), str(c["FN"]), str(c["TN"]),
          pct(c["정밀도"]), pct(c["재현율"])]
         for task, c in sorted(report["과제별"].items())],
    )

    if report["틀린사례"]:
        print("\n[틀린 사례 — 사람 눈으로 볼 것]")
        print_table(
            ["파일", "정답", "판정", "원본 라벨", "사람 교정", "사유"],
            [[w["id"][-18:], w["정답"], w["판정"], w["원본라벨"][:28],
              w["사람교정"][:28], w["사유"][:40]] for w in report["틀린사례"]],
        )


if __name__ == "__main__":
    raise SystemExit(main())
