"""체크리스트 실험실(scripts/checklist_lab)의 계산 규칙 회귀 테스트.

이 실험은 "내용 및 과제 수행을 어떻게 채점할 것인가"를 정하는 근거가 된다.
그런데 채점·통계 코드는 눈으로 훑어서는 맞는지 알 수 없다. 한 칸만 어긋나도
"체크리스트가 더 낫다" 같은 결론이 통째로 뒤집힌다. 그래서 답을 아는 예시를 넣어
규칙 하나하나를 못 박아 둔다.

여기서 확인하는 것 여섯:
  ① QWK        — 완전 일치 1.0 / 무작위 0 근처 / 널리 쓰이는 구현과 같은 값
  ② 겹 나누기  — 같은 화자가 배우는 쪽과 시험 보는 쪽에 동시에 들어가지 않는가
  ③ 앵커 뽑기  — 점수대가 퍼지는가, 시험 볼 답안이 섞이지 않는가(누출)
  ④ 점수 변환  — 충족율 × 5 반올림 규칙(0.5 는 위로)
  ⑤ C 계산     — B 의 0/1 만으로 0~5 를 내는가, 범위를 벗어나지 않는가
  ⑥ 이어서 하기 — 실패로 적힌 줄을 나중 성공 줄이 덮어쓰는가

**네트워크를 쓰지 않는다.** LLM 자리에는 답을 정해 둔 가짜 응답을 넣는다.

실행: .venv\\Scripts\\python.exe -m pytest tests/test_checklist_lab.py -q
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest


# 이 실험 테스트는 scripts/checklist_lab 의 학습 코드(sklearn/xgboost)를 임포트한다.
# 운영 requirements 에는 그 라이브러리가 없으므로, 없으면 이 파일 전체를 건너뛴다.
pytest.importorskip("sklearn", reason="checklist_lab 실험 전용 자질/학습 라이브러리 — 운영 CI에는 미설치, 여기서 통째로 건너뛴다")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "checklist_lab"))

from _lab_common import (  # noqa: E402
    SCORE_LABELS,
    CallThrottle,
    all_metrics,
    append_record,
    assign_folds,
    bootstrap_qwk_ci,
    check_folds,
    classify_429,
    group_by_prompt,
    load_done,
    prompt_key,
    qwk,
    select_repro_subset,
    verdict,
)
from analyze import clean_nan, compute_method_c, round_half_up  # noqa: E402
from gen_checklists import build_generation_prompt, normalize_items  # noqa: E402
from run_experiment import (  # noqa: E402
    RUBRIC,
    build_judge_prompt,
    format_anchors,
    met_ratio_to_score,
    parse_direct_score,
    pick_anchors,
)


# ── 가짜 데이터 만들기 ───────────────────────────────────────────────────────
def make_row(rid: str, prompt: str, speaker: str, score: int, ref: str = "예시 답안입니다."):
    """목록 파일 한 줄과 같은 모양의 가짜 답안을 만든다."""
    return {
        "id": rid,
        "ref": ref,
        "prompt": prompt,
        "task": "ATQ",
        "speaker_id": speaker,
        "nationality": "Testland",
        "topik_level": "2",
        "evals": {"content": score, "language_use": 3, "delivery": 3},
    }


def make_dataset(n_prompts: int = 3, n_per_prompt: int = 30):
    """문항 여러 개 × 답안 여러 개짜리 가짜 표본. 점수는 0~5 를 골고루 돌려 준다."""
    rows = []
    for p in range(n_prompts):
        prompt = f"가짜 문항 {p} 지시문입니다. 자세히 말해 주세요."
        for i in range(n_per_prompt):
            rows.append(make_row(
                rid=f"{p:02d}{i:03d}-F-99-KR-B-ATQ{p:03d}-{i:07d}",
                prompt=prompt,
                speaker=f"{p:02d}{i:03d}",
                score=i % 6,
                ref=f"{p}번 문항에 대한 {i}번 답안입니다. 이유는 편리하기 때문입니다.",
            ))
    return rows


# ── ① QWK ────────────────────────────────────────────────────────────────────
def test_qwk_완전일치는_1이다():
    truth = [0, 1, 2, 3, 4, 5, 3, 2, 4]
    assert qwk(truth, truth) == pytest.approx(1.0)


def test_qwk_무작위_예측은_0_근처다():
    rng = random.Random(7)
    truth = [rng.randint(0, 5) for _ in range(4000)]
    pred = [rng.randint(0, 5) for _ in range(4000)]
    assert abs(qwk(pred, truth)) < 0.06


def test_qwk_많이_빗나갈수록_더_깎인다():
    truth = [0, 1, 2, 3, 4, 5] * 6
    near = [min(5, t + 1) for t in truth]
    far = [min(5, t + 3) for t in truth]
    assert qwk(near, truth) > qwk(far, truth)


def test_qwk_널리_쓰이는_구현과_같은_값을_낸다():
    """우리가 직접 구현한 QWK 가 scikit-learn 과 같은 값을 내는지 대조한다."""
    from sklearn.metrics import cohen_kappa_score

    truth = [0, 1, 2, 3, 4, 5, 3, 2, 3, 4, 2, 3, 1, 5, 0]
    pred = [1, 1, 2, 4, 4, 5, 2, 2, 3, 3, 3, 4, 0, 4, 2]
    assert qwk(pred, truth) == pytest.approx(
        cohen_kappa_score(pred, truth, weights="quadratic", labels=list(SCORE_LABELS))
    )


def test_qwk_정반대로_매기면_음수다():
    truth = [0, 1, 2, 3, 4, 5] * 4
    assert qwk([5 - t for t in truth], truth) < 0


def test_qwk_한쪽이_전부_같은_값이면_나눌_수_없어_0이_된다():
    """모든 답안에 3점만 준 채점자는 '우연 벌점'이 0이라 나눌 수 없다. 0으로 본다."""
    truth = [0, 1, 2, 3, 4, 5]
    assert qwk([3] * 6, truth) == 0.0


def test_all_metrics_참고지표까지_함께_낸다():
    truth = [0, 1, 2, 3]
    pred = [0, 1, 3, 3]          # 한 건만 1점 차
    m = all_metrics(pred, truth)
    assert m["n"] == 4
    assert m["exact"] == pytest.approx(0.75)
    assert m["within1"] == pytest.approx(1.0)


# ── ② 겹 나누기 ──────────────────────────────────────────────────────────────
def test_겹나누기는_같은_화자를_학습과_평가에_동시에_넣지_않는다():
    rows = make_dataset()
    fold_of, diag = assign_folds(rows, n_folds=5)
    assert diag["speaker_leak_count"] == 0
    assert diag["usable"] is True


def test_겹나누기는_한_화자가_여러_문항에_답해도_한_겹에_머문다():
    """같은 사람이 두 문항에 답한 경우(실데이터에 11명 있다) 겹이 갈리면 안 된다."""
    rows = [
        make_row("A1", "문항 하나입니다.", "S001", 3),
        make_row("A2", "문항 둘입니다.", "S001", 4),   # 같은 화자, 다른 문항
        *[make_row(f"B{i}", "문항 하나입니다.", f"T{i:03d}", i % 6) for i in range(20)],
        *[make_row(f"C{i}", "문항 둘입니다.", f"U{i:03d}", i % 6) for i in range(20)],
    ]
    fold_of, diag = assign_folds(rows, n_folds=5)
    assert fold_of["A1"] == fold_of["A2"]
    assert diag["speaker_leak_count"] == 0


def test_겹나누기는_문항마다_모든_겹에_시험볼_답안을_남긴다():
    """문항별 학습(C)과 앵커 뽑기(A1)가 성립하려면 빈 칸이 없어야 한다."""
    rows = make_dataset(n_prompts=4, n_per_prompt=27)
    fold_of, diag = assign_folds(rows, n_folds=5)
    assert diag["prompts_with_empty_fold"] == []
    assert diag["min_train_rows_in_any_prompt_fold"] >= 15


def test_겹나누기는_무작위를_쓰지_않아_두_번_돌려도_같다():
    rows = make_dataset()
    assert assign_folds(rows, 5)[0] == assign_folds(rows, 5)[0]


def test_겹_점검기는_빈_칸을_찾아낸다():
    """일부러 한 문항을 한 겹에 몰아 놓고, 점검기가 '못 쓴다'고 하는지 본다."""
    rows = make_dataset(n_prompts=1, n_per_prompt=10)
    broken = {str(r["id"]): 0 for r in rows}      # 전부 0번 겹에만 넣는다
    diag = check_folds(rows, broken, n_folds=5)
    assert diag["usable"] is False
    assert len(diag["prompts_with_empty_fold"]) == 4    # 1~4번 겹이 비어 있다


# ── 부분표본 고르기 ──────────────────────────────────────────────────────────
def test_재현성_부분표본은_문항이_고루_섞이고_두_번_돌려도_같다():
    rows = make_dataset(n_prompts=3, n_per_prompt=30)
    first = select_repro_subset(rows, 30)
    second = select_repro_subset(rows, 30)
    assert [r["id"] for r in first] == [r["id"] for r in second]
    assert len(first) == 30
    # 세 문항에서 고르게 나뉘어야 한다(한 문항에 몰리면 안 된다)
    counts = {}
    for r in first:
        counts[prompt_key(r["prompt"])] = counts.get(prompt_key(r["prompt"]), 0) + 1
    assert max(counts.values()) - min(counts.values()) <= 1


# ── ③ 앵커 뽑기 (A1) ─────────────────────────────────────────────────────────
def test_앵커는_점수대가_퍼지게_4에서_6개를_고른다():
    train = [make_row(f"T{i}", "문항", f"S{i}", i % 6) for i in range(30)]
    anchors = pick_anchors(train)
    assert 4 <= len(anchors) <= 6
    scores = [a["evals"]["content"] for a in anchors]
    # 같은 점수만 뽑히면 안 된다 — 점수 종류가 최소 4가지는 나와야 한다
    assert len(set(scores)) >= 4
    assert scores == sorted(scores)


def test_앵커는_점수_종류가_적어도_최소_개수를_채운다():
    """학습 겹에 점수가 두 종류뿐인 문항에서도 예시가 너무 적으면 안 된다."""
    train = [make_row(f"T{i}", "문항", f"S{i}", 2 if i % 2 else 3) for i in range(10)]
    anchors = pick_anchors(train)
    assert len(anchors) >= 4


def test_앵커는_시험_겹_답안을_절대_포함하지_않는다():
    """누출 방지의 핵심. 앵커는 학습 겹에서만 나와야 한다."""
    rows = make_dataset(n_prompts=1, n_per_prompt=30)
    fold_of, _ = assign_folds(rows, 5)
    buckets = group_by_prompt(rows)
    pkey = next(iter(buckets))
    for fold in range(5):
        train = [r for r in buckets[pkey] if fold_of[str(r["id"])] != fold]
        anchors = pick_anchors(train)
        assert all(fold_of[str(a["id"])] != fold for a in anchors)


def test_앵커_뽑기는_두_번_돌려도_같은_것을_고른다():
    train = [make_row(f"T{i}", "문항", f"S{i}", i % 6) for i in range(30)]
    assert [a["id"] for a in pick_anchors(train)] == [a["id"] for a in pick_anchors(train)]


# ── A0·A1 프롬프트 ───────────────────────────────────────────────────────────
def test_A0와_A1은_채점기준이_글자까지_같고_앵커만_다르다():
    """두 방식의 차이가 '예시가 붙었느냐'뿐이어야 비교가 성립한다."""
    a0 = build_judge_prompt("답안입니다.", "문항 지시문", [])
    a1 = build_judge_prompt("답안입니다.", "문항 지시문",
                            [make_row("T1", "문항 지시문", "S1", 4)])
    assert RUBRIC in a0 and RUBRIC in a1
    assert "채점 예시" not in a0        # A0 에는 예시가 없다
    assert "채점 예시" in a1
    # 앵커 부분만 빼면 두 프롬프트는 같아야 한다
    assert a0.replace("\n\n", "\n") == a1.replace(format_anchors(
        [make_row("T1", "문항 지시문", "S1", 4)]), "\n").replace("\n\n", "\n")


def test_앵커_글에는_예시의_사람_점수가_들어간다():
    text = format_anchors([make_row("T1", "문항", "S1", 5, ref="아주 잘 쓴 답안입니다.")])
    assert "5점" in text and "아주 잘 쓴 답안입니다." in text


# ── ④ 점수 변환 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ratio,expected", [
    (0.0, 0), (0.1, 1), (0.2, 1), (0.3, 2), (0.5, 3),
    (0.6, 3), (0.75, 4), (0.9, 5), (1.0, 5),
])
def test_충족율은_5를_곱해_반올림한다(ratio, expected):
    assert met_ratio_to_score(ratio) == expected


def test_반올림은_0점5를_위로_올린다():
    """파이썬 기본 round 는 2.5 를 2로 내린다. 사람이 기대하는 것과 다르므로 못 박는다."""
    assert [round_half_up(v) for v in (-0.4, 0.5, 2.4, 2.5, 3.5, 5.6)] == [0, 1, 2, 3, 4, 5]


# ── A0·A1 응답 해석 + 인용 검증 ──────────────────────────────────────────────
def test_인용이_원문에_있으면_확인됨으로_기록된다():
    answer = "저는 보통 집 근처 마트에서 쇼핑해요. 가깝고 값이 싸기 때문이에요."
    out = parse_direct_score(
        {"score": 4, "quote": "집 근처 마트에서 쇼핑해요", "reason": "장소와 이유를 말했다"},
        answer)
    assert out["status"] == "ok"
    assert out["pred"] == 4
    assert out["citation_ok"] is True


def test_지어낸_인용은_점수를_그대로_두되_근거없음으로_표시된다():
    """A0·A1 은 점수를 LLM 이 정하는 방식이라 점수를 내리지 않는다.
    대신 '근거를 못 댄 점수'가 몇 건인지 셀 수 있게 표시만 남긴다."""
    answer = "저는 보통 집 근처 마트에서 쇼핑해요."
    out = parse_direct_score(
        {"score": 5, "quote": "백화점에서 옷을 샀습니다", "reason": "지어낸 근거"}, answer)
    assert out["pred"] == 5              # 점수는 그대로
    assert out["citation_ok"] is False   # 근거는 가짜라고 표시
    assert "폐기" in out["citation_reason"] or out["citation_reason"]


def test_범위를_벗어난_점수는_0에서_5로_눌리고_그_사실이_남는다():
    out = parse_direct_score({"score": 9, "quote": "", "reason": ""}, "답안")
    assert out["pred"] == 5 and out["clipped"] is True


def test_숫자가_아닌_점수는_실패로_처리한다():
    out = parse_direct_score({"score": "아주 좋음", "quote": "", "reason": ""}, "답안")
    assert out["status"] == "bad_score"


# ── 체크리스트 생성 응답 다듬기 ──────────────────────────────────────────────
def test_생성_프롬프트는_팀원_원문에_지시문만_끼워_넣는다():
    text = build_generation_prompt("보통 어디에서 쇼핑하세요?")
    assert "보통 어디에서 쇼핑하세요?" in text
    assert "{prompt_text}" not in text
    # 원문의 규칙 문장이 그대로 살아 있어야 한다
    assert "개수를 채우지 마십시오. 최대 5개이되" in text
    assert '"정보전달"' in text


def test_체크리스트_다듬기는_빈_질문을_버리고_5개로_자른다():
    payload = {"checklist": [
        {"id": 1, "question": "장소를 말했는가", "category": "정보전달", "required": True},
        {"id": 2, "question": "   ", "category": "정보전달", "required": False},
        *[{"id": i, "question": f"항목 {i}", "category": "행위수행", "required": False}
          for i in range(3, 9)],
    ]}
    items, warnings = normalize_items(payload)
    assert len(items) == 5
    assert all(it["question"].strip() for it in items)
    assert any("비어" in w for w in warnings)
    assert any("상한" in w for w in warnings)


def test_체크리스트_다듬기는_정해진_갈래가_아닌_category를_경고로_남긴다():
    items, warnings = normalize_items({"checklist": [
        {"id": 1, "question": "장소를 말했는가", "category": "발음정확성", "required": True}]})
    assert len(items) == 1
    assert any("category" in w for w in warnings)


# ── ⑤ C 계산 (B 의 0/1 을 재료로) ────────────────────────────────────────────
def _fake_b_records(rows, fold_of, rule):
    """B 판정 결과를 가짜로 만든다. `rule(row)` 이 항목별 0/1 목록을 돌려준다."""
    records = {}
    for row in rows:
        rid = str(row["id"])
        mets = rule(row)
        records[rid] = {
            "id": rid,
            "method": "B",
            "pass": "main",
            "status": "ok",
            "prompt_key": prompt_key(row["prompt"]),
            "fold": fold_of[rid],
            "items": [{"cid": str(i + 1), "met": m} for i, m in enumerate(mets)],
            "pred": met_ratio_to_score(sum(mets) / len(mets)),
        }
    return records


def _fake_checklists(rows, n_items=3):
    out = {}
    for pkey, items in group_by_prompt(rows).items():
        out[pkey] = {
            "prompt_key": pkey,
            "prompt": items[0]["prompt"],
            "status": "ok",
            "items": [{"id": str(i + 1), "question": f"항목 {i + 1}",
                       "category": "정보전달", "required": i == 0}
                      for i in range(n_items)],
        }
    return out


def test_C는_LLM을_부르지_않고_B의_0과1만으로_0에서5를_낸다():
    rows = make_dataset(n_prompts=2, n_per_prompt=30)
    fold_of, _ = assign_folds(rows, 5)
    checklists = _fake_checklists(rows)
    rows_by_id = {str(r["id"]): r for r in rows}

    # 사람 점수와 관계있는 0/1 을 만들어 준다(점수가 높을수록 충족 항목이 많다)
    def rule(row):
        score = row["evals"]["content"]
        return [1 if score >= t else 0 for t in (1, 3, 5)]

    records_b = _fake_b_records(rows, fold_of, rule)
    preds, learned = compute_method_c(records_b, rows_by_id, fold_of, checklists)

    assert len(preds) == len(rows)
    assert all(0 <= v <= 5 for v in preds.values())
    assert all(isinstance(v, int) for v in preds.values())
    # 문항마다 항목별 비중을 배운 기록이 남아야 한다(근거 없는 점수는 결함이다)
    assert set(learned) == set(checklists)
    for entry in learned.values():
        assert entry["folds"]
        assert any(f.get("coefficients") for f in entry["folds"])


def test_C는_항목이_점수를_잘_설명하면_B보다_사람점수에_가까워진다():
    """'첫 항목만 중요한 문항'을 만들어, 가중치 학습이 그것을 잡아내는지 본다."""
    rows = make_dataset(n_prompts=1, n_per_prompt=40)
    fold_of, _ = assign_folds(rows, 5)
    checklists = _fake_checklists(rows, n_items=3)
    rows_by_id = {str(r["id"]): r for r in rows}

    # 사람 점수는 1번 항목에만 달려 있고, 2·3번은 아무 정보가 없는 잡음이다
    def rule(row):
        score = row["evals"]["content"]
        noise = int(str(row["id"])[-1]) % 2
        return [1 if score >= 3 else 0, noise, 1 - noise]

    records_b = _fake_b_records(rows, fold_of, rule)
    c_preds, _ = compute_method_c(records_b, rows_by_id, fold_of, checklists)

    ids = sorted(c_preds)
    truth = [rows_by_id[i]["evals"]["content"] for i in ids]
    b_pred = [records_b[i]["pred"] for i in ids]
    c_pred = [c_preds[i] for i in ids]
    # 충족율은 잡음 항목까지 똑같이 세므로 흐려진다. 학습은 잡음의 비중을 줄일 수 있다
    assert qwk(c_pred, truth) > qwk(b_pred, truth)


def test_C는_B가_실패한_답안에는_점수를_내지_않는다():
    """B 판정이 없으면 C 도 없다. 공통 표본 규칙이 여기서부터 지켜진다."""
    rows = make_dataset(n_prompts=1, n_per_prompt=30)
    fold_of, _ = assign_folds(rows, 5)
    checklists = _fake_checklists(rows)
    rows_by_id = {str(r["id"]): r for r in rows}
    records_b = _fake_b_records(rows, fold_of, lambda r: [1, 0, 1])
    missing = sorted(records_b)[0]
    records_b[missing]["status"] = "llm_failed"

    preds, _ = compute_method_c(records_b, rows_by_id, fold_of, checklists)
    assert missing not in preds


# ── 부트스트랩 신뢰구간 ──────────────────────────────────────────────────────
def test_같은_예측끼리는_차이_구간이_0을_걸쳐_개선이라고_말할_수_없다():
    truth = [i % 6 for i in range(60)]
    same = list(truth)
    speakers = [f"S{i:03d}" for i in range(60)]
    _, diffs = bootstrap_qwk_ci({"갑": same, "을": list(same)}, truth, speakers,
                                n_boot=200, seed=1)
    d = diffs["갑-을"]
    assert d["lo"] <= 0 <= d["hi"]
    assert "주장할 수 없다" in verdict(d)


def test_확실히_나은_예측은_차이_구간이_0_위에_놓인다():
    truth = [i % 6 for i in range(120)]
    good = list(truth)
    bad = [(t + 3) % 6 for t in truth]
    speakers = [f"S{i:03d}" for i in range(120)]
    _, diffs = bootstrap_qwk_ci({"good": good, "bad": bad}, truth, speakers,
                                n_boot=200, seed=1)
    assert diffs["good-bad"]["lo"] > 0
    assert verdict(diffs["good-bad"]) == "앞쪽이 유의하게 높다"


# ── ⑥ 이어서 하기 ────────────────────────────────────────────────────────────
def test_같은_열쇠가_두_번_적히면_나중_줄이_이긴다(tmp_path):
    """실패로 적힌 줄을 나중 성공이 덮어써야 재실행이 뜻을 가진다."""
    path = tmp_path / "judgments.jsonl"
    append_record(path, {"id": "X1", "method": "A0", "pass": "main",
                         "status": "llm_failed", "reason": "504"})
    append_record(path, {"id": "X1", "method": "A0", "pass": "main",
                         "status": "ok", "pred": 3})
    done = load_done(path)
    assert done[("X1", "A0", "main")]["status"] == "ok"
    assert done[("X1", "A0", "main")]["pred"] == 3


def test_실행_이름표가_다르면_다른_줄로_센다(tmp_path):
    """재현성 회차(rep1·rep2·rep3)가 본실행을 덮어쓰면 안 된다."""
    path = tmp_path / "judgments.jsonl"
    for tag, pred in (("main", 3), ("rep1", 4), ("rep2", 3)):
        append_record(path, {"id": "X1", "method": "A0", "pass": tag,
                             "status": "ok", "pred": pred})
    done = load_done(path)
    assert len(done) == 3
    assert done[("X1", "A0", "rep1")]["pred"] == 4


def test_중간에_끊겨_잘린_줄이_있어도_나머지는_읽는다(tmp_path):
    path = tmp_path / "judgments.jsonl"
    append_record(path, {"id": "X1", "method": "B", "pass": "main", "status": "ok"})
    with path.open("a", encoding="utf-8") as f:
        f.write('{"id": "X2", "method": "B", "pa')     # 실행 중 끊긴 흔적
    assert len(load_done(path)) == 1


# ── 결과 파일이 표준 JSON 으로 읽히는가 ──────────────────────────────────────
def test_못_잰_값은_0이_아니라_null로_적는다():
    """0 은 '재 봤더니 0'이라는 뜻이라 '못 쟀다'와 전혀 다른 말이다.
    그리고 NaN 을 그대로 적으면 표준 JSON 이 아니어서 다른 도구가 파일을 못 읽는다."""
    cleaned = clean_nan({"qwk": float("nan"), "n": 0,
                         "ci": [float("inf"), 0.3], "이름": "A0"})
    assert cleaned["qwk"] is None
    assert cleaned["ci"][0] is None and cleaned["ci"][1] == 0.3
    # 표준 JSON 으로 적히는지 실제로 확인한다
    text = json.dumps(cleaned, ensure_ascii=False, allow_nan=False)
    assert json.loads(text)["qwk"] is None


# ── 429 갈래 가리기 (기다리면 풀리는가, 오늘 끝인가) ─────────────────────────
def test_분당_한도_429는_기다리면_풀리는_것으로_본다():
    """무료 등급의 실제 벽은 '분당 15회'다. 이것을 '오늘 끝'으로 오해하면
    멀쩡히 더 돌릴 수 있는 실험을 스스로 접게 된다."""
    detail = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
              "'You exceeded your current quota... Please retry in 22.985286332s.', "
              "'details': [{'quotaId': "
              "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}], "
              "'retryDelay': '22s'}}")
    kind, wait = classify_429("LLM 하루 호출 한도를 다 썼다(429).", detail)
    assert kind == "rate"
    assert 20 <= wait <= 30      # 서버가 알려 준 시간을 그대로 따른다


def test_잔액_소진_429는_기다려도_안_풀리는_것으로_본다():
    detail = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
              "'Your prepayment credits are depleted.'}}")
    kind, wait = classify_429("LLM 하루 호출 한도를 다 썼다(429).", detail)
    assert kind == "hard" and wait == 0.0


def test_429가_아닌_실패는_한도_문제로_보지_않는다():
    assert classify_429("LLM 응답이 제한 시간 안에 오지 않았다.", "DEADLINE_EXCEEDED") == ("", 0.0)


def test_조절기는_분당_한도를_넘겨_부르지_않는다():
    """분당 3회로 잡아 두고 4번째 호출이 실제로 붙들리는지 시간으로 확인한다."""
    import time

    throttle = CallThrottle(workers=3, rpm=3)
    started = time.monotonic()
    for _ in range(3):
        with throttle.slot():
            pass
    # 여기까지는 예산 안이라 거의 즉시 끝나야 한다
    assert time.monotonic() - started < 1.0
    # 4번째는 1분 구간이 지나야 하므로, 잠깐이라도 붙들려야 한다.
    # (테스트를 60초씩 세우지 않으려고 붙들리기 시작하는지만 확인한다)
    throttle._recent = [time.monotonic() - 59.5] * 3     # 0.5초 뒤 풀리도록 꾸민다
    blocked_at = time.monotonic()
    with throttle.slot():
        pass
    assert time.monotonic() - blocked_at >= 0.4


# ── 실데이터가 있을 때만 도는 확인 ───────────────────────────────────────────
DATA_DIR = Path(r"C:\해커톤\data\manifests")


@pytest.mark.skipif(not DATA_DIR.exists(), reason="AI Hub 목록 파일이 없는 환경")
def test_실데이터_겹나누기가_실제로_성립한다():
    """실험 대상 실데이터에서 화자 단위 5겹이 문항 안에서도 성립하는지 확인한다.

    여기가 깨지면 LOO(하나 빼기)로 바꿔야 하므로, 조용히 지나가면 안 된다.
    """
    from _lab_common import load_rows

    rows, counts = load_rows()
    assert counts["대상 문항 수"] >= 5
    _, diag = assign_folds(rows, 5)
    assert diag["speaker_leak_count"] == 0
    assert diag["prompts_with_empty_fold"] == []
