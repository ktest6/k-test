"""체크리스트 v2 실험(scripts/checklist_lab/*_v2.py)의 계산 규칙 회귀 테스트.

v2 는 논문(RLCF, arXiv 2507.18624v2)의 후보 기반 체크리스트 생성을 이식한 것이고,
v1 과 달라진 부분이 여럿이다 — 중요도 가중, 보편 항목, 0~100 점 판정.
숫자 하나만 어긋나도 "논문 방식이 더 낫다/아니다"가 통째로 뒤집히므로,
답을 아는 예시를 넣어 규칙을 못 박아 둔다.

여기서 확인하는 것 일곱:
  ① 체크리스트 v2 다듬기 — 중요도 범위, 항목 수 상한, 보편 항목 붙이기
  ② 생성 프롬프트    — 팀원 원 규칙(발음·문법 금지, 억지 금지)이 살아 있는가
  ③ 점수 패스 판정   — 0~100 해석, **근거 인용이 가짜면 0점으로 내리는가**
  ④ 중요도 가중      — 중요한 항목을 맞힌 쪽이 더 높은 점수를 받는가
  ⑤ 보편 항목 빼기   — ablation 이 표시(universal)만 보고 정확히 가르는가
  ⑥ F·H 학습        — LLM 없이 항목 벡터만으로 0~5 를 내는가, 겹을 넘지 않는가
  ⑦ 천장            — '정답을 보고 맞춘 상한'이 실제 방식보다 낮아지지 않는가

**네트워크를 쓰지 않는다.** LLM 자리에는 답을 정해 둔 가짜 응답을 넣는다.

실행: .venv\\Scripts\\python.exe -m pytest tests/test_checklist_lab_v2.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# 이 실험 테스트는 scripts/checklist_lab 의 학습 코드(sklearn/xgboost)를 임포트한다.
# 운영 requirements 에는 그 라이브러리가 없으므로, 없으면 이 파일 전체를 건너뛴다.
pytest.importorskip("sklearn", reason="checklist_lab 실험 전용 자질/학습 라이브러리 — 운영 CI에는 미설치, 여기서 통째로 건너뛴다")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "checklist_lab"))

from _lab_common import assign_folds, prompt_key, qwk  # noqa: E402
from analyze_v2 import (  # noqa: E402
    binary_vector,
    ceiling_by_linear_fit,
    ceiling_by_met_count,
    ceiling_by_met_count_optimized,
    included_items,
    learn_per_prompt,
    score_vector,
    weighted_ratio,
)
from gen_checklists_v2 import (  # noqa: E402
    MAX_TASK_ITEMS,
    UNIVERSAL_ITEMS,
    attach_universal,
    build_candidate_prompt,
    build_checklist_prompt,
    normalize_candidates,
    normalize_items_v2,
)
from run_experiment_v2 import (  # noqa: E402
    build_score_prompt,
    ratio_to_score,
    score_results_from_payload,
    weighted_mean_0to100,
)


# ── 가짜 데이터 만들기 ───────────────────────────────────────────────────────
def make_row(rid: str, prompt: str, speaker: str, score: int, ref: str = "예시 답안입니다."):
    """목록 파일 한 줄과 같은 모양의 가짜 답안."""
    return {"id": rid, "ref": ref, "prompt": prompt, "task": "ATQ",
            "speaker_id": speaker, "evals": {"content": score}}


def make_items(n: int = 3, importances=None) -> list[dict]:
    """과제 항목 n 개 + 보편 항목 2개짜리 가짜 체크리스트."""
    imps = importances or [100 - i * 20 for i in range(n)]
    task = [{"id": str(i + 1), "question": f"항목 {i + 1}", "category": "정보전달",
             "required": i == 0, "importance": imps[i], "universal": False}
            for i in range(n)]
    return attach_universal(task)


# ── ① 체크리스트 v2 다듬기 ───────────────────────────────────────────────────
def test_중요도가_없거나_이상하면_50으로_두고_경고를_남긴다():
    items, warnings, _ = normalize_items_v2({"failure_modes": [], "checklist": [
        {"id": 1, "question": "가", "category": "정보전달", "required": True,
         "importance": "아주 중요"},
        {"id": 2, "question": "나", "category": "정보전달", "required": False,
         "importance": 250},
    ]})
    assert items[0]["importance"] == 50
    assert items[1]["importance"] == 100          # 100 위로는 눌린다
    assert any("숫자로 읽지 못해" in w for w in warnings)
    assert any("0~100 밖" in w for w in warnings)


def test_항목이_상한을_넘으면_중요도가_높은_것부터_남긴다():
    """v1 은 앞에서부터 잘랐다. 중요도가 생긴 이상 앞뒤 순서보다 경중이 낫다."""
    payload = {"failure_modes": [], "checklist": [
        {"id": i, "question": f"항목 {i}", "category": "정보전달",
         "required": False, "importance": i}
        for i in range(1, MAX_TASK_ITEMS + 4)     # 상한보다 3개 많게
    ]}
    items, warnings, _ = normalize_items_v2(payload)
    assert len(items) == MAX_TASK_ITEMS
    assert min(it["importance"] for it in items) > 3      # 낮은 것부터 떨어진다
    assert any("상한" in w for w in warnings)


def test_중요도가_전부_0이면_나눌_수_없어_50으로_되돌린다():
    items, warnings, _ = normalize_items_v2({"failure_modes": [], "checklist": [
        {"id": 1, "question": "가", "category": "정보전달", "required": True, "importance": 0},
        {"id": 2, "question": "나", "category": "정보전달", "required": False, "importance": 0},
    ]})
    assert [it["importance"] for it in items] == [50, 50]
    assert any("전부 0" in w for w in warnings)


def test_보편_항목과_id가_부딪히면_이름을_바꾼다():
    """판정 결과를 항목에 짝지을 열쇠라서, 겹치면 결과가 섞인다."""
    items, warnings, _ = normalize_items_v2({"failure_modes": [], "checklist": [
        {"id": "U1", "question": "가", "category": "정보전달",
         "required": True, "importance": 80},
    ]})
    assert items[0]["id"] != "U1"
    assert any("같은 id" in w for w in warnings)


def test_보편_항목_2개가_붙고_중요도_합이_100이다():
    """논문 3.1 의 universal criteria. 둘의 중요도 합은 100 이어야 한다."""
    items = attach_universal([{"id": "1", "question": "가", "category": "정보전달",
                               "required": True, "importance": 90, "universal": False}])
    universal = [it for it in items if it.get("universal")]
    assert len(universal) == len(UNIVERSAL_ITEMS) == 2
    assert sum(it["importance"] for it in universal) == 100
    # 표시가 있어야 분석에서 빼고 다시 계산할 수 있다(ablation)
    assert all("universal" in it for it in items)


def test_빈_질문과_형식이_깨진_항목은_버린다():
    items, warnings, modes = normalize_items_v2({
        "failure_modes": ["장소를 말하지 않음", "  "],
        "checklist": [
            {"id": 1, "question": "  ", "category": "정보전달",
             "required": True, "importance": 90},
            "이건 항목이 아니다",
            {"id": 2, "question": "나", "category": "정보전달",
             "required": True, "importance": 90},
        ]})
    assert [it["id"] for it in items] == ["2"]
    assert modes == ["장소를 말하지 않음"]        # 빈 실패 방식은 버린다
    assert any("비어" in w for w in warnings)


def test_후보_답안_다듬기는_빈_본문을_버리고_개수를_경고한다():
    candidates, warnings = normalize_candidates({"candidates": [
        {"level": "모범", "text": "잘 쓴 답안입니다."},
        {"level": "보통", "text": "   "},
    ]})
    assert len(candidates) == 1
    assert any("비어" in w for w in warnings)
    assert any("후보가 1개" in w for w in warnings)


# ── ② 생성 프롬프트 — 원 규칙이 살아 있는가 ──────────────────────────────────
def test_후보_생성_프롬프트는_품질_네_칸을_모두_요구한다():
    text = build_candidate_prompt("보통 어디에서 쇼핑하세요?")
    assert "보통 어디에서 쇼핑하세요?" in text
    assert "{prompt_text}" not in text
    for level in ("모범", "보통", "최소한", "과제 놓침"):
        assert level in text


def test_체크리스트_생성_프롬프트는_후보를_보여주고_금지_규칙을_유지한다():
    """팀원 원 프롬프트의 세 규칙(발음·문법 금지, 억지 금지, 한 항목 한 가지)은 v2 에서도 지킨다."""
    text = build_checklist_prompt("문항 지시문", [{"level": "모범", "text": "후보 답안 본문"}])
    assert "후보 답안 본문" in text
    assert "실패하는 방식" in text
    assert "발음·억양·속도에 대한 항목, 문법·어휘의 정확성에 대한 항목은 만들지 마라" in text
    assert "개수를 채우려고 억지 항목이나 자명한 항목을 만들지 마라" in text
    assert "한 가지만" in text
    assert "importance" in text
    assert str(MAX_TASK_ITEMS) in text


def test_점수_패스_프롬프트에는_항목_id와_0에서100_지시가_들어간다():
    text = build_score_prompt("답안 원문입니다.", "문항 지시문", make_items(2))
    assert "id=1" in text and "id=U1" in text
    assert "0에서 100 사이의 정수" in text
    assert "답안 원문입니다." in text


# ── ③ 점수 패스 판정 + 인용 검증 ─────────────────────────────────────────────
def test_점수_패스는_0에서100을_그대로_받고_인용_위치를_남긴다():
    answer = "저는 보통 집 근처 마트에서 쇼핑해요. 가깝고 값이 싸기 때문이에요."
    items = [{"id": "1", "question": "장소를 말했는가", "importance": 90}]
    results, warnings, dropped = score_results_from_payload(answer, items, {"results": [
        {"id": "1", "score": 80, "quote": "집 근처 마트에서 쇼핑해요", "reason": "장소를 말했다"}]})
    assert results[0]["score"] == 80
    assert results[0]["citation_ok"] is True
    assert results[0]["start"] is not None and results[0]["end"] is not None
    assert dropped == 0 and warnings == []


def test_지어낸_인용으로_받은_점수는_0으로_내려간다():
    """v1 이진 규약과 같다 — '근거는 못 대지만 70점'을 남기면 v1 에서 막은 구멍이 다시 열린다."""
    answer = "저는 보통 집 근처 마트에서 쇼핑해요."
    items = [{"id": "1", "question": "장소를 말했는가", "importance": 90}]
    results, warnings, dropped = score_results_from_payload(answer, items, {"results": [
        {"id": "1", "score": 70, "quote": "백화점에서 옷을 샀습니다", "reason": "지어낸 근거"}]})
    assert results[0]["score"] == 0
    assert results[0]["raw_score"] == 70          # 폐기 전 값은 남긴다
    assert results[0]["discarded_quote"] == "백화점에서 옷을 샀습니다"
    assert dropped == 1
    assert any("폐기" in w for w in warnings)


def test_판정하지_않은_항목은_만점이_아니라_0점으로_본다():
    items = [{"id": "1", "question": "가", "importance": 90},
             {"id": "2", "question": "나", "importance": 50}]
    results, warnings, _ = score_results_from_payload("답안", items, {"results": [
        {"id": "1", "score": 100, "quote": "답안", "reason": ""}]})
    assert results[1]["score"] == 0
    assert results[1]["note"] == "LLM 응답 누락"
    assert any("판정이 없어" in w for w in warnings)


def test_범위를_벗어난_점수와_읽을_수_없는_점수를_눌러_담는다():
    items = [{"id": "1", "question": "가", "importance": 90},
             {"id": "2", "question": "나", "importance": 90}]
    results, warnings, _ = score_results_from_payload("답안 원문", items, {"results": [
        {"id": "1", "score": 250, "quote": "답안", "reason": ""},
        {"id": "2", "score": "아주 좋음", "quote": "답안", "reason": ""}]})
    assert results[0]["score"] == 100
    assert results[1]["score"] == 0
    assert any("숫자로 읽지 못해" in w for w in warnings)


def test_응답_형식이_깨지면_전_항목을_0점으로_처리한다():
    items = make_items(2)
    results, warnings, _ = score_results_from_payload("답안", items, {"결과": []})
    assert all(r["score"] == 0 for r in results)
    assert any("results 목록이 없어" in w for w in warnings)


# ── ④ 중요도 가중 ────────────────────────────────────────────────────────────
def test_중요도_가중은_중요한_항목을_맞힌_쪽을_더_높게_친다():
    items = [{"id": "1", "question": "가", "importance": 90},
             {"id": "2", "question": "나", "importance": 10}]
    assert weighted_ratio([1.0, 0.0], items, True) == pytest.approx(0.9)
    assert weighted_ratio([0.0, 1.0], items, True) == pytest.approx(0.1)
    # 단순 평균은 둘을 구분하지 못한다 — 이것이 E 가 D 와 달라지는 지점이다
    assert weighted_ratio([1.0, 0.0], items, False) == weighted_ratio([0.0, 1.0], items, False)


def test_중요도_합이_0이면_단순_평균으로_물러난다():
    items = [{"id": "1", "question": "가", "importance": 0},
             {"id": "2", "question": "나", "importance": 0}]
    assert weighted_ratio([1.0, 0.0], items, True) == pytest.approx(0.5)


def test_판정_중_계산한_가중평균은_분석과_같은_값을_낸다():
    """실행 중 화면에 찍히는 값(run_experiment_v2)과 최종 분석(analyze_v2)이
    어긋나면, 실행을 지켜보며 내린 판단이 결과와 달라진다."""
    items = make_items(2)
    results = [{"cid": it["id"], "score": 60} for it in items]
    from_run = weighted_mean_0to100(results, items)
    from_analysis = weighted_ratio(score_vector({"items": results}, items), items, True)
    assert from_run == pytest.approx(from_analysis)


@pytest.mark.parametrize("ratio,expected", [
    (0.0, 0), (0.1, 1), (0.5, 3), (0.75, 4), (0.9, 5), (1.0, 5),
])
def test_비율은_5를_곱해_반올림한다_v1과_같은_규칙(ratio, expected):
    assert ratio_to_score(ratio) == expected


# ── ⑤ 보편 항목 빼기 (ablation) ──────────────────────────────────────────────
def test_ablation은_표시만_보고_보편_항목을_정확히_가른다():
    entry = {"items": make_items(3)}
    assert len(included_items(entry, exclude_universal=False)) == 5
    kept = included_items(entry, exclude_universal=True)
    assert len(kept) == 3
    assert all(not it.get("universal") for it in kept)


def test_보편_항목을_빼면_점수가_달라질_수_있다():
    """보편 항목이 도움인지 잡음인지 재려면, 뺐을 때 값이 실제로 움직여야 한다."""
    items = make_items(1)                      # 과제 1개 + 보편 2개
    rec = {"items": [{"cid": "1", "met": 1}, {"cid": "U1", "met": 0}, {"cid": "U2", "met": 0}]}
    full = weighted_ratio(binary_vector(rec, items), items, False)
    only_task = weighted_ratio(binary_vector(rec, items[:1]), items[:1], False)
    assert full == pytest.approx(1 / 3)
    assert only_task == pytest.approx(1.0)


def test_판정이_없는_항목은_이진에서_0_점수에서_0으로_읽는다():
    items = make_items(2)
    assert sum(binary_vector({"items": []}, items)) == 0.0
    assert sum(score_vector({"items": []}, items)) == 0.0


# ── ⑥ F·H 학습 (LLM 추가 호출 0회) ───────────────────────────────────────────
def _learning_fixture(n_per_prompt: int = 40):
    """문항 1종 × 답안 여러 건. 사람 점수는 1번 항목에만 달려 있고 나머지는 잡음이다."""
    rows = [make_row(f"S{i:03d}-ATQ001-{i:04d}", "가짜 문항 지시문", f"S{i:03d}", i % 6)
            for i in range(n_per_prompt)]
    fold_of, _ = assign_folds(rows, 5)
    rows_by_id = {str(r["id"]): r for r in rows}
    prompt_of = {rid: prompt_key(r["prompt"]) for rid, r in rows_by_id.items()}
    items = make_items(3)
    names = {prompt_key("가짜 문항 지시문"): [str(it["id"]) for it in items]}
    return rows, rows_by_id, fold_of, prompt_of, items, names


def test_F는_항목_벡터만으로_0에서5를_내고_근거를_남긴다():
    rows, rows_by_id, fold_of, prompt_of, items, names = _learning_fixture()
    vec = {}
    for rid, row in rows_by_id.items():
        score = row["evals"]["content"]
        noise = int(rid[3]) % 2
        vec[rid] = [1.0 if score >= 3 else 0.0, float(noise), 1.0 - noise, 0.0, 0.0]

    preds, learned = learn_per_prompt(vec, prompt_of, rows_by_id, fold_of, names, "F")
    assert len(preds) == len(rows)
    assert all(isinstance(v, int) and 0 <= v <= 5 for v in preds.values())
    # 문항마다 항목별 비중이 남아야 한다(근거 없는 점수는 이 프로젝트에서 결함이다)
    entry = learned[prompt_key("가짜 문항 지시문")]
    assert entry["method"] == "F"
    assert any(f.get("coefficients") for f in entry["folds"])
    assert set(next(f["coefficients"] for f in entry["folds"] if f.get("coefficients"))) \
        == {str(it["id"]) for it in items}


def test_학습은_시험_겹_답안을_보지_않는다():
    """out-of-fold 규칙. 한 겹의 답안 점수를 통째로 바꿔도 그 겹의 예측만 바뀌어야 한다."""
    rows, rows_by_id, fold_of, prompt_of, _, names = _learning_fixture()
    vec = {rid: [1.0 if rows_by_id[rid]["evals"]["content"] >= 3 else 0.0, 0.0, 0.0, 0.0, 0.0]
           for rid in rows_by_id}
    before, _ = learn_per_prompt(vec, prompt_of, rows_by_id, fold_of, names, "F")

    # 0번 겹의 사람 점수만 흔든다. 학습은 나머지 겹으로만 하므로 0번 겹 예측은 그대로여야 한다
    shaken = {rid: dict(r, evals={"content": 5 - r["evals"]["content"]})
              if fold_of[rid] == 0 else r for rid, r in rows_by_id.items()}
    after, _ = learn_per_prompt(vec, prompt_of, shaken, fold_of, names, "F")
    for rid in rows_by_id:
        if fold_of[rid] == 0:
            assert before[rid] == after[rid]


def test_H는_0에서100_벡터로도_같은_절차로_돈다():
    rows, rows_by_id, fold_of, prompt_of, _, names = _learning_fixture()
    vec = {rid: [rows_by_id[rid]["evals"]["content"] / 5.0, 0.5, 0.2, 0.0, 0.0]
           for rid in rows_by_id}
    preds, learned = learn_per_prompt(vec, prompt_of, rows_by_id, fold_of, names, "H")
    assert len(preds) == len(rows)
    assert all(0 <= v <= 5 for v in preds.values())
    assert learned[prompt_key("가짜 문항 지시문")]["method"] == "H"


# ── ⑦ 천장 ───────────────────────────────────────────────────────────────────
def _ceiling_fixture():
    ids = [f"R{i:03d}" for i in range(40)]
    rows_by_id = {rid: {"id": rid, "evals": {"content": i % 6}} for i, rid in enumerate(ids)}
    prompt_of = {rid: "P" for rid in ids}
    vec = {rid: [1.0 if (i % 6) >= 3 else 0.0, float(i % 2)] for i, rid in enumerate(ids)}
    truth = [rows_by_id[r]["evals"]["content"] for r in ids]
    return ids, rows_by_id, prompt_of, vec, truth


def test_천장은_같은_정보를_쓰는_실제_방식보다_낮을_수_없다():
    """이것이 깨지면 '천장'이라는 말 자체가 성립하지 않는다.

    중앙값 사상만으로는 실제로 깨진다(중앙값은 QWK 를 최대로 만드는 답이 아니다).
    그래서 QWK 를 직접 최대로 만드는 사상을 따로 두었고, 여기서 그것을 확인한다.
    """
    ids, rows_by_id, prompt_of, vec, truth = _ceiling_fixture()
    plain = [ratio_to_score(sum(vec[r]) / 2) for r in ids]
    opt = ceiling_by_met_count_optimized(ids, rows_by_id, vec, prompt_of, {"P": 2})
    assert qwk([opt[r] for r in ids], truth) >= qwk(plain, truth) - 1e-9


def test_QWK_최대_사상은_중앙값_사상보다_낮지_않다():
    ids, rows_by_id, prompt_of, vec, truth = _ceiling_fixture()
    med = ceiling_by_met_count(ids, rows_by_id, vec, prompt_of)
    opt = ceiling_by_met_count_optimized(ids, rows_by_id, vec, prompt_of, {"P": 2})
    assert qwk([opt[r] for r in ids], truth) >= qwk([med[r] for r in ids], truth) - 1e-9


def test_천장_계산은_두_번_돌려도_같은_값을_낸다():
    """무작위를 쓰지 않아야 어제 잰 천장과 오늘 잰 천장을 나란히 놓을 수 있다."""
    ids, rows_by_id, prompt_of, vec, _ = _ceiling_fixture()
    first = ceiling_by_met_count_optimized(ids, rows_by_id, vec, prompt_of, {"P": 2})
    second = ceiling_by_met_count_optimized(ids, rows_by_id, vec, prompt_of, {"P": 2})
    assert first == second


def test_선형_천장은_어느_항목을_맞혔는지까지_쓴다():
    """개수만 쓰는 천장보다 정보를 더 쓰므로, 항목별로 값이 다른 자료에서 더 높아야 한다."""
    ids, rows_by_id, prompt_of, vec, truth = _ceiling_fixture()
    med = ceiling_by_met_count(ids, rows_by_id, vec, prompt_of)
    lin = ceiling_by_linear_fit(ids, rows_by_id, vec, prompt_of)
    assert qwk([lin[r] for r in ids], truth) >= qwk([med[r] for r in ids], truth) - 1e-9


# ── 고정해 둔 v2 체크리스트가 실제로 규약을 지키는가 ─────────────────────────
CHECKLIST_V2_FILE = (Path(__file__).resolve().parent.parent
                     / "outputs" / "checklist_lab" / "checklists_v2.json")


@pytest.mark.skipif(not CHECKLIST_V2_FILE.exists(), reason="아직 v2 체크리스트를 만들지 않았다")
def test_고정된_v2_체크리스트가_규약을_지킨다():
    """만들어 둔 파일 자체를 검사한다. 생성기는 맞는데 결과물이 어긋나면 소용이 없다."""
    import json

    data = json.loads(CHECKLIST_V2_FILE.read_text(encoding="utf-8"))
    assert data, "v2 체크리스트가 비어 있다"
    for pkey, entry in data.items():
        if entry.get("status") != "ok":
            continue
        items = entry["items"]
        ids = [it["id"] for it in items]
        assert len(ids) == len(set(ids)), f"{pkey}: 항목 id 가 겹친다"
        universal = [it for it in items if it.get("universal")]
        assert len(universal) == 2, f"{pkey}: 보편 항목이 2개가 아니다"
        assert sum(it["importance"] for it in universal) == 100
        task = [it for it in items if not it.get("universal")]
        assert 0 < len(task) <= MAX_TASK_ITEMS, f"{pkey}: 과제 항목 수가 범위를 벗어났다"
        assert all(0 <= it["importance"] <= 100 for it in items)
        # 후보 답안에서 나왔다는 근거가 파일에 남아 있어야 한다
        assert entry.get("candidates"), f"{pkey}: 후보 답안 기록이 없다"
        assert entry.get("failure_modes"), f"{pkey}: 실패 방식 기록이 없다"
